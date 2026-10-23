"""Run status for /status.

    uv run python scripts/status.py                 # recent runs and their stages
    uv run python scripts/status.py --limit 20
    uv run python scripts/status.py <run_id>        # one run in detail

With a run id: the stages, claims per dimension by verification state, kill flags fired
(verified claims), VALIDATION_FAILED / VALIDATION_WARNINGS / BUDGET_EXCEEDED markers and the
usage summary. Exit 0 once printed, 1 for a bad or unknown run id.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import db, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--limit", type=int, default=10, help="recent runs to list (default 10)")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    db.init()
    if args.run_id is None:
        print(status.recent_runs(args.limit))
        return 0
    try:
        print(status.run_status(args.run_id))
    except (ValueError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
