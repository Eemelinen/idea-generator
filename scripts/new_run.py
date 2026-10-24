"""Create a new run: runs/<run_id>/ with idea.md and meta.json, db rows, active marker.

    uv run python scripts/new_run.py "<idea text>" [--preset economy|standard|deep]
                                     [--from <parent_run_id>] [--as-of YYYY-MM-DD]
                                     [--intake '<json>']
    uv run python scripts/new_run.py --from <parent_run_id> ["<revised idea text>"]

With --from the run is the parent's next idea version, `<parent id>-v<N>` (`runs.child_run`),
linked through `idea_versions.parent`; the idea text, budget preset and as-of date default to the
parent's, and the parent's
directory, rows and report are never touched. meta.json records the provenance (`ideaforge.meta`).
--intake takes the clarifications as JSON (schema `Intake`: goal, capital_eur, hours_per_week,
skills, geography, answers, kill_trigger_overrides) and writes them to `runs/<run_id>/intake.json`,
so `/validate`'s stage 0 asks nothing (IF-604); an invalid intake creates nothing (exit 2).
Prints the run_id on stdout (and nothing else) so callers can capture it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from pydantic import ValidationError

from ideaforge import config, db, meta, runs
from ideaforge.schemas import Intake


def parent_row(parent: str):
    """The parent's `runs` row: idea text, budget preset and as-of date a new version inherits."""
    with db.session() as conn:
        return conn.execute(
            "SELECT idea_text, budget_preset, as_of FROM runs WHERE run_id=?", (parent,)
        ).fetchone()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("idea", nargs="?", default=None, help="the idea, in free text (default with --from: the parent's)")
    parser.add_argument("--preset", default=None, help="budget preset from config/budget.yaml")
    parser.add_argument("--from", dest="parent", default=None, help="parent run id (new idea version)")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="back-test date")
    parser.add_argument("--intake", default=None, help="clarifications as JSON (schema Intake) → intake.json")
    args = parser.parse_args(argv)

    intake = None
    if args.intake is not None:
        try:
            intake = Intake.model_validate_json(args.intake)
        except ValidationError as e:
            parser.error(f"invalid --intake: {e}")

    db.init()
    idea, preset, as_of = args.idea, args.preset, args.as_of
    if args.parent:
        try:
            run_id, version, idea_id = runs.child_run(args.parent)
        except ValueError as e:
            parser.error(str(e))
        row = parent_row(args.parent)
        if idea is None or not idea.strip():
            idea = row["idea_text"]
        # A revision of a back-test stays a back-test, at the parent's budget, unless overridden.
        preset = preset or row["budget_preset"]
        if as_of is None and row["as_of"]:
            as_of = date.fromisoformat(row["as_of"])

    budget = config.budget()
    preset = preset or budget.default_preset
    if preset not in budget.presets:
        parser.error(f"unknown preset {preset!r}; choose from {sorted(budget.presets)}")
    if idea is None or not idea.strip():
        parser.error("idea text must not be empty")
    if not args.parent:
        run_id, version, idea_id = runs.new_run_id(idea), 1, runs.slugify(idea, 30)
    if runs.run_dir(run_id).exists():
        parser.error(f"run directory runs/{run_id} already exists")
    run_dir = runs.create_run_dir(run_id, idea)
    if intake is not None:
        (run_dir / "intake.json").write_text(intake.model_dump_json(indent=2) + "\n", encoding="utf-8")

    run_meta = meta.build(
        run_id,
        idea_id=idea_id,
        version=version,
        parent_run_id=args.parent,
        budget_preset=preset,
        as_of=as_of,
    )
    meta.write(run_dir, run_meta)

    db.create_run(
        run_id,
        idea,
        idea_id=idea_id,
        version=version,
        parent=args.parent,
        budget_preset=preset,
        as_of=as_of.isoformat() if as_of else None,
        stages=runs.STAGES,
    )
    runs.set_active(run_id)
    print(run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
