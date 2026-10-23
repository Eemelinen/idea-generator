# Progress log

Repository-local session log. Read it at clock-in, update it at clock-out (AGENTS.md).

## Current Verified State

- Repository root: `idea-generator/` (this directory; contains `AGENTS.md`, `feature_list.json`, `init.sh`, `harness.config.json`).
- Standard startup path: `./init.sh` (`FAST=1` skips the baseline). It needs node 24, pnpm and uv on `PATH`.
- Standard verification path: L1 `pnpm check` (Prettier, `pnpm harness:check`, `uv run pytest`). There is no L2/L3 (D-001). Per feature: `pnpm harness:verify F-NNN`.
- Phase 1 skeleton (F-001) and the harness (F-000) are `passing`. Nothing in Phase 2+ is built: `fi/` clients are stubs, and there is no `verify.py`, scoring, report, debate or eval code yet.
- Queue: 29 features (`pnpm harness:feature list`), 20 unattended and 7 human-only among the 27 open.
  - Ready now, unattended: F-006 (research validator), F-007 (claim verification), F-009 (usage report + status), F-010 (stage state machine), F-014 (scoring), F-015 (economics), F-021 (debate anonymization + validation).
  - Ready now, human-only: F-002 (§13 decisions), F-003 (record API fixtures). Both gate later work.
- Last verified commit: `db97340` (working tree with only `feature_list.json` changed by activate/verify). `pnpm harness:verify F-000` and `F-001` ran green on 2026-10-23: `pnpm check` = 25 Vitest + 124 pytest tests in about 14 s. The evidence lines are in `feature_list.json`.
- Session 002 (interactive: shared harness): the copied harness is replaced by `@eemelinen/harness` (devDependency, tag `v0.2.0`; the CLI behind every `pnpm harness:*`, new `pnpm harness:doctor`, also run by `./init.sh`) and the plugin `harness@eemelinen-harness` (skills `/harness:clock-in`, `/harness:verify-feature`, `/harness:clock-out`, agent `harness:evaluator`, hooks); the pipeline hooks are unchanged. Project rules live in `harness.config.json` and `docs/harness/generator-notes.md`. The evaluator is no longer generated (`agents.AGENTS["harness:evaluator"]`, 17 generated agents). D-007.
- Current blocker: none in the repo.
  - Host: `uv`, `claude` and `gh` are installed but not on the Git Bash `PATH` (`~/.local/bin`, `C:\Program Files\GitHub CLI`). The pipeline hooks fail open without `uv`. `gh` is already logged in (account Eemelinen, keyring).
  - Loop merging: `main` is protected with the required check `L1 (pnpm check)` (no review requirement) and `harness.config.json` has `merge: "auto"`, so `pnpm harness:loop` opens a PR per feature and GitHub squash-merges it once CI passes.

## Next Steps

1. Human, once: add `%USERPROFILE%\.local\bin` and `C:\Program Files\GitHub CLI` to the user `Path`, then open a new terminal and restart VS Code. Run `claude` in the repository once and accept the trust dialog and the harness plugin marketplace.
2. GitHub is set up for unattended runs: `main` is pushed, auto-merge and squash merging are allowed, `main` requires `L1 (pnpm check)`, and the loop merges with `merge: "auto"`.
3. Human-only features, interactively: F-002 (answer the §13 questions) and F-003 (record the API fixtures with network). They unblock F-004/F-005/F-008, the Phase 2 run and the starttiraha draft.
4. Unattended: `pnpm harness:loop --dry-run`, then `pnpm harness:loop --once` (F-006 first). Compare the evaluator's verdict with your own and add a row to the rubric's tuning log for each of the first 3–5 runs.

## Session Log

### Session 002 — 2026-10-23 (interactive: move to the shared harness)

- Goal: stop carrying a copy of the harness (D-001) now that it lives in `Eemelinen/harness`, so fixes made for any project reach this one by a version bump.
- Completed:
  - Installed `@eemelinen/harness` and enabled the plugin (both `v0.1.0`).
  - Deleted the copies: the harness `scripts/*.ts` and `clean-state-check.sh`, `.claude/hooks`, `.claude/skills`, `docs/harness/prompts/`, `tests/unit/`, `tsconfig.json`, `vitest.config.ts`, and TypeScript/tsx/zod/Vitest.
  - The evaluator is no longer generated: `agent_templates/evaluator.md.j2` and `.claude/agents/evaluator.md` are gone, `agents.AGENTS["harness:evaluator"]` is registered, and `gen_agents.py` skips harness agents. The guard and validate_file tests use the plugin's agent type.
  - Moved the project values into `harness.config.json` and `docs/harness/generator-notes.md`.
  - Commit gates and checks: `pnpm check` = Prettier + `pnpm harness:check` + pytest; pre-commit no longer runs `typecheck`; `init.sh` runs `pnpm harness:doctor`.
  - Docs: AGENTS.md, CLAUDE.md, README, IMPLEMENTATION_PLAN §14, TICKETS, `docs/harness/README.md` (now the project page), the checklist and the rubric, D-007.
  - The release also brings the loop's stop on a failed CI check (Metsävahti).
- Verification run: `pnpm check` green (Prettier, `harness:check`, 124 pytest tests) with the package installed from the `v0.1.0` tag; `uv run python scripts/gen_agents.py --check` → 17 agent files up to date; `pnpm harness:doctor` ok; `pnpm harness:check` accepts the 29 features and a write through `harness feature attempt` (on a copy) leaves the file byte-identical apart from `attempts`; `pnpm harness:feature next` still picks F-006; `pnpm harness:clean-state --base main` after the commit.
- Known risk: interactive sessions need the folder trusted once for the plugin marketplace and `.claude/settings.json` permissions; driver sessions load the plugin from the package.
- Next best step: Next Steps 1–4.

### Session 001 — 2026-10-23 (interactive: harness bootstrap, F-000; Phase 1 recorded as F-001)

- Goal: port the Metsävahti agent harness (tag `harness-reference`, `docs/harness/porting-guide.md`) and re-cut the open tickets so the driver can build the rest of the plan one feature per session.
- Completed:
  - COPY: `scripts/harness-feature.ts`, `verify-feature.ts`, `harness-events.ts`, the Vitest tests in `tests/unit/harness/`, `stop-guard.sh`, `format.sh`, the evaluator prompt and schema, `.gitattributes`, husky hooks and `commitlint.config.mjs`.
  - ADAPT:
    - `validate-feature-list.ts` (`IF-NNN` tickets; no `epic`/`design`) and the two `harness-feature.ts` lines that printed those fields
    - `harness-loop.ts` (no Docker preflight)
    - `clean-state-check.sh` (Python skip/xfail, coverage and debugger checks)
    - `guard.sh` (uv-only Python, `pip install` block, generated agents and both lockfiles denied, ask on `models.yaml`)
    - `session-start.sh`, the skills, `harness.config.json`, `init.sh`
    - `.claude/settings.json`, merged with the pipeline hooks
    - `docs/harness/*`, and `CLAUDE.md` (`@AGENTS.md`, plus a Pipeline sessions section)
  - WRITE: `AGENTS.md`, this file, `feature_list.json`, `docs/DECISIONS.md` (D-001–D-006), `session-handoff.md`, `quality-document.md`, `.github/workflows/ci.yml` and the Node plumbing (`package.json`, `tsconfig.json`, `vitest.config.ts`, Prettier config).
  - Python:
    - `evaluator` registered as a generated agent (kind `harness`, role `harness_evaluator`)
    - `ideaforge.guard`: `HARNESS_LOOP=1` counts as a development session; evaluator allow-list
    - `validate_file --auto` ignores the evaluator
    - `tests/conftest.py` clears `HARNESS_LOOP`
    - `tests/test_harness_config.py`
  - Tickets: `docs/TICKETS.md` rewritten as the spec (44 open tickets → 27 features plus IF-200; no status column); `IMPLEMENTATION_PLAN.md` intro, §1, §2, §3, §4.1, §7, §9, §11 and the new §14.
- Choices made without a human:
  1. pnpm is pinned to 10.15.0, as in the reference. pnpm 12 creates real symlinks, and Windows refused them here ("Access is denied").
  2. Prettier formats only harness and docs files. `prompts/`, `agent_templates/` and `config/` are ignored because they feed generated agents byte-for-byte.
  3. There is no eslint, so lint-staged runs Prettier and the feature-list validator only.
  4. Harness models are the alias `opus`, kept equal to `models.yaml` by a test (D-004).
  5. Phase gates became `depends_on` (D-006).
  6. `merge: "wait"` until branch protection exists.
- Verification run: the F-000 / F-001 evidence, plus the porting guide's § 8 acceptance checks 1–9, all passing:
  1. `pnpm install` runs husky (`core.hooksPath=.husky/_`).
  2. `pnpm harness:check` prints `29 features · 2 passing … 9 ready (7 unattended) · VCR 2/2`.
  3. `pnpm check`: 25 Vitest and 124 pytest tests in about 14 s.
  4. `./init.sh` and `FAST=1 ./init.sh` both exit 0.
  5. `scripts/clean-state-check.sh` on the committed tree: all `[ok]`. Probes confirmed that an added `@pytest.mark.skip` and an added `breakpoint()` are caught.
  6. Hooks:
     - `session-start.sh` prints the summary.
     - `guard.sh` blocks npm, bare python/pytest and `pip install`.
     - It denies `uv.lock` / `pnpm-lock.yaml` (also via backslash paths) and `.claude/agents/*`, and asks on `config/models.yaml`.
     - With `HARNESS_LOOP=1` it denies a write outside the repo, `mkdir -p ~/x` and `git push`.
     - `ideaforge.guard` allows a `src/` write in a marker-less worktree only with `HARNESS_LOOP=1`.
  7. Commit gates: commitlint rejects "bad message"; commit-msg rejects an AI attribution trailer; both the guard's commit gate and lint-staged reject a `passing` feature without evidence.
  8. `pnpm harness:feature next` → F-006. `pnpm harness:loop --dry-run` passes preflight and prints the worktree and `claude` commands for the 7 ready unattended features. Its only warning is that `main` is ahead of `origin/main` (not pushed, by design). A one-off probe `claude -p --model opus` answered (claude-opus-5-5).
  9. A fresh worktree with committed files only: `FAST=1 ./init.sh` and `pnpm check` pass. The worktree and branch were removed afterwards.
- Fixed during the checks: the clean-state debugger check matched its own pattern in `scripts/clean-state-check.sh` (now `*.py` only), and the guard's Python rules matched heredoc lines (now command position only).
- Known risk: the driver has not run for real (no `pnpm harness:loop --once` yet), CI has not run on GitHub, and the evaluator rubric is uncalibrated.
- Next best step: Next Steps 1–4 above.
