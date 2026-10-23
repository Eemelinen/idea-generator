"""Create a new run: runs/<run_id>/ with idea.md and meta.json, db rows, active marker.

    uv run python scripts/new_run.py "<idea text>" [--preset economy|standard|deep]
                                     [--from <parent_run_id>] [--as-of YYYY-MM-DD]
    uv run python scripts/new_run.py --from <parent_run_id> ["<revised idea text>"]

With --from the run is the parent's next idea version, `<parent id>-v<N>` (`runs.child_run`),
linked through `idea_versions.parent`; the idea text defaults to the parent's, and the parent's
directory, rows and report are never touched. meta.json records the provenance (`ideaforge.meta`).
Prints the run_id on stdout (and nothing else) so callers can capture it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from ideaforge import config, db, meta, runs


def parent_idea_text(parent: str) -> str | None:
    with db.session() as conn:
        row = conn.execute("SELECT idea_text FROM runs WHERE run_id=?", (parent,)).fetchone()
    return row["idea_text"] if row else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("idea", nargs="?", default=None, help="the idea, in free text (default with --from: the parent's)")
    parser.add_argument("--preset", default=None, help="budget preset from config/budget.yaml")
    parser.add_argument("--from", dest="parent", default=None, help="parent run id (new idea version)")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="back-test date")
    args = parser.parse_args(argv)

    budget = config.budget()
    preset = args.preset or budget.default_preset
    if preset not in budget.presets:
        parser.error(f"unknown preset {preset!r}; choose from {sorted(budget.presets)}")

    db.init()
    idea = args.idea
    if args.parent:
        try:
            run_id, version, idea_id = runs.child_run(args.parent)
        except ValueError as e:
            parser.error(str(e))
        if idea is None or not idea.strip():
            idea = parent_idea_text(args.parent)
    if idea is None or not idea.strip():
        parser.error("idea text must not be empty")
    if not args.parent:
        run_id, version, idea_id = runs.new_run_id(idea), 1, runs.slugify(idea, 30)
    if runs.run_dir(run_id).exists():
        parser.error(f"run directory runs/{run_id} already exists")
    run_dir = runs.create_run_dir(run_id, idea)

    run_meta = meta.build(
        run_id,
        idea_id=idea_id,
        version=version,
        parent_run_id=args.parent,
        budget_preset=preset,
        as_of=args.as_of,
    )
    meta.write(run_dir, run_meta)

    db.create_run(
        run_id,
        idea,
        idea_id=idea_id,
        version=version,
        parent=args.parent,
        budget_preset=preset,
        as_of=args.as_of.isoformat() if args.as_of else None,
        stages=runs.STAGES,
    )
    runs.set_active(run_id)
    print(run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
