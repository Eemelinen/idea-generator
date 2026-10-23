"""Render agent_templates/*.md.j2 with config/*.yaml into .claude/agents/*.md.

    uv run python scripts/gen_agents.py           # write the agent files
    uv run python scripts/gen_agents.py --check   # exit 1 if any generated file is stale

Model names come only from config/models.yaml (roles); never edit .claude/agents by hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ideaforge import agents, config
from ideaforge.schemas import KILL_TRIGGERS


def environment() -> Environment:
    return Environment(
        loader=FileSystemLoader([config.AGENT_TEMPLATES_DIR, config.PROMPTS_DIR]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )


def context(spec: agents.AgentSpec) -> dict:
    preset = config.budget().preset()
    ctx: dict = {
        "agent": spec,
        "roles": config.models().roles,
        "template_name": f"{spec.name}.md.j2",
    }
    if spec.kind == "research":
        rubric = config.rubric()
        if spec.dimension == "killcause":
            title, questions, min_evidence, rubric_domains = (
                "Kill causes", rubric.killcause.research_questions, None, []
            )
        else:
            dim = rubric.dimension(spec.dimension)
            title, questions, min_evidence, rubric_domains = (
                dim.name, dim.research_questions, dim.min_evidence_for_3, dim.preferred_domains
            )
        domains = list(dict.fromkeys([*rubric_domains, *config.domains().preferred.get(spec.dimension, [])]))
        ctx |= {
            "title": title,
            "questions": questions,
            "min_evidence": min_evidence,
            "preferred_domains": domains,
            "budget_line": getattr(preset, spec.budget_key),
            "kill_triggers": KILL_TRIGGERS,
        }
    elif spec.kind == "debate":
        ctx["evidence"] = agents.PERSONA_EVIDENCE[spec.persona]
    return ctx


def render_all() -> dict[Path, str]:
    env = environment()
    templates = {p.name for p in config.AGENT_TEMPLATES_DIR.glob("*.md.j2") if not p.name.startswith("_")}
    expected = {f"{name}.md.j2" for name in agents.AGENTS}
    if templates != expected:
        missing, extra = sorted(expected - templates), sorted(templates - expected)
        raise SystemExit(f"template set mismatch: missing={missing} unregistered={extra}")
    return {
        config.AGENTS_DIR / f"{spec.name}.md": env.get_template(f"{spec.name}.md.j2").render(context(spec))
        for spec in agents.AGENTS.values()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if generated files are stale")
    args = parser.parse_args(argv)

    config.load_all()
    rendered = render_all()
    stray = sorted(p.name for p in config.AGENTS_DIR.glob("*.md") if p not in rendered)

    if args.check:
        stale = [
            p.name for p, text in rendered.items()
            if not p.exists() or p.read_text(encoding="utf-8") != text
        ]
        if stale or stray:
            print(f"stale: {stale}  stray: {stray}\nrun: uv run python scripts/gen_agents.py", file=sys.stderr)
            return 1
        print(f"ok: {len(rendered)} agent files up to date")
        return 0

    config.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    for path, text in rendered.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    for name in stray:
        print(f"warning: {name} in .claude/agents has no template", file=sys.stderr)
    print(f"wrote {len(rendered)} agent files to {config.AGENTS_DIR.relative_to(config.ROOT).as_posix()}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
