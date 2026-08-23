"""A/B causal-intervention demo (M1): prove the world is genuinely live.

Runs the authoritative :class:`WorldSession` twice against the *same* city, seed
and command stream, differing only in whether a cordon is applied to the outbreak
seed zone at t=0. If the bridge were replaying a baked timeline the two runs would
be identical; because the live Python World owns the outbreak, run B's later
authoritative state measurably diverges from run A's.

Run::

    python -m asphodel.bridge.ab_demo --city houston --seed 7 --ticks 100
"""

from __future__ import annotations

import argparse

from .session import WorldSession
from .protocol import Command, PROTOCOL_VERSION


def _run(city: str, seed: int, ticks: int, cordon: bool) -> dict:
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    s.handle({"cmd": Command.START_WORLD, "bundle": city, "seed": seed})
    if cordon:
        s.handle({"cmd": Command.INTERVENE, "action": "cordon",
                  "zones": [s.world.cfg.seed_zone]})
    last = s.handle({"cmd": Command.ADVANCE, "ticks": ticks})
    return last["totals"]


def _infected(t: dict) -> float:
    return sum(t[k] for k in ("E", "Ia", "Is", "R", "D"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--city", default="houston")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ticks", type=int, default=100)
    args = ap.parse_args(argv)

    a = _run(args.city, args.seed, args.ticks, cordon=False)
    b = _run(args.city, args.seed, args.ticks, cordon=True)
    ia, ib = _infected(a), _infected(b)

    print(f"city={args.city} seed={args.seed} ticks={args.ticks}")
    print(f"  A  no intervention : infected={ia:12.2f}  deaths={a['D']:10.2f}")
    print(f"  B  cordon seed zone: infected={ib:12.2f}  deaths={b['D']:10.2f}")
    print(f"  divergence         : {ia - ib:12.2f} fewer infected under the cordon")
    identical = a == b
    print(f"  trajectories identical? {identical}  "
          f"(expected False -> the world is live, not a baked replay)")
    return 0 if (not identical and ib < ia) else 1


if __name__ == "__main__":
    raise SystemExit(main())
