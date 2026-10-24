"""Registry of the project's subagents: name → model role, kind and output file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ideaforge import db
from ideaforge.schemas import PERSONAS, RESEARCH_DIMENSIONS


@dataclass(frozen=True)
class AgentSpec:
    name: str          # subagent name == .claude/agents/<name>.md == hook agent_type
    role: str          # key in config/models.yaml roles
    kind: str          # research | extractor | synthesizer | debate | judge | harness
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
# Stage 3 (IF-211): the optional claim-extraction pass, launched only when
# scripts/extract_claims.py lists research sentences no candidate claim covers.
AGENTS["claim-extractor"] = AgentSpec(name="claim-extractor", role="claim_extractor", kind="extractor")
# Stage 5 (IF-304): proposes scores and risks from runs/<run_id>/04_synthesis_input.json only.
AGENTS["synthesizer"] = AgentSpec(name="synthesizer", role="synthesizer", kind="synthesizer")
for _p in PERSONAS:
    AGENTS[f"debate-{_p}"] = AgentSpec(name=f"debate-{_p}", role="debate_persona", kind="debate", persona=_p)
AGENTS["debate-judge"] = AgentSpec(name="debate-judge", role="debate_judge", kind="judge")
# Development harness reviewer (docs/harness/evaluator-rubric.md); read-only, writes no run files.
# It comes from the shared harness plugin (agent type "harness:evaluator"), so gen_agents.py does
# not render it; it is registered here for the guards.
AGENTS["harness:evaluator"] = AgentSpec(name="harness:evaluator", role="harness_evaluator", kind="harness")


def get(name: str | None) -> AgentSpec | None:
    return AGENTS.get(name or "")


def research_agent(dimension: str) -> AgentSpec | None:
    return AGENTS.get(_research_name(dimension))


def research_output(run_dir: Path, spec: AgentSpec) -> Path:
    return run_dir / "02_research" / f"{spec.dimension}.md"


# Debate mini-research (IF-404): task n of a debate is researched by the dimension's research
# agent into 02_research/mini-<n>-<dimension>.md, which verify_claims.py reads like the others.
MINI_STEM_RE = re.compile(r"^mini-(\d+)-([a-z_]+)$")


def mini_output(run_dir: Path, n: int, dimension: str) -> Path:
    return run_dir / "02_research" / f"mini-{n}-{dimension}.md"


def research_target(run_dir: Path, spec: AgentSpec) -> Path:
    """The file a research agent writes now: during a debate, the running mini-research task's
    file for its dimension (`mini_research` table), otherwise its stage-2 file."""
    for task in db.mini_research_tasks(run_dir.name):
        if task["status"] == "running" and task["dimension"] == spec.dimension:
            return mini_output(run_dir, task["n"], spec.dimension)
    return research_output(run_dir, spec)


def parse_mini_stem(stem: str) -> tuple[int, str] | None:
    """(n, dimension) of a mini-research file stem such as `mini-2-pricing`, else None."""
    m = MINI_STEM_RE.match(stem)
    if m is None or m.group(2) not in RESEARCH_DIMENSIONS:
        return None
    return int(m.group(1)), m.group(2)


# Claim-extraction pass (IF-211): scripts/extract_claims.py writes the request, the claim-extractor
# agent one JSON list of candidate claims per listed research file stem next to it.
EXTRACT_REQUEST = "request.json"


def extracted_dir(run_dir: Path) -> Path:
    return run_dir / "03_claims" / "extracted"


def extract_request(run_dir: Path) -> Path:
    return extracted_dir(run_dir) / EXTRACT_REQUEST


def extracted_output(run_dir: Path, stem: str) -> Path:
    return extracted_dir(run_dir) / f"{stem}.json"


SYNTHESIS_INPUT = "04_synthesis_input.json"
SYNTHESIS_OUTPUTS = ("04_scores_proposed.json", "04_risks.json")


def synthesizer_outputs(run_dir: Path) -> list[Path]:
    return [run_dir / name for name in SYNTHESIS_OUTPUTS]


def latest_debate_output(run_dir: Path, spec: AgentSpec) -> Path | None:
    """The persona's file in the highest-numbered round directory that has one. The judge's is
    debate/verdict.json once written, before that its latest round<N>/interim_scores.json."""
    if spec.kind == "judge":
        p = run_dir / "debate" / "verdict.json"
        if p.exists():
            return p
    rounds = sorted(
        (d for d in (run_dir / "debate").glob("round*") if d.name[5:].isdigit()),
        key=lambda d: int(d.name[5:]),
        reverse=True,
    )
    name = "interim_scores.json" if spec.kind == "judge" else f"{spec.persona}.json"
    for d in rounds:
        p = d / name
        if p.exists():
            return p
    return None
