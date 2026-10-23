"""Run lifecycle: run ids, run directories and the active-run marker.

The stage state machine and resume logic land in ticket IF-214; this module
holds the stage list and the helpers every stage needs.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from ideaforge import config
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
