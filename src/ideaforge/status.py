"""Text for /status: the recent runs, or one run's stages, claims, kill flags, markers and usage;
`diff_runs` compares two runs' score sheets (IF-505). Review scores live in `ideaforge.review`.

Reads only what earlier stages wrote (SQLite and runs/<run_id>/); computes nothing that feeds a
score. A kill flag "fires" when a verified claim carries it (config/rubric.yaml); triggers the
spec overrides are still listed, marked as overridden, because score_run.py decides what they do.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from ideaforge import config, db, review, runs, scoring, usage
from ideaforge.schemas import KILL_TRIGGERS, RESEARCH_DIMENSIONS, RUBRIC_DIMENSIONS, DimensionScore, ScoreSheet
from ideaforge.synthesis import InputError, load_scores

STAGE_STATUSES = ("done", "insufficient_data", "running", "failed", "pending")
CLAIM_STATES = ("verified", "unverified", "conflict", "pending")
MARKER_PREFIXES = ("VALIDATION_FAILED_", "VALIDATION_WARNINGS_", "BUDGET_EXCEEDED_")
MARKER_TEXT_MAX = 100


def short_ts(ts: str | None) -> str:
    return ts[:19].replace("T", " ") if ts else "-"


def stage_line(stage_rows: list[sqlite3.Row]) -> str:
    """One line per run: each stage's status, the parallel research stages folded into counts."""
    parts: list[str] = []
    research: Counter[str] = Counter()
    research_at = 0  # the research summary goes where the first research stage is
    for r in stage_rows:
        if r["stage"].startswith("research:"):
            if not research:
                research_at = len(parts)
            research[r["status"]] += 1
        else:
            parts.append(f"{r['stage']} {r['status']}")
    if research:
        counts = ", ".join(f"{research[s]} {s}" for s in STAGE_STATUSES if research[s])
        parts.insert(research_at, f"research: {counts}")
    return " · ".join(parts) or "no stages"


def recent_runs(limit: int = 10) -> str:
    with db.session() as conn:
        run_rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC, run_id DESC LIMIT ?", (limit,)
        ).fetchall()
    if not run_rows:
        return "no runs yet; start one with /validate <idea>"
    lines = ["recent runs, newest first (times UTC)"]
    for r in run_rows:
        lines.append(f"{r['run_id']}  {short_ts(r['created_at'])}  {r['budget_preset']}  {r['status']}")
        lines.append(f"  {stage_line(db.stages(r['run_id']))}")
    return "\n".join(lines)


def claims_table(claim_rows: list[sqlite3.Row]) -> list[str]:
    counts: dict[str, Counter[str]] = {d: Counter() for d in RESEARCH_DIMENSIONS}
    for c in claim_rows:
        counts.setdefault(c["dimension"], Counter())[c["verification"]] += 1
    total: Counter[str] = sum(counts.values(), Counter())
    rows = [(d, *(n[s] for s in CLAIM_STATES), n.total()) for d, n in counts.items()]
    rows.append(("total", *(total[s] for s in CLAIM_STATES), total.total()))
    return usage.table(("dimension", *CLAIM_STATES, "total"), rows)


def spec_overrides(run_dir: Path) -> set[str]:
    try:
        spec = json.loads((run_dir / "00_spec.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    overrides = spec.get("kill_trigger_overrides") if isinstance(spec, dict) else None
    return {str(t) for t in overrides} if isinstance(overrides, list) else set()


def kill_flag_lines(claim_rows: list[sqlite3.Row], overrides: set[str]) -> list[str]:
    fired: dict[str, list[str]] = {}
    not_fired: dict[str, list[str]] = {}
    for c in claim_rows:
        try:
            flags = json.loads(c["flags"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(flags, list):
            continue
        for flag in (f for f in flags if isinstance(f, str) and f in KILL_TRIGGERS):
            if c["verification"] == "verified":
                fired.setdefault(flag, []).append(c["claim_id"])
            else:
                not_fired.setdefault(flag, []).append(f"{c['claim_id']} {c['verification']}")
    lines = [
        f"{flag}: {', '.join(sorted(ids))}" + (" (overridden in 00_spec.json)" if flag in overrides else "")
        for flag, ids in sorted(fired.items())
    ] or ["none"]
    if not_fired:
        lines.append("flagged only on claims that are not verified (not fired):")
        lines += [f"  {flag}: {', '.join(sorted(ids))}" for flag, ids in sorted(not_fired.items())]
    return lines


def marker_lines(run_dir: Path) -> list[str]:
    lines = []
    for p in sorted(run_dir.iterdir()):
        if not (p.is_file() and p.name.startswith(MARKER_PREFIXES)):
            continue
        text = usage.marker_text(p)
        first = text[0] if text else ""
        if len(first) > MARKER_TEXT_MAX:
            first = first[: MARKER_TEXT_MAX - 1] + "…"
        more = f" (+{len(text) - 1} more line(s))" if len(text) > 1 else ""
        lines.append(f"{p.name}: {first}{more}")
    return lines or ["none"]


def run_status(run_id: str) -> str:
    """Raises LookupError when the run has neither a DB row nor a directory."""
    run_dir = runs.run_dir(run_id)
    with db.session() as conn:
        run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        claim_rows = conn.execute(
            "SELECT claim_id, dimension, verification, flags FROM claims WHERE run_id=? ORDER BY claim_id",
            (run_id,),
        ).fetchall()
    if run is None and not run_dir.is_dir():
        raise LookupError(f"unknown run {run_id!r}")
    stage_rows = db.stages(run_id)

    lines = [f"run {run_id} (times UTC)"]
    if run is None:
        lines.append("not in the database")
    else:
        idea = run["idea_text"].strip().splitlines()[0] if run["idea_text"].strip() else ""
        lines.append(f"idea: {idea}")
        lines.append(f"created {short_ts(run['created_at'])} · preset {run['budget_preset']} · status {run['status']}")
    if not run_dir.is_dir():
        lines.append(f"warning: {run_dir.relative_to(config.ROOT)} does not exist")

    lines += ["", "stages"]
    if stage_rows:
        lines += usage.table(
            ("stage", "status", "attempts", "started", "finished"),
            # a restarted stage keeps its previous finished_at until it finishes again
            [(r["stage"], r["status"], r["attempts"], short_ts(r["started_at"]),
              "-" if r["status"] == "running" else short_ts(r["finished_at"]))
             for r in stage_rows],
            align="llrll",
        )
    else:
        lines.append("none")

    lines += ["", "claims per dimension", *claims_table(claim_rows)]
    lines += ["", "kill flags fired (verified claims)"]
    lines += kill_flag_lines(claim_rows, spec_overrides(run_dir))

    if run_dir.is_dir():
        lines += ["", "markers", *marker_lines(run_dir)]
        summary = usage.summarize(run_id, run_dir, stage_rows)
        t = summary.total
        lines += ["", f"usage: {t.calls} tool calls, {t.searches} searches, {t.fetches} fetches, ~{t.tokens} tokens"]
        if summary.skipped_lines:
            lines.append(f"warning: skipped {summary.skipped_lines} malformed line(s) in usage.jsonl")
        if t.calls:
            lines += usage.usage_table("stage", summary.by_stage, t)
    return "\n".join(lines)


# ---------------------------------------------------------------- score sheet diff (IF-505)


def _num(x: float) -> str:
    return f"{round(x, 2):g}"


def _change(a: float | None, b: float | None) -> str:
    if a is None or b is None:
        return "-"
    return f"{round(b - a, 2):+g}" if round(b - a, 2) else "0"


def _score_cell(s: DimensionScore | None) -> str:
    if s is None:
        return "-"
    if s.final_score is None:
        return "n/a"
    return f"{_num(s.final_score)} capped" if s.cap_reason else _num(s.final_score)


def _load_sheet(run_id: str) -> ScoreSheet:
    run_dir = runs.run_dir(run_id)
    if not run_dir.is_dir():
        raise LookupError(f"unknown run {run_id!r}: {run_dir.relative_to(config.ROOT)} does not exist")
    try:
        return load_scores(run_dir)
    except InputError as e:
        raise LookupError(f"run {run_id} has no valid 04_scores.json: {e}") from None


def _provenance(run_id: str) -> tuple[str, str, dict[str, str] | None]:
    """(idea version text, config text, models) from meta.json."""
    m = review.run_meta(run_id)
    idea = "meta.json missing or invalid" if m is None else f"idea {m.idea_id or '?'} v{m.version}"
    return (idea, *review.version_key(m))


def diff_runs(run_a: str, run_b: str) -> str:
    """Compare two runs' 04_scores.json: per-dimension final score, weighted total, verdict and
    kill triggers, with the prompt/config and model versions from meta.json. Raises
    ValueError / LookupError for a bad run id or a missing or invalid score sheet."""
    a, b = _load_sheet(run_a), _load_sheet(run_b)
    (idea_a, cfg_a, models_a), (idea_b, cfg_b, models_b) = _provenance(run_a), _provenance(run_b)
    lines = [
        "score sheet diff (04_scores.json, final scores)",
        f"A: {run_a} · {idea_a} · config {cfg_a} · models {review.models_text(models_a)}",
        f"B: {run_b} · {idea_b} · config {cfg_b} · models {review.models_text(models_b)}",
        f"config: same ({cfg_a})" if cfg_a == cfg_b else f"config: {cfg_a} → {cfg_b}",
    ]
    if models_a is None or models_b is None:
        lines.append("models: unknown (meta.json missing)")
    else:
        moved = [
            f"{role} {models_a.get(role, '-')} → {models_b.get(role, '-')}"
            for role in sorted(models_a.keys() | models_b.keys())
            if models_a.get(role) != models_b.get(role)
        ]
        lines.append(f"models: changed {', '.join(moved)}" if moved else "models: same")

    verdict = f"{a.verdict} → {b.verdict}" if a.verdict != b.verdict else f"{a.verdict} (same)"
    lines += [
        "",
        f"verdict: {verdict}",
        f"weighted total: {_num(a.weighted_total)} → {_num(b.weighted_total)}"
        f" ({_change(a.weighted_total, b.weighted_total)})",
        "",
    ]

    scores_a = {s.dimension: s for s in a.scores}
    scores_b = {s.dimension: s for s in b.scores}
    dims = [d for d in RUBRIC_DIMENSIONS if d in scores_a or d in scores_b]
    rows = []
    for d in dims:
        sa, sb = scores_a.get(d), scores_b.get(d)
        rows.append((
            d, _score_cell(sa), _score_cell(sb),
            _change(sa.final_score if sa else None, sb.final_score if sb else None),
        ))
    lines += usage.table(("dimension", "A", "B", "change"), rows) if rows else ["no dimension scores in either"]
    if any(s.cap_reason for s in (*a.scores, *b.scores)):
        lines.append(f"capped: the evidence rules capped the final score at {scoring.CAP:g} (insufficient data)")

    fired_a, fired_b = set(a.kill_triggers_fired), set(b.kill_triggers_fired)
    lines += ["", "kill triggers fired"]
    if not fired_a | fired_b:
        lines.append("none in either")
    for label, triggers in (
        ("in both", fired_a & fired_b),
        ("only in A", fired_a - fired_b),
        ("only in B", fired_b - fired_a),
    ):
        if triggers:
            lines.append(f"{label}: {', '.join(t for t in KILL_TRIGGERS if t in triggers)}")
    return "\n".join(lines)
