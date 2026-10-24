"""Stage 5 report: render a scored run into runs/<run_id>/05_report.md; with --debate, the
debate's revised plan into runs/<run_id>/debate/revised_plan.md.

    uv run python scripts/render_report.py <run_id>
    uv run python scripts/render_report.py <run_id> --debate

Reads runs/<run_id>/00_spec.json, 03_claims/verified.json, 04_scores.json, 04_risks.json, the
research files' Gaps sections and usage.jsonl, writes 05_report.md (verdict, score table with cap
labels, kill triggers, unit economics and sensitivity, dimension sections, Finland funding fit,
Rääkkylä notes, risk register, starttiraha business-plan draft, sources, usage summary) and stores
its `reports` row. Reports are
immutable: an existing report is never overwritten. Exit 0 once written, 1 when the run is
unknown, an input file is missing or invalid, or the run already has a report.

--debate (after the judge wrote debate/verdict.json): checks that every accepted change cites
verified claim ids, recomputes `conformity_flag` and writes it into verdict.json, then writes
debate/revised_plan.md (the diff against 05_report.md, the accepted and rejected changes, the
assumption register and the experiments by info value per euro), stores the `assumptions` and
`experiments` tables, the `reports` row (kind revised_plan) and finishes the `debates` row. Also
written once. Exit 0 once written, 1 on any of the errors above or a verdict that does not pass.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import db, debate, report, revised_plan, runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("--debate", action="store_true", help="render debate/revised_plan.md from debate/verdict.json")
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

    if args.debate:
        try:
            plan = revised_plan.render(args.run_id)
        except (revised_plan.InputError, revised_plan.PlanExists, debate.DebateError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        flag = "RAISED" if plan.verdict.conformity_flag else "not raised"
        print(
            f"accepted {len(plan.verdict.accepted_changes)} change(s), rejected {len(plan.verdict.rejected_changes)};"
            f" {len(plan.experiments)} experiment(s); conformity flag {flag}"
        )
        print(f"wrote {plan.path.relative_to(run_dir.parent.parent).as_posix()}")
        return 0

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
