"""Offline tests for asphodel.world_source (no network access).

RangeReader's HTTP path is exercised against a local http.server on
127.0.0.1, which bypasses the mandatory HTTPS proxy and stays fully local to
this machine -- no traffic leaves the sandbox.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import threading

import pytest

from asphodel.world_source import bbox as bbox_mod
from asphodel.world_source import gate as gate_mod
from asphodel.world_source import overture
from asphodel.world_source import provenance

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# bbox.py
# ---------------------------------------------------------------------------

def test_houston_bbox_exact():
    w, s, e, n = bbox_mod.city_bbox("houston")
    assert w == pytest.approx(-95.4908972)
    assert s == pytest.approx(29.79371055)
    assert e == pytest.approx(-95.4308972)
    assert n == pytest.approx(29.853710550000002)


def test_madisonville_bbox_matches_meta_json():
    meta = bbox_mod.load_bundle_meta("madisonville_tx")
    s, w, n, e = meta["bbox"]
    assert bbox_mod.city_bbox("madisonville_tx") == (w, s, e, n)


def test_bbox_unknown_city_raises():
    with pytest.raises(bbox_mod.BundleNotFound):
        bbox_mod.city_bbox("nonexistent_city_xyz")


# ---------------------------------------------------------------------------
# provenance.py structure
# ---------------------------------------------------------------------------

def test_manifest_file_exists_and_parses():
    assert os.path.exists(provenance.MANIFEST_PATH)
    manifest = provenance.load_manifest()
    assert "artifacts" in manifest
    assert len(manifest["artifacts"]) > 0


def test_manifest_ok_entries_have_required_fields():
    manifest = provenance.load_manifest()
    required = {
        "provider", "dataset", "theme", "type", "release", "city",
        "source_url_pattern", "retrieval_date", "bbox", "license_family",
        "license_name", "attribution", "commercial_permitted", "share_alike",
        "sha256", "raw_path", "row_count", "file_size_bytes", "status",
    }
    ok_entries = [a for a in manifest["artifacts"] if a.get("status") == "ok"]
    assert ok_entries, "expected at least one 'ok' artifact in the committed manifest"
    for entry in ok_entries:
        missing = required - entry.keys()
        assert not missing, f"artifact {entry.get('type')}/{entry.get('city')} missing fields {missing}"
        assert entry["license_family"] in provenance.LICENSE_FAMILIES


def test_manifest_contains_failed_egress_sources():
    manifest = provenance.load_manifest()
    failed = [a for a in manifest["artifacts"] if a.get("status") == "unreachable_egress_policy"]
    datasets = {a["dataset"] for a in failed}
    assert any("parcel" in d.lower() or "land-use" in d.lower() for d in datasets)
    assert any("3dep" in d.lower() or "dem" in d.lower() for d in datasets)
    assert any("nlcd" in d.lower() or "land cover" in d.lower() for d in datasets)
    for entry in failed:
        assert entry["license_family"] == "UNKNOWN"
        assert entry["commercial_permitted"] is False
        assert entry.get("fallback")


# ---------------------------------------------------------------------------
# gate.py
# ---------------------------------------------------------------------------

def test_gate_passes_on_committed_manifest():
    manifest = provenance.load_manifest()
    gate_mod.assert_commercial_clean(manifest)  # must not raise


def test_gate_fails_on_synthetic_unknown_ok_entry():
    manifest = {
        "artifacts": [
            {
                "provider": "Mystery Corp",
                "type": "mystery",
                "release": "1.0",
                "city": "nowhere",
                "license_family": "UNKNOWN",
                "commercial_permitted": False,
                "status": "ok",
            }
        ]
    }
    with pytest.raises(gate_mod.GateFailure):
        gate_mod.assert_commercial_clean(manifest)


def test_gate_ignores_failed_status_regardless_of_license():
    manifest = {
        "artifacts": [
            {
                "provider": "Mystery Corp",
                "type": "mystery",
                "release": "1.0",
                "city": "nowhere",
                "license_family": "UNKNOWN",
                "commercial_permitted": False,
                "status": "unreachable_egress_policy",
            }
        ]
    }
    gate_mod.assert_commercial_clean(manifest)  # must not raise


# ---------------------------------------------------------------------------
# overture.RangeReader
# ---------------------------------------------------------------------------

def test_range_reader_local_file(tmp_path):
    path = tmp_path / "sample.bin"
    payload = bytes(range(256)) * 40  # 10240 bytes
    path.write_bytes(payload)

    reader = overture.RangeReader(local_path=str(path))
    assert reader.size == len(payload)

    reader.seek(0)
    assert reader.read(10) == payload[:10]
    assert reader.tell() == 10

    reader.seek(100)
    assert reader.read(5) == payload[100:105]

    reader.seek(-4, whence=2)
    assert reader.read() == payload[-4:]

    reader.seek(0)
    assert reader.read(-1) == payload
    reader.close()


@pytest.fixture(scope="module")
def local_http_server(tmp_path_factory):
    """A tiny http.server on 127.0.0.1 serving a directory of files, to
    exercise RangeReader's HTTP Range-GET path without any real network
    egress (127.0.0.1 bypasses the mandatory HTTPS proxy)."""
    directory = tmp_path_factory.mktemp("range_reader_http")
    payload = bytes((i * 7) % 256 for i in range(50_000))
    (directory / "blob.bin").write_bytes(payload)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    yield f"http://127.0.0.1:{port}/blob.bin", payload
    httpd.shutdown()
    thread.join(timeout=5)


def test_range_reader_http_range_requests(local_http_server):
    url, payload = local_http_server
    reader = overture.RangeReader(url=url)
    assert reader.size == len(payload)

    reader.seek(1000)
    assert reader.read(500) == payload[1000:1500]

    reader.seek(-10, whence=2)
    assert reader.read() == payload[-10:]

    reader.seek(0)
    all_bytes = reader.read(-1)
    assert all_bytes == payload
    reader.close()


# ---------------------------------------------------------------------------
# overture row-group bbox pruning (pure function, no network)
# ---------------------------------------------------------------------------

class _FakeStats:
    def __init__(self, mn, mx):
        self.min = mn
        self.max = mx


class _FakeColumn:
    def __init__(self, path, mn, mx):
        self.path_in_schema = path
        self.statistics = _FakeStats(mn, mx)


class _FakeRowGroup:
    def __init__(self, xmin, xmax, ymin, ymax):
        self._cols = [
            _FakeColumn("bbox.xmin", xmin, xmin),
            _FakeColumn("bbox.xmax", xmax, xmax),
            _FakeColumn("bbox.ymin", ymin, ymin),
            _FakeColumn("bbox.ymax", ymax, ymax),
        ]

    @property
    def num_columns(self):
        return len(self._cols)

    def column(self, i):
        return self._cols[i]


def test_row_group_matches_intersecting_bbox():
    houston = (-95.4908972, 29.79371055, -95.4308972, 29.85371055)
    rg_inside = _FakeRowGroup(-95.48, 29.80, -95.47, 29.81)
    assert overture._row_group_matches(rg_inside, houston) is True


def test_row_group_matches_rejects_disjoint_bbox():
    houston = (-95.4908972, 29.79371055, -95.4308972, 29.85371055)
    rg_far = _FakeRowGroup(2.0, 2.1, 48.0, 48.1)  # Paris, nowhere near Houston
    assert overture._row_group_matches(rg_far, houston) is False


def test_type_themes_cover_all_ten_required_types():
    expected = {
        "building", "building_part", "segment", "connector", "land",
        "land_cover", "land_use", "water", "infrastructure", "place",
    }
    assert set(overture.TYPE_THEMES.keys()) == expected
