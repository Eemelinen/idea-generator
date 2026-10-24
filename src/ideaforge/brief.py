"""The run-specific lines of a research brief: the preset's budget line and the back-test header.

The generated research agents carry the default preset's numbers and no as-of date, because
`.claude/agents/` is rendered once from `config/`. The orchestrator therefore pastes these lines
into every research brief (stage 2 and debate mini-research), so an agent works to the budget the
usage hook counts against it and, in a back-test run, never cites a later source.
"""

from __future__ import annotations

from datetime import date

from ideaforge import agents, config, db


class BriefError(Exception):
    """Unknown run, dimension or budget preset."""


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
    lines = [budget_line(preset, dimension)]
    if as_of is not None:
        lines.append(as_of_header(as_of))
    return lines
