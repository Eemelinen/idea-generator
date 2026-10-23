# Ideaforge

Ideaforge is a local business-idea validator built as a Claude Code project. The user types a business idea. The pipeline (1) researches its feasibility online using standard start-a-business checklists, adapted to Finland and to Rääkkylä / North Karelia, and produces a scored, evidence-backed report. On request it then (2) runs a structured multi-agent debate that tries to improve the plan and outputs a revised plan, an assumption register and experiments. Claude Code skills, subagents and hooks do the AI work; Python + SQLite do everything deterministic. The full design is in `IMPLEMENTATION_PLAN.md`, and work is tracked in `docs/TICKETS.md`.

**Non-negotiables**
1. **No paid services.** Only the built-in `WebSearch`/`WebFetch`, free public APIs (Statistics Finland, Luke, PRH open data, Eurostat), Python + pip packages and SQLite.
2. **Model choice lives only in `config/models.yaml`.** Never hardcode a model name in an agent file or script.
3. **Every number has a source:** URL + retrieval timestamp + verified quote. Anything else doesn't count toward a score.
4. **Python decides, the model proposes.** Scores, caps, kill triggers, totals, unit economics and the verdict are computed in Python.
5. **Resumable.** Every stage writes its output to disk/SQLite before the next one starts. Re-running a run id skips completed stages.
6. **Validated outputs.** Every structured file is validated against a Pydantic schema (`src/ideaforge/schemas.py`) by a hook. An invalid file fails loudly and is re-prompted once.
7. **Anti-sycophancy debate.** Round-0 positions are written in isolated subagent contexts. A stance change needs a new claim id or a computed number. The judge is author-blind. Max 3 rounds.

## How to run
```
uv sync
uv run python scripts/gen_agents.py
/validate <idea text>
```
Tests: `uv run pytest`.

## Rules for the orchestrator (main session)
- Never do research yourself in the main context. Delegate every dimension to its `research-*` subagent so the main context stays small.
- Never write claim files by hand. Subagents write prose; `scripts/verify_claims.py` extracts and verifies the claims.
- After each stage, run that stage's validator script and check its exit code before continuing.
- At the end of every stage, report usage from `uv run python scripts/usage_report.py <run_id>`.
- After each stage, check `runs/<run_id>/` for `BUDGET_EXCEEDED_<agent>` and `VALIDATION_FAILED_<agent>` files.
- If a subagent fails validation twice, mark that dimension `INSUFFICIENT_DATA` and continue. Never fabricate.

## Where things are
- `config/`: models, rubric, Finland hints, domain allow-lists, budgets, founder constraints.
- `prompts/`: long prompt bodies, included into agent templates.
- `agent_templates/`: sources for `.claude/agents/` (edit these, then run `gen_agents.py`; never edit `.claude/agents/` by hand).
- `src/ideaforge/`: schemas, db, runs, hooks (`usage`, `guard`, `validate_file`), Finnish data tools (`fi/`).
- `scripts/`: stage entry points (`new_run.py`, `gen_agents.py`, …).
- `runs/<run_id>/`: all outputs of one run. `runs/.active` holds the active run id, which hooks read. `IDEAFORGE_RUN_ID` overrides it.

## Model policy
All roles default to `opus` per `config/models.yaml`. Do not change models in agent files; change the config and run `gen_agents.py`.

## Finland policy
Regulatory, tax and grant claims must cite an allow-listed official domain from `config/domains.yaml` (vero.fi, prh.fi, ytj.fi, suomi.fi, tyomarkkinatori.fi, finlex.fi, elinvoimakeskus.fi, finnvera.fi, businessfinland.fi, luotsipohjoiskarjala.fi, jetina.fi, maaseutu.fi, raakkyla.fi, stat.fi, luke.fi, ec.europa.eu/eurostat). Values in `config/finland.yaml` are *hints to verify*, not facts.

## Hooks and the development session
`.claude/settings.json` wires these hooks:
- PostToolUse → `ideaforge.usage` (usage log, budget counters)
- PreToolUse → `ideaforge.guard` (write and shell policy)
- SubagentStop / Stop → `ideaforge.validate_file --auto`

Subagents are always held to the strict guard policy. The main session gets the strict policy too (writes only under `runs/` and `cache/`, allow-listed shell commands, no `curl`/`wget`) **unless** the gitignored marker file `.ideaforge-dev` exists at the project root. Create the marker to develop the project; delete it before running the pipeline unattended.
