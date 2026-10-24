# Decisions

Lightweight decision records. Newest last. Add an entry whenever a choice is made that a
future session could not derive from the code alone (why, not what). The design is
[IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md); smaller deviations from it are listed in
[TICKETS.md → Plan notes and deviations](TICKETS.md#plan-notes-and-deviations).

Format: **Context** (what forced a choice) · **Decision** · **Consequences**.

## D-001 · Agent harness layout (2026-10-23)

- Context: Phase 1 is done and 44 tickets remain. The work should be built one feature per Claude Code session, partly unattended, without losing state between sessions. The Metsävahti harness (tag `harness-reference`, course _learn-harness-engineering_) already solves this and is ported by its porting guide.
- Decision:
  - The development manual is `AGENTS.md` (agent-agnostic). `CLAUDE.md` imports it with `@AGENTS.md`, adds the Claude Code wiring, and keeps the pipeline-session rules (orchestrator, model and Finland policy) that a `/validate` run needs.
  - State files: `feature_list.json` (the queue, changed only by `pnpm harness:*`) and `PROGRESS.md`. `docs/TICKETS.md` stays the spec and has no status column, so status lives in one place.
  - Verification is named, not rebuilt: one layer, L1 `pnpm check` = `tsc` + Prettier + Vitest (harness scripts) + `uv run pytest`. There is no L2/L3: the project has no runtime services, and a real pipeline run needs Claude and the network, so it is a `manual:` step.
  - Claude Code wiring in `.claude/`: `settings.json` merges the harness permissions and hooks with the existing pipeline hooks. Hooks are `session-start.sh`, `guard.sh`, `format.sh` and `stop-guard.sh`; skills are `clock-in`, `clock-out` and `verify-feature`; the subagent is `evaluator`.
- Consequences: one manual for every development agent; the loop (read state → one feature → verify → write state) is enforced by scripts. Two PreToolUse guards run on every call (`guard.sh` for development rules, `ideaforge.guard` for the pipeline); either can block.

## D-002 · Driver-run sessions: local loop, auto permissions, PR per feature, opt-in Stop hook (2026-10-23)

- Context: unattended sessions need hard stop conditions and a merge gate that does not rely on the session's own judgement.
- Decision:
  - The driver is the local script `scripts/harness-loop.ts` (`pnpm harness:loop`), run from Git Bash with the existing Claude Code login. No CI or cloud runner.
  - Sessions run `claude -p --permission-mode auto --permission-prompts none` with `--allowedTools` from `harness.config.json`. `bypassPermissions` is not used.
  - One worktree and branch `feat/F-NNN` per feature, cut from `main`. The driver pushes and opens a PR with `gh`, and waits for the merge before a dependent feature starts.
  - `merge` started at `"wait"` (a human merges) and is `"auto"` since 2026-10-23, when `main` got the protection below. Switch it to `"auto"` only after `main` is protected with the required check `L1 (pnpm check)`; without protection `gh pr merge --auto` merges before CI.
  - Caps start at the porting guide's values: 2 attempts, 200 turns, 15 USD and 60 minutes per generator session; evaluator 60 turns and 4 USD; the loop stops after 2 consecutive failures. `manual:` steps are never waived unattended.
  - The evaluator is a separate fresh-context `claude -p` session with the body and tools of `.claude/agents/evaluator.md` (`--append-system-prompt`, `--tools`) and a JSON verdict schema.
  - The Stop hook `stop-guard.sh` is inert unless `HARNESS_STOP_GUARD=1` (set by the driver) and blocks at most three times.
  - The Docker preflight of the reference driver is removed: the project has no services.
- Consequences: `.harness/` is gitignored. In loop mode `guard.sh` blocks `git push`, `git checkout main`, worktree commands and writes outside the worktree. `gh` must be installed and logged in for PRs.

## D-003 · Node and pnpm as development-only tooling (2026-10-23)

- Context: the harness scripts are TypeScript (zod, tsx, Vitest) and the commit gates are husky + lint-staged + commitlint. The porting guide says to copy the scripts, not to rewrite them. Ideaforge itself is Python.
- Decision: add a `package.json` (pnpm 10.15.0, pinned because pnpm 12 creates real symlinks, which this Windows machine refuses) for the harness, its tests and the commit gates only. Prettier formats only the harness and docs files; `.prettierignore` excludes `prompts/`, `agent_templates/` and `config/`, because those feed generated agents byte-for-byte or hold hand-commented YAML. The pipeline never calls Node.
- Consequences: `./init.sh` installs both toolchains (`pnpm install --frozen-lockfile`, `uv sync --frozen`). Non-negotiable 1 (no paid services) is unaffected. There is no eslint, so `.lintstagedrc.mjs` runs Prettier and the feature-list validator only.

## D-004 · Harness models are single-sourced in `config/models.yaml` (2026-10-23)

- Context: non-negotiable 2 says model choice lives only in `config/models.yaml`, and `gen_agents.py --check` rejects any hand-written file in `.claude/agents/`. The reference harness hard-codes model ids in `harness.config.json` and in a hand-written `evaluator.md`.
- Decision: `config/models.yaml` gains the roles `harness_generator` and `harness_evaluator` (`opus`). The evaluator is a registered agent (`agents.AGENTS["evaluator"]`, kind `harness`) rendered from `agent_templates/evaluator.md.j2`. `harness.config.json` uses the same aliases, and `tests/test_harness_config.py` fails when they drift.
- Consequences: changing a harness model means editing both files (the test says so). The driver still reads `harness.config.json`, so the reference script is unchanged.

## D-005 · `HARNESS_LOOP=1` is a development session for the pipeline guard (2026-10-23)

- Context: `ideaforge.guard` limits main-session writes to `runs/` and `cache/`, and shell commands to an allow-list, unless the gitignored `.ideaforge-dev` marker exists. A driver worktree contains only committed files, so it has no marker, and a generator session could not edit `src/` or run `pnpm`.
- Decision: `guard.dev_mode()` is also true when `HARNESS_LOOP=1`, which the driver sets for generator and evaluator sessions. Subagents stay strict whatever the mode. The `evaluator` subagent (interactive use) may additionally run `pnpm check`, `pnpm harness:check` and `pnpm harness:feature show|list|next`, and nothing that changes state. `validate_file --auto` ignores the evaluator. `tests/conftest.py` clears `HARNESS_LOOP` so the strict-mode tests also pass inside a driver session.
- Consequences: an unattended pipeline batch (IF-604) must not set `HARNESS_LOOP`. The pipeline's own protections for subagents are unchanged.

## D-006 · Tickets re-cut for one-session features; order by `depends_on`, not phase gates (2026-10-23)

- Context: the 44 open tickets were sized for a person (S/M/L), and the plan said "do not start a phase until the previous phase's acceptance passes". In Metsävahti about a third of each driver-run session went on clock-in overhead, so many tiny features cost more than fewer session-sized ones. Strict phase gates would also stop the driver at every human-only acceptance run.
- Decision: merge tightly coupled tickets into 27 features. Each survivor keeps its IF id and lists what it absorbs. Each is sized for one session (roughly ≤ 100 turns) and has its verification commands. One new ticket, IF-200, records the live API fixtures: offline sessions must never invent fixture data. Work is ordered by `depends_on`; a phase-acceptance feature is a dependency only of the work that needs real-run output. Phase 6 stays an unqueued backlog.
- Consequences: 20 features can run unattended, and 7 are human-only (`manual:` steps): the §13 decisions, fixture recording, prompt tuning against live runs, the three phase-acceptance runs and the golden set. The phase acceptance criteria from the plan §11 are unchanged; they now sit in those features' `verification` lists.

## D-007 · The harness is the shared package and Claude Code plugin, not a copy (2026-10-23)

- Context: D-001 ported the harness by copying Metsävahti's files at its `harness-reference` tag. The copies drifted at once: this repository fixed the guard's command-start matching (`1094bfa`), Metsävahti fixed the loop's wait on a failed CI check, and neither fix reached the other without porting it by hand.
- Decision:
  - **Source.** The harness now comes from `Eemelinen/harness`, pinned to one git tag twice:
    - the package `@eemelinen/harness` (`devDependencies`; the `harness` CLI behind `pnpm harness:*`);
    - the Claude Code plugin `harness@eemelinen-harness` (`.claude/settings.json`; skills `/harness:*`, agent `harness:evaluator`, the harness hooks).
  - **Configuration.** The project values live in `harness.config.json`:
    - `IF-NNN` tickets;
    - guard rules: uv-only Python, `pip install`, generated agents, `uv.lock`, `.env*`, `config/models.yaml`;
    - clean-state checks: skips/xfails, `fail_under`, debugger calls;
    - `services: null`;
    - `uv run pytest` / `pnpm test:py` milestones;
    - the uv and dev-marker session-start lines.

    The plan and offline rules moved into `docs/harness/generator-notes.md`.

  - **Pipeline hooks.** They stay in `.claude/settings.json` next to the plugin.
  - **Evaluator agent.** It is no longer generated (`agent_templates/evaluator.md.j2` is gone). It is registered as `agents.AGENTS["harness:evaluator"]` (kind `harness`), so `ideaforge.guard` and `validate_file` still recognise it, and `gen_agents.py` skips harness agents.
  - **Node side.** It shrinks to the harness package, Prettier and the commit gates: TypeScript, tsx, zod and Vitest are removed with the copied scripts and their tests. `pnpm check` is Prettier + `pnpm harness:check` + pytest.
  - **Plugin loading.** Driver sessions load the plugin from the installed package (`--plugin-dir`) and stop when it is missing.
  - This amends D-001, D-002 and D-004.
- Consequences:
  - Harness fixes arrive by bumping both pins (`docs/harness/README.md`).
  - Skill names gained the `harness:` prefix.
  - The evaluator's model for interactive use comes from the plugin (`opus`, the same as `harness_evaluator`); driver runs still take it from `harness.config.json`, which `tests/test_harness_config.py` keeps equal to `config/models.yaml`.
  - Interactive sessions need the folder trusted once for the marketplace and the permissions to apply.

## D-008 · Local web UI: FastAPI + Jinja2 + HTMX, headless control via `claude -p` (2026-10-24)

- Context:
  - The user wants a UI that starts and controls the pipeline, shows its reports and results, edits every pipeline setting, and keeps all data persistent.
  - The plan had only a read-only Streamlit viewer (IF-601) and a batch wrapper (IF-604) as optional v2 items.
  - The pipeline runs inside Claude Code skills. `/validate` asks up to five clarifying questions, which a headless run cannot ask.
  - D-003 keeps Node for development tooling only.
- Decision:
  - **Stack:** a local FastAPI app with server-rendered Jinja2 templates (Jinja2 is already a dependency) and HTMX, vendored so no page or test touches the network. Streamlit was rejected: forms, background jobs and offline tests through `TestClient` are simpler in FastAPI, and every ticket stays buildable unattended.
  - **Binding:** the server binds to `127.0.0.1` only and has no login.
  - **Control:** the UI never runs the model itself. It enqueues jobs that run the existing skills through `claude -p`, one at a time, with the strict pipeline guard. The new-idea form collects the clarifying answers up front as `intake.json`.
  - **Settings:** the UI edits `config/*.yaml` through the `ideaforge.config` models. `harness.config.json` is out of scope.
  - **Persistence:** the existing `ideaforge.db` and `runs/`, plus versioned migrations, job and settings-history tables, job logs and a backup command.
  - New dependencies: `fastapi`, `uvicorn`, `python-multipart`, `markdown-it-py`, `ruamel.yaml` (keeps the hand-commented YAML's comments), and `httpx` in the dev group.
- Consequences:
  - Seven tickets, IF-601 and IF-604–IF-609 (F-030–F-036), with the rules in TICKETS.md plan note 36. IF-601 and IF-604 are promoted from the backlog and widened.
  - Non-negotiable 1 is unaffected: everything is local and free.
  - Settings changed in the UI make `config/` differ from git, which `meta.json` already records as `config_dirty`.
  - The live headless path is first exercised by the human acceptance ticket IF-609.
