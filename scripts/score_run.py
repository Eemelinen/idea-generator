"""Stage 5 scoring: turn the synthesizer's proposal into the final score sheet.

    uv run python scripts/score_run.py <run_id>

Reads runs/<run_id>/00_spec.json, 03_claims/verified.json and 04_scores_proposed.json, drops
cited claim ids that are unknown or not verified, sets an uncited proposal to 0, applies the
rubric's evidence rules, caps and kill triggers (scoring.py) and the unit economics
(economics.py, from the synthesizer's unit_economics_inputs), then writes 04_scores.json and
the run's `scores` rows. Prints the score table, dropped citations, the verdict and the unit
economics on stdout and warnings on stderr. Exit 0 once 04_scores.json is written, 1 when the
run is unknown or an input file is missing or invalid.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import db, runs, synthesis


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
    db.init()
    with db.session() as conn:
        known = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (args.run_id,)).fetchone()
    if known is None:
        print(f"error: run {args.run_id!r} is not in the database; create it with scripts/new_run.py", file=sys.stderr)
        return 1

    try:
        result = synthesis.score_run(args.run_id)
    except synthesis.InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(synthesis.summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
