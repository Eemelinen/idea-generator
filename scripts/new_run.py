"""Create a new run: runs/<run_id>/ with idea.md and meta.json, db rows, active marker.

    uv run python scripts/new_run.py "<idea text>" [--preset economy|standard|deep]
                                     [--from <parent_run_id>] [--as-of YYYY-MM-DD]

Prints the run_id on stdout (and nothing else) so callers can capture it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import UTC, date, datetime

from ideaforge import config, db, runs
from ideaforge.schemas import RunMeta


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("idea", help="the idea, in free text")
    parser.add_argument("--preset", default=None, help="budget preset from config/budget.yaml")
    parser.add_argument("--from", dest="parent", default=None, help="parent run id (new idea version)")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="back-test date")
    args = parser.parse_args(argv)

    if not args.idea.strip():
        parser.error("idea text must not be empty")
    budget = config.budget()
    preset = args.preset or budget.default_preset
    if preset not in budget.presets:
        parser.error(f"unknown preset {preset!r}; choose from {sorted(budget.presets)}")

    db.init()
    version, idea_id = 1, runs.slugify(args.idea, 30)
    if args.parent:
        with db.session() as conn:
            row = conn.execute(
                "SELECT idea_id, version FROM idea_versions WHERE run_id=?", (args.parent,)
            ).fetchone()
        if row is None:
            parser.error(f"unknown parent run {args.parent!r}")
        version, idea_id = row["version"] + 1, row["idea_id"]

    run_id = runs.new_run_id(args.idea)
    if args.parent:
        run_id = f"{re.sub(r'-v\d+$', '', args.parent)}-v{version}"
    run_dir = runs.create_run_dir(run_id, args.idea)

    meta = RunMeta(
        run_id=run_id,
        parent_run_id=args.parent,
        created_at=datetime.now(UTC),
        git_commit=git_commit(),
        claude_code_version=None,
        models=dict(config.models().roles),
        budget_preset=preset,
        as_of=args.as_of,
    )
    (run_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    db.create_run(
        run_id,
        args.idea,
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
