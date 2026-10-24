"""The run page (IF-605): one run's stages and markers, idea spec and research plan, claim ledger,
score sheet, unit economics, report, usage and a read-only browser over runs/<run_id>/.

Reads only, through the pipeline's own loaders and helpers (`synthesis.load_*`,
`verify.load_conflicts`, `status`, `usage.summarize`, `report.kill_trigger_rows` /
`economics_rows` / `sensitivity_grid`), so a figure here matches /status, the usage report and
05_report.md. A stage file that does not exist yet is reported as "not run yet", one that does
not validate as an error; neither fails the page.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Generic, TypeVar, get_args

from markdown_it import MarkdownIt
from markupsafe import Markup, escape
from pydantic import TypeAdapter

from ideaforge import db, debate, report, runs, status, usage
from ideaforge.schemas import (
    CLAIM_ID_RE,
    KILL_TRIGGERS,
    RESEARCH_DIMENSIONS,
    Claim,
    ClaimFlag,
    ConflictGroup,
    ResearchPlan,
    ScoreSheet,
    SourceType,
)
from ideaforge.synthesis import InputError, load_claims, load_scores, load_spec
from ideaforge.verify import load_conflicts

T = TypeVar("T")

# (key, label, URL suffix); the stages tab is the run page itself.
TABS = (
    ("stages", "Stages", ""),
    ("idea", "Idea", "/idea"),
    ("claims", "Claims", "/claims"),
    ("scores", "Scores", "/scores"),
    ("economics", "Economics", "/economics"),
    ("report", "Report", "/report"),
    ("usage", "Usage", "/usage"),
    ("files", "Files", "/files"),
)
# The stage whose output a tab shows, named when that output does not exist yet.
TAB_STAGE = {
    "idea": "intake",
    "claims": "verify",
    "scores": "score",
    "economics": "score",
    "report": "report",
}
CLAIMS_FILE = "03_claims/verified.json"
CLAIMS_TABLE = "the claims table"
TEXT_VIEW_MAX = 1_000_000  # bytes; a larger or non-UTF-8 file is offered for download only
CLAIM_REF_RE = re.compile(r"\b[a-z_]+-\d{3,}\b")


class NotFound(Exception):
    """An unknown run, or a file path the browser refuses."""


@dataclass
class Loaded(Generic[T]):
    """A run file: `value` when it validates, `error` when it exists but does not, neither when
    it does not exist yet."""

    path: str  # run-relative
    value: T | None = None
    error: str | None = None

    @property
    def missing(self) -> bool:
        return self.value is None and self.error is None


def _load(run_dir: Path, rel: str, loader: Callable[[Path], T]) -> Loaded[T]:
    if not (run_dir / rel).is_file():
        return Loaded(rel)
    try:
        return Loaded(rel, value=loader(run_dir))
    except InputError as e:
        return Loaded(rel, error=str(e).replace(str(run_dir) + os.sep, ""))
    except (OSError, ValueError) as e:
        return Loaded(rel, error=f"{rel} is not valid: {e}")


# ---------------------------------------------------------------- run header and stages


@dataclass
class Run:
    run_id: str
    run_dir: Path
    title: str = ""
    idea_text: str = ""
    created_at: str | None = None
    preset: str | None = None
    as_of: str | None = None
    run_status: str | None = None
    in_db: bool = False
    has_dir: bool = False


def run(run_id: str) -> Run:
    """The run's DB row and directory; NotFound for a bad id or a run with neither."""
    try:
        run_dir = runs.run_dir(run_id)
    except ValueError as e:
        raise NotFound(str(e)) from None
    with db.session() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    r = Run(run_id, run_dir, has_dir=run_dir.is_dir() and not run_dir.is_symlink())
    if row is None and not r.has_dir:
        raise NotFound(f"unknown run {run_id!r}")
    if row is not None:
        r.in_db = True
        r.idea_text = row["idea_text"]
        r.created_at, r.preset, r.as_of, r.run_status = (
            row["created_at"], row["budget_preset"], row["as_of"], row["status"],
        )
    elif (run_dir / "idea.md").is_file():
        r.idea_text = (run_dir / "idea.md").read_text(encoding="utf-8", errors="replace")
    text = r.idea_text.strip()
    r.title = text.splitlines()[0] if text else "(no idea text)"
    return r


@dataclass
class StageRow:
    stage: str
    status: str
    attempts: int
    started: str
    finished: str


@dataclass
class Marker:
    name: str
    lines: list[str]


def stage_rows(run_id: str) -> list[StageRow]:
    # as in /status: a restarted stage keeps its previous finished_at until it finishes again
    return [
        StageRow(r["stage"], r["status"], r["attempts"], status.short_ts(r["started_at"]),
                 "-" if r["status"] == "running" else status.short_ts(r["finished_at"]))
        for r in db.stages(run_id)
    ]


def markers(run_dir: Path) -> list[Marker]:
    """The BUDGET_EXCEEDED_*, VALIDATION_WARNINGS_* and VALIDATION_FAILED_* files, full text."""
    if not run_dir.is_dir():
        return []
    return [
        Marker(p.name, usage.marker_text(p))
        for p in sorted(run_dir.iterdir())
        if p.is_file() and not p.is_symlink() and p.name.startswith(status.MARKER_PREFIXES)
    ]


def stage_status(run_id: str, stage: str) -> str | None:
    with db.session() as conn:
        row = conn.execute("SELECT status FROM stages WHERE run_id=? AND stage=?", (run_id, stage)).fetchone()
    return row["status"] if row else None


# ---------------------------------------------------------------- idea


@dataclass
class Idea:
    idea_md: str | None
    spec: Loaded[Any]
    plan: Loaded[ResearchPlan]


def _plan(run_dir: Path) -> ResearchPlan:
    return TypeAdapter(ResearchPlan).validate_json((run_dir / "01_plan.json").read_bytes())


def idea(run_dir: Path) -> Idea:
    md = run_dir / "idea.md"
    return Idea(
        md.read_text(encoding="utf-8", errors="replace") if md.is_file() else None,
        _load(run_dir, "00_spec.json", load_spec),
        _load(run_dir, "01_plan.json", _plan),
    )


# ---------------------------------------------------------------- claims


@dataclass
class Ledger:
    claims: list[Claim]
    source: str | None  # CLAIMS_FILE, CLAIMS_TABLE, or None when neither has claims
    error: str | None = None  # verified.json exists but does not validate
    conflicts: list[ConflictGroup] = field(default_factory=list)
    conflicts_error: str | None = None

    def by_id(self) -> dict[str, Claim]:
        return {c.claim_id: c for c in self.claims}


def _db_claims(run_id: str) -> list[Claim]:
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM claims WHERE run_id=? ORDER BY claim_id", (run_id,)).fetchall()
    result = []
    for r in rows:
        data = {k: r[k] for k in r.keys() if k != "run_id"}
        try:
            data["flags"] = json.loads(data["flags"])
            result.append(Claim.model_validate(data))
        except (ValueError, TypeError):  # a malformed row is left out rather than failing the page
            continue
    return result


def ledger(run_id: str, run_dir: Path) -> Ledger:
    """The claims from 03_claims/verified.json (what scoring reads); while it does not exist or
    does not validate, the rows of the claims table."""
    loaded = _load(run_dir, CLAIMS_FILE, load_claims)
    if loaded.value is not None:
        result = Ledger(loaded.value, CLAIMS_FILE)
    else:
        claims = _db_claims(run_id)
        result = Ledger(claims, CLAIMS_TABLE if claims else None, error=loaded.error)
    try:
        result.conflicts = load_conflicts(run_dir)
    except (OSError, ValueError) as e:
        result.conflicts_error = f"03_claims/conflicts.json is not valid: {e}"
    return result


@dataclass
class ClaimFilters:
    dimension: str = ""
    verification: str = ""
    source_type: str = ""
    flag: str = ""

    def active(self) -> bool:
        return any((self.dimension, self.verification, self.source_type, self.flag))


def filter_claims(claims: Iterable[Claim], f: ClaimFilters) -> list[Claim]:
    return [
        c for c in claims
        if (not f.dimension or c.dimension == f.dimension)
        and (not f.verification or c.verification == f.verification)
        and (not f.source_type or c.source_type == f.source_type)
        and (not f.flag or f.flag in c.flags)
    ]


def claim_options(claims: list[Claim]) -> dict[str, list[str]]:
    """Filter choices: every value the schema allows for states and flags, the ledger's own
    dimensions and source types."""
    return {
        "dimension": [d for d in RESEARCH_DIMENSIONS if any(c.dimension == d for c in claims)],
        "verification": list(status.CLAIM_STATES),
        "source_type": [s for s in get_args(SourceType) if any(c.source_type == s for c in claims)],
        "flag": list(get_args(ClaimFlag)),
    }


def claim_href(run_id: str, claim_id: str) -> str:
    return f"/runs/{run_id}/claims#claim-{claim_id}"


def link_claims(text: str, run_id: str, known: set[str]) -> Markup:
    """`text` escaped, with every claim id of the ledger in it linked to the claims tab."""
    out, last = [], 0
    for m in CLAIM_REF_RE.finditer(text):
        if m.group() not in known or not CLAIM_ID_RE.match(m.group()):
            continue
        out.append(escape(text[last:m.start()]))
        out.append(Markup('<a href="{}">{}</a>').format(claim_href(run_id, m.group()), m.group()))
        last = m.end()
    out.append(escape(text[last:]))
    return Markup("").join(out)


# ---------------------------------------------------------------- scores and economics


@dataclass
class Scores:
    sheet: Loaded[ScoreSheet]
    kill_rows: list[dict[str, Any]] = field(default_factory=list)
    overrides: list[str] = field(default_factory=list)
    economics_rows: list[tuple[str, str]] = field(default_factory=list)
    sensitivity: dict[str, Any] | None = None


def scores(run_dir: Path, claims: list[Claim]) -> Scores:
    result = Scores(_load(run_dir, "04_scores.json", load_scores))
    overrides = status.spec_overrides(run_dir)
    result.overrides = [t for t in KILL_TRIGGERS if t in overrides]
    sheet = result.sheet.value
    if sheet is not None:
        result.kill_rows = report.kill_trigger_rows(sheet, claims, overrides)
        result.economics_rows = report.economics_rows(sheet)
        result.sensitivity = report.sensitivity_grid(sheet)
    return result


# ---------------------------------------------------------------- report


def render_markdown(text: str) -> Markup:
    """CommonMark plus tables; HTML in the Markdown is escaped, unsafe link schemes are dropped."""
    return Markup(MarkdownIt("commonmark", {"html": False}).enable("table").render(text))


# ---------------------------------------------------------------- usage


@dataclass
class Usage:
    summary: usage.UsageSummary
    by_stage: list[tuple[str, usage.Tally]]
    by_agent: list[tuple[str, usage.Tally]]


def usage_view(run_id: str, run_dir: Path, rows: list[sqlite3.Row]) -> Usage:
    s = usage.summarize(run_id, run_dir, rows)
    return Usage(s, usage.ordered("stage", s.by_stage), usage.ordered("agent", s.by_agent))


# ---------------------------------------------------------------- files


@dataclass
class FileEntry:
    path: str  # run-relative, with /
    size: int


def withheld(run_dir: Path, rel: PurePosixPath) -> bool:
    """The debate's role mapping stays hidden until the verdict exists (as in the debate tab,
    IF-606: role names only after the verdict)."""
    return rel == PurePosixPath("debate", debate.MAPPING_NAME) and not (run_dir / "debate" / debate.VERDICT_NAME).is_file()


def list_files(run_dir: Path) -> list[FileEntry]:
    """Every regular file under the run directory, sorted; symlinks are neither listed nor followed."""
    if not run_dir.is_dir() or run_dir.is_symlink():
        return []
    entries = []
    for dirpath, dirnames, filenames in os.walk(run_dir):
        base = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not (base / d).is_symlink())
        for name in filenames:
            p = base / name
            if p.is_symlink() or not p.is_file():
                continue
            rel = PurePosixPath(p.relative_to(run_dir).as_posix())
            if not withheld(run_dir, rel):
                entries.append(FileEntry(str(rel), p.stat().st_size))
    return sorted(entries, key=lambda e: e.path)


def safe_file(run_dir: Path, rel: str) -> Path:
    """The file `rel` names inside the run directory. NotFound for an absolute path, a `..`
    segment, a symlink anywhere on the way, a path that resolves outside the run directory, or
    anything but a regular file."""
    if (
        not rel
        or "\\" in rel
        or "\0" in rel
        or PurePosixPath(rel).is_absolute()
        or PureWindowsPath(rel).drive
        or PureWindowsPath(rel).is_absolute()
    ):
        raise NotFound(f"not a run-relative path: {rel!r}")
    if any(part in ("", ".", "..") for part in rel.split("/")):
        raise NotFound(f"not a run-relative path: {rel!r}")
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise NotFound("the run has no directory")
    p = run_dir
    for part in rel.split("/"):
        p = p / part
        if p.is_symlink():
            raise NotFound(f"{rel} is a symlink")
    try:
        p.resolve(strict=True).relative_to(run_dir.resolve(strict=True))
    except (OSError, ValueError):
        raise NotFound(f"{rel} is not inside the run directory") from None
    if not p.is_file() or withheld(run_dir, PurePosixPath(rel)):
        raise NotFound(f"{rel} is not a file of this run")
    return p


def file_text(path: Path) -> str | None:
    """The file as text for the viewer, or None when it is too large or not UTF-8."""
    if path.stat().st_size > TEXT_VIEW_MAX:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
