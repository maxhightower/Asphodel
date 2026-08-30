"""Overture Maps downloader: the one network client in Asphodel.

AGENT NOTES -- verified network reality, do not re-litigate:
  * The only reachable data host from this environment is Overture's public
    S3 bucket over plain HTTPS/REST (anonymous):
    https://overturemaps-us-west-2.s3.amazonaws.com
  * boto3 / s3fs / pyarrow.fs.S3FileSystem do not work through the mandatory
    HTTPS proxy in this environment -- only plain `requests` calls do. Do not
    reintroduce them.
  * The `overturemaps` CLI's STAC-based discovery is blocked; we list objects
    directly via the S3 ListObjectsV2 REST API instead.
  * tnmaccess.nationalmap.gov, services.arcgis.com, *.houstontx.gov,
    docs.overturemaps.org, overturemaps.org are blocked by egress policy.
    Do not add retries against them beyond one recorded attempt; see
    provenance.FAILED_SOURCES for how those gaps are documented instead.

Strategy for pulling a small bbox out of a global, hive-partitioned release
without downloading gigabytes: each (theme, type) is split into many
"part-*.parquet" files; each file's Parquet footer carries per-row-group
min/max statistics on the flattened `bbox.xmin/xmax/ymin/ymax` columns.
`RangeReader` lets pyarrow read just that footer (a handful of small HTTP
Range GETs) without transferring the file's data pages. We then keep only
the row groups whose bbox statistics intersect the target bbox, download
just those row groups' bytes, and finish with an exact per-row bbox filter
(row-group stats are a superset, not an exact match).
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import io
import os
import time
import xml.etree.ElementTree as ET

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

S3_BASE = "https://overturemaps-us-west-2.s3.amazonaws.com"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

USER_AGENT = "Asphodel/0.1 (research prototype; public-data acquisition layer)"

# theme/type pairs Asphodel's world_source pulls, keyed by the short "type"
# name used on the CLI and in the provenance manifest.
TYPE_THEMES = {
    "building": "buildings",
    "building_part": "buildings",
    "segment": "transportation",
    "connector": "transportation",
    "land": "base",
    "land_cover": "base",
    "land_use": "base",
    "water": "base",
    "infrastructure": "base",
    "place": "places",
}

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_RAW_DIR = os.path.join(_REPO_ROOT, "data", "raw", "overture")


class DownloadError(Exception):
    """Raised when a network operation exhausts its retries."""


def _retry(fn, retries: int = 4, base_delay: float = 1.0, what: str = "request"):
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- broad: network/HTTP/parse errors all retry
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise DownloadError(f"{what} failed after {retries} attempts: {last_exc}") from last_exc


def list_parquet_urls(theme: str, type_: str, release: str, session: requests.Session | None = None) -> list[str]:
    """List every part-*.parquet object under theme=<theme>/type=<type_> via
    S3 ListObjectsV2 REST, following continuation tokens."""
    session = session or requests.Session()
    prefix = f"release/{release}/theme={theme}/type={type_}/"
    urls: list[str] = []
    token = None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token

        def _do_get():
            r = session.get(S3_BASE + "/", params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
            r.raise_for_status()
            return r.text

        body = _retry(_do_get, what=f"list {prefix}")
        root = ET.fromstring(body)
        for contents in root.findall(f"{_S3_NS}Contents"):
            key = contents.findtext(f"{_S3_NS}Key")
            if key and key.endswith(".parquet"):
                urls.append(f"{S3_BASE}/{key}")
        truncated = root.findtext(f"{_S3_NS}IsTruncated")
        if truncated == "true":
            token = root.findtext(f"{_S3_NS}NextContinuationToken")
        else:
            break
    return urls


class RangeReader(io.RawIOBase):
    """A seekable, read-only file-like object backed by HTTP Range GETs.

    pyarrow.parquet.ParquetFile accepts any Python file object supporting
    read/seek/tell -- this lets it read a remote parquet file's footer and
    selected row groups without ever downloading the whole file. Also
    supports a local-file fallback (pass `local_path`) so the same class is
    testable without any network access.
    """

    def __init__(self, url: str | None = None, session: requests.Session | None = None,
                 size: int | None = None, local_path: str | None = None):
        if url is None and local_path is None:
            raise ValueError("RangeReader requires either url or local_path")
        self.url = url
        self.local_path = local_path
        self.session = session or requests.Session()
        self._pos = 0
        self._size = size
        self._local_fh = open(local_path, "rb") if local_path else None

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    @property
    def size(self) -> int:
        if self._size is None:
            if self._local_fh is not None:
                self._size = os.fstat(self._local_fh.fileno()).st_size
            else:
                def _head():
                    r = self.session.head(self.url, headers={"User-Agent": USER_AGENT}, timeout=30)
                    r.raise_for_status()
                    return int(r.headers["Content-Length"])
                self._size = _retry(_head, what=f"HEAD {self.url}")
        return self._size

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        elif whence == 2:
            self._pos = self.size + offset
        else:
            raise ValueError(f"invalid whence: {whence}")
        return self._pos

    def read(self, n: int = -1) -> bytes:
        size = self.size
        if self._pos >= size:
            return b""
        end = size - 1 if n is None or n < 0 else min(self._pos + n, size) - 1
        if end < self._pos:
            return b""
        if self._local_fh is not None:
            self._local_fh.seek(self._pos)
            data = self._local_fh.read(end - self._pos + 1)
        else:
            def _get():
                headers = {"Range": f"bytes={self._pos}-{end}", "User-Agent": USER_AGENT}
                r = self.session.get(self.url, headers=headers, timeout=60)
                r.raise_for_status()
                if r.status_code == 200:
                    # Server ignored the Range header (e.g. a plain
                    # http.server used in local tests) and sent the whole
                    # body -- slice out the requested window ourselves.
                    return r.content[self._pos:end + 1]
                return r.content
            data = _retry(_get, what=f"GET {self.url} bytes={self._pos}-{end}")
        self._pos += len(data)
        return data

    def readall(self) -> bytes:
        return self.read(-1)

    def close(self) -> None:
        if self._local_fh is not None:
            self._local_fh.close()
        super().close()


def _row_group_matches(rg_metadata, bbox: tuple[float, float, float, float]) -> bool:
    """True if a row group's bbox.{xmin,xmax,ymin,ymax} statistics intersect
    the target (W, S, E, N) bbox. Row groups lacking bbox stats are kept
    (conservative: never silently drop data we can't evaluate)."""
    w, s, e, n = bbox
    stats = {}
    for i in range(rg_metadata.num_columns):
        col = rg_metadata.column(i)
        path = col.path_in_schema
        if path in ("bbox.xmin", "bbox.xmax", "bbox.ymin", "bbox.ymax") and col.statistics is not None:
            stats[path] = (col.statistics.min, col.statistics.max)
    if len(stats) < 4:
        return True
    xmin_lo, _ = stats["bbox.xmin"]
    _, xmax_hi = stats["bbox.xmax"]
    ymin_lo, _ = stats["bbox.ymin"]
    _, ymax_hi = stats["bbox.ymax"]
    return xmin_lo <= e and xmax_hi >= w and ymin_lo <= n and ymax_hi >= s


def _matching_row_groups(pf: pq.ParquetFile, bbox: tuple[float, float, float, float]) -> list[int]:
    return [i for i in range(pf.metadata.num_row_groups) if _row_group_matches(pf.metadata.row_group(i), bbox)]


def _exact_bbox_filter(table: pa.Table, bbox: tuple[float, float, float, float]) -> pa.Table:
    w, s, e, n = bbox
    bbox_col = table.column("bbox")
    xmin = pc.struct_field(bbox_col, "xmin")
    xmax = pc.struct_field(bbox_col, "xmax")
    ymin = pc.struct_field(bbox_col, "ymin")
    ymax = pc.struct_field(bbox_col, "ymax")
    mask = pc.and_(
        pc.and_(pc.less_equal(xmin, pa.scalar(e)), pc.greater_equal(xmax, pa.scalar(w))),
        pc.and_(pc.less_equal(ymin, pa.scalar(n)), pc.greater_equal(ymax, pa.scalar(s))),
    )
    return table.filter(mask)


def _inspect_one_file(url: str, bbox: tuple[float, float, float, float], session: requests.Session):
    """Open a remote parquet file's footer and return (url, pf, matching_row_group_indices)."""
    def _open():
        reader = RangeReader(url=url, session=session)
        return pq.ParquetFile(reader)
    pf = _retry(_open, what=f"open footer {url}")
    matches = _matching_row_groups(pf, bbox)
    return url, pf, matches


def download_type(
    city: str,
    bbox: tuple[float, float, float, float],
    type_: str,
    release: str,
    out_dir: str = DEFAULT_RAW_DIR,
    force: bool = False,
    max_workers: int = 16,
    progress=print,
) -> dict:
    """Download the rows of Overture `type_` intersecting `bbox` for `city`.

    Writes `<out_dir>/<release>/<city>/<type_>.parquet` (creating an
    empty-but-correctly-schemad file if no rows fall in the bbox) and returns
    a dict describing the artifact (row_count, file_size_bytes, sha256,
    raw_path, urls_scanned, row_groups_read).
    """
    theme = TYPE_THEMES[type_]
    out_path = os.path.join(out_dir, release, city, f"{type_}.parquet")
    if os.path.exists(out_path) and not force:
        progress(f"[{city}/{type_}] cached at {out_path}, skipping (use --force to redownload)")
        return _describe_existing(out_path)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    session = requests.Session()

    progress(f"[{city}/{type_}] listing theme={theme} type={type_} release={release} ...")
    urls = list_parquet_urls(theme, type_, release, session=session)
    progress(f"[{city}/{type_}] {len(urls)} part file(s) to inspect")

    tables: list[pa.Table] = []
    schema_ref: pa.Schema | None = None
    row_groups_read = 0
    files_with_matches = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_inspect_one_file, url, bbox, session): url for url in urls}
        for fut in concurrent.futures.as_completed(futures):
            url = futures[fut]
            try:
                url, pf, matches = fut.result()
            except DownloadError as exc:
                progress(f"[{city}/{type_}] WARNING: failed to inspect {url}: {exc}")
                continue
            if schema_ref is None:
                schema_ref = pf.schema_arrow
            if not matches:
                continue
            files_with_matches += 1
            for rg_idx in matches:
                def _read_rg(pf=pf, rg_idx=rg_idx, url=url):
                    return pf.read_row_group(rg_idx)
                table = _retry(_read_rg, what=f"read row group {rg_idx} of {url}")
                row_groups_read += 1
                tables.append(_exact_bbox_filter(table, bbox))

    if tables:
        combined = pa.concat_tables(tables, promote_options="permissive")
    else:
        combined = pa.Table.from_pylist([], schema=schema_ref) if schema_ref is not None else pa.table({})

    pq.write_table(combined, out_path)
    size = os.path.getsize(out_path)
    sha256 = _sha256_file(out_path)
    progress(
        f"[{city}/{type_}] wrote {combined.num_rows} row(s), {size} bytes "
        f"({files_with_matches}/{len(urls)} part file(s) matched, {row_groups_read} row group(s) read)"
    )
    return {
        "raw_path": os.path.relpath(out_path, _REPO_ROOT),
        "row_count": combined.num_rows,
        "file_size_bytes": size,
        "sha256": sha256,
        "urls_scanned": len(urls),
        "row_groups_read": row_groups_read,
    }


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _describe_existing(out_path: str) -> dict:
    pf = pq.ParquetFile(out_path)
    return {
        "raw_path": os.path.relpath(out_path, _REPO_ROOT),
        "row_count": pf.metadata.num_rows,
        "file_size_bytes": os.path.getsize(out_path),
        "sha256": _sha256_file(out_path),
        "urls_scanned": None,
        "row_groups_read": None,
    }


def verify_cached(out_path: str, expected_sha256: str) -> bool:
    """Offline mode: verify a cached file matches its recorded checksum."""
    if not os.path.exists(out_path):
        return False
    return _sha256_file(out_path) == expected_sha256
