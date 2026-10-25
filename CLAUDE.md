@AGENTS.md

## Claude Code specifics

The operating manual above applies to every development session. This section covers what
Claude Code does automatically in this repository, then the rules for sessions that run the
pipeline. Permissions and the pipeline hooks live in `.claude/settings.json`; the harness hooks,
skills and evaluator agent come from the shared harness plugin (`harness@eemelinen-harness`,
pinned to the same tag as the `@eemelinen/harness` package; project rules in
`harness.config.json`).

- **Permissions** (`.claude/settings.json`):
  - Run without prompting: read-only git commands, the verification scripts (`pnpm check*`, `format*`, `test:py*`, `uv run pytest*`), the harness scripts (`pnpm harness:*`), the pipeline commands (`uv run python -m ideaforge*`, `uv run python scripts/*`), `WebSearch`, `WebFetch` and `Agent`.
  - Denied: reading or editing `.env`; editing `.claude/agents/**`, `uv.lock` and `pnpm-lock.yaml`; `curl`/`wget`; force pushes; `git reset --hard`.
- **Hooks**: two sets run side by side, and either can block a call (D-001).
  - Harness (plugin, configured in `harness.config.json`):
    - `SessionStart` prints branch, recent commits, Current Verified State, the active feature and the dev-marker state.
    - `PreToolUse` (the guard) blocks bare `python`/`pytest`/`pip`, `pip install`, npm/yarn/npx and destructive commands. It runs `pnpm harness:check` before every `git commit`, denies edits to generated agents and lockfiles, and asks before edits to `config/models.yaml`.
    - `PostToolUse` runs Prettier on the edited file, honouring `.prettierignore`, so prompts and config are never reformatted.
    - `Stop` is inert unless the loop driver sets `HARNESS_STOP_GUARD=1`; then it blocks stopping until the clean-state check passes (D-002).
  - Pipeline:
    - `PreToolUse` → `ideaforge.guard` (write and shell policy)
    - `PostToolUse` → `ideaforge.usage` (usage log, budget counters)
    - `SubagentStop` / `Stop` → `ideaforge.validate_file --auto`
- **Development mode**: subagents are always held to the strict pipeline guard. The main session gets the strict policy too (writes only under `runs/` and `cache/`, allow-listed shell commands, no `curl`/`wget`) **unless** the gitignored marker file `.ideaforge-dev` exists at the project root or the loop driver set `HARNESS_LOOP=1` (D-005). Create the marker to develop the project; delete it before running the pipeline unattended.
- **Skills**:
  - `/harness:clock-in [F-NNN]` runs the clock-in routine and activates a feature (`pnpm harness:feature activate`).
  - `/harness:verify-feature F-NNN` runs `pnpm harness:verify`, which executes the feature's steps in order and records evidence.
  - `/harness:clock-out` runs `pnpm harness:clean-state`, updates the state files and commits. It is user-only.
- **Driver-run sessions**: `pnpm harness:loop` (config in `harness.config.json`) starts one `claude -p` session per ready feature in its own worktree, with the plugin loaded from the installed package, re-checks the result, runs the evaluator in a second session and opens a PR. How it works: [docs/harness/README.md](docs/harness/README.md).
- **Agent** `harness:evaluator` (from the plugin; registered in `src/ideaforge/agents.py` so the pipeline guard lets it run the read-only harness checks): a fresh-context reviewer that scores a diff against `docs/harness/evaluator-rubric.md`. Use it from `/harness:clock-out` or on request; it never edits.
- **Hooks need `uv`, `node` and `bash` on PATH.** Without `uv` the pipeline hooks fail open; on this Windows machine add `%USERPROFILE%\.local\bin` to the user `Path`.

## Pipeline sessions

A session that runs the pipeline (`/validate <idea>`, `/research`, `/synthesize`, `/debate`,
`/status`, `/eval`) is not a development session: skip the clock-in loop and follow these rules.
How to run: `uv sync`, `uv run python scripts/gen_agents.py`, then `/validate <idea text>`.

**Rules for the orchestrator (main session)**

- Never do research yourself in the main context. Delegate every dimension to its `research-*` subagent so the main context stays small.
- Never write claim files by hand. Subagents write prose; `scripts/verify_claims.py` extracts and verifies the claims.
- After each stage, run that stage's validator script and check its exit code before continuing.
- At the end of every stage, report usage from `uv run python scripts/usage_report.py <run_id>`.
- After each stage, check `runs/<run_id>/` for `BUDGET_EXCEEDED_<agent>` and `VALIDATION_FAILED_<agent>` files.
- If a subagent fails validation twice, mark that dimension `INSUFFICIENT_DATA` and continue. Never fabricate.

**Where things are**

- `config/`: models, rubric, Finland hints, domain allow-lists, budgets, founder constraints.
- `prompts/`: long prompt bodies, included into agent templates.
- `agent_templates/`: sources for `.claude/agents/` (edit these, then run `gen_agents.py`; never edit `.claude/agents/` by hand).
- `src/ideaforge/`: schemas, db, runs, hooks (`usage`, `guard`, `validate_file`), Finnish data tools (`fi/`).
- `scripts/`: stage entry points (`new_run.py`, `gen_agents.py`, …).
- `runs/<run_id>/`: all outputs of one run. `runs/.active` holds the active run id, which hooks read. `IDEAFORGE_RUN_ID` overrides it.

**Model policy.** All roles default to `opus` per `config/models.yaml`. Do not change models in agent files; change the config and run `gen_agents.py`. The web UI's Settings pages (`/settings`) are another way to edit `config/` under the same single-source rule: a save validates the file, regenerates the agents when they depend on it and is refused while a job runs; the `harness_*` roles stay hand-edited.

**Finland policy.** Regulatory, tax and grant claims must cite an allow-listed official domain from `config/domains.yaml` (vero.fi, prh.fi, ytj.fi, suomi.fi, tyomarkkinatori.fi, finlex.fi, elinvoimakeskus.fi, finnvera.fi, businessfinland.fi, maaseutu.fi, stat.fi, luke.fi, ec.europa.eu/eurostat) or one of the run's own official domains: its base location's `official_domains` and Leader group domain in `00_spec.json` (by default `config/founder.yaml`'s raakkyla.fi, luotsipohjoiskarjala.fi and jetina.fi), which count for that run only (D-009). Values in `config/finland.yaml` are _hints to verify_, not facts.
