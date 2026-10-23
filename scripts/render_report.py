"""Stage 5 report: render a scored run into runs/<run_id>/05_report.md.

    uv run python scripts/render_report.py <run_id>

Reads runs/<run_id>/00_spec.json, 03_claims/verified.json, 04_scores.json, 04_risks.json, the
research files' Gaps sections and usage.jsonl, writes 05_report.md (verdict, score table with cap
labels, kill triggers, unit economics and sensitivity, dimension sections, Finland funding fit,
Rääkkylä notes, risk register, sources, usage summary) and stores its `reports` row. Reports are
immutable: an existing report is never overwritten. Exit 0 once written, 1 when the run is
unknown, an input file is missing or invalid, or the run already has a report.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import db, report, runs


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
        result = report.render(args.run_id)
    except (report.InputError, report.ReportExists) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"verdict: {result.sheet.verdict} (weighted total {result.sheet.weighted_total:.2f})")
    print(f"wrote {result.path.relative_to(run_dir.parent.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
