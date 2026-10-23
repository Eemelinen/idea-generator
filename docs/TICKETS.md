# Ideaforge: feature tickets

This file breaks [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) (the plan) into tickets. `§` numbers refer to sections of the plan.

**How tickets relate to the harness.** Every open ticket is one feature in [feature_list.json](../feature_list.json); the feature's `spec` field links the ticket heading here. This file is the **spec**: goal, scope, verification, acceptance. It has no status column. Status lives only in `feature_list.json` and changes only through `pnpm harness:*` (`pnpm harness:feature list` shows the queue). The session loop is in [AGENTS.md](../AGENTS.md).

**Size.** Each ticket fits one Claude Code session (roughly ≤ 100 turns). Tightly coupled tickets were merged into one (D-006 in [DECISIONS.md](DECISIONS.md)); a survivor keeps its id and lists what it absorbs. If a ticket turns out too big, split it in `feature_list.json` before starting.

**Mode.** `unattended` features can run under `pnpm harness:loop`: their verification is offline `L1:` commands. `human` features have a `manual:` step: a live API call, a real Claude run of the pipeline, or a decision only the user can make. The driver skips them and they run interactively.

**Order.** Work is ordered by `depends_on`, not by phase. A phase-acceptance ticket (IF-216, IF-309, IF-408, IF-501) gates only the work that needs its real-run output, so pure-Python work keeps moving while a human run waits.

**Verification.** `L1: pnpm check` is always the first step (Prettier, `pnpm harness:check`, full pytest). The focused `uv run pytest …` steps name the test files the ticket creates or extends. Tests never touch the network: they run on fixtures recorded by IF-200 or on synthetic fixtures that are clearly labelled as such.

---

## Plan notes and deviations

These came out of reviewing the plan. Phase 1 already applies them; later tickets must follow them. Add a note here whenever a session knowingly deviates from the plan.

1. **Missing from the §1 layout:** `04_scores_proposed.json`, `04_risks.json`, `meta.json`, `config/founder.yaml` (§13), `tests/fixtures/` (§9) and the `reviews` table (§9, missing from §5). All have been added: schemas `ProposedScores`, `RiskRegister`, `RunMeta`; table `reviews`.
2. **`killcause` is a research task, not a rubric dimension.** `Dimension` = the 10 rubric ids + `killcause`. Killcause claims carry kill-trigger flags and feed the investor persona, but have no weight.
3. **Budget presets (§10) vs flat `budget.yaml` (§4.4).** `budget.yaml` now holds `default_preset` plus `presets: {economy, standard, deep}`, each with the §4.4 keys. `meta.json` records each run's preset.
4. **Active run.** `scripts/new_run.py` writes `runs/.active`. Hooks read `IDEAFORGE_RUN_ID` first, then the marker, and do nothing when neither exists.
5. **Development session (§7).** A gitignored `.ideaforge-dev` marker relaxes the guard for the **main session only**. `HARNESS_LOOP=1` (set by the loop driver) does the same (D-005). Subagents (hook input has `agent_type`) are always strict: a research agent may write only its own `02_research/<dim>.md`, a debate agent only `debate/`. Writes outside the project root or into `.git/` are always denied. ⚠ The guard fails open when `uv` isn't on PATH, because the hook then exits with a non-blocking error code.
6. **Windows.** The shell guard also covers the `PowerShell` tool (denies `Invoke-WebRequest`, `iwr`, `irm`, …) and normalizes Git Bash paths (`/c/…`).
7. **Hook semantics.** SubagentStop exit 2 sends stderr back to the _subagent_, so it fixes its own file. The validator blocks once. On the second failure (`stop_hook_active`) it writes `runs/<id>/VALIDATION_FAILED_<agent>` and lets the agent stop; the orchestrator then marks the dimension `INSUFFICIENT_DATA`. PostToolUse has no token counts, so `approx_tokens = len(json(in+out)) / 4`.
8. **Mechanical "no invented URL" check.** The usage hook logs every URL seen in WebSearch/WebFetch results to `runs/<id>/.seen_urls.txt`. IF-205 uses it to reject citations that never appeared.
9. **TLS interception on the dev machine.** uv needed `system-certs = true` (in `pyproject.toml`). Python `requests` will hit the same issue: use `truststore.inject_into_ssl()` (dependency already added) in every HTTP client (IF-200–IF-202, IF-208).
10. **New modules not in §1:** `config.py` (validated config loading), `agents.py` (agent registry: name → role/dimension/persona/evidence subset), `guard.py` (PreToolUse policy), `hookio.py` (hook I/O).
11. **Rebuttal schema.** `Response.cited_claim_ids` (existing ledger ids backing a `disagree`), `Rebuttal.round`, `Rebuttal.updated_change_basis` and `Rebuttal.mini_research` were added so the §6.7 rules can be checked mechanically. `IdeaSpec.kill_trigger_overrides` implements "unless the user has explicitly overridden in the spec" (§6 stage 5).
12. **Development harness (D-001–D-004).** `AGENTS.md`, `PROGRESS.md`, `feature_list.json`, `scripts/*.ts`, `.claude/hooks/*.sh`, the `clock-in` / `verify-feature` / `clock-out` skills and an 18th generated agent, `evaluator` (kind `harness`, role `harness_evaluator` in `models.yaml`). Node + pnpm are development-only tooling. IF-211 makes the claim extractor the 19th agent.
13. **Ticket re-cut (D-006).** 44 open tickets became 27 features. IF-200 (live API fixtures) is new. The "works on the real run" acceptance lines of the merged tickets moved into the phase-acceptance tickets, because offline sessions cannot produce a real run. Phase gating is replaced by `depends_on`.
14. **No invented data in tests.** Fixture responses of the Finnish APIs come only from IF-200. Golden-set facts (IF-501) are researched by a person. Unattended sessions may write synthetic fixtures for logic tests, labelled `synthetic` in the file or its name, and never present them as real sources.
15. **Research validator rules (IF-205).** Interpretations made unattended, to be tuned in IF-216:
    - The bare-number and `[src: …]` rules apply to every `##` section except `## Candidate claims` and `## Gaps`; the title + summary before the first `##` is exempt (the contract lists both rules under `## Findings`, and the summary restates findings).
    - "Immediately followed" is strict: a figure sentence must be the last sentence of its paragraph or list item, and the next block must be a `>` quote. Two figure sentences sharing one quote fail.
    - Not figures: ISO / Finnish / month-year dates, day + month name (English months capitalised only, so "30 may be" stays a figure; Finnish `…kuu…` forms), claim ids, identifiers (`B2B`, `Q1`, `COVID-19`; not `EUR650`), digits inside URLs and `[src: …]` tags. A 4-digit 1800–2099 number counts as a year only in a year context: after in/since/until/during/before/after, a year word (`vuonna`, `vuoden`, …) or a month, in parentheses, with a Finnish case ending (`2024:n`), or in a range or season (`2019–2024`, `2024/25`). "1900 residents", "grew to 2000 visitors" and "in 2000 EUR instalments" are figures. Inline code is checked like prose.
    - The `[src: …]` heuristic treats a sentence of ≥ 4 words as factual unless it reports a gap (`no data`, `not found`, `could not`, `unknown`, …). It only warns: `warning:` lines in the CLI; in hook mode stderr plus `runs/<id>/VALIDATION_WARNINGS_<agent>` (exit-0 hook output reaches nobody), removed when a later run is clean. The `/validate` skill and `/status` (F-011, F-009) should surface that file.
    - URL provenance checks every URL in the prose outside `## Gaps` (which names sources the agent could not reach) plus each claim's `source_url` against the lines of `.seen_urls.txt` for the dimension's agent, after stripping trailing punctuation, backticks and `*`, the `#fragment` and a trailing `/`. A missing file means nothing was seen. "`ideaforge.fi` API URLs" means the request URLs the data tools print (their Bash output is not logged): the prefixes in `ideaforge.fi.API_URL_PREFIXES` (StatFin and Luke PxWeb API, PRH YTJ API, Eurostat dissemination API).

---

## Index

| Ticket        | Feature | Title                                                  | Absorbs         | Depends on                 | Mode       |
| ------------- | ------- | ------------------------------------------------------ | --------------- | -------------------------- | ---------- |
| —             | F-000   | Agent harness bootstrap                                | —               | —                          | done       |
| IF-101        | F-001   | Phase 1 skeleton                                       | IF-102–IF-107   | —                          | done       |
| IF-150        | F-002   | Resolve open decisions (§13)                           | —               | F-001                      | human      |
| IF-200        | F-003   | Record Finnish open-data API fixtures                  | —               | F-001                      | human      |
| IF-201        | F-004   | PxWeb client (StatFin + Luke)                          | —               | F-003                      | unattended |
| IF-202        | F-005   | PRH and Eurostat clients                               | IF-203          | F-003                      | unattended |
| IF-205        | F-006   | Full research validator                                | —               | F-001                      | unattended |
| IF-208        | F-007   | Claim verification: fetch, cache, quote match          | —               | F-001                      | unattended |
| IF-209        | F-008   | API re-query verification and conflict detection       | IF-210          | F-004, F-005, F-007        | unattended |
| IF-212        | F-009   | Usage report and basic status                          | IF-213          | F-001                      | unattended |
| IF-214        | F-010   | Stage state machine and resume                         | IF-507 (Python) | F-001                      | unattended |
| IF-206        | F-011   | Validate and research skills, stages 0–3               | IF-207, IF-215  | F-006, F-007, F-009, F-010 | unattended |
| IF-204        | F-012   | Research briefs tuned and claim-extractor agent        | IF-211          | F-004, F-005, F-006, F-007 | human      |
| IF-216        | F-013   | Phase 2 acceptance run                                 | —               | F-002, F-008, F-011, F-012 | human      |
| IF-302        | F-014   | Scoring                                                | —               | F-001                      | unattended |
| IF-303        | F-015   | Unit economics                                         | —               | F-001                      | unattended |
| IF-304        | F-016   | Synthesis and score run                                | IF-301          | F-014, F-015               | unattended |
| IF-305        | F-017   | Report rendering with Finland and Rääkkylä sections    | IF-306          | F-009, F-016               | unattended |
| IF-307        | F-018   | Starttiraha business-plan draft                        | —               | F-002, F-017               | unattended |
| IF-308        | F-019   | Versioning, meta.json and validate --from              | —               | F-010, F-017               | unattended |
| IF-309        | F-020   | Phase 3 acceptance run                                 | —               | F-013, F-018, F-019        | human      |
| IF-402        | F-021   | Debate anonymization and rebuttal validation           | IF-403          | F-001                      | unattended |
| IF-405        | F-022   | Convergence, conformity flag, verdict and revised plan | IF-406          | F-017, F-021               | unattended |
| IF-407        | F-023   | Debate skill, prompts and mini-research                | IF-401, IF-404  | F-011, F-022               | unattended |
| IF-408        | F-024   | Phase 4 acceptance run                                 | —               | F-020, F-023               | human      |
| IF-502        | F-025   | Eval checker and eval skill                            | —               | F-016                      | unattended |
| IF-501        | F-026   | Golden set and eval run                                | —               | F-024, F-025               | human      |
| IF-503        | F-027   | Back-test as-of, preset wiring and usage-limit docs    | IF-506, IF-508  | F-007, F-011, F-025        | unattended |
| IF-504        | F-028   | Review scores and status diff                          | IF-505          | F-009, F-019               | unattended |
| IF-601–IF-604 | —       | Phase 6 backlog (not queued)                           | —               | —                          | —          |

---

## Phase 1: Skeleton (done)

**Phase 1 acceptance (§11): met.** `uv run pytest` passes (schema, config, db, guard, usage, validator and run tests). `gen_agents.py` produces the agent files, all `model: opus`. A `Write` outside the allowed paths gets exit 2 from the guard hook. In the queue as F-001.

### IF-101 Phase 1 skeleton

Absorbs IF-102–IF-107. Kept for reference:

- **IF-101 Toolchain and repo skeleton:** `pyproject.toml` (uv, hatchling, Python 3.12 pinned in `.python-version`, deps from §2 + `truststore`), `.gitignore`, directory layout from §1, `runs/.gitkeep`.
- **IF-102 CLAUDE.md and config files:** `CLAUDE.md` (§3), `README.md`, `config/models.yaml`, `rubric.yaml` (10 dimensions with questions, evidence rules, kill triggers, verdict thresholds, killcause block), `domains.yaml`, `finland.yaml` (hints with `verify_at_runtime`), `budget.yaml` (presets), `founder.yaml` (placeholder, `confirmed: false`), `src/ideaforge/config.py` validators. Tests: `tests/test_config.py`.
- **IF-103 Pydantic schemas:** every §5 model plus `CandidateClaim`, `ProposedScores`, `RiskRegister`, `UnitEconomics`, `RunMeta`; `extra="forbid"` everywhere; claim-id/quote/URL validators; `SCHEMAS` registry. Tests: `tests/test_schemas.py`.
- **IF-104 SQLite schema and helpers:** all §5 tables + `reviews`, WAL mode, FTS5 `claims_fts` with sync triggers, `init`, `create_run`, `upsert_claims`, `stage_set`, `stage_done`, `log_usage`. Tests: `tests/test_db.py`.
- **IF-105 Agent templates and `gen_agents.py`:** base and per-agent templates, `prompts/*.md`, `scripts/gen_agents.py` (`--check`), `src/ideaforge/agents.py`. Tests: `tests/test_gen_agents.py`.
- **IF-106 Hooks:** `.claude/settings.json`; `usage.py` (JSONL + DB usage, per-agent counters, `BUDGET_EXCEEDED_<agent>`, seen-URL log); `validate_file.py` (`--kind`, inference, research contract, `--auto` block-once-then-record); `guard.py` (note 5). Tests: `tests/test_guard.py`, `test_validate_file.py`, `test_usage.py`.
- **IF-107 `new_run.py` and run basics:** run dir, `idea.md`, `meta.json`, db rows for every stage, active marker, `--preset`, `--from`, `--as-of`; `runs.py` (`STAGES`, run ids, active marker). Tests: `tests/test_new_run.py`.

---

## Phase 1→2: Decisions and fixtures

### IF-150 Resolve open decisions

- **Mode:** human (only the user can answer). **Depends on:** F-001.
- **Goal:** get the user's answers to the four §13 questions and write them into config.
- **Scope:**
  1. Geography ladder (`config/finland.yaml: geography_ladder`; the `IdeaSpec.geography` default).
  2. Founder constraints in `config/founder.yaml` (hours/week, capital, skills, goal), then set `confirmed: true`.
  3. Verdict thresholds (3.5 / 2.5) and dimension weights in `config/rubric.yaml`.
  4. Report language: English, Finnish or both. Recommended: business-plan draft in Finnish.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_config.py` (extended: `founder.yaml` is confirmed and the report language is set) · `manual:` the user answered the four questions.
- **Acceptance:** `founder.yaml` has `confirmed: true`; the answers are recorded below this ticket.

### IF-200 Record Finnish open-data API fixtures

- **Mode:** human (needs the network). **Depends on:** F-001. New ticket (D-006).
- **Goal:** real recorded responses of the free APIs, so the `fi` clients (IF-201, IF-202) and API re-query (IF-209) can be built and tested offline by unattended sessions.
- **Scope:**
  - `scripts/record_fixtures.py`: plain `requests` with `truststore.inject_into_ssl()`, a UA string and a 10 s timeout. It prints each request URL and saves `tests/fixtures/api/<source>/<name>.json` next to `<name>.meta.json` (`url`, `method`, request body, `status`, `retrieved_at`).
  - Recordings (§8):
    - PxWeb StatFin: a table listing, one table's metadata, a Rääkkylä population query, and metadata of a table large enough to exceed 100 000 cells unfiltered
    - Luke: one table's metadata and a query
    - PRH YTJ v3 `companies`: an industry + municipality search (e.g. TOL 55201, Rääkkylä) and a name search
    - Eurostat: one JSON-stat dataset filtered to `geo=FI`
  - Keep the total under 1 MB; trim long listings and say so in the meta file.
  - `tests/test_api_fixtures.py`: every fixture parses, has its meta file, and its `url` is on an allow-listed domain from `config/domains.yaml`.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_api_fixtures.py` · `manual:` fixtures recorded from the live APIs and reviewed.
- **Acceptance:** the fixture set above exists, with dates; no personal data beyond public company registry fields.

---

## Phase 2: Research pipeline (MVP)

### IF-201 PxWeb client

- **Mode:** unattended. **Depends on:** F-003.
- **Goal:** free statistics tool for research agents (§8).
- **Scope:** `src/ideaforge/fi/pxweb.py`:
  - `list_tables(path)`, `metadata(table)`, `query(table, filters) -> DataFrame`
  - CLI `search "<keyword>"` / `get <table_path> --filter Alue=…` with a `--json` flag
  - base-URL wrapper so the newer API can be swapped in
  - refuses queries over the 100 000-cell limit with a helpful message
  - 24 h cache in `cache/`, `truststore` for TLS
  - prints the exact request URL
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_pxweb.py` (search, `get` CSV plus URL, cell-limit refusal and cache hit, all on IF-200 fixtures through a fake transport).
- **Acceptance:** `get` for the recorded Rääkkylä population table returns CSV plus the URL; no test touches the network.

### IF-202 PRH and Eurostat clients

- **Mode:** unattended. **Depends on:** F-003. **Absorbs:** IF-203.
- **Scope:**
  - `src/ideaforge/fi/prh.py`, YTJ v3 `companies` endpoint:
    - search by `--name`, `--industry <TOL>`, `--municipality`, registration date
    - returns count + rows (name, business id, registration date, status)
    - docstring notes: no sole traders, no contact details
  - `src/ideaforge/fi/eurostat.py`: JSON-stat `get(dataset, filters)` → DataFrame, CLI `get <dataset> --geo FI`.
  - Both: cache, URL printing, `--json`, `truststore`.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_prh.py tests/test_eurostat.py` (parsers on IF-200 fixtures).
- **Acceptance:** `search --industry 55201 --municipality Rääkkylä` prints a count and the request URL on the recorded response; JSON-stat → DataFrame matches the recorded values.

### IF-205 Full research validator

- **Mode:** unattended. **Depends on:** F-001.
- **Scope:** extend `validate_file.validate_research`:
  - **bare numbers:** a sentence with a digit-bearing figure must be followed by a `>` quote block, with exemptions for years, dates and claim ids
  - **every factual sentence has `[src: …]`:** a heuristic, reported as warnings until it is tuned
  - **URL provenance:** every cited URL and claim `source_url` must appear in `.seen_urls.txt` for that agent or be an `ideaforge.fi` API URL
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_validate_file.py` (table-driven cases per rule).
- **Acceptance:** each rule has passing and failing cases; the existing research fixture still validates. The "no false rejections on real files" check is part of IF-216.

### IF-208 Claim verification: fetch, cache, quote match

- **Mode:** unattended. **Depends on:** F-001.
- **Scope:** `scripts/verify_claims.py` + `src/ideaforge/verify.py`:
  - **parse:** candidate-claim blocks → `03_claims/<dim>.json`; fill `retrieved_at`
  - **fetch:** `requests` with a 10 s timeout and a UA string; `urllib.robotparser` (disallowed → `unverified` + `robots_disallowed`); `trafilatura` text → `cache/<sha256(url)>.txt`; record in the `sources` table
  - **match:** `rapidfuzz.fuzz.partial_ratio ≥ 90` → `verified`, else `unverified`; JS-only/403 pages → `unverified` + `unfetchable`
  - **source typing:** allow-listed official domain → `official` (domain matching from `domains.yaml`, including path entries)
  - **write:** `03_claims/verified.json` + `db.upsert_claims`
  - the HTTP fetcher is injectable so tests use synthetic pages
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_verify.py` (threshold boundaries 89/90, whitespace and diacritic normalization, unfetchable page, robots-disallowed, cache hits; no network).
- **Acceptance:** as the verification; a run directory fixture goes from candidate claims to `verified.json` and DB rows.

### IF-209 API re-query verification and conflict detection

- **Mode:** unattended. **Depends on:** F-004, F-005, F-007. **Absorbs:** IF-210.
- **Scope:**
  - **API re-query (IF-209):** for `source_type: api` claims, parse the cited URL back into a `fi` client call, re-run it and compare: exact for counts, ±1 % for floats. Tests use the IF-200 fixtures.
  - **Conflicts (IF-210):** `verify.detect_conflicts`: same dimension + similar statement (FTS candidates, then `fuzz ≥ 80`) + values differing by > 25 % → both marked `conflict`, both kept. Preference order: official > api > industry > news > forum > vendor, then newest. The order is recorded for the synthesizer.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_verify.py` (a mismatched API value → `unverified`; conflict cases 24 % no conflict, 26 % conflict, non-numeric ignored).
- **Acceptance:** as the verification.

### IF-212 Usage report and basic status

- **Mode:** unattended. **Depends on:** F-001. **Absorbs:** IF-213.
- **Scope:**
  - `scripts/usage_report.py <run_id>` summarizes `usage.jsonl` per stage and per agent (tool calls, searches, fetches, approx tokens) and lists `BUDGET_EXCEEDED_*`. Stage attribution is by time window from the `stages` table.
  - `.claude/skills/status/SKILL.md` + `scripts/status.py`. With no args: recent runs and their stages. With a `run_id`: claims per dimension (verified / unverified / conflict), kill flags fired, failure/budget markers, usage summary.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_usage_report.py tests/test_status.py` (golden output on a fixture JSONL and a fixture DB built in the test).
- **Acceptance:** both outputs match their golden text. The live check on a real run is part of IF-216.

### IF-214 Stage state machine and resume

- **Mode:** unattended. **Depends on:** F-001. **Absorbs:** the Python side of IF-507.
- **Scope:** `runs.py`:
  - `next_stages(run_id)`
  - `begin(run_id, stage)` / `finish(...)`, wrapping `db.stage_set`
  - a stage is `done` only if its output file exists **and** validates; a `running` stage left behind by a crash is reset to `pending` on resume
  - `scripts/run_stage.py <run_id> <stage> --begin|--finish` so skills can call it
  - IF-507 (Python side): a test simulates a crash in the middle of stage 2 (some research files done, one half-written, stages `running`) and asserts that resume skips the completed dimensions and re-queues the half-written one
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_runs.py` (transitions, done-needs-valid-file, crash reset, mid-stage-2 resume).
- **Acceptance:** as the verification. The manual Claude Code crash test is documented in this ticket's notes and checked in IF-216.

### IF-206 Validate and research skills, stages 0–3

- **Mode:** unattended. **Depends on:** F-006, F-007, F-009, F-010. **Absorbs:** IF-207, IF-215.
- **Scope:**
  - `.claude/skills/validate/SKILL.md`:
    - **Stage 0:** `new_run.py`; the orchestrator writes `00_spec.json`, asking at most 5 clarifying `AskUserQuestion`s, only where the answer changes research direction; merges `config/founder.yaml` defaults.
    - **Stage 1:** writes `01_plan.json` from rubric + spec, adding 1–2 Finland/Rääkkylä questions per dimension and the killcause task; shows a plan summary; continues without blocking if the user said "just run it".
    - **Stage 2 (IF-207):**
      - launch all 11 `research-*` agents **in one message**; each brief has `run_id`, the spec path, its plan section, budget line, preferred domains and the output path
      - afterwards, check the `VALIDATION_FAILED_*` markers: re-launch a failed agent once with the error appended; a second failure → `stage_set(research:<dim>, insufficient_data)`
      - check and report the `BUDGET_EXCEEDED_*` markers
      - skip dimensions whose stage is already `done`
    - **Stage 3:** `verify_claims.py`, then `usage_report.py`.
    - Calls `validate_file` and `scripts/run_stage.py --begin/--finish` around every stage.
  - `.claude/skills/research/SKILL.md` (IF-215): stages 1–3 for an existing run id, resumable.
  - `tests/test_skills.py`, a static consistency test:
    - the validate skill names every research agent in `agents.AGENTS`
    - every `scripts/*.py` and `python -m ideaforge.*` command a skill cites exists
    - each stage is wrapped in `run_stage.py`
    - the marker checks and the usage report are present
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_skills.py`.
- **Acceptance:** the static test passes. The live run (sauna idea, re-run skips completed dimensions) is IF-216.

### IF-204 Research briefs tuned and claim-extractor agent

- **Mode:** human (prompt tuning needs live agent runs). **Depends on:** F-004, F-005, F-006, F-007. **Absorbs:** IF-211.
- **Goal:** turn the Phase 1 prompts into production briefs (§12) and add the optional extraction pass.
- **Scope:**
  - `prompts/*.md` and the per-agent `focus` blocks: concrete search strategies per dimension, which `fi` tool to use when, Finnish search terms (e.g. "toiminimi", "arvonlisävero vähäinen toiminta")
  - an `{% if as_of %}` back-test header hook for IF-503
  - **IF-211:** an agent template `claim-extractor.md.j2` (role `claim_extractor`), run only when a research file has `[src:]` sentences with no matching candidate claim. Its output goes through the same verification. Register it in `agents.py` (19 agents; update the tests).
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_gen_agents.py` (19 agents, briefs name their `fi` tool, the extractor is on its role) · `manual:` one research agent run live produces a file that passes `validate_file --kind research`, and the extractor pass adds a prose claim the parser missed.
- **Acceptance:** `gen_agents.py --check` is clean; the manual observations are recorded in the evidence.

### IF-216 Phase 2 acceptance run

- **Mode:** human. **Depends on:** F-002, F-008, F-011, F-012.
- **Steps:** run `/validate "sauna-and-lake cabin rentals for remote workers in Rääkkylä"` (stages 0–3), then re-run the run id once.
- **Verification:** `L1: pnpm check` · `manual:` the acceptance list below, observed on the real run.
- **Acceptance (§11, plus the live checks moved here from merged tickets):**
  - all 11 research files exist, or their dimension is marked `insufficient_data`
  - ≥ 60 % of claims verify
  - a spot-check of 10 claims finds no invented URLs
  - the usage report prints, and `/status <run_id>` shows the run
  - the re-run launches no agent for completed dimensions; a killed stage-2 session resumes (IF-507)
  - 3 sampled research files show no false rejections by the IF-205 rules
- Record the results under this ticket.

---

## Phase 3: Scoring and report

### IF-302 Scoring

- **Mode:** unattended. **Depends on:** F-001.
- **Scope:** `src/ideaforge/scoring.py`:
  - named evidence rules `min_sources(n, independent)`, `has_official_source()` and `has_numeric(field)`, driven by `rubric.yaml: evidence_rule`
  - caps: `final_score = min(proposed, 2)` + `cap_reason` + `insufficient_data`
  - kill triggers fired from verified claim flags, minus `spec.kill_trigger_overrides`
  - `weighted_total`; verdict: ≥ 3.5 GO, 2.5–3.5 PIVOT, < 2.5 NO_GO; ≥ 3 insufficient dimensions → INSUFFICIENT_DATA
  - thresholds read from the rubric
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_scoring.py --cov=ideaforge.scoring --cov-report=term-missing --cov-fail-under=90` (table-driven; coverage of `scoring.py` ≥ 90 %).
- **Acceptance:** as the verification.

### IF-303 Unit economics

- **Mode:** unattended. **Depends on:** F-001.
- **Scope:** `src/ideaforge/economics.py`:
  - maps numeric claims (by unit/field tags) to price, variable cost, CAC proxy, fixed costs and volume
  - computes contribution margin (EUR and %), break-even units/month, payback months, and a ±30 % price × volume sensitivity table
  - missing inputs are listed, never guessed
  - VAT handling is explicit
  - output: `UnitEconomics`
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_economics.py` (known inputs, including a negative margin that sets `negative_contribution_margin` evidence for IF-302).
- **Acceptance:** as the verification.

### IF-304 Synthesis and score run

- **Mode:** unattended. **Depends on:** F-014, F-015. **Absorbs:** IF-301.
- **Scope:**
  - **Synthesizer (IF-301):** `prompts/synthesizer.md` + `.claude/skills/synthesize/SKILL.md`:
    - the synthesizer gets **only** `00_spec.json`, the verified + conflict claims and the rubric
    - it writes `04_scores_proposed.json` and `04_risks.json`
    - every justification cites ≥ 1 claim id; a dimension with no verified claims gets 0 with "no verified evidence"
    - the hook validates both files
  - **`scripts/score_run.py <run_id>`:**
    - load the proposed scores, drop cited claim ids that don't exist or aren't verified
    - apply `scoring.py` + `economics.py`
    - write `04_scores.json` and the `scores` table
  - `tests/test_skills.py`: the synthesize skill passes only the allowed inputs.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_score_run.py tests/test_skills.py` (end to end on fixture files; a hand-crafted `permit_impossible` claim flips the verdict to NO_GO; unverified citations are dropped).
- **Acceptance:** as the verification. Running the synthesizer on the real run is IF-309.

### IF-305 Report rendering with Finland and Rääkkylä sections

- **Mode:** unattended. **Depends on:** F-009, F-016. **Absorbs:** IF-306.
- **Scope:** `scripts/render_report.py` + `src/ideaforge/report.py`, Jinja2 → `05_report.md`, with these sections:
  - Verdict & why
  - Score table
  - Kill triggers
  - Unit economics + sensitivity
  - Dimension sections (findings, cited claim ids, gaps)
  - **Finland funding fit (IF-306):** starttiraha / Leader (Jetina) / elinvoimakeskus / Finnvera eligibility, each backed by its official-source claim, or shown as "unverified – see gaps"
  - **Rääkkylä location notes (IF-306)**
  - Risk register
  - Sources (url, title, retrieved_at, verification)
  - Usage summary (from `usage_report.py`)

  Store a row in the `reports` table. Reports are immutable: refuse to overwrite.

- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_report.py` (snapshot on fixtures; a dimension with under 3 sources shows as capped at 2 with a label; a funding section without an official claim renders the gap and never a value from `finland.yaml`; overwrite is refused).
- **Acceptance:** as the verification.

### IF-307 Starttiraha business-plan draft

- **Mode:** unattended. **Depends on:** F-002 (report language), F-017.
- **Scope:** a liiketoimintasuunnitelma skeleton plus a kannattavuuslaskelma table from `economics.py`, in the language chosen in IF-150, as a section of the report (or a sibling file the report links).
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_report.py` (the draft renders in the configured language; every figure in the calculation traces to a claim id or is marked as an assumption).
- **Acceptance:** as the verification. Rendering on the real run is IF-309.

### IF-308 Versioning, meta.json and validate --from

- **Mode:** unattended. **Depends on:** F-010, F-017.
- **Scope:**
  - fill `meta.json` with the git commit of prompts/config, a models snapshot, the Claude Code version and timestamps
  - `/validate --from <run_id>` creates `<run_id>-v2` linked via `idea_versions.parent` (`new_run.py --from` already exists)
  - the old run stays immutable
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_versioning.py` (meta fields; a v2 run has its own directory and its parent link; the v1 report is unchanged).
- **Acceptance:** as the verification.

### IF-309 Phase 3 acceptance run

- **Mode:** human. **Depends on:** F-013, F-018, F-019.
- **Steps:** on the IF-216 run: `/synthesize`, `score_run.py`, `render_report.py`.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_scoring.py --cov=ideaforge.scoring --cov-fail-under=90` (§11: coverage of `scoring.py` ≥ 90 %) · `L1: uv run pytest tests/test_score_run.py` (§11: a `permit_impossible` claim flips the verdict to NO_GO) · `manual:` the acceptance list below, observed on the real run.
- **Acceptance (§11):**
  - the report renders on the real run, including the Finland sections and the starttiraha draft
  - a dimension with < 3 sources is capped at 2 and labelled
  - every figure in the starttiraha calculation traces to a claim id or is marked as an assumption

---

## Phase 4: Debate

### IF-402 Debate anonymization and rebuttal validation

- **Mode:** unattended. **Depends on:** F-001. **Absorbs:** IF-403.
- **Scope:**
  - **Anonymization (IF-402):** `src/ideaforge/debate.py anonymize <run_id> <round>`: role → P1…P5 with a seeded shuffle (seed stored in the `debates` table), mapping kept in `debate/.mapping.json` (never shown to personas or the judge), output `positions_anon.json`.
  - **`scripts/debate_validate.py <run_id> <round>` (IF-403):**
    - `agree`/`modify`, or any change to the persona's own proposal, needs `basis.new_claim_ids` that the role hasn't cited before, or a `basis.computation`
    - `disagree` needs `cited_claim_ids` or an `evidence_gap`
    - every claim id must exist and be verified
    - at most 1 mini-research request per round
    - rejections are written per role with a reason, so the persona can be re-prompted once; turns go into `debate_turns`
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_debate.py tests/test_debate_validate.py` (anonymization is deterministic given the seed and leaks no role names; a stance change without a new claim id is rejected; one with a new claim id is accepted).
- **Acceptance:** as the verification (§11).

### IF-405 Convergence, conformity flag, verdict and revised plan

- **Mode:** unattended. **Depends on:** F-017, F-021. **Absorbs:** IF-406.
- **Scope:**
  - **Convergence (IF-405):** `scripts/debate_converged.py` exits 0 when any of these holds:
    - (a) no new claim ids were introduced and no proposed change moved
    - (b) the judge's interim projected scores moved < `convergence_score_delta` on every dimension
    - (c) round == `max_rounds`
  - **Conformity:** `debate.conformity_flag()`: ≥ 4 of 5 personas `agree` on the same change while zero new claim ids entered → true
  - **Verdict and revised plan (IF-406):**
    - Python recomputes `conformity_flag` on `debate/verdict.json` and checks that every accepted change's claim ids exist
    - `render_report.py --debate` writes `debate/revised_plan.md`: a diff-style comparison against `05_report.md`, the assumption register, and the experiments sorted by `info_value / cost`
    - persist the `assumptions` and `experiments` tables
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_debate_converged.py tests/test_debate.py tests/test_revised_plan.py` (each exit condition; the conformity flag; a fixture verdict renders a revised plan with ≥ 5 experiments, each with cost, days and a success threshold).
- **Acceptance:** as the verification (§11: the conformity logic has a unit test).

### IF-407 Debate skill, prompts and mini-research

- **Mode:** unattended. **Depends on:** F-011, F-022. **Absorbs:** IF-401, IF-404.
- **Scope:**
  - **Prompts (IF-401):** finalize `prompts/debate_persona.md`, `debate_judge.md` and the lens blocks (§12): "Agreement is not a goal…"; the judge may not introduce facts and needs a claim id per accepted change. Build each persona's evidence-subset file from `agents.PERSONA_EVIDENCE`.
  - **Mini-research (IF-404):** the orchestrator runs each `MiniResearchRequest` as a research subagent (same contract, output `02_research/mini-<n>-<dim>.md`), runs it through `verify_claims.py`, and makes the new claim ids available next round. At most 3 per debate (`budget.yaml`), enforced in Python.
  - **`.claude/skills/debate/SKILL.md`:**
    - **round 0:** the 5 personas in one message
    - **anonymize**
    - **rounds 1..N:** rebuttals → validate → re-prompt rejected personas once → mini-research → convergence check
    - **judge**
    - **render**, then offer `/validate --from <run_id>`
    - resumable per round
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_gen_agents.py tests/test_debate.py tests/test_skills.py` (persona briefs reference only their evidence subset; a 4th mini-research request is refused; round-1 mini-research claims are usable in round 2; the debate skill wires every step).
- **Acceptance:** as the verification. The live 3-round debate is IF-408.

### IF-408 Phase 4 acceptance run

- **Mode:** human. **Depends on:** F-020, F-023.
- **Steps:** `/debate <run_id>` on the Phase 2 run.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_debate.py` (§11: the conformity flag has a unit test) · `manual:` the acceptance list below, observed on the real run.
- **Acceptance (§11):**
  - an unsupported stance change is rejected and re-prompted (see `debate_turns`)
  - a 3-round debate on the Phase 2 idea completes unattended
  - the output lists ≥ 5 experiments with cost, days and a success threshold

---

## Phase 5: Evaluation and hardening

### IF-502 Eval checker and eval skill

- **Mode:** unattended. **Depends on:** F-016.
- **Scope:**
  - a `GoldenIdea` schema for `tests/golden/*.yaml`: idea, expected verdict range, 2–3 must-find facts
  - `scripts/eval_check.py` checks three things for a finished run: the verdict is in range, the must-find facts are among the verified claims, and zero unverified claims are cited in the score sheet. It writes a summary table.
  - `.claude/skills/eval/SKILL.md` runs the golden ideas **sequentially** (`--limit N` for spot checks) and then `eval_check.py`
  - every committed golden file must validate (zero files is fine until IF-501)
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_eval_check.py tests/test_skills.py` (synthetic golden + run fixtures, labelled synthetic).
- **Acceptance:** as the verification.

### IF-501 Golden set and eval run

- **Mode:** human (the facts must be researched by a person). **Depends on:** F-024, F-025.
- **Scope:** 10 files in `tests/golden/`, each with an idea, an expected verdict range and 2–3 must-find facts with their source URLs. Include obviously bad ideas, one real existing Rääkkylä business and one idea with a Finnish regulatory trap. Extend the test so it requires exactly 10 valid files.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_eval_check.py` (10 golden files validate) · `manual:` `/eval` passes on ≥ 8 of 10 (§11).
- **Acceptance:** as the verification; record the summary table under this ticket.

### IF-503 Back-test as-of, preset wiring and usage-limit docs

- **Mode:** unattended. **Depends on:** F-007, F-011, F-025. **Absorbs:** IF-506, IF-508.
- **Scope:**
  - **Back-test (IF-503):** `new_run.py --as-of` (already stored in `meta.json`) → the research-prompt header that forbids later sources (the IF-204 hook), and `verify_claims.py` rejecting claims with `published_date > as_of` (flag `after_as_of`).
  - **Presets (IF-506):** `/validate --preset economy|standard|deep` → `new_run.py --preset` → budget lines in the agent briefs (the orchestrator passes them in the brief, since agent files are rendered from the default preset) and the usage hook's limits (already reads `meta.json`).
  - **README (IF-508):** document:
    - checking `/usage` before a batch
    - the presets
    - the downgrade order from `models.yaml`
    - the procedure: edit config → `gen_agents.py` → `/eval` on 3 golden ideas → `/status --diff`
    - Fable models: counted faster against the weekly limit, capped at 50 %; use them only via `/model` for the synthesizer/judge on important ideas
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_verify.py tests/test_usage.py tests/test_skills.py` (a claim after the as-of date → `unverified` + `after_as_of`; an economy run flags `BUDGET_EXCEEDED` at 7 searches; the validate skill passes the preset's budget lines).
- **Acceptance:** as the verification; the README section exists and matches `config/`.

### IF-504 Review scores and status diff

- **Mode:** unattended. **Depends on:** F-009, F-019. **Absorbs:** IF-505.
- **Scope:**
  - **Reviews (IF-504):** `/status <run_id> --review` asks the user to score each report section 1–5 and stores the scores in the `reviews` table. `/status --reviews` shows the trend across prompt and model versions (via `meta.json`).
  - **Diff (IF-505):** `/status --diff` compares two score sheets (versions of an idea, or the same idea under different models): per-dimension final score, verdict, kill triggers.
- **Verification:** `L1: pnpm check` · `L1: uv run pytest tests/test_status.py` (scores persist and show in the trend view; a v1/v2 fixture pair diffs correctly).
- **Acceptance:** as the verification.

---

## Phase 6: v2 (optional, not queued)

Add these to `feature_list.json` only when the user asks for them.

- **IF-601 Streamlit viewer:** read-only browser over SQLite: runs, claims (filter by verification), score sheets, debates.
- **IF-602 Local competitor index:** PRH data plus the yc-oss company list, with local embeddings (no paid API), as a `fi`-style CLI the competition and killcause agents can query.
- **IF-603 Experiment tracker → claims:** record experiment results. A result enters idea version n+1 as a top-confidence claim (`source_type: official`-equivalent "experiment").
- **IF-604 `claude -p` batch wrapper:** a script that runs `/validate` headless for a list of ideas overnight, sequentially, with the strict guard on (no `.ideaforge-dev`, no `HARNESS_LOOP`).
