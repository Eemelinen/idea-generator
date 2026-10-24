"""Debate output: render runs/<run_id>/debate/revised_plan.md from the judge's verdict (IF-405, IF-406).

    render(run_id)   → debate/revised_plan.md (once) + its `reports` row, the `assumptions` and
                       `experiments` tables and the finished `debates` row

`debate.finalize_verdict` first checks debate/verdict.json (every accepted change cites verified
claim ids) and computes `conformity_flag`; `debate.write_verdict` stores the computed flag in
verdict.json only after the plan and its rows are committed. The plan then shows,
diff-style against 05_report.md, the dimension scores the report gave and the judge's projection,
the weighted total of that projection (computed here, labelled a projection: only a new version's
run scores it) and the accepted changes; then the rejected changes, the assumption register and
the experiments ordered by info value per euro (a free experiment first). The judge decides
nothing that is not checked: its projected scores are proposals, as the synthesizer's are.

Like the report, the revised plan is written once and never overwritten. Rules chosen unattended
are TICKETS.md plan note 26.
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ideaforge import config, db, debate, report, runs, scoring
from ideaforge.schemas import Claim, Experiment, Verdict
from ideaforge.synthesis import InputError, load_claims, load_scores, load_spec

REVISED_PLAN = "revised_plan.md"


class PlanExists(Exception):
    """The run already has a revised plan; like the report it is immutable."""


def info_per_euro(e: Experiment) -> float:
    return math.inf if e.cost_eur == 0 else e.info_value / e.cost_eur


def experiment_order(experiments: list[Experiment]) -> list[Experiment]:
    """By info value per euro, highest first (free first); ties: higher info value, cheaper, faster, name."""
    return sorted(experiments, key=lambda e: (-info_per_euro(e), -e.info_value, e.cost_eur, e.days, e.name))


def per_100_eur(e: Experiment) -> str:
    return "free" if e.cost_eur == 0 else report.num(100 * e.info_value / e.cost_eur)


def score_diff(sheet_scores: dict[str, float | None], projected: dict[str, float], capped: set[str]) -> list[str]:
    """Unified-diff lines: unchanged dimensions as context, a changed one as `-` report / `+` projection.
    A projection above the cap of a dimension with insufficient data is marked: only new verified
    evidence in a new version can lift the cap."""
    width = max((len(d) for d in sheet_scores), default=0)
    lines = []
    for dim, final in sheet_scores.items():
        label = dim.ljust(width)
        if dim not in projected:
            lines.append(f"  {label}  {report.score_fmt(final)}  (not projected)")
        elif final is not None and projected[dim] == final:
            lines.append(f"  {label}  {report.score_fmt(final)}")
        else:
            lines.append(f"- {label}  {report.score_fmt(final)}")
            above = dim in capped and projected[dim] > scoring.CAP
            note = f"  (above the cap of {scoring.CAP:g}: insufficient data)" if above else ""
            lines.append(f"+ {label}  {report.score_fmt(projected[dim])}{note}")
    return lines


def projected_total(run_dir: Path, verdict: Verdict) -> float:
    """Σ weight × score with each projected dimension's score replaced by the judge's projection."""
    sheet = load_scores(run_dir)
    scores = [
        s.model_copy(update={"final_score": verdict.projected_scores[s.dimension]})
        if s.dimension in verdict.projected_scores
        else s
        for s in sheet.scores
    ]
    try:
        return scoring.weighted_total(scores, config.rubric())
    except ValueError as e:
        raise InputError(f"04_scores.json: {e}") from None


def context(run_id: str, final: debate.FinalVerdict, now: datetime) -> dict[str, Any]:
    run_dir = runs.run_dir(run_id)
    if not (run_dir / report.REPORT).exists():
        raise InputError(f"{report.REPORT} does not exist; the debate starts from the report (render_report.py)")
    spec = load_spec(run_dir)
    sheet = load_scores(run_dir)
    claims: dict[str, Claim] = {c.claim_id: c for c in load_claims(run_dir)}
    verdict = final.verdict
    row = db.get_report(run_id)
    report_changed = row is not None and (row["verdict"], row["weighted_total"]) != (sheet.verdict, sheet.weighted_total)
    total = projected_total(run_dir, verdict)
    return {
        "run_id": run_id,
        "generated_at": now.isoformat(timespec="seconds"),
        "spec": spec,
        "sheet": sheet,
        "report_name": report.REPORT,
        "report_changed": report_changed,
        "report_row": row,
        "rounds": final.rounds,
        "conformity_flag": verdict.conformity_flag,
        "judge_flag": final.judge_flag,
        "min_agree": debate.CONFORMITY_MIN_AGREE,
        "score_lines": score_diff(
            {s.dimension: s.final_score for s in sheet.scores},
            verdict.projected_scores,
            {s.dimension for s in sheet.scores if s.status == "insufficient_data"},
        ),
        "total_lines": (
            [f"  {report.num(sheet.weighted_total)}"]
            if round(total, 2) == round(sheet.weighted_total, 2)
            else [f"- {report.num(sheet.weighted_total)}", f"+ {report.num(total)}"]
        ),
        "accepted": [
            {"change": c, "claims": [claims[cid] for cid in c.claim_ids]} for c in verdict.accepted_changes
        ],
        "rejected": [
            {"change": c, "unknown": [cid for cid in c.claim_ids if cid not in claims]}
            for c in verdict.rejected_changes
        ],
        "assumptions": verdict.assumption_register,
        "experiments": [(e, per_100_eur(e)) for e in experiment_order(verdict.experiments)],
    }


def render_text(run_id: str, final: debate.FinalVerdict, now: datetime | None = None) -> str:
    """The revised plan's Markdown; reads the run's files and writes nothing."""
    ctx = context(run_id, final, now or datetime.now(UTC))
    text = report.environment().get_template("revised_plan.md.j2").render(ctx)
    return re.sub(r"\n{3,}", "\n\n", text)


@dataclass
class PlanResult:
    run_id: str
    path: Path
    verdict: Verdict
    experiments: list[Experiment]


def render(run_id: str, now: datetime | None = None) -> PlanResult:
    """Finalize the verdict, write debate/revised_plan.md and persist the tables, once.

    Raises PlanExists if the file or its `reports` row exists, debate.DebateError when the verdict
    or the debate's files do not pass, InputError when a run file is missing or invalid."""
    run_dir = runs.run_dir(run_id)
    path = run_dir / "debate" / REVISED_PLAN
    rel = path.relative_to(config.ROOT).as_posix()
    if path.exists():
        raise PlanExists(f"{rel} already exists; the revised plan is immutable (a new version is a new run)")
    if db.get_report(run_id, "revised_plan") is not None:
        raise PlanExists(f"run {run_id} already has a revised_plan row; the revised plan is immutable")
    if not (run_dir / report.REPORT).exists():
        raise InputError(f"{report.REPORT} does not exist; the debate starts from the report (render_report.py)")
    now = now or datetime.now(UTC)
    final = debate.finalize_verdict(run_id)
    text = render_text(run_id, final, now)
    experiments = experiment_order(final.verdict.experiments)
    try:
        db.add_revised_plan(
            run_id, rel, assumptions=final.verdict.assumption_register, experiments=experiments,
            conformity_flag=final.verdict.conformity_flag, rounds=final.rounds,
            created_at=now.isoformat(timespec="seconds"), then=lambda: report.write_new(path, text),
        )  # fmt: skip
        debate.write_verdict(run_id, final)
    except FileExistsError:
        raise PlanExists(f"{rel} was written concurrently; the revised plan is immutable") from None
    except sqlite3.IntegrityError as e:
        if "UNIQUE" not in str(e):
            raise
        raise PlanExists(f"run {run_id} already has a revised_plan row; the revised plan is immutable") from None
    return PlanResult(run_id, path, final.verdict, experiments)


__all__ = ["InputError", "PlanExists", "PlanResult", "experiment_order", "render", "render_text"]
