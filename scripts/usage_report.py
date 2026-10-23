"""Usage of one run: tool calls, searches, fetches and approximate tokens per stage and agent.

    uv run python scripts/usage_report.py <run_id>

Reads runs/<run_id>/usage.jsonl (written by the PostToolUse hook). A row's stage is its own
`stage` field when set; else a research agent's dimension stage (`research:<dim>`); else the
latest-started stage whose time window in the `stages` table holds its timestamp (`(no stage)`
when none does).
Lists the run's BUDGET_EXCEEDED_<agent> markers. Exit 0 once printed, 1 for a bad run id or a
missing run directory.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import db, runs, usage


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
    print(usage.render_summary(usage.summarize(args.run_id, run_dir, db.stages(args.run_id))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
