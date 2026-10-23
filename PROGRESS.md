# Progress log

Repository-local session log. Read it at clock-in, update it at clock-out (AGENTS.md).

## Current Verified State

- Repository root: `idea-generator/` (this directory; contains `AGENTS.md`, `feature_list.json`, `init.sh`, `harness.config.json`).
- Standard startup path: `./init.sh` (`FAST=1` skips the baseline). It needs node 24, pnpm and uv on `PATH`.
- Standard verification path: L1 `pnpm check` (tsc, Prettier, Vitest harness tests, `uv run pytest`). There is no L2/L3 (D-001). Per feature: `pnpm harness:verify F-NNN`.
- Phase 1 skeleton (F-001) and the harness (F-000) are `passing`. Nothing in Phase 2+ is built: `fi/` clients are stubs, and there is no `verify.py`, scoring, report, debate or eval code yet.
- Queue: 29 features (`pnpm harness:feature list`), 20 unattended and 7 human-only among the 27 open.
  - Ready now, unattended: F-006 (research validator), F-007 (claim verification), F-009 (usage report + status), F-010 (stage state machine), F-014 (scoring), F-015 (economics), F-021 (debate anonymization + validation).
  - Ready now, human-only: F-002 (§13 decisions), F-003 (record API fixtures). Both gate later work.
- Last verified commit: see Session 001 below and the F-000 / F-001 evidence in `feature_list.json`.
- Current blocker: none in the repo.
  - Host: `uv`, `claude` and `gh` are installed but not on the Git Bash `PATH` (`~/.local/bin`, `C:\Program Files\GitHub CLI`). The pipeline hooks fail open without `uv`.
  - GitHub branch protection does not exist yet, so `harness.config.json` keeps `merge: "wait"`.

## Next Steps

1. Human, once: add `%USERPROFILE%\.local\bin` and `C:\Program Files\GitHub CLI` to the user `Path`, then open a new terminal and restart VS Code. Run `gh auth login`. Run `claude` in the repository once and accept the trust dialog.
2. Human, GitHub (`docs/harness/README.md` § 4):
   - allow auto-merge and squash merging
   - push `main` so CI runs once
   - protect `main` with the required check `L1 (pnpm check)`
   - then set `merge` to `"auto"` in `harness.config.json`
3. Human-only features, interactively: F-002 (answer the §13 questions) and F-003 (record the API fixtures with network). They unblock F-004/F-005/F-008, the Phase 2 run and the starttiraha draft.
4. Unattended: `pnpm harness:loop --dry-run`, then `pnpm harness:loop --once` (F-006 first). Compare the evaluator's verdict with your own and add a row to the rubric's tuning log for each of the first 3–5 runs.

## Session Log

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
- Verification run: see the F-000 / F-001 evidence. `pnpm check` (25 Vitest + 124 pytest tests), `pnpm harness:check`, `./init.sh` and `FAST=1 ./init.sh`, and the porting guide's § 8 acceptance checks 1–9 (results in the commit that records this entry).
- Known risk: the driver has not run for real (no `pnpm harness:loop --once` yet), CI has not run on GitHub, and the evaluator rubric is uncalibrated.
- Next best step: Next Steps 1–4 above.
