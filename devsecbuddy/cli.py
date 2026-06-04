"""``python -m devsecbuddy`` — run the resume-scorer demo end-to-end on MockEngine.

Runs the full three-phase loop against one or all reference tiles and prints each
run's findings. Demonstrates the docs/tiles.md payoff: the same probe suite empties
the ledger as guardrails are added.
"""
from __future__ import annotations

import argparse
import sys

from .attack_library import load_vectors
from .demo import CLEAN_CORPUS, TILES
from .engines import get_engine
from .ledger import Ledger
from .runner import run_assessment


def _print_run(out: dict) -> None:
    s = out["summary"]
    print(f"\n=== {out['tile_id']}  (run {out['run_id']}) ===")
    print(f"  probes: {s['probes_run']}   vulnerabilities: {s['vulnerabilities_found']}   "
          f"passed: {s['probes_passed']}")
    if s["by_category"]:
        print(f"  by severity: {s['by_severity']}   by category: {s['by_category']}")
    for f in out["findings"]:
        print(f"  [{f.severity:>8}] {f.category:<17} {f.owasp_ref:<6} {f.vector_id}")
        print(f"             {f.evidence.get('detail', '')}")
    if not out["findings"]:
        print("  (no vulnerabilities — guardrails held)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="devsecbuddy",
                                     description="AI DevSecBuddy demo runner (offline MockEngine).")
    parser.add_argument("--tile", default="all",
                        help=f"tile id or 'all' (choices: {', '.join(TILES)})")
    parser.add_argument("--engine", default="mock", help="engine name (default: mock)")
    parser.add_argument("--db", default=None, help="ledger db path (default: data/ledger.db)")
    parser.add_argument("--vectors", default=None, help="attack-library vectors dir")
    args = parser.parse_args(argv)

    if args.tile != "all" and args.tile not in TILES:
        parser.error(f"unknown tile {args.tile!r}; choices: all, {', '.join(TILES)}")

    vectors = load_vectors(args.vectors, enabled_only=True)
    if not vectors:
        print("No enabled attack vectors found.", file=sys.stderr)
        return 1

    tile_ids = list(TILES) if args.tile == "all" else [args.tile]
    print(f"Loaded {len(vectors)} enabled vector(s); running {len(tile_ids)} tile(s) "
          f"on engine '{args.engine}'.")

    ledger = Ledger(args.db)
    try:
        for tile_id in tile_ids:
            adapter = TILES[tile_id](get_engine(args.engine))
            out = run_assessment(adapter, vectors, CLEAN_CORPUS, ledger=ledger, engine_name=args.engine)
            _print_run(out)
        print(f"\nLedger written to: {ledger.db_path}")
    finally:
        ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
