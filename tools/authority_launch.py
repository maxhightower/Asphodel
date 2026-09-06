#!/usr/bin/env python3
"""Dev entrypoint the Godot AuthorityLauncher spawns to bring up the simulation
authority without a manual terminal (Convergence V2, §8).

It is cwd-independent: it inserts the repository root (its own parent's parent)
onto sys.path so `asphodel` imports resolve however Godot was launched, then runs
the bridge server on the parent-selected port. A packaged Windows build ships a
frozen `asphodel-authority` executable instead and does not use this script.

    python3 tools/authority_launch.py --port <N> [--host 127.0.0.1]
"""
import argparse
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    from asphodel.bridge.server import serve_forever
    serve_forever(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
