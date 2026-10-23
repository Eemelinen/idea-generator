"""Run lifecycle: run ids, run directories, the active-run marker and the stage state machine.

Stage statuses (the `stages` table): pending → running → done | failed, plus
insufficient_data for a research dimension that failed validation twice. A stage is
complete only when it is `insufficient_data`, or `done` and its output file(s) exist and
validate. `resume` repairs what a crash left behind; `next_stages` lists what to run.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from ideaforge import config, db
from ideaforge.schemas import RESEARCH_DIMENSIONS

# Ordered pipeline stages. Research is tracked per dimension so a resumed run
# skips the dimensions that already finished.
STAGES: list[str] = [
    "intake",
    "plan",
    *(f"research:{d}" for d in RESEARCH_DIMENSIONS),
    "verify",
    "synthesize",
    "score",
    "report",
]

# Stages run in groups; every stage of a group needs every stage of the earlier groups
# complete. The research dimensions form one group and run in parallel.
STAGE_GROUPS: list[list[str]] = [
    ["intake"],
    ["plan"],
    [s for s in STAGES if s.startswith("research:")],
    ["verify"],
    ["synthesize"],
    ["score"],
    ["report"],
]

# Run-relative output file(s) → validator kind ("research", a schemas.SCHEMAS / LIST_KINDS
# kind, or "markdown" for a report that only has to exist and be non-blank).
STAGE_OUTPUTS: dict[str, list[tuple[str, str]]] = {
    "intake": [("00_spec.json", "spec")],
    "plan": [("01_plan.json", "plan")],
    **{f"research:{d}": [(f"02_research/{d}.md", "research")] for d in RESEARCH_DIMENSIONS},
    "verify": [("03_claims/verified.json", "claims")],
    "synthesize": [("04_scores_proposed.json", "scores_proposed"), ("04_risks.json", "risks")],
    "score": [("04_scores.json", "scores")],
    "report": [("05_report.md", "markdown")],
}

COMPLETE = ("done", "insufficient_data")

ACTIVE_MARKER_NAME = ".active"
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]{1,40}(-v\d+)?$")


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > max_len:
        # Cut at the last word boundary that fits; fall back to a hard cut for one long word.
        cut = slug[: max_len + 1].rfind("-")
        slug = slug[:cut] if cut > 0 else slug[:max_len]
    return slug.rstrip("-") or "idea"


def new_run_id(idea_text: str, now: datetime | None = None) -> str:
    ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{slugify(idea_text, 30)}"


def run_dir(run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"not a valid run id: {run_id!r}")
    return config.RUNS_DIR / run_id


def create_run_dir(run_id: str, idea_text: str) -> Path:
    d = run_dir(run_id)
    for sub in ("02_research", "03_claims", "debate"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    (d / "idea.md").write_text(f"# Idea\n\n{idea_text.strip()}\n", encoding="utf-8")
    return d


def active_marker() -> Path:
    return config.RUNS_DIR / ACTIVE_MARKER_NAME


def set_active(run_id: str) -> None:
    config.RUNS_DIR.mkdir(exist_ok=True)
    active_marker().write_text(run_id, encoding="utf-8")


def active_run_id() -> str | None:
    """IDEAFORGE_RUN_ID wins; otherwise the runs/.active marker; otherwise None."""
    env = os.environ.get("IDEAFORGE_RUN_ID")
    if env:
        return env
    try:
        rid = active_marker().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return rid if rid and (config.RUNS_DIR / rid).is_dir() else None


# ---------------------------------------------------------------- stage state machine


class StageError(Exception):
    """A transition the state machine does not allow, or an output that does not validate."""


def _check_stage(stage: str) -> None:
    if stage not in STAGES:
        raise StageError(f"unknown stage {stage!r}; choose from {', '.join(STAGES)}")


def _run_dir(run_id: str) -> Path:
    try:
        return run_dir(run_id)
    except ValueError as e:
        raise StageError(str(e)) from None


def _check_run(run_id: str) -> None:
    d = _run_dir(run_id)
    with db.session() as conn:
        known = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if known is None or not d.is_dir():
        raise StageError(f"unknown run {run_id!r} (needs a runs/ directory and a db row; use new_run.py)")


def statuses(run_id: str) -> dict[str, str]:
    """Stage → status as stored; a stage without a row is pending."""
    stored = {r["stage"]: r["status"] for r in db.stages(run_id)}
    return {s: stored.get(s, "pending") for s in STAGES}


def output_problems(run_id: str, stage: str) -> list[str]:
    """Why the stage's output does not count (missing or invalid); empty when it validates."""
    from ideaforge import validate_file  # imports this module

    _check_stage(stage)
    d = _run_dir(run_id)
    problems = []
    for rel, kind in STAGE_OUTPUTS[stage]:
        path = d / rel
        try:
            if kind == "markdown":
                if not path.is_file():
                    raise validate_file.Invalid(f"{path} does not exist")
                if not path.read_text(encoding="utf-8", errors="replace").strip():
                    raise validate_file.Invalid(f"{path} is empty")
            else:
                validate_file.validate_path(path, kind)
        except validate_file.Invalid as e:
            problems.append(str(e))
    return problems


def is_complete(run_id: str, stage: str, status: str | None = None) -> bool:
    """insufficient_data, or done with an output that exists and validates."""
    status = status or statuses(run_id)[stage]
    if status not in COMPLETE:
        return False
    return status == "insufficient_data" or not output_problems(run_id, stage)


def _group_of(stage: str) -> int:
    return next(i for i, group in enumerate(STAGE_GROUPS) if stage in group)


def _blockers(run_id: str, stage: str, current: dict[str, str]) -> list[str]:
    """Stages of earlier groups that are not complete."""
    earlier = [s for group in STAGE_GROUPS[: _group_of(stage)] for s in group]
    return [s for s in earlier if not is_complete(run_id, s, current[s])]


def next_stages(run_id: str) -> list[str]:
    """The stages to run now: those of the first incomplete group that are pending or failed.

    Empty when every stage is complete, or when the first incomplete group only has stages
    that are running (wait for them). Several research dimensions can be returned at once.
    """
    _check_run(run_id)
    current = statuses(run_id)
    for group in STAGE_GROUPS:
        todo = [s for s in group if not is_complete(run_id, s, current[s])]
        if todo:
            return [s for s in todo if current[s] != "running"]
    return []


def begin(run_id: str, stage: str) -> None:
    """pending | failed → running. Every stage of the earlier groups must be complete."""
    _check_stage(stage)
    _check_run(run_id)
    current = statuses(run_id)
    status = current[stage]
    if status == "running":
        raise StageError(f"{stage} is already running; finish it, or run --resume after a crash")
    if is_complete(run_id, stage, status):
        raise StageError(f"{stage} is already {status}; skip it")
    blockers = _blockers(run_id, stage, current)
    if blockers:
        raise StageError(f"{stage} cannot begin before {', '.join(blockers)} complete")
    db.stage_set(run_id, stage, "running")


def finish(run_id: str, stage: str) -> None:
    """running → done when the output exists and validates, otherwise → failed (StageError)."""
    _check_stage(stage)
    _check_run(run_id)
    status = statuses(run_id)[stage]
    if status != "running":
        raise StageError(f"{stage} is {status}, not running; --begin it first")
    problems = output_problems(run_id, stage)
    if problems:
        db.stage_set(run_id, stage, "failed")
        raise StageError(f"{stage} failed: its output does not validate\n" + "\n".join(problems))
    db.stage_set(run_id, stage, "done")


def mark_insufficient(run_id: str, stage: str) -> None:
    """A research dimension that failed validation twice → insufficient_data (no output needed)."""
    _check_stage(stage)
    _check_run(run_id)
    if not stage.startswith("research:"):
        raise StageError(f"only a research stage can be insufficient_data, not {stage}")
    status = statuses(run_id)[stage]
    if is_complete(run_id, stage, status):
        raise StageError(f"{stage} is already {status}")
    db.stage_set(run_id, stage, "insufficient_data")


def resume(run_id: str) -> list[tuple[str, str, str]]:
    """Repair the stage table before re-running a run; returns (stage, old, new) per change.

    A `running` stage was left behind by a crash: its output decides, so a valid file becomes
    `done` (the work finished, the bookkeeping did not) and anything else goes back to
    `pending`. A `done` stage whose output has gone missing or invalid is also `pending` again.
    `failed` and `insufficient_data` stay; `next_stages` re-queues failed stages.
    """
    _check_run(run_id)
    changes = []
    for stage, status in statuses(run_id).items():
        if status not in ("running", "done"):
            continue
        valid = not output_problems(run_id, stage)
        new = "done" if valid else "pending"
        if new != status:
            db.stage_set(run_id, stage, new)
            changes.append((stage, status, new))
    return changes
