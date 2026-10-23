"""`runs/<run_id>/meta.json`: what produced a run (plan §6 stage 6).

Recorded once at creation: the repository HEAD, the last commit that touched the pipeline's
prompts and config (`PROVENANCE_PATHS`) and whether they had uncommitted changes, a snapshot
of the `config/models.yaml` roles, the Claude Code version and the idea version. `updated_at`
is refreshed by every stage transition (`runs.begin` / `finish` / `mark_insufficient` /
`resume`); `created_at` never changes. Every probe fails soft to `None`: a run must start
even without git or the `claude` CLI on PATH.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from ideaforge import config
from ideaforge.schemas import RunMeta

# Repository paths whose content decides what the pipeline does: prompts, agent templates
# (the generated .claude/agents/ follow from them) and config.
PROVENANCE_PATHS = ("config", "prompts", "agent_templates")

_VERSION_RE = re.compile(r"\d+\.\d+[\w.+-]*")


def _repo() -> Path:
    # config/ always lives in the repository (tests move ROOT, not CONFIG_DIR).
    return config.CONFIG_DIR.parent


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=_repo(), capture_output=True, text=True, encoding="utf-8", timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_commit() -> str | None:
    """HEAD of the repository, or None outside git."""
    return _git("rev-parse", "HEAD") or None


def config_commit() -> str | None:
    """The last commit that changed prompts, agent templates or config."""
    return _git("log", "-1", "--format=%H", "--", *PROVENANCE_PATHS) or None


def config_dirty() -> bool | None:
    """True when prompts, agent templates or config have uncommitted changes (None without git)."""
    out = _git("status", "--porcelain", "--", *PROVENANCE_PATHS)
    return None if out is None else bool(out)


def claude_code_version() -> str | None:
    """`claude --version` (e.g. "2.1.309"); `IDEAFORGE_CLAUDE_CODE_VERSION` overrides it."""
    env = os.environ.get("IDEAFORGE_CLAUDE_CODE_VERSION")
    if env:
        return env.strip()
    exe = shutil.which("claude")
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _VERSION_RE.search(out.stdout) if out.returncode == 0 else None
    return m.group(0) if m else None


def models_snapshot() -> dict[str, str]:
    return dict(config.models().roles)


def build(
    run_id: str,
    *,
    idea_id: str,
    version: int = 1,
    parent_run_id: str | None = None,
    budget_preset: str,
    as_of: date | None = None,
    now: datetime | None = None,
) -> RunMeta:
    ts = now or datetime.now(UTC)
    return RunMeta(
        run_id=run_id,
        idea_id=idea_id,
        version=version,
        parent_run_id=parent_run_id,
        created_at=ts,
        updated_at=ts,
        git_commit=git_commit(),
        config_commit=config_commit(),
        config_dirty=config_dirty(),
        claude_code_version=claude_code_version(),
        models=models_snapshot(),
        budget_preset=budget_preset,
        as_of=as_of,
    )


def write(run_dir: Path, meta: RunMeta) -> Path:
    path = run_dir / "meta.json"
    tmp = path.with_name("meta.json.tmp")
    tmp.write_text(meta.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load(run_dir: Path) -> RunMeta:
    return RunMeta.model_validate_json((run_dir / "meta.json").read_text(encoding="utf-8"))


def touch(run_dir: Path, now: datetime | None = None) -> bool:
    """Set `updated_at`; a missing or invalid meta.json is left alone (False)."""
    try:
        meta = load(run_dir)
    except (OSError, ValueError, ValidationError):
        return False
    write(run_dir, meta.model_copy(update={"updated_at": now or datetime.now(UTC)}))
    return True
