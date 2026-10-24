"""The runs dashboard (IF-601): one row per run, grouped into idea lineages, and the warnings for
runs/ and the database disagreeing.

Reads only: the `runs`, `idea_versions` and `stages` tables, `meta.json`, `04_scores.json` and
the debate files, through the same functions /status and /debate use (`status.stage_line`,
`usage.summarize`, `synthesis.load_scores`, `debate.progress`), so the two never disagree.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ideaforge import config, db, debate, review, runs, status, usage
from ideaforge.synthesis import InputError, load_scores

UNSCORED = "none"  # the verdict filter's value for runs without a valid score sheet


@dataclass
class RunRow:
    run_id: str
    title: str
    created_at: str
    idea_id: str
    version: int
    parent: str | None
    preset: str
    as_of: str | None
    run_status: str
    stages_done: int
    stages_total: int
    stage_line: str
    verdict: str | None = None
    weighted_total: float | None = None
    debate: str = "-"
    usage: usage.Tally = field(default_factory=usage.Tally)
    has_dir: bool = True


@dataclass
class Lineage:
    idea_id: str
    runs: list[RunRow]  # newest version first


@dataclass
class Mismatch:
    dirs_without_row: list[str]  # runs/<run_id>/ with no `runs` row
    rows_without_dir: list[str]  # `runs` rows with no directory

    def __bool__(self) -> bool:
        return bool(self.dirs_without_row or self.rows_without_dir)


def _title(idea_text: str) -> str:
    text = idea_text.strip()
    return text.splitlines()[0] if text else "(no idea text)"


def debate_state(run_id: str, run_dir: Path) -> str:
    """`done`, `not started`, the next step as `python -m ideaforge.debate status` prints it,
    or `-` when the run has no report to debate yet."""
    if (run_dir / "debate" / "revised_plan.md").exists():
        return "done"
    if not (run_dir / "05_report.md").exists():
        return "-"
    d = run_dir / "debate"
    if not ((d / "round0").is_dir() or (d / debate.EVIDENCE_DIR).is_dir()):
        return "not started"
    try:
        return debate.progress(run_id).line()
    except (debate.DebateError, OSError, ValueError) as e:
        return f"error: {e}"


def _row(r: sqlite3.Row, stage_rows: list[sqlite3.Row]) -> RunRow:
    run_dir = runs.run_dir(r["run_id"])
    row = RunRow(
        run_id=r["run_id"],
        title=_title(r["idea_text"]),
        created_at=r["created_at"],
        idea_id=r["idea_id"] or r["run_id"],
        version=r["version"] or 1,
        parent=r["parent"],
        preset=r["budget_preset"],
        as_of=r["as_of"],
        run_status=r["status"],
        stages_done=sum(s["status"] in runs.COMPLETE for s in stage_rows),
        stages_total=len(stage_rows),
        stage_line=status.stage_line(stage_rows),
        has_dir=run_dir.is_dir(),
    )
    if not row.has_dir:
        return row
    m = review.run_meta(row.run_id)
    if r["idea_id"] is None and m is not None:  # no idea_versions row: fall back to meta.json
        row.idea_id, row.version, row.parent = m.idea_id or row.run_id, m.version, m.parent_run_id
    try:
        sheet = load_scores(run_dir)
        row.verdict, row.weighted_total = sheet.verdict, sheet.weighted_total
    except InputError:
        pass
    row.debate = debate_state(row.run_id, run_dir)
    row.usage = usage.summarize(row.run_id, run_dir, stage_rows).total
    return row


def run_rows() -> list[RunRow]:
    """Every run in the database, newest first."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT r.*, v.idea_id, v.version, v.parent FROM runs r"
            " LEFT JOIN idea_versions v ON v.run_id = r.run_id"
            " ORDER BY r.created_at DESC, r.run_id DESC"
        ).fetchall()
    result = []
    for r in rows:
        try:
            result.append(_row(r, db.stages(r["run_id"])))
        except ValueError:  # not a valid run id: it cannot have a directory
            continue
    return result


def filter_rows(rows: list[RunRow], *, verdict: str | None = None, idea: str | None = None) -> list[RunRow]:
    if verdict:
        rows = [r for r in rows if (r.verdict or UNSCORED) == verdict]
    if idea:
        rows = [r for r in rows if r.idea_id == idea]
    return rows


def lineages(rows: list[RunRow]) -> list[Lineage]:
    """Runs grouped by idea_id; the group with the newest run first, versions newest first."""
    groups: dict[str, Lineage] = {}
    for r in rows:  # rows are newest first, so groups are created in that order
        groups.setdefault(r.idea_id, Lineage(r.idea_id, [])).runs.append(r)
    for g in groups.values():
        g.runs.sort(key=lambda r: (r.version, r.created_at), reverse=True)
    return list(groups.values())


def mismatch() -> Mismatch:
    """Run directories (named like a run id) without a `runs` row, and rows without a directory."""
    with db.session() as conn:
        ids = {r["run_id"] for r in conn.execute("SELECT run_id FROM runs")}
    dirs = (
        {p.name for p in config.RUNS_DIR.iterdir() if p.is_dir() and runs.RUN_ID_RE.match(p.name)}
        if config.RUNS_DIR.is_dir()
        else set()
    )
    return Mismatch(sorted(dirs - ids), sorted(ids - dirs))
