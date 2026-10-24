"""Check the golden-set runs (plan §9, IF-502) and print a summary table.

    uv run python scripts/eval_check.py                  # check every golden idea
    uv run python scripts/eval_check.py --limit 3        # the first 3 (file-name order)
    uv run python scripts/eval_check.py --plan [--limit N]

Golden ideas are `tests/golden/*.yaml` (schema `GoldenIdea`). Each is checked on the newest run
created with its idea text: the verdict of `04_scores.json` is one of `expected_verdicts`, every
must-find fact is found by a verified claim of `03_claims/verified.json`, and the score sheet
cites no claim id that is not verified. The Markdown table goes to stdout.

`--plan` checks nothing: it prints one tab-separated line per golden idea for /eval,
`<golden_id> <state> <run_id or -> <idea text>`, where the state is `none` (no run yet),
`incomplete` or `complete` (every stage complete). It never prints the expected verdicts or
the must-find facts, which the orchestrator must not see.

Exit 0 when every checked idea passes (also with no golden files), 2 when one fails, 1 when a
golden file is invalid.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ideaforge import db, golden


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="only the first N golden ideas")
    parser.add_argument("--plan", action="store_true", help="list the golden ideas and their runs; check nothing")
    parser.add_argument("--golden-dir", type=Path, default=None, help="default: tests/golden")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    try:
        ideas = golden.load_all(args.golden_dir, args.limit)
    except golden.GoldenError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not ideas:
        print(f"no golden ideas in {args.golden_dir or golden.golden_dir()}")
        return 0

    db.init()
    if args.plan:
        for gid, g in ideas:
            run_id = golden.latest_run(g.idea)
            print(f"{gid}\t{golden.run_state(run_id)}\t{run_id or '-'}\t{g.idea}")
        return 0
    results = [golden.check(gid, g) for gid, g in ideas]
    print(golden.summary(results))
    return 0 if all(r.passed for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
