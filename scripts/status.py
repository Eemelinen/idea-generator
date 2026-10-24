"""Run status for /status.

    uv run python scripts/status.py                 # recent runs and their stages
    uv run python scripts/status.py --limit 20
    uv run python scripts/status.py <run_id>        # one run in detail
    uv run python scripts/status.py <run_id> --review                    # sections to score
    uv run python scripts/status.py <run_id> --review verdict=4 'risks=2:too generic' …
    uv run python scripts/status.py --reviews       # review scores by prompt/model version
    uv run python scripts/status.py --diff <run_a> <run_b>   # compare two score sheets

With a run id: the stages, claims per dimension by verification state, kill flags fired
(verified claims), VALIDATION_FAILED / VALIDATION_WARNINGS / BUDGET_EXCEEDED markers and the
usage summary. `--review` with no scores lists the report sections (`ideaforge.review.SECTIONS`)
and any stored scores; with `section=score[:note]` entries (score 1–5) it stores them in the
`reviews` table. `--diff` compares two runs' 04_scores.json per dimension, verdict and kill
triggers. Exit 0 once printed or stored, 1 for a bad or unknown run id, a run without a report
or score sheet, or a bad review entry.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import db, review, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--limit", type=int, default=10, help="recent runs to list (default 10)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--review", nargs="*", metavar="SECTION=SCORE[:NOTE]", help="score the run's report sections")
    mode.add_argument("--reviews", action="store_true", help="review scores by prompt/model version")
    mode.add_argument("--diff", nargs=2, metavar=("RUN_A", "RUN_B"), help="compare two runs' score sheets")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.review is not None and args.run_id is None:
        parser.error("--review needs a run id: status.py <run_id> --review [section=score …]")
    if (args.reviews or args.diff) and args.run_id is not None:
        parser.error("--reviews and --diff take no separate run id")

    db.init()
    try:
        if args.reviews:
            print(review.trend())
        elif args.diff:
            print(status.diff_runs(*args.diff))
        elif args.run_id is None:
            print(status.recent_runs(args.limit))
        elif args.review == []:
            print(review.pending(args.run_id))
        elif args.review:
            print(review.store(args.run_id, args.review))
        else:
            print(status.run_status(args.run_id))
    except (ValueError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
