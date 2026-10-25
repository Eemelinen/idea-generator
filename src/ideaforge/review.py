"""Human review scores for /status (plan §9 "Human review", IF-504).

    pending(run_id)                 → the report's sections and the scores already stored
    store(run_id, ["verdict=4", "risks=2:too generic", …])  → `reviews` rows
    trend()                         → the mean score per section for each prompt/model version
                                      (`trend_data()`: the same as rows, for the web UI)

The user scores each `05_report.md` section 1–5; a section left out keeps its earlier score (or
none). Scoring a section again replaces its score. The trend groups the reviewed runs by what
produced them, from each run's `meta.json`: the last commit that touched config/, prompts/ or
agent_templates/ (marked `+dirty` when they had uncommitted changes) and the `config/models.yaml`
roles. A run without a valid `meta.json` falls into an "unknown" group. Reviews never feed a
score, cap or verdict: they only show drift after a prompt or model change.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ideaforge import db, meta, runs, usage
from ideaforge.report import REPORT
from ideaforge.schemas import RunMeta

# Every `## ` section of templates/report.md.j2, in report order (tests/test_status.py checks
# that the two agree). The ids are what the user types: `verdict=4`.
SECTIONS: dict[str, str] = {
    "verdict": "Verdict",
    "score_table": "Score table",
    "kill_triggers": "Kill triggers",
    "unit_economics": "Unit economics",
    "dimensions": "Dimensions",
    "funding": "Finland funding fit",
    "location": "Location notes",
    "risks": "Risk register",
    "business_plan": "Starttiraha business-plan draft",
    "sources": "Sources",
    "usage": "Usage summary",
}
_ENTRY_RE = re.compile(r"^(?P<section>[a-z_]+)=(?P<score>[^:]*)(?::(?P<note>.*))?$", re.S)
UNKNOWN = "unknown"


class ReviewError(ValueError):
    """A bad review entry, or a run that cannot be reviewed."""


def parse(entries: list[str]) -> dict[str, tuple[int, str | None]]:
    """`section=score` or `section=score:note` → {section: (score, note)}; raises ReviewError."""
    parsed: dict[str, tuple[int, str | None]] = {}
    for entry in entries:
        m = _ENTRY_RE.match(entry.strip())
        if m is None:
            raise ReviewError(f"expected section=score[:note], got {entry!r}")
        section, score = m["section"], m["score"].strip()
        if section not in SECTIONS:
            raise ReviewError(f"unknown section {section!r}; sections: {', '.join(SECTIONS)}")
        if section in parsed:
            raise ReviewError(f"section {section!r} given twice")
        if score not in {"1", "2", "3", "4", "5"}:
            raise ReviewError(f"{section}: the score must be a whole number 1–5, got {score!r}")
        note = (m["note"] or "").strip() or None
        parsed[section] = (int(score), note)
    return parsed


def _check_run(run_id: str) -> None:
    run_dir = runs.run_dir(run_id)
    with db.session() as conn:
        row = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise LookupError(f"unknown run {run_id!r}")
    if not (run_dir / REPORT).is_file():
        raise ReviewError(f"run {run_id} has no {REPORT} to review yet; run /synthesize {run_id} first")


def stored(run_id: str) -> dict[str, tuple[int, str | None]]:
    with db.session() as conn:
        rows = conn.execute("SELECT section, score, note FROM reviews WHERE run_id=?", (run_id,)).fetchall()
    return {r["section"]: (r["score"], r["note"]) for r in rows}


def pending(run_id: str) -> str:
    """The sections to score, with any earlier scores. Raises LookupError / ReviewError."""
    _check_run(run_id)
    earlier = stored(run_id)

    def shown(section: str) -> str:
        if section not in earlier:
            return "-"
        score, note = earlier[section]
        return f"{score} ({note})" if note else str(score)

    lines = [
        f"review of runs/{run_id}/{REPORT}: score each section 1 (useless) to 5 (excellent)",
        *usage.table(
            ("section", "report heading", "stored"),
            [(s, heading, shown(s)) for s, heading in SECTIONS.items()],
            align="lll",
        ),
        "",
        f"store: uv run python scripts/status.py {run_id} --review section=score[:note] …",
    ]
    return "\n".join(lines)


def store(run_id: str, entries: list[str]) -> str:
    """Upsert the given section scores in one transaction; returns a confirmation line."""
    parsed = parse(entries)
    if not parsed:
        raise ReviewError("no section scores given")
    _check_run(run_id)
    ts = db.now()
    with db.session() as conn:
        conn.executemany(
            """
            INSERT INTO reviews(run_id, section, score, note, created_at) VALUES (?,?,?,?,?)
            ON CONFLICT(run_id, section) DO UPDATE SET
                score=excluded.score, note=excluded.note, created_at=excluded.created_at
            """,
            [(run_id, s, score, note, ts) for s, (score, note) in parsed.items()],
        )
    missing = [s for s in SECTIONS if s not in stored(run_id)]
    tail = f"; not scored yet: {', '.join(missing)}" if missing else "; every section is scored"
    return f"stored {len(parsed)} review score(s) for {run_id}{tail}"


# ---------------------------------------------------------------- trend


@dataclass
class Version:
    """One prompt/config + models combination, in order of its first reviewed run."""

    label: str
    config: str
    models: dict[str, str] | None
    run_ids: list[str] = field(default_factory=list)
    scores: dict[str, list[int]] = field(default_factory=dict)


def run_meta(run_id: str) -> RunMeta | None:
    try:
        return meta.load(runs.run_dir(run_id))
    except (OSError, ValueError):
        return None


def version_key(m: RunMeta | None) -> tuple[str, dict[str, str] | None]:
    """(config text, models): `abc1234`, `abc1234+dirty` or `no-git`, and the models roles."""
    if m is None:
        return UNKNOWN, None
    config = (m.config_commit or "no-git")[:7] + ("+dirty" if m.config_dirty else "")
    return config, dict(m.models)


def models_text(models: dict[str, str] | None) -> str:
    """`opus (all roles)` or `opus except judge=sonnet, synthesizer=sonnet`."""
    if models is None:
        return UNKNOWN
    if not models:
        return "none recorded"
    common = Counter(models.values()).most_common(1)[0][0]
    other = sorted(f"{role}={m}" for role, m in models.items() if m != common)
    return f"{common} (all roles)" if not other else f"{common} except {', '.join(other)}"


def _label(i: int) -> str:
    label = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        label = chr(ord("A") + r) + label
    return label


def versions() -> list[Version]:
    """The reviewed runs grouped by version, oldest run first."""
    with db.session() as conn:
        rows = conn.execute(
            """
            SELECT v.run_id, v.section, v.score FROM reviews v JOIN runs r ON r.run_id = v.run_id
            ORDER BY r.created_at, r.run_id
            """
        ).fetchall()
    groups: dict[str, Version] = {}
    run_groups: dict[str, Version] = {}
    for r in rows:
        run_id = r["run_id"]
        if run_id not in run_groups:
            config, models = version_key(run_meta(run_id))
            key = repr((config, sorted(models.items()) if models is not None else None))
            if key not in groups:
                groups[key] = Version(_label(len(groups)), config, models)
            run_groups[run_id] = groups[key]
            groups[key].run_ids.append(run_id)
        run_groups[run_id].scores.setdefault(r["section"], []).append(r["score"])
    return list(groups.values())


def _mean(values: list[int]) -> str:
    return f"{sum(values) / len(values):.1f}" if values else "-"


@dataclass
class Trend:
    """The trend /status --reviews prints and the web UI's reviews page shows (IF-606)."""

    versions: list[Version]
    section_rows: list[tuple[str, ...]]  # (section, the mean per version …), then all sections and runs
    run_rows: list[tuple[str, str, int, str]]  # (run, version label, sections scored, mean)


def trend_data() -> Trend:
    vs = versions()
    rows: list[tuple[str, ...]] = [(s, *(_mean(v.scores.get(s, [])) for v in vs)) for s in SECTIONS]
    rows.append(("all sections", *(_mean([x for xs in v.scores.values() for x in xs]) for v in vs)))
    rows.append(("runs", *(str(len(v.run_ids)) for v in vs)))
    run_rows = [
        (run_id, v.label, len(per_run := stored(run_id)), _mean([score for score, _ in per_run.values()]))
        for v in vs
        for run_id in v.run_ids
    ]
    return Trend(vs, rows, run_rows)


def version_line(v: Version) -> str:
    return f"{v.label}: config {v.config} · models {models_text(v.models)} · {len(v.run_ids)} run(s)"


def trend() -> str:
    t = trend_data()
    if not t.versions:
        return "no reviews yet; score a report with /status <run_id> --review"
    lines = ["review scores by prompt/config and model version (oldest first; mean of 1–5)"]
    lines += [version_line(v) for v in t.versions]
    lines += ["", *usage.table(("section", *(v.label for v in t.versions)), t.section_rows)]
    lines += ["", "reviewed runs"]
    lines += usage.table(("run", "version", "sections", "mean"), t.run_rows, align="llrr")
    return "\n".join(lines)
