"""The run-specific lines of a brief: the run's scope, the preset's budget line and the back-test header.

The generated agents carry the default preset's numbers, no as-of date and no place (D-009),
because `.claude/agents/` is rendered once from `config/`. The orchestrator therefore pastes these
lines into every research brief (stage 2 and debate mini-research), so an agent researches the
run's own base and markets, works to the budget the usage hook counts against it and, in a
back-test run, never cites a later source. Debate personas get the scope lines alone.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import ValidationError

from ideaforge import agents, config, db, runs
from ideaforge.schemas import BusinessMode, IdeaSpec


class BriefError(Exception):
    """Unknown run, dimension or budget preset, or a run without a valid spec."""


def run_settings(run_id: str) -> tuple[str, date | None]:
    """The run's budget preset and as-of date from its `runs` row."""
    db.init()
    with db.session() as conn:
        row = conn.execute("SELECT budget_preset, as_of FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise BriefError(f"run {run_id!r} is not in the database; create it with scripts/new_run.py")
    if row["budget_preset"] not in config.budget().presets:
        raise BriefError(f"run {run_id} has budget preset {row['budget_preset']!r}, which config/budget.yaml does not define")
    return row["budget_preset"], date.fromisoformat(row["as_of"]) if row["as_of"] else None


# What each business mode means for the research (TICKETS.md Phase 7 → Modes). The prompts mark
# their mode-specific steps "Local or hybrid:" and "Online or hybrid:".
MODE_GUIDANCE: dict[BusinessMode, str] = {
    "online": (
        "Customers buy remotely, so the base matters only for logistics, costs, registration and"
        ' funding: follow the "Online or hybrid:" steps, skip the "Local or hybrid:" ones, and size'
        " demand and competition in the target markets, not around the base."
    ),
    "local": (
        'Customers come to the business or are served near the base: follow the "Local or hybrid:"'
        ' steps and skip the "Online or hybrid:" ones.'
    ),
    "hybrid": (
        "Customers come to or are served near the base and also buy remotely: follow both the"
        ' "Local or hybrid:" and the "Online or hybrid:" steps.'
    ),
}


def _place(name: str, code: str | None) -> str:
    return f"{name} ({code})" if code else name


def scope_lines(run_dir: Path) -> list[str]:
    """The scope line, the base's own sources, a missing-code note and the mode guidance, from
    the run's `00_spec.json`."""
    path = run_dir / "00_spec.json"
    if not path.is_file():
        raise BriefError(f"{path} does not exist; finish stage 0 (intake) first")
    try:
        spec = IdeaSpec.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as e:
        raise BriefError(f"{path} is not a valid IdeaSpec ({e.error_count()} errors)") from e
    base = spec.base_location
    scope = f"Scope: {spec.business_mode} business. Base: {_place(base.municipality, base.municipality_code)}"
    scope += f", {_place(base.region, base.region_code)}"
    if base.nearby:
        scope += f"; nearby: {', '.join(base.nearby)}"
    lines = [f"{scope}. Target markets, nearest first: {' → '.join(spec.geography)}."]

    sources = []
    if base.official_domains:
        sources.append(f"official sites {', '.join(base.official_domains)}")
    if base.leader_group:
        sources.append(f"Leader group {base.leader_group.name} ({base.leader_group.domain})")
    if sources:
        lines.append(f"The base's {'; '.join(sources)}.")
    missing = [kind for kind, code in (("municipality", base.municipality_code), ("region", base.region_code)) if not code]
    if missing:
        lines.append(
            f"The spec gives no Statistics Finland {' or '.join(missing)} code: find it with `pxweb meta`"
            " before filtering `Alue=`; never guess a code."
        )
    lines.append(MODE_GUIDANCE[spec.business_mode])
    return lines


def budget_line(preset: str, dimension: str) -> str:
    """The budget of the dimension's agent under `preset`, as the hook and validator apply it."""
    spec = agents.research_agent(dimension)
    if spec is None or spec.budget_key is None:
        raise BriefError(f"unknown research dimension {dimension!r}")
    b: config.ResearchBudget = getattr(config.budget().preset(preset), spec.budget_key)
    return (
        f"Budget (preset {preset}): at most {b.max_web_searches} web searches, {b.max_web_fetches} web fetches"
        f" and {b.max_output_words} words of prose. These replace the numbers in your own prompt."
    )


def as_of_header(as_of: date) -> str:
    d = as_of.isoformat()
    return (
        f"Back-test as of {d}: research the idea as it stood on {d}. Use and cite only sources published"
        f" on or before {d}, and give every claim the `published_date` its page shows. A claim whose"
        f" `published_date` is after {d} is rejected as `after_as_of`; a page with no visible date"
        " cannot show that it predates the back-test, so prefer dated sources."
    )


def brief_lines(run_id: str, dimension: str) -> list[str]:
    preset, as_of = run_settings(run_id)
    budget = budget_line(preset, dimension)
    lines = [*scope_lines(runs.run_dir(run_id)), budget]
    if as_of is not None:
        lines.append(as_of_header(as_of))
    return lines
