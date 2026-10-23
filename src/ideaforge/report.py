"""Stage 5 report: render runs/<run_id>/05_report.md from the run's files (IF-305, IF-306).

    render(run_id)   → 05_report.md (once) + its `reports` row

The report presents what earlier stages decided and computes nothing that decides the outcome:
scores, caps, kill triggers, the verdict and the unit economics come from 04_scores.json
(score_run.py), the claims and their verification from 03_claims/verified.json, the risks from
04_risks.json, the gaps from each research file's `## Gaps` section and the usage summary from
usage.jsonl (`usage.render_summary`).

Finland funding fit: each programme (starttiraha, Leader / Jetina, elinvoimakeskus, Finnvera) is
backed by the verified claims on an allow-listed official domain (`verify.is_official`) that name
it, or shown as "unverified – see gaps". `config/finland.yaml` is never read here: its values are
hints to verify, never facts. The Rääkkylä notes are the location claims plus the claims that name
Rääkkylä, Keski-Karjala or North Karelia.

Reports are immutable: an existing 05_report.md or `reports` row is never overwritten; a new
version is a new run (IF-308). Rules chosen unattended are TICKETS.md plan note 23.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ideaforge import config, db, runs, scoring, usage, verify
from ideaforge.schemas import KILL_TRIGGERS, RUBRIC_DIMENSIONS, Claim, IdeaSpec, RiskItem, ScoreSheet
from ideaforge.synthesis import InputError, load_claims, load_risks, load_scores, load_spec

REPORT = "05_report.md"
TEMPLATES_DIR = Path(__file__).parent / "templates"
CAP_LABEL = f"capped at {scoring.CAP:g}"
UNVERIFIED_GAP = "unverified – see gaps"


class ReportExists(Exception):
    """The run already has a report; reports are immutable."""


@dataclass(frozen=True)
class Programme:
    key: str
    name: str
    pattern: re.Pattern[str]
    domains: tuple[str, ...] = ()  # official domains that are the programme's own site


# Only `financing` claims are about a programme: elinvoimakeskus.fi also hosts environmental and
# shoreline permits, and "leader" or "starttiraha" appear in competition and tax claims. A
# financing claim is about a programme when its statement, source title or quote names it, or its
# URL is on the programme's own site; only the verified ones on an allow-listed domain back it.
PROGRAMMES = (
    Programme("starttiraha", "Starttiraha (start-up grant)", re.compile(r"starttirah|start-?up grant", re.I)),
    Programme("leader", "Leader (Jetina)", re.compile(r"jetina|\bleader\b(?!ship)", re.I), ("jetina.fi",)),
    Programme(
        "elinvoimakeskus",
        "Elinvoimakeskus business development grants",
        re.compile(r"elinvoimakesk|\bely-keskus|\bely cent(?:re|er)", re.I),
        ("elinvoimakeskus.fi",),
    ),
    Programme("finnvera", "Finnvera loans and guarantees", re.compile(r"finnvera", re.I), ("finnvera.fi",)),
)
LOCAL_RE = re.compile(r"r[aä][aä]kkyl[aä]|keski-karjala|central karelia|pohjois-karjala|north karelia", re.I)
GAPS_RE = re.compile(r"^##\s+Gaps\s*$(.*?)(?=^##\s|\Z)", re.I | re.M | re.S)
LIST_MARK_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


# ---------------------------------------------------------------- formatting


def cell(value: Any) -> str:
    """Text safe inside a Markdown table cell: one line, pipes escaped."""
    return " ".join(str(value).split()).replace("|", "\\|")


def num(x: float | None, digits: int = 2) -> str:
    return "–" if x is None else f"{x:,.{digits}f}".replace(",", " ")


def score_fmt(x: float | None) -> str:
    return "–" if x is None else f"{x:g}"


def pct_change(x: float) -> str:
    return "0 %" if x == 0 else f"{x:+g} %"


def link(title: str, url: str) -> str:
    title = " ".join(title.split()).replace("[", "(").replace("]", ")") or url
    return f"[{title}](<{url}>)"


def value_fmt(c: Claim) -> str:
    if c.value is None:
        return ""
    return f"{c.value:g}" + (f" {c.unit}" if c.unit else "")


def claim_text(c: Claim) -> str:
    """The statement as one sentence, with the claim's value and unit when it has one."""
    text = c.statement.strip().rstrip(".")
    if c.value is not None:
        text += f" ({value_fmt(c)})"
    return text + "."


def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    env.filters.update(oneline=lambda text: " ".join(str(text).split()), cell=cell, num=num, score=score_fmt, link=link, claim=claim_text)
    return env


# ---------------------------------------------------------------- run files


def research_gaps(run_dir: Path, dimension: str) -> list[str] | None:
    """The list items (or lines) of a research file's `## Gaps` section; None without a file."""
    try:
        md = (run_dir / "02_research" / f"{dimension}.md").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    m = GAPS_RE.search(md)
    if not m:
        return []
    return [LIST_MARK_RE.sub("", line).strip() for line in m.group(1).splitlines() if line.strip()]


# ---------------------------------------------------------------- sections


def why(sheet: ScoreSheet, rubric: config.RubricConfig, n_dims: int) -> str:
    """The one-paragraph reason for the verdict, in scoring.verdict's order of precedence."""
    t = rubric.verdict_thresholds
    capped = [s.dimension for s in sheet.scores if s.status == "insufficient_data"]
    total = f"The weighted total is {sheet.weighted_total:.2f} of 5 (GO ≥ {t.go:g}, PIVOT ≥ {t.pivot:g})."
    if sheet.kill_triggers_fired:
        parts = [
            f"Kill trigger(s) fired: {', '.join(sheet.kill_triggers_fired)}. "
            "A fired kill trigger forces NO_GO whatever the total.",
            total,
        ]
    elif len(capped) > t.max_insufficient_dimensions:
        parts = [
            f"{len(capped)} of {n_dims} dimensions lack the evidence their rubric rules require "
            f"(at most {t.max_insufficient_dimensions} may), so the scores cannot support a decision.",
            total,
        ]
    elif sheet.weighted_total >= t.go:
        parts = [total.replace("The weighted", "No kill trigger fired and the weighted"), "That reaches GO."]
    elif sheet.weighted_total >= t.pivot:
        parts = [total.replace("The weighted", "No kill trigger fired and the weighted"), "That is PIVOT: below GO."]
    else:
        parts = [total.replace("The weighted", "No kill trigger fired, but the weighted"), "That is below PIVOT."]
    if capped:
        parts.append(f"{CAP_LABEL.capitalize()} for missing evidence: {', '.join(capped)}.")
    scored = [s for s in sheet.scores if s.final_score is not None]
    if scored:
        best = max(scored, key=lambda s: s.final_score or 0)
        worst = min(scored, key=lambda s: s.final_score or 0)
        parts.append(
            f"Strongest dimension: {best.dimension} ({best.final_score:g}); "
            f"weakest: {worst.dimension} ({worst.final_score:g})."
        )
    ue = sheet.unit_economics
    if ue.contribution_margin_eur is not None:
        parts.append(f"Contribution margin: {num(ue.contribution_margin_eur)} EUR per unit sold.")
    elif ue.missing_inputs:
        parts.append(f"Unit economics incomplete: missing {', '.join(ue.missing_inputs)}.")
    expected = scoring.verdict(sheet.weighted_total, len(capped), sheet.kill_triggers_fired, rubric)
    if expected != sheet.verdict:
        parts.append(
            f"Note: 04_scores.json says {sheet.verdict}, but the current rubric gives {expected}; "
            "re-run score_run.py."
        )
    return " ".join(parts)


def kill_trigger_rows(sheet: ScoreSheet, claims: list[Claim], overrides: Iterable[str]) -> list[dict[str, Any]]:
    overrides = set(overrides)
    rows = []
    for trigger in KILL_TRIGGERS:
        verified = [c.claim_id for c in claims if trigger in c.flags and c.verification == "verified"]
        other = [f"{c.claim_id} ({c.verification})" for c in claims if trigger in c.flags and c.verification != "verified"]
        if trigger in sheet.kill_triggers_fired:
            state = "**fired**"
        elif trigger in overrides:
            state = "overridden in the spec" if verified else "not fired (overridden in the spec)"
        else:
            state = "not fired"
        evidence = ", ".join(verified)
        if trigger in sheet.kill_triggers_fired and not verified:
            evidence = (
                "computed: contribution margin below 0"
                if trigger == "negative_contribution_margin"
                else "no verified claim carries it now: 04_scores.json may be stale, re-run score_run.py"
            )
        rows.append({"trigger": trigger, "state": state, "evidence": evidence, "not_counted": ", ".join(other)})
    return rows


def economics_rows(sheet: ScoreSheet) -> list[tuple[str, str]]:
    ue = sheet.unit_economics
    margin = num(ue.contribution_margin_eur)
    if ue.contribution_margin_pct is not None:
        margin += f" ({num(ue.contribution_margin_pct, 1)} %)"
    vat = "unknown" if ue.vat_registered is None else ("registered" if ue.vat_registered else "not registered")
    if ue.vat_rate_pct is not None:
        vat += f", rate {ue.vat_rate_pct:g} %"
    return [
        ("Price per unit sold (EUR)", num(ue.price_eur)),
        ("Variable cost per unit sold (EUR)", num(ue.variable_cost_eur)),
        ("Contribution margin per unit (EUR)", margin),
        ("Fixed costs per month (EUR)", num(ue.fixed_costs_month_eur)),
        ("Customer acquisition cost (EUR)", num(ue.cac_eur)),
        ("Units sold per month", num(ue.volume_month, 1)),
        ("Purchases per customer per month", num(ue.purchases_per_customer_month, 2)),
        ("Monthly profit (EUR)", num(ue.monthly_profit_eur)),
        ("Break-even units per month", num(ue.break_even_units_month, 1)),
        ("Payback (months)", num(ue.payback_months, 1)),
        ("VAT", vat),
    ]


def sensitivity_grid(sheet: ScoreSheet) -> dict[str, Any] | None:
    rows = sheet.unit_economics.sensitivity
    if not rows:
        return None
    prices = sorted({r.price_change_pct for r in rows})
    volumes = sorted({r.volume_change_pct for r in rows})
    by = {(r.price_change_pct, r.volume_change_pct): r.monthly_profit_eur for r in rows}
    return {
        "volumes": [pct_change(v) for v in volumes],
        "rows": [(pct_change(p), [num(by.get((p, v))) for v in volumes]) for p in prices],
    }


def not_counted(c: Claim) -> str:
    if c.verification != "verified":
        return c.verification
    return "not on an allow-listed official domain"


def _mentions(c: Claim, pattern: re.Pattern[str]) -> bool:
    return any(pattern.search(text) for text in (c.statement, c.source_title, c.quote))


def funding_fit(claims: list[Claim]) -> list[dict[str, Any]]:
    """Per programme: the verified official financing claims that back it and the financing claims
    about it that do not count."""
    financing = [c for c in claims if c.dimension == "financing"]
    out = []
    for p in PROGRAMMES:
        about = [
            c
            for c in financing
            if _mentions(c, p.pattern) or any(verify.domain_matches(c.source_url, d) for d in p.domains)
        ]
        backing = [c for c in about if c.verification == "verified" and verify.is_official(c.source_url)]
        out.append(
            {
                "name": p.name,
                "backing": backing,
                "not_counted": [(c, not_counted(c)) for c in about if c not in backing],
            }
        )
    return out


def location_notes(claims: list[Claim]) -> tuple[list[Claim], list[Claim]]:
    """Location claims plus claims of any dimension naming Rääkkylä / Keski-Karjala / North Karelia:
    (verified, the rest)."""
    local = [c for c in claims if c.dimension == "location" or _mentions(c, LOCAL_RE)]
    return [c for c in local if c.verification == "verified"], [c for c in local if c.verification != "verified"]


def risk_rows(risks: list[RiskItem], known: set[str]) -> list[dict[str, Any]]:
    ordered = sorted(risks, key=lambda r: -r.likelihood * r.impact)
    return [
        {
            "risk": r,
            "severity": r.likelihood * r.impact,
            "claims": ", ".join(cid if cid in known else f"{cid} (unknown)" for cid in r.claim_ids),
        }
        for r in ordered
    ]


def source_rows(claims: list[Claim]) -> list[dict[str, Any]]:
    by_url: dict[str, list[Claim]] = {}
    for c in claims:
        by_url.setdefault(c.source_url, []).append(c)
    rows = []
    for url in sorted(by_url):
        group = by_url[url]
        states: dict[str, int] = {}
        for c in group:
            states[c.verification] = states.get(c.verification, 0) + 1
        flags = sorted({f for c in group for f in c.flags if f in verify.FETCH_FLAGS})
        rows.append(
            {
                "url": url,
                "title": group[0].source_title,
                "retrieved_at": min(c.retrieved_at for c in group).isoformat(timespec="seconds"),
                "verification": ", ".join(f"{s} ×{n}" for s, n in sorted(states.items())) + "".join(f"; {f}" for f in flags),
                "official": "yes" if verify.is_official(url) else "",
                "claim_ids": ", ".join(c.claim_id for c in group),
            }
        )
    return rows


def dimension_sections(
    run_dir: Path, sheet: ScoreSheet, claims: list[Claim], rubric: config.RubricConfig
) -> list[dict[str, Any]]:
    by_id = {c.claim_id: c for c in claims}
    scores = {s.dimension: s for s in sheet.scores}
    out = []
    for dim in (*RUBRIC_DIMENSIONS, "killcause"):
        own = [c for c in claims if c.dimension == dim]
        s = scores.get(dim)
        cited_ids = s.supporting_claim_ids if s else []
        cited = [by_id[cid] for cid in cited_ids if cid in by_id and by_id[cid].verification == "verified"]
        out.append(
            {
                "id": dim,
                "name": rubric.dimension(dim).name if dim in RUBRIC_DIMENSIONS else "Kill causes (not scored)",
                "score": s,
                "cited": cited,
                "uncited": [c.claim_id for c in own if c.verification == "verified" and c not in cited],
                "not_counted": [c for c in own if c.verification != "verified"],
                "gaps": research_gaps(run_dir, dim),
            }
        )
    return out


def context(run_id: str, now: datetime) -> dict[str, Any]:
    run_dir = runs.run_dir(run_id)
    spec: IdeaSpec = load_spec(run_dir)
    claims = sorted(load_claims(run_dir), key=lambda c: c.claim_id)
    sheet = load_scores(run_dir)
    risks = load_risks(run_dir).risks
    rubric = config.rubric()
    weights = {d.id: d.weight for d in rubric.dimensions}
    local_verified, local_other = location_notes(claims)
    return {
        "run_id": run_id,
        "generated_at": now.isoformat(timespec="seconds"),
        "spec": spec,
        "sheet": sheet,
        "cap_label": CAP_LABEL,
        "why": why(sheet, rubric, len(rubric.dimensions)),
        "score_rows": [(s, weights.get(s.dimension, 0.0)) for s in sheet.scores],
        "insufficient": sum(s.status == "insufficient_data" for s in sheet.scores),
        "triggers": kill_trigger_rows(sheet, claims, spec.kill_trigger_overrides),
        "economics": economics_rows(sheet),
        "sensitivity": sensitivity_grid(sheet),
        "dimensions": dimension_sections(run_dir, sheet, claims, rubric),
        "funding": funding_fit(claims),
        "funding_gaps": research_gaps(run_dir, "financing"),
        "unverified_gap": UNVERIFIED_GAP,
        "location_score": next((s for s in sheet.scores if s.dimension == "location"), None),
        "local_verified": local_verified,
        "local_other": local_other,
        "location_gaps": research_gaps(run_dir, "location"),
        "risks": risk_rows(risks, {c.claim_id for c in claims}),
        "sources": source_rows(claims),
        "usage": usage.render_summary(usage.summarize(run_id, run_dir, db.stages(run_id))),
    }


def render_text(run_id: str, now: datetime | None = None) -> str:
    """The report's Markdown; reads the run's files and writes nothing."""
    ctx = context(run_id, now or datetime.now(UTC))
    # optional template blocks can leave runs of blank lines; Markdown needs at most one
    return re.sub(r"\n{3,}", "\n\n", environment().get_template("report.md.j2").render(ctx))


# ---------------------------------------------------------------- writing


@dataclass
class ReportResult:
    run_id: str
    path: Path
    sheet: ScoreSheet


def _write_new(path: Path, text: str) -> None:
    """Create `path` with `text` in one step, failing if it exists: a crash leaves no half report."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.link(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def render(run_id: str, now: datetime | None = None) -> ReportResult:
    """Write 05_report.md and its `reports` row once; raise ReportExists if either exists."""
    run_dir = runs.run_dir(run_id)
    path = run_dir / REPORT
    rel = path.relative_to(config.ROOT).as_posix()
    if path.exists():
        raise ReportExists(f"{rel} already exists; reports are immutable (a new version is a new run)")
    if db.get_report(run_id) is not None:
        raise ReportExists(f"run {run_id} already has a report row; reports are immutable")
    now = now or datetime.now(UTC)
    text = render_text(run_id, now)
    sheet = load_scores(run_dir)
    try:
        db.add_report(
            run_id, "report", rel, weighted_total=sheet.weighted_total, verdict=sheet.verdict,
            created_at=now.isoformat(timespec="seconds"), then=lambda: _write_new(path, text),
        )  # fmt: skip
    except FileExistsError:
        raise ReportExists(f"{rel} was written concurrently; reports are immutable") from None
    except sqlite3.IntegrityError as e:
        if "UNIQUE" not in str(e):
            raise
        raise ReportExists(f"run {run_id} already has a report row; reports are immutable") from None
    return ReportResult(run_id, path, sheet)


__all__ = ["InputError", "ReportExists", "ReportResult", "render", "render_text"]
