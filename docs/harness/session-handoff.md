# Session handoff

Compact handoff for the next session. Fill it in at clock-out when the session was long or
touched several areas; for a short single-feature session the `PROGRESS.md` entry is enough.
Copy the template below into the top of this file (newest first) and fill every line.

### Handoff — 2026-10-23 · session 001 (harness bootstrap, F-000) → next: F-006 or F-002/F-003

#### Verified now

- What is currently working: `pnpm check` (typecheck, Prettier, harness unit tests, full pytest), `pnpm harness:check`, `pnpm harness:feature next/show/list`, `pnpm harness:verify`, `scripts/clean-state-check.sh`, `pnpm harness:loop --dry-run`; hooks (`session-start.sh`, `guard.sh`, `stop-guard.sh`, `format.sh`) next to the pipeline hooks; commit gates (commitlint, lint-staged, AI-attribution check).
- What verification actually ran: see Session 001 in `PROGRESS.md` and the F-000 evidence lines.

#### Changed this session

- Code or behaviour added: `evaluator` agent registered in `src/ideaforge/agents.py` (kind `harness`) and rendered by `gen_agents.py`; `ideaforge.guard` treats `HARNESS_LOOP=1` as a development session and gives the evaluator a read-only allow-list; `validate_file --auto` ignores the evaluator.
- Infrastructure or harness changes: the whole harness (see `docs/harness/README.md`); tickets re-cut from 44 open to 27 features (`docs/TICKETS.md`, D-006).

#### Broken or unverified

- Known defect: none known.
- Unverified path: a real `pnpm harness:loop --once` (driver + evaluator + PR + merge) has not run yet; CI has not run on GitHub yet.
- Risk for the next session: `uv`, `claude` and `gh` are not on the Git Bash `PATH` of this machine; the pipeline hooks fail open without `uv`.

#### Next best step

- Highest-priority unfinished feature: unattended F-006 (research validator); human-only F-002 (§13 decisions) and F-003 (API fixtures) unblock the rest.
- Why it is next: lowest priority number among ready features; F-002/F-003 gate every client and the Phase 2 run.
- What counts as passing (from `feature_list.json` → `verification`): its `L1:` steps green through `pnpm harness:verify`.
- What must not change during that step: the pipeline hooks in `.claude/settings.json`, the generated `.claude/agents/`, `config/models.yaml`.

#### Commands

- Startup: `./init.sh` (`FAST=1` to skip the baseline)
- Verification: `pnpm check` (L1) · `pnpm harness:verify F-NNN`
- Focused debug command: `uv run pytest tests/test_x.py -x -q` · `pnpm test:unit` · `pnpm harness:feature list`

## Template

### Handoff — YYYY-MM-DD · feature F-NNN

#### Verified now

- What is currently working:
- What verification actually ran (commands + result):

#### Changed this session

- Code or behaviour added:
- Infrastructure or harness changes:

#### Broken or unverified

- Known defect:
- Unverified path:
- Risk for the next session:

#### Next best step

- Highest-priority unfinished feature:
- Why it is next:
- What counts as passing (from `feature_list.json` → `verification`):
- What must not change during that step:

#### Commands

- Startup: `./init.sh` (`FAST=1` to skip the baseline)
- Verification: `pnpm check` (L1) · `pnpm harness:verify F-NNN`
- Focused debug command: `uv run pytest tests/test_x.py -x -q`
