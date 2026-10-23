# Ideaforge — agent operating manual

Ideaforge is a local business-idea validator for founders in Rääkkylä / North Karelia, Finland.
A user types an idea; Claude Code skills and subagents research it across ten feasibility
dimensions, `scripts/verify_claims.py` verifies every quoted claim against its source, Python
scores it and writes an evidence-backed report, and an optional multi-agent debate improves the
plan. Python 3.12 + uv + SQLite do everything deterministic; Node + pnpm are development-only
tooling for this harness (D-003). Docs, code and commits are English; report content may be Finnish.
Design: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) · tickets: [docs/TICKETS.md](docs/TICKETS.md).

This file is a router, not a manual: it defines the development session loop and the invariants
and links to the detail. The repository, not the chat, is the system of record. A session started
to **run** the pipeline (`/validate`, `/research`, `/debate`, `/status`) follows
[CLAUDE.md → Pipeline sessions](CLAUDE.md#pipeline-sessions) instead of the loop below.

## Clock-in (session start)

Before touching code:

1. `pwd` — confirm you are in the repository root.
2. Read [PROGRESS.md](PROGRESS.md) — Current Verified State and Next Steps.
3. `pnpm harness:feature next --include-manual` — the highest-priority `not_started` feature whose `depends_on` are all `passing` ([feature_list.json](feature_list.json)). `pnpm harness:feature show F-NNN` prints its spec link; read that ticket in `docs/TICKETS.md` and the plan sections it cites before coding.
4. `git log --oneline -5` — what changed most recently.
5. `./init.sh` — checks node/pnpm/uv, installs both toolchains and runs the L1 baseline (`FAST=1` skips it).
6. If the baseline is red, fix that first. Never stack feature work on a broken start.
7. `pnpm harness:feature activate F-NNN` (WIP=1, dependency check) and work only on it.

Claude Code: `/clock-in` runs these steps; the SessionStart hook prints the state summary.

## Verification layers

| Layer | Command      | Covers                                                                                               | Needs                      |
| ----- | ------------ | ---------------------------------------------------------------------------------------------------- | -------------------------- |
| L1    | `pnpm check` | `tsc` on the harness scripts, Prettier check, Vitest harness tests, the full `uv run pytest` (~15 s) | node, pnpm, uv; no network |

- There is no L2/L3: the project runs no services, and a real pipeline run needs Claude and the network, so features that need one carry a `manual:` step instead (D-001).
- Steps run in order. Do not proceed to step N+1 while step N fails, and do not skip a step a feature lists.
- The repository is in a consistent state when `pnpm check` exits 0.
- `pnpm harness:check` validates `feature_list.json`; it also runs from `pnpm test:unit`, lint-staged and the commit guard.
- `pnpm harness:verify F-NNN` runs a feature's steps in order and records evidence; `manual:` steps fail closed. `scripts/clean-state-check.sh` is the machine-checkable clock-out gate.

## Constraints

Each rule carries a `why:` so it can be revisited when the reason disappears.

- MUST NOT add a paid service or API key; only `WebSearch`/`WebFetch`, the free Finnish/EU open-data APIs, pip packages and SQLite. why: the tool runs on a Claude Max subscription with no other budget. source: IMPLEMENTATION_PLAN.md §0.1.
- MUST keep model choice in `config/models.yaml` only; agent files get `model:` from `scripts/gen_agents.py`, and `harness.config.json` must match the `harness_*` roles. why: the user downgrades roles when usage limits bite, in one place. source: §0.2, §4.3, D-004, tests/test_harness_config.py.
- MUST NOT hand-edit `.claude/agents/`; edit `agent_templates/` or `prompts/` and run `uv run python scripts/gen_agents.py`. why: generated, and `gen_agents.py --check` (in pytest) fails on drift or stray files. source: §4.3.
- MUST give every number the pipeline uses a source URL, a retrieval timestamp and a verified quote; anything else never counts toward a score. why: the report's value is that it is evidence-backed. source: §0.3.
- MUST compute scores, caps, kill triggers, totals, unit economics and the verdict in Python; the model only proposes. why: model arithmetic and self-grading are unreliable. source: §0.4.
- MUST write every stage's output to disk/SQLite before the next stage, and skip completed stages on re-run. why: runs are long and usage-limited; a crash must not cost a re-run. source: §0.5.
- MUST validate every structured file against a schema in `src/ideaforge/schemas.py`. why: hooks re-prompt once on invalid output, then mark the dimension `INSUFFICIENT_DATA`. source: §0.6.
- MUST keep the debate anti-sycophantic: isolated round 0, stance changes only with a new claim id or a computation, author-blind judge, max 3 rounds. why: personas otherwise converge on agreement. source: §0.7.
- MUST cite an allow-listed official domain (`config/domains.yaml`) for regulatory, tax and grant claims, and treat `config/finland.yaml` values as hints to verify, never facts. why: Finnish rules change; stale hints mislead founders. source: §3.6.
- MUST run Python only through `uv run` (`uv run pytest …`, `uv run python …`) and add dependencies with `uv add`. why: PATH on the dev machine has other Pythons first; `guard.sh` blocks bare `python`/`pytest`/`pip`. source: .claude/hooks/guard.sh.
- MUST keep tests offline and MUST NOT invent fixture data: Finnish API responses come only from IF-200 recordings; synthetic fixtures for logic tests are labelled synthetic. why: tests run in worktrees and CI without network; invented "facts" would pass verification. source: docs/TICKETS.md notes 13–14.
- MUST NOT skip, xfail or weaken tests, or lower coverage thresholds, to get green. why: verification is the completion gate; `scripts/clean-state-check.sh` checks it.
- MUST update docs affected by a change in the same commit (README, `IMPLEMENTATION_PLAN.md`, `docs/TICKETS.md` plan notes, `docs/DECISIONS.md`). why: stale docs mislead the next session more than no docs.
- MUST make one logical change per commit, with a conventional-commit subject and a body that explains why, and no AI attribution lines. why: commitlint and the commit-msg hook enforce it; the history is read at every clock-in. source: .husky/commit-msg.
- MUST NOT add secrets or a `.env`; the project needs none. why: free public APIs only; the deny list blocks `.env`.

## Working rules

- WIP=1: only one feature may be `in_progress`. Finish it (`passing`) or mark it `blocked` with a note before activating the next.
- State machine: `not_started → in_progress → passing`, or `→ blocked` with the reason in `notes`. Change status only through `pnpm harness:feature` / `pnpm harness:verify`; never set `passing` by hand without evidence.
- Dependencies live in `depends_on`; a feature is ready when every dependency is `passing`. Each feature maps to one ticket in `docs/TICKETS.md` (`ticket`, `spec` fields).
- Granularity: a feature must be completable in one session. If it cannot, split it in `feature_list.json` (and the ticket) before starting.
- Scope: stay inside the selected feature; a narrow supporting fix is fine, a second feature is not.
- Completion means evidence, not confidence: run the listed steps and record `YYYY-MM-DD <command> → pass (commit <hash>)` in `evidence` (`pnpm harness:verify` writes it).
- Context anxiety: if you are running low on context, do not rush to finish. Stop, update `PROGRESS.md`, commit a clean checkpoint, and leave the next step written down.
- Escalate instead of guessing: unclear requirements → the ticket, then the plan section it cites and "Plan notes and deviations" in `docs/TICKETS.md`, then ask; design decisions → `IMPLEMENTATION_PLAN.md` + `docs/DECISIONS.md`, then ask; repeated failures → record in `PROGRESS.md` and flag for review. In a driver-run session (`HARNESS_LOOP=1`) nobody can answer: pick the simplest reading, record it (a plan deviation goes into the TICKETS.md notes), or block the feature.

## Definition of done

A feature is done only when all of these are true:

- [ ] The `user_visible_behavior` is implemented.
- [ ] Every listed verification step actually ran, in order, and passed.
- [ ] Evidence is recorded in `feature_list.json` and the status is `passing`.
- [ ] `PROGRESS.md` is updated (Current Verified State, session entry, Next Steps).
- [ ] Affected docs are updated in the same commit.
- [ ] The tree is committed and clean, and `FAST=1 ./init.sh` still exits 0.

## Clock-out (session end)

1. `scripts/clean-state-check.sh --allow-state-dirty`, then the judgement items of [docs/harness/clean-state-checklist.md](docs/harness/clean-state-checklist.md).
2. Update `PROGRESS.md`; `feature_list.json` is already updated by `pnpm harness:verify` (or `pnpm harness:feature block`); `pnpm harness:check`.
3. `pnpm check`.
4. Optional: score the diff with [docs/harness/evaluator-rubric.md](docs/harness/evaluator-rubric.md) (Claude Code: `evaluator` subagent). Revise before committing if any category is below 2.
5. Commit; for long sessions also fill [docs/harness/session-handoff.md](docs/harness/session-handoff.md).
6. Leave a clean restart path: the next session must be able to run `./init.sh` immediately.

Cleanup is dual-mode: immediate at every clock-out, plus a periodic (monthly) sweep that prunes stale docs and old PROGRESS.md sessions and regrades [docs/harness/quality-document.md](docs/harness/quality-document.md).

Claude Code: `/clock-out` walks these steps; `/verify-feature F-NNN` runs a feature's steps and records evidence.

## Driver-run sessions

`pnpm harness:loop` runs the same loop unattended: one fresh session per ready feature in its own worktree, `pnpm harness:verify` as the gate, a fresh-context evaluator, then a PR. Inside such a session `HARNESS_LOOP=1` is set (the pipeline guard then treats it as a development session, D-005), questions cannot be asked, `manual:` steps are never waived, nothing fetches live data, and the driver (not the session) pushes. Everything about it: [docs/harness/README.md](docs/harness/README.md).

## State artefacts and further reading

- State: [PROGRESS.md](PROGRESS.md) · [feature_list.json](feature_list.json) · [docs/DECISIONS.md](docs/DECISIONS.md) · [docs/harness/](docs/harness/) (README, prompts, handoff, checklist, rubric, quality document).
- Spec: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (§1 layout, §5 data model, §6 stages) · [docs/TICKETS.md](docs/TICKETS.md) (tickets, plan notes and deviations).
- Project: [README.md](README.md) · `config/` (models, rubric, Finland hints, domains, budgets, founder) · `prompts/` + `agent_templates/` (sources of `.claude/agents/`) · `src/ideaforge/` · `scripts/` · `tests/` (pytest; `tests/unit/harness/` is Vitest).
- Tools: Claude Code permissions, hooks, skills and the evaluator subagent are described in [CLAUDE.md](CLAUDE.md) and live in `.claude/`.
