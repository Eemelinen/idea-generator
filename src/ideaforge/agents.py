"""Registry of the project's subagents: name → model role, kind and output file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ideaforge.schemas import PERSONAS, RESEARCH_DIMENSIONS


@dataclass(frozen=True)
class AgentSpec:
    name: str          # subagent name == .claude/agents/<name>.md == hook agent_type
    role: str          # key in config/models.yaml roles
    kind: str          # research | debate | judge
    dimension: str | None = None
    persona: str | None = None
    budget_key: str | None = None   # key in a budget preset


# Debate personas: the claim dimensions each one is shown (§6 stage 7). None = all.
PERSONA_EVIDENCE: dict[str, tuple[str, ...] | None] = {
    "founder": None,
    "investor": ("market", "competition", "pricing", "killcause"),
    "customer": ("customer", "pricing", "competition"),
    "accountant": ("regulation", "financing", "unit_economics"),
    "operator": ("unit_economics", "gtm", "location", "founder_risk"),
}


def _research_name(dim: str) -> str:
    return f"research-{dim.replace('_', '-')}"


AGENTS: dict[str, AgentSpec] = {}
for _dim in RESEARCH_DIMENSIONS:
    _killcause = _dim == "killcause"
    AGENTS[_research_name(_dim)] = AgentSpec(
        name=_research_name(_dim),
        role="killcause_scout" if _killcause else "research_subagent",
        kind="research",
        dimension=_dim,
        budget_key="killcause_scout" if _killcause else "research_subagent",
    )
for _p in PERSONAS:
    AGENTS[f"debate-{_p}"] = AgentSpec(name=f"debate-{_p}", role="debate_persona", kind="debate", persona=_p)
AGENTS["debate-judge"] = AgentSpec(name="debate-judge", role="debate_judge", kind="judge")


def get(name: str | None) -> AgentSpec | None:
    return AGENTS.get(name or "")


def research_output(run_dir: Path, spec: AgentSpec) -> Path:
    return run_dir / "02_research" / f"{spec.dimension}.md"


def latest_debate_output(run_dir: Path, spec: AgentSpec) -> Path | None:
    """The persona's file in the highest-numbered round directory that has one."""
    if spec.kind == "judge":
        p = run_dir / "debate" / "verdict.json"
        return p if p.exists() else None
    rounds = sorted(
        (d for d in (run_dir / "debate").glob("round*") if d.name[5:].isdigit()),
        key=lambda d: int(d.name[5:]),
        reverse=True,
    )
    for d in rounds:
        p = d / f"{spec.persona}.json"
        if p.exists():
            return p
    return None
