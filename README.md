# Ideaforge

A local business-idea validator for founders in Rääkkylä / North Karelia, Finland. It runs on Claude Code with a Claude Max subscription and uses no paid third-party services.

You type an idea. Ideaforge researches it across ten feasibility dimensions with parallel subagents, verifies every quoted claim against its source, scores the idea in Python and writes an evidence-backed report. If you ask, it also runs a structured debate that tries to improve the plan.

- Design: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- Work breakdown: [docs/TICKETS.md](docs/TICKETS.md)
- Instructions for Claude Code: [CLAUDE.md](CLAUDE.md)

## Setup

1. Install [uv](https://docs.astral.sh/uv/). uv downloads Python 3.12 for the project.
2. `uv sync`
3. `uv run python scripts/gen_agents.py`
4. `uv run pytest`

If downloads fail with `invalid peer certificate: UnknownIssuer`, something on the machine (antivirus or a proxy) is intercepting TLS. `pyproject.toml` already sets `[tool.uv] system-certs = true`, so commands run inside the project use the system certificate store. Commands run outside the project need `--system-certs`.

## Usage

Inside Claude Code, in this directory:

```
/validate <idea text>        # full pipeline (Phase 2+)
/status [run_id]
/debate <run_id>             # Phase 4
```

Status: Phase 1 (the skeleton) is done; of Phase 2, the research validator, claim verification (`uv run python scripts/verify_claims.py <run_id>`), the usage report and basic `/status` are built. See `docs/TICKETS.md` for what comes next.

- `uv run python scripts/usage_report.py <run_id>`: tool calls, searches, fetches and approximate tokens per stage and per agent, plus the run's `BUDGET_EXCEEDED_*` markers.
- `/status` (`uv run python scripts/status.py [run_id] [--limit N]`): the recent runs and their stages; with a run id, its stages, claims per dimension by verification state, kill flags fired, validation and budget markers and the usage summary.

## Development

The project's hooks block writes outside `runs/` and `cache/` and allow only a short list of shell commands. To work on the code itself, create an empty `.ideaforge-dev` file at the project root (it is gitignored). Subagents are always held to the strict rules.

After editing `config/models.yaml`, `agent_templates/` or `prompts/`, run `uv run python scripts/gen_agents.py`. The tests fail if the generated agent files are stale.

The remaining work is built with an agent harness: one feature per Claude Code session, verified by scripts before it counts as done. You need Node 24 (`.nvmrc`) with pnpm, plus uv, and on Windows Git Bash. `uv`, `claude` and `gh` must be on `PATH`.

- `./init.sh` installs both toolchains and runs the L1 check, `pnpm check`.
- In Claude Code: `/harness:clock-in` picks and activates the next feature, `/harness:verify-feature F-NNN` runs its checks, and `/harness:clock-out` commits. The skills, hooks and loop come from the shared harness ([Eemelinen/harness](https://github.com/Eemelinen/harness)), configured in `harness.config.json`.
- `pnpm harness:feature list` shows the queue (`feature_list.json`; tickets in `docs/TICKETS.md`).
- `pnpm harness:loop --once` runs one ready feature unattended in its own worktree and opens a PR.

The session loop is described in [AGENTS.md](AGENTS.md) and the driver in [docs/harness/README.md](docs/harness/README.md).
