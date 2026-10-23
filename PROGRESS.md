# Progress log

Repository-local session log. Read it at clock-in, update it at clock-out (AGENTS.md).

## Current Verified State

- Repository root: `idea-generator/` (this directory; contains `AGENTS.md`, `feature_list.json`, `init.sh`, `harness.config.json`).
- Standard startup path: `./init.sh` (`FAST=1` skips the baseline). It needs node 24, pnpm and uv on `PATH`.
- Standard verification path: L1 `pnpm check` (Prettier, `pnpm harness:check`, `uv run pytest`). There is no L2/L3 (D-001). Per feature: `pnpm harness:verify F-NNN`.
- Phase 1 skeleton (F-001), the harness (F-000), the full research validator (F-006), claim verification (F-007), the usage report + basic `/status` (F-009) and the stage state machine (F-010) are `passing`. Otherwise nothing in Phase 2+ is built: `fi/` clients are stubs, and there is no API re-query or conflict detection, scoring, report, debate or eval code yet.
- F-006: `validate_file --kind research` (and the SubagentStop hook) rejects figures without a following `>` quote and cited URLs missing from the agent's `.seen_urls.txt` (API URLs in `ideaforge.fi.API_URL_PREFIXES` exempt), and warns about factual sentences without `[src: …]` (hook mode also writes `VALIDATION_WARNINGS_<agent>`). The rule choices are TICKETS.md plan note 15; IF-216 (F-013) tunes them on real files.
- F-007: `uv run python scripts/verify_claims.py <run_id>` (`ideaforge.verify`, lxml + trafilatura, XHTML declarations stripped) parses the candidate claims of `02_research/*.md` into `03_claims/<dim>.json`, fetches each source once (robots.txt, 10 s timeout, UA, truststore; text cached in `cache/<sha256(url)>.txt`, `sources` rows), sets `verified` at normalized `partial_ratio ≥ 90`, flags `unfetchable` / `robots_disallowed`, types allow-listed URLs `official` (not `api`), and writes `03_claims/verified.json` + `claims` rows. Rules chosen unattended: TICKETS.md plan note 16.
- F-009: `uv run python scripts/usage_report.py <run_id>` (`ideaforge.usage.summarize` / `render_summary`) prints calls, searches, fetches and `~tokens` per stage and per agent from `usage.jsonl`, plus `BUDGET_EXCEEDED_*` markers. A research agent's calls are attributed to its own `research:<dim>`; other calls go to the latest-started `stages` window holding the timestamp, else `(no stage)`. `/status` (`.claude/skills/status/SKILL.md` → `scripts/status.py [run_id] [--limit N]`, `ideaforge.status`) lists recent runs with a folded stage line; with a run id: stages, claims per dimension × verification state, kill flags fired by verified claims (overrides marked), `VALIDATION_FAILED_*` / `VALIDATION_WARNINGS_*` / `BUDGET_EXCEEDED_*` markers and per-stage usage. Rules: TICKETS.md plan note 17.
- F-010: `runs.py` holds the stage state machine (`begin`, `finish`, `mark_insufficient`, `resume`, `next_stages`, `is_complete`, `STAGE_OUTPUTS`, `STAGE_GROUPS`); `scripts/run_stage.py <run_id> <stage> --begin|--finish|--insufficient-data` and `<run_id> --resume|--next` expose it to the skills. A stage is complete only when `insufficient_data`, or `done` with its output file(s) present and valid; `begin` needs every earlier group complete; `--finish` on an invalid output → `failed` (exit 1); `--resume` turns crashed `running` stages into `done` (valid file) or `pending`. Rules: TICKETS.md plan note 18; the manual crash test is in the IF-214 notes and runs in F-013.
- Queue: 29 features (`pnpm harness:feature list`), 20 unattended and 7 human-only among the 27 open.
  - Ready now, unattended: F-014 (scoring), F-015 (economics), F-021 (debate anonymization + validation). F-011 (skills, stages 0–3) is ready once F-010 merges; F-008 needs F-004/F-005 (behind F-003).
  - Ready now, human-only: F-002 (§13 decisions), F-003 (record API fixtures). Both gate later work.
- Last verified: branch `feat/F-010` on 2026-10-23, `pnpm harness:verify F-010` green (`pnpm check` = Prettier, `harness:check` and 302 pytest tests passed, 1 Windows-only skip; `tests/test_runs.py` 14 passed). Evidence for the other passing features is in `feature_list.json`.
- Session 002 (interactive: shared harness): the copied harness is replaced by `@eemelinen/harness` (devDependency, tag `v0.2.0`; the CLI behind every `pnpm harness:*`, new `pnpm harness:doctor`, also run by `./init.sh`) and the plugin `harness@eemelinen-harness` (skills `/harness:clock-in`, `/harness:verify-feature`, `/harness:clock-out`, agent `harness:evaluator`, hooks); the pipeline hooks are unchanged. Project rules live in `harness.config.json` and `docs/harness/generator-notes.md`. The evaluator is no longer generated (`agents.AGENTS["harness:evaluator"]`, 17 generated agents). D-007.
- Current blocker: none in the repo.
  - Host: `uv`, `claude` and `gh` are installed but not on the Git Bash `PATH` (`~/.local/bin`, `C:\Program Files\GitHub CLI`). The pipeline hooks fail open without `uv`. `gh` is already logged in (account Eemelinen, keyring).
  - Loop merging: `main` is protected with the required check `L1 (pnpm check)` (no review requirement) and `harness.config.json` has `merge: "auto"`, so `pnpm harness:loop` opens a PR per feature and GitHub squash-merges it once CI passes.

## Next Steps

1. Human, once: add `%USERPROFILE%\.local\bin` and `C:\Program Files\GitHub CLI` to the user `Path`, then open a new terminal and restart VS Code. Run `claude` in the repository once and accept the trust dialog and the harness plugin marketplace.
2. GitHub is set up for unattended runs: `main` is pushed, auto-merge and squash merging are allowed, `main` requires `L1 (pnpm check)`, and the loop merges with `merge: "auto"`.
3. Human-only features, interactively: F-002 (answer the §13 questions) and F-003 (record the API fixtures with network). They unblock F-004/F-005/F-008, the Phase 2 run and the starttiraha draft.
4. Unattended: `pnpm harness:loop` continues with the next ready feature (F-011 by priority once F-010 merges: the `/validate` and `/research` skills wrap every stage in `run_stage.py --begin/--finish`, start a re-run with `--resume`, and use `--insufficient-data` after a second validation failure). Usage attribution was checked against the new bookkeeping (plan note 18, last bullet); the usage hook still writes `stage: null`. Compare the evaluator's verdict with your own and add a row to the rubric's tuning log for each of the first 3–5 runs.

## Session Log

### Session 007 — 2026-10-23 (driver-run: F-010 stage state machine and resume)

- Goal: F-010 / IF-214 (absorbs the Python side of IF-507): `runs.py` state machine and `scripts/run_stage.py`.
- Completed:
  - `runs.py`: `STAGE_OUTPUTS` (stage → output file(s) + validator kind), `STAGE_GROUPS`, `StageError`, `statuses`, `output_problems`, `is_complete`, `next_stages`, `begin`, `finish`, `mark_insufficient`, `resume`. Validation reuses `validate_file.validate_path` (imported lazily; `validate_file` imports `runs`).
  - `scripts/run_stage.py <run_id> <stage> --begin|--finish|--insufficient-data`, `<run_id> --resume|--next` (exit 1 with `error:` on a refused transition or an invalid output).
  - `tests/test_runs.py` (14 tests, synthetic research files): transitions, earlier-group gating, done needs a valid file (also after the fact), synthesize needs both files, blank report, `insufficient_data`, crash reset, the IF-507 mid-stage-2 resume, CLI.
  - Docs: README usage line, §1 layout (`run_stage.py`), TICKETS.md plan note 18 and the IF-214 manual crash-test notes; `db.stage_done` docstring points at `runs.is_complete`.
- Choices (no one to ask): plan note 18. The notable ones: resume is an explicit `--resume`, not part of `--next` (research stages are legitimately running in parallel); a crashed `running` stage with a valid file becomes `done` instead of being re-run; `05_report.md` only has to be non-blank until IF-303 gives it a check; `--insufficient-data` is research-only.
- Verification run: `pnpm harness:verify F-010` → `pnpm check` (302 passed, 1 skipped) and `uv run pytest tests/test_runs.py` (14 passed).
- Next best step: F-011 (skills for stages 0–3) on top of `run_stage.py`.

### Session 006 — 2026-10-23 (driver-run: F-009 usage report and basic status)

- Goal: F-009 / IF-212 (absorbs IF-213): `scripts/usage_report.py` and `/status`.
- Completed (commit 9c39638):
  - `ideaforge.usage`: `read_log` (skips non-object lines, tolerates invalid UTF-8), `stage_windows` / `attribute_stage`, `summarize`, `table`, `usage_table`, `render_summary`, `budget_markers`, `marker_text`. `scripts/usage_report.py <run_id>` (exit 1 for a bad id or missing run dir).
  - New `ideaforge.status` (`recent_runs`, `run_status`, `stage_line`, `claims_table`, `kill_flag_lines`, `marker_lines`) and `scripts/status.py`; `.claude/skills/status/SKILL.md` runs it and shows the output verbatim.
  - Tests: `tests/test_usage_report.py`, `tests/test_status.py` with golden text in `tests/fixtures/status/` from a synthetic usage log and a fixture DB built in `conftest.synthetic_run` (fixed timestamps, every verification state, a restarted stage, markers, an override).
  - Docs: README usage lines, §1 layout (`status.py` in `src/ideaforge/` and `scripts/`), TICKETS.md plan note 17.
- Choices (no one to ask): see plan note 17. The notable ones: research calls attributed by agent identity, not time; kill flags "fire" only on `verified` claims (rubric comment), with overrides still listed and marked; `usage.jsonl` is the source, not the `usage` table.
- Evaluator (fresh context) before verification: Block, because no evidence was recorded yet; the code findings alone were a Revise. Fixed before the commit: attribution by research agent identity (a retried dimension's first-attempt calls had landed in another stage), invalid UTF-8 and directory-named markers no longer crash, non-list `flags` are ignored, a DB-only run test, §1 layout, script docstring.
- Verification run: `pnpm harness:verify F-009` → `pnpm check` (253 passed, 1 skipped) and the focused tests (20 passed).
- Next best step: F-010 (stage state machine), then F-011. The live check of both outputs on a real run is in F-013 (IF-216).

### Session 005 — 2026-10-23 (driver-run: F-007 attempt 2, evaluator revisions)

- Goal: address the evaluator's Revise verdict on F-007 (correctness 1, maintainability 1).
- Completed (commit c20324f):
  - `verify.page_text` strips a leading `<?xml … encoding=…?>` declaration (and BOM) before `lxml.html.fromstring`, which rejects an already-decoded str that declares an encoding. `extract_text` falls back to `trafilatura.extract` on any lxml `ValueError`/`LxmlError`, so XHTML sources are no longer flagged `unfetchable`.
  - `lxml` is a direct dependency (`uv add "lxml>=5.3"`; it was only pulled in by trafilatura).
  - `VerifyResult.files` → `by_file` (verified claims per research file stem); `summary()` groups by file stem, so a file whose claims name another dimension no longer prints a stray `0 claims` line.
  - Cache temp file is `<hash>.txt.<pid>.tmp` and is removed if the write or rename fails.
  - Tests: XHTML with an encoding declaration (`text/html` and `application/xhtml+xml`) is `ok` and its quote matches; the trafilatura fallback; the temp file is cleaned up after a failed rename; summary grouping by stem. Plan note 16 updated.
- Choice (no one to ask): a failed cache write still raises (a full disk should stop the run, not mark sources unfetchable).
- Verification run: `pnpm harness:verify F-007` → `pnpm check` (233 passed, 1 skipped) and `uv run pytest tests/test_verify.py` (46 passed).
- Next best step: F-009 or F-010.

### Session 004 — 2026-10-23 (driver-run: F-007 claim verification)

- Goal: F-007 / IF-208, stage 3 claim verification: parse candidate claims, fetch and cache sources, fuzzy-match quotes, type official sources, persist.
- Completed:
  - `src/ideaforge/verify.py`: injectable `HttpGet` (`requests_get` is the real one), `Fetcher` (per-run memo, cache, robots.txt per origin, `sources` rows via new `db.upsert_source`), `extract_text` (trafilatura, raw text types, JS-only detection), `normalize` / `quote_score` / `quote_matches`, `domain_matches` / `is_official` / `source_type`, `verify_claim`, `verify_run`, `summary`.
  - `scripts/verify_claims.py <run_id>`: summary per dimension on stdout, `warning:` lines on stderr, exit 1 only for an unknown run.
  - `validate_file.candidate_claims(md)` factored out of `validate_research` so the validator and the verifier parse claim blocks the same way.
  - Tests (`tests/test_verify.py`, synthetic pages only): 89/90 boundary, normalization, short-page guard, official-domain matching incl. path entries, source typing, cache hits (no network on re-run), robots semantics, unfetchable cases (403, 500, JS-only, empty, PDF, timeout), UA + timeout, and a run directory going from research Markdown to `verified.json`, DB claim and source rows and the script's output.
  - Docs: TICKETS.md plan note 16, README status line.
- Choices (no one to ask): see plan note 16. The notable ones: PDFs are `unfetchable`; unparseable claim blocks are warnings, not a failed stage; a model-declared `official` on a non-listed domain is kept, so scoring (F-014 / IF-302) must check `verify.is_official(url)` for `has_official_source`; `api` claims are quote-matched until F-008.
- Evaluator (fresh context) on the first commit: Revise (maintainability 1: `VerifyResult.files` unused, `summary()` docstring wrong). Fixed in a second commit together with the cheap robustness findings: every research file appears in the summary (`gtm: 0 claims`), cache files are written atomically, any fetch or extraction exception marks the source `unfetchable` instead of aborting the run, HTML is matched against the whole visible page (a quote in an `<aside>` was missed by trafilatura's main-content extract), more text types (`text/*`, `+json`, `+xml`), the re-run test checks cached claims stay `verified`, the exit-code doc names the missing-`02_research/` case. Not changed, recorded in plan note 16 for IF-216: robots.txt 5xx allows, no total-time/size cap, stale DB rows on re-run, model-declared `official` kept.
- Verification run: `pnpm harness:verify F-007` re-run after the fixes → `pnpm check` (228 passed, 1 skipped) and `uv run pytest tests/test_verify.py` (41 passed).
- Next best step: F-009 or F-010 (both gate F-011, the validate/research skills). Watch the PDF and JS-only rates on the first real run (F-013).

### Session 003 — 2026-10-23 (driver-run: F-006 full research validator)

- Goal: F-006 / IF-205, the bare-number, `[src: …]` and URL-provenance rules of the research output contract.
- Completed:
  - `validate_file.validate_research`: `check_prose` (figure sentence must end its paragraph or list item and be followed by a `>` quote; `[src: …]` warnings), `check_provenance` (prose URLs + claim `source_url` vs `.seen_urls.txt` of the dimension's agent, read from the run dir), warnings surfaced by the CLI (`warning:` lines) and the hook (stderr on exit 0, appended to block messages).
  - `ideaforge.fi.API_URL_PREFIXES` (the API URLs the data tools print, exempt from provenance) and `agents.research_agent(dimension)`.
  - Tests: table-driven bare-number (23), src-tag (7) and provenance (11) cases plus run-dir loading, CLI and hook warnings; synthetic `tests/fixtures/.seen_urls.txt` so the existing research fixture still validates under the full rules.
  - Docs: TICKETS.md plan note 15 (interpretations, chosen unattended), IMPLEMENTATION_PLAN §6 stage 2 hook description.
- Choices (no one to ask): the title + summary, `## Candidate claims` and `## Gaps` are exempt from the prose rules; "immediately followed" is strict (two figure sentences cannot share one quote); a missing `.seen_urls.txt` means nothing was seen.
- Evaluator (fresh context) on the first commit: Revise, because any 1800–2099 number counted as a year ("1900 residents" got through), and a lower-case "may" counted as a month. Fixed in a second commit: years only in a year context, capitalised English months, figures in inline code and `EUR650` checked, backtick/bold URLs normalized, `## Gaps` URLs skipped by provenance, hook warnings written to `VALIDATION_WARNINGS_<agent>`. Each fix has a table case.
- Verification run: `pnpm harness:verify F-006` re-run after the fixes → `pnpm check` and `uv run pytest tests/test_validate_file.py` (86 passed).
- Next best step: F-007 (claim verification). Watch the strict quote rule on the first real run (F-013).

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
