"""Stage 5 input: write the only file the synthesizer reads.

    uv run python scripts/synthesis_input.py <run_id>

Writes runs/<run_id>/04_synthesis_input.json: 00_spec.json, the verified and conflict claims of
03_claims/verified.json (unverified and pending claims left out), the rubric (weights, evidence
rules, kill triggers, verdict thresholds) and the unit-economics input roles. Prints the path and
the claim count per dimension. Exit 0 once written, 1 when the run is unknown or the spec or
verified.json is missing or invalid.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from ideaforge import runs, synthesis
from ideaforge.schemas import RESEARCH_DIMENSIONS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    args = parser.parse_args(argv)

    try:
        run_dir = runs.run_dir(args.run_id)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not run_dir.is_dir():
        print(f"error: {run_dir} does not exist", file=sys.stderr)
        return 1
    try:
        path, data = synthesis.write_synthesis_input(args.run_id)
    except synthesis.InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    counts = Counter((c["dimension"], c["verification"]) for c in data["claims"])
    for dim in RESEARCH_DIMENSIONS:
        verified, conflict = counts[(dim, "verified")], counts[(dim, "conflict")]
        flag = "  (no verified evidence)" if not verified and dim != "killcause" else ""
        print(f"{dim:<16} {verified:>3} verified {conflict:>3} conflict{flag}")
    print(f"wrote {path.relative_to(run_dir.parent.parent).as_posix()} ({len(data['claims'])} claims)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
