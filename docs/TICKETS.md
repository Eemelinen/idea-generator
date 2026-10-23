# Ideaforge: feature tickets

This file breaks [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) (the plan) into feature tickets. Work through them in phase order: a phase's acceptance ticket (IF-x09/IF-x16/…) must pass before the next phase starts. `§` numbers refer to sections of the plan.

**Sizes:** S ≈ under 2 h · M ≈ half a day · L ≈ a day or more.
**Status:** `done` · `todo` · `blocked` (waiting on a dependency or a decision).

---

## Plan notes and deviations

These came out of reviewing the plan. Phase 1 already applies them; later tickets must follow them.

1. **Missing from the §1 layout:** `04_scores_proposed.json`, `04_risks.json`, `meta.json`, `config/founder.yaml` (§13), `tests/fixtures/` (§9) and the `reviews` table (§9, missing from §5). All have been added: schemas `ProposedScores`, `RiskRegister`, `RunMeta`; table `reviews`.
2. **`killcause` is a research task, not a rubric dimension.** `Dimension` = the 10 rubric ids + `killcause`. Killcause claims carry kill-trigger flags and feed the investor persona, but have no weight.
3. **Budget presets (§10) vs flat `budget.yaml` (§4.4).** `budget.yaml` now holds `default_preset` plus `presets: {economy, standard, deep}`, each with the §4.4 keys. `meta.json` records each run's preset.
4. **Active run.** `scripts/new_run.py` writes `runs/.active`. Hooks read `IDEAFORGE_RUN_ID` first, then the marker, and do nothing when neither exists.
5. **Development session (§7).** A gitignored `.ideaforge-dev` marker relaxes the guard for the **main session only**. Subagents (hook input has `agent_type`) are always strict: a research agent may write only its own `02_research/<dim>.md`, a debate agent only `debate/`. Writes outside the project root or into `.git/` are always denied. ⚠ The guard fails open when `uv` isn't on PATH, because the hook then exits with a non-blocking error code.
6. **Windows.** The shell guard also covers the `PowerShell` tool (denies `Invoke-WebRequest`, `iwr`, `irm`, …) and normalizes Git Bash paths (`/c/…`).
7. **Hook semantics.** SubagentStop exit 2 sends stderr back to the *subagent*, so it fixes its own file. The validator blocks once. On the second failure (`stop_hook_active`) it writes `runs/<id>/VALIDATION_FAILED_<agent>` and lets the agent stop; the orchestrator then marks the dimension `INSUFFICIENT_DATA`. PostToolUse has no token counts, so `approx_tokens = len(json(in+out)) / 4`.
8. **Mechanical "no invented URL" check.** The usage hook logs every URL seen in WebSearch/WebFetch results to `runs/<id>/.seen_urls.txt`. IF-205 uses it to reject citations that never appeared.
9. **TLS interception on the dev machine.** uv needed `system-certs = true` (in `pyproject.toml`). Python `requests` will hit the same issue: use `truststore.inject_into_ssl()` (dependency already added) in every HTTP client (IF-201–203, IF-208).
10. **New modules not in §1:** `config.py` (validated config loading), `agents.py` (agent registry: name → role/dimension/persona/evidence subset), `guard.py` (PreToolUse policy), `hookio.py` (hook I/O).
11. **Rebuttal schema.** `Response.cited_claim_ids` (existing ledger ids backing a `disagree`), `Rebuttal.round`, `Rebuttal.updated_change_basis` and `Rebuttal.mini_research` were added so the §6.7 rules can be checked mechanically. `IdeaSpec.kill_trigger_overrides` implements "unless the user has explicitly overridden in the spec" (§6 stage 5).

---

## Index

| ID | Title | Phase | Depends on | Size | Status |
|---|---|---|---|---|---|
| IF-101 | Toolchain and repo skeleton | 1 | – | S | done |
| IF-102 | CLAUDE.md and config files | 1 | IF-101 | M | done |
| IF-103 | Pydantic schemas | 1 | IF-101 | M | done |
| IF-104 | SQLite schema and helpers | 1 | IF-103 | M | done |
| IF-105 | Agent templates and `gen_agents.py` | 1 | IF-102 | M | done |
| IF-106 | Hooks: usage log, validator, guard | 1 | IF-103 | L | done |
| IF-107 | `new_run.py` and run basics | 1 | IF-104 | S | done |
| IF-150 | Resolve open decisions (§13) | 1→2 | – | S | todo |
| IF-201 | PxWeb client (StatFin + Luke) | 2 | IF-101 | M | todo |
| IF-202 | PRH open-data client | 2 | IF-101 | M | todo |
| IF-203 | Eurostat client | 2 | IF-101 | S | todo |
| IF-204 | Research prompts tuned per dimension | 2 | IF-201–203 | M | todo |
| IF-205 | Full research validator | 2 | IF-106 | M | todo |
| IF-206 | `/validate` stages 0–1 (intake, plan) | 2 | IF-150 | M | todo |
| IF-207 | Stage 2 parallel research orchestration | 2 | IF-204, IF-205, IF-206 | L | todo |
| IF-208 | `verify_claims.py`: fetch, cache, quote match | 2 | IF-104 | L | todo |
| IF-209 | API-claim re-query verification | 2 | IF-201–203, IF-208 | M | todo |
| IF-210 | Conflict detection | 2 | IF-208 | M | todo |
| IF-211 | Optional `claim_extractor` pass | 2 | IF-208 | S | todo |
| IF-212 | `usage_report.py` | 2 | IF-106 | S | todo |
| IF-213 | `/status` skill (basic) | 2 | IF-208, IF-212 | S | todo |
| IF-214 | Stage state machine and resume | 2 | IF-104 | M | todo |
| IF-215 | `/research` skill | 2 | IF-207, IF-208 | S | todo |
| IF-216 | Phase 2 acceptance run | 2 | IF-201–215 | M | todo |
| IF-301 | Synthesizer and `/synthesize` | 3 | IF-216 | M | todo |
| IF-302 | `scoring.py` | 3 | IF-103 | M | todo |
| IF-303 | `economics.py` | 3 | IF-103 | M | todo |
| IF-304 | `score_run.py` | 3 | IF-301–303 | M | todo |
| IF-305 | `render_report.py`: core report | 3 | IF-304 | M | todo |
| IF-306 | Finland funding fit and Rääkkylä sections | 3 | IF-305 | M | todo |
| IF-307 | Starttiraha business-plan draft | 3 | IF-305, IF-150 | M | todo |
| IF-308 | Versioning, `meta.json`, `/validate --from` | 3 | IF-214 | M | todo |
| IF-309 | Phase 3 acceptance | 3 | IF-301–308 | S | todo |
| IF-401 | Debate persona and judge prompts | 4 | IF-309 | M | todo |
| IF-402 | Anonymization (`debate.py anonymize`) | 4 | IF-103 | S | todo |
| IF-403 | `debate_validate.py` | 4 | IF-402 | M | todo |
| IF-404 | Mini-research requests | 4 | IF-207, IF-208 | M | todo |
| IF-405 | Convergence and conformity flag | 4 | IF-403 | M | todo |
| IF-406 | Judge verdict and revised plan | 4 | IF-405 | M | todo |
| IF-407 | `/debate` skill orchestration | 4 | IF-401–406 | L | todo |
| IF-408 | Phase 4 acceptance | 4 | IF-407 | S | todo |
| IF-501 | Golden set (10 ideas) | 5 | IF-309 | M | todo |
| IF-502 | `/eval` skill | 5 | IF-501 | M | todo |
| IF-503 | Back-test mode `--as-of` | 5 | IF-208 | M | todo |
| IF-504 | Human review scores | 5 | IF-213 | S | todo |
| IF-505 | `/status --diff` | 5 | IF-308 | S | todo |
| IF-506 | `--preset` wiring | 5 | IF-206 | S | todo |
| IF-507 | Crash-resume test | 5 | IF-214 | S | todo |
| IF-508 | README: usage limits and model downgrade | 5 | IF-502 | S | todo |
| IF-601 | Streamlit viewer | 6 | Phase 5 | L | todo |
| IF-602 | Local competitor index | 6 | IF-202 | L | todo |
| IF-603 | Experiment tracker → claims | 6 | IF-408 | M | todo |
| IF-604 | `claude -p` batch wrapper | 6 | Phase 5 | S | todo |

---

## Phase 1: Skeleton (done)

**Phase 1 acceptance (§11): met.** `uv run pytest` passes (108 tests, including schema tests). `gen_agents.py` produces 17 agent files, all `model: opus`. A `Write` outside the allowed paths gets exit 2 from the guard hook.

### IF-101 Toolchain and repo skeleton (done)
- **Scope:** `pyproject.toml` (uv, hatchling, Python 3.12 pinned in `.python-version`, deps from §2 + `truststore`), `.gitignore`, directory layout from §1, `runs/.gitkeep`.
- **Acceptance:** `uv sync` succeeds on a fresh clone.

### IF-102 CLAUDE.md and config files (done)
- **Scope:** `CLAUDE.md` (§3), `README.md`, `config/models.yaml`, `rubric.yaml` (10 dimensions with questions, evidence rules, kill triggers, verdict thresholds, killcause block), `domains.yaml`, `finland.yaml` (hints with `verify_at_runtime`), `budget.yaml` (presets), `founder.yaml` (placeholder, `confirmed: false`), `src/ideaforge/config.py` validators.
- **Acceptance:** `tests/test_config.py`: weights sum to 1, every role is opus, every Finland hint has `verify_at_runtime: true` and a `verify_url`.

### IF-103 Pydantic schemas (done)
- **Scope:** `src/ideaforge/schemas.py`: every §5 model plus `CandidateClaim`, `ProposedScores`, `RiskRegister`, `UnitEconomics`, `RunMeta`; `extra="forbid"` everywhere; claim-id/quote/URL validators; `SCHEMAS` registry.
- **Acceptance:** `tests/test_schemas.py`: every fixture in `tests/fixtures/` validates and extra fields are rejected.

### IF-104 SQLite schema and helpers (done)
- **Scope:** `src/ideaforge/db.py`: all §5 tables + `reviews`, WAL mode, FTS5 `claims_fts` with sync triggers, `init`, `create_run`, `upsert_claims`, `stage_set`, `stage_done`, `log_usage`.
- **Acceptance:** `tests/test_db.py`.

### IF-105 Agent templates and `gen_agents.py` (done)
- **Scope:** `agent_templates/_research_base.md.j2`, `_debate_base.md.j2` and 17 per-agent templates; `prompts/research_base.md`, `research_contract.md`, `killcause.md`, `debate_persona.md`, `debate_judge.md`; `scripts/gen_agents.py` (`--check` mode); `src/ideaforge/agents.py` registry.
- **Acceptance:** `tests/test_gen_agents.py`: 17 files, the model comes from config, the committed files are up to date.

### IF-106 Hooks: usage log, validator, guard (done)
- **Scope:** `.claude/settings.json`; `src/ideaforge/usage.py` (JSONL + DB usage, per-agent counters, `BUDGET_EXCEEDED_<agent>`, seen-URL log); `validate_file.py` (`--kind`, kind inference, research-contract check, `--auto` for SubagentStop/Stop with block-once-then-record); `guard.py` (write and shell policy, see note 5).
- **Acceptance:** `tests/test_guard.py`, `test_validate_file.py`, `test_usage.py`.

### IF-107 `new_run.py` and run basics (done)
- **Scope:** `scripts/new_run.py` (run dir, `idea.md`, `meta.json`, db rows for every stage, active marker, `--preset`, `--from`, `--as-of`); `src/ideaforge/runs.py` (`STAGES`, run ids, active marker).
- **Acceptance:** `tests/test_new_run.py`.

### IF-150 Resolve open decisions (§13) (todo, blocks IF-206 and IF-307)
- **Goal:** get the user's answers to the four §13 questions and write them into config.
- **Scope:**
  1. Geography ladder (`config/finland.yaml: geography_ladder`; the `IdeaSpec.geography` default).
  2. Founder constraints in `config/founder.yaml` (hours/week, capital, skills, goal), then set `confirmed: true`.
  3. Verdict thresholds (3.5 / 2.5) and dimension weights in `config/rubric.yaml`.
  4. Report language: English, Finnish or both. Recommended: business-plan draft in Finnish.
- **Acceptance:** `founder.yaml` has `confirmed: true`; the decisions are recorded in this file under the ticket; `uv run pytest` passes.

---

## Phase 2: Research pipeline (MVP)

### IF-201 PxWeb client (StatFin + Luke)
- **Goal:** free statistics tool for research agents (§8).
- **Scope:** `src/ideaforge/fi/pxweb.py`:
  - `list_tables(path)`, `metadata(table)`, `query(table, filters) -> DataFrame`
  - CLI `search "<keyword>"` / `get <table_path> --filter Alue=…` with a `--json` flag
  - base-URL wrapper so the newer API can be swapped in
  - refuses queries over the 100 000-cell limit with a helpful message
  - 24 h cache in `cache/`, `truststore` for TLS
  - prints the exact request URL
- **Acceptance:** `get` for a Rääkkylä population table returns CSV plus the URL; unit tests with recorded responses (no network in CI); the cell-limit refusal is tested.

### IF-202 PRH open-data client
- **Scope:** `src/ideaforge/fi/prh.py`, using the YTJ v3 `companies` endpoint:
  - search by `--name`, `--industry <TOL>`, `--municipality`, registration date
  - returns count + rows (name, business id, registration date, status)
  - docstring notes: no sole traders, no contact details
  - cache, URL printing, `--json`
- **Acceptance:** `search --industry 55201 --municipality Rääkkylä` prints a count and the request URL; parser tests against a recorded response.

### IF-203 Eurostat client
- **Scope:** `src/ideaforge/fi/eurostat.py`: JSON-stat `get(dataset, filters)`, CLI `get <dataset> --geo FI`, cache, URL printing.
- **Acceptance:** a JSON-stat → DataFrame test against a recorded response.

### IF-204 Research prompts tuned per dimension
- **Goal:** turn the Phase 1 prompts into production briefs (§12).
- **Scope:**
  - `prompts/*.md` and the per-agent `focus` blocks: concrete search strategies per dimension, which `fi` tool to use when, Finnish search terms (e.g. "toiminimi", "arvonlisävero vähäinen toiminta")
  - an `{% if as_of %}` back-test header hook for IF-503
- **Acceptance:** `gen_agents.py --check` is clean; a manual run of one research agent produces a file that passes `validate_file --kind research`.

### IF-205 Full research validator
- **Scope:** extend `validate_file.validate_research`:
  - **bare numbers:** a sentence with a digit-bearing figure must be followed by a `>` quote block, with exemptions for years, dates and claim ids
  - **every factual sentence has `[src: …]`:** a heuristic, reported as warnings until it is tuned
  - **URL provenance:** every cited URL and claim `source_url` must appear in `.seen_urls.txt` for that agent or be an `ideaforge.fi` API URL
- **Acceptance:** table-driven tests for each rule; the IF-216 run shows no false rejections on 3 sampled files.

### IF-206 `/validate` stages 0–1 (intake, plan)
- **Scope:** `.claude/skills/validate/SKILL.md`:
  - **Stage 0:** `new_run.py`; the orchestrator writes `00_spec.json`, asking at most 5 clarifying `AskUserQuestion`s, only where the answer changes research direction; merges `config/founder.yaml` defaults.
  - **Stage 1:** writes `01_plan.json` from rubric + spec, adding 1–2 Finland/Rääkkylä questions per dimension and the killcause task; shows a plan summary; continues without blocking if the user said "just run it".
  - Calls `validate_file` and `db.stage_set` after each stage.
- **Acceptance:** for the sauna idea, `00_spec.json` and `01_plan.json` validate and the stages read `done` in the DB.

### IF-207 Stage 2 parallel research orchestration
- **Scope:** in the `/validate` skill:
  - launch all 11 `research-*` agents **in one message**; each brief has `run_id`, the spec path, its plan section, budget line, preferred domains and the output path
  - after they return:
    - check the `VALIDATION_FAILED_*` markers; re-launch a failed agent once with the error appended; a second failure → `stage_set(research:<dim>, insufficient_data)`
    - check the `BUDGET_EXCEEDED_*` markers and report them
  - skip dimensions whose stage is already `done` (uses IF-214)
- **Acceptance:** all 11 files exist or are marked `insufficient_data`; re-running the run id launches no agent for completed dimensions.

### IF-208 `verify_claims.py`: fetch, cache, quote match
- **Scope:** `scripts/verify_claims.py` + `src/ideaforge/verify.py`:
  - **parse:** candidate-claim blocks → `03_claims/<dim>.json`; fill `retrieved_at`
  - **fetch:** `requests` with a 10 s timeout and a UA string; `urllib.robotparser` (disallowed → `unverified` + `robots_disallowed`); `trafilatura` text → `cache/<sha256(url)>.txt`; record in the `sources` table
  - **match:** `rapidfuzz.fuzz.partial_ratio ≥ 90` → `verified`, else `unverified`; JS-only/403 pages → `unverified` + `unfetchable`
  - **source typing:** allow-listed official domain → `official` (domain matching from `domains.yaml`, including path entries)
  - **write:** `03_claims/verified.json` + `db.upsert_claims`
- **Acceptance:** `tests/test_verify.py` covers threshold boundaries (89/90), whitespace and diacritic normalization, an unfetchable page, robots-disallowed and cache hits; no network in tests.

### IF-209 API-claim re-query verification
- **Scope:** for `source_type: api` claims, parse the cited URL back into a `fi` client call, re-run it and compare: exact for counts, ±1 % for floats.
- **Acceptance:** tests where a mismatched value → `unverified`.

### IF-210 Conflict detection
- **Scope:** `verify.detect_conflicts`: same dimension + similar statement (FTS candidates, then `fuzz ≥ 80`) + values differing by > 25 % → both marked `conflict`, both kept. Preference order: official > api > industry > news > forum > vendor, then newest. The order is recorded for the synthesizer.
- **Acceptance:** `tests/test_verify.py` conflict cases (24 % no conflict, 26 % conflict, non-numeric ignored).

### IF-211 Optional `claim_extractor` pass
- **Scope:** an agent template `claim-extractor.md.j2` (role `claim_extractor`), run only when a research file has `[src:]` sentences with no matching candidate claim. Its output goes through the same verification. Register it in `agents.py` (18 agents; update the tests).
- **Acceptance:** a research file with an unextracted prose claim gains that claim after the pass.

### IF-212 `usage_report.py`
- **Scope:** `scripts/usage_report.py <run_id>` summarizes `usage.jsonl` per stage and per agent (tool calls, searches, fetches, approx tokens) and lists `BUDGET_EXCEEDED_*`. Stage attribution is by time window from the `stages` table.
- **Acceptance:** golden-output test on a fixture JSONL.

### IF-213 `/status` skill (basic)
- **Scope:** `.claude/skills/status/SKILL.md` + `scripts/status.py`. With no args: recent runs and their stages. With a `run_id`: claims per dimension (verified / unverified / conflict), kill flags fired, failure/budget markers, usage summary.
- **Acceptance:** works on the IF-216 run.

### IF-214 Stage state machine and resume
- **Scope:** `runs.py`:
  - `next_stages(run_id)`
  - `begin(run_id, stage)` / `finish(...)`, wrapping `db.stage_set`
  - a stage is `done` only if its output file exists **and** validates; a `running` stage left behind by a crash is reset to `pending` on resume
  - `scripts/run_stage.py <run_id> <stage> --begin|--finish` so skills can call it
- **Acceptance:** unit tests for the transitions; feeds IF-507.

### IF-215 `/research` skill
- **Scope:** `.claude/skills/research/SKILL.md`: stages 1–3 for an existing run id (plan, parallel research, verify), resumable.
- **Acceptance:** `/research <run_id>` on a run with only stage 0 done completes stages 1–3.

### IF-216 Phase 2 acceptance run
- **Steps:** run `/validate "sauna-and-lake cabin rentals for remote workers in Rääkkylä"` (stages 0–3).
- **Acceptance (§11):**
  - all 11 research files exist
  - ≥ 60 % of claims verify
  - a spot-check of 10 claims finds no invented URLs
  - the usage report prints
- Record the results in this ticket.

---

## Phase 3: Scoring and report

### IF-301 Synthesizer and `/synthesize`
- **Scope:** `prompts/synthesizer.md` + `.claude/skills/synthesize/SKILL.md`:
  - the synthesizer gets **only** `00_spec.json`, the verified + conflict claims and the rubric
  - it writes `04_scores_proposed.json` and `04_risks.json`
  - every justification cites ≥ 1 claim id; a dimension with no verified claims gets 0 with "no verified evidence"
  - the hook validates both files
- **Acceptance:** both files validate on the IF-216 run.

### IF-302 `scoring.py`
- **Scope:**
  - named evidence rules `min_sources(n, independent)`, `has_official_source()` and `has_numeric(field)`, driven by `rubric.yaml: evidence_rule`
  - caps: `final_score = min(proposed, 2)` + `cap_reason` + `insufficient_data`
  - kill triggers fired from verified claim flags, minus `spec.kill_trigger_overrides`
  - `weighted_total`; verdict: ≥ 3.5 GO, 2.5–3.5 PIVOT, < 2.5 NO_GO; ≥ 3 insufficient dimensions → INSUFFICIENT_DATA
  - thresholds read from the rubric
- **Acceptance:** table-driven `tests/test_scoring.py`; **coverage of `scoring.py` ≥ 90 %**.

### IF-303 `economics.py`
- **Scope:**
  - maps numeric claims (by unit/field tags) to price, variable cost, CAC proxy, fixed costs and volume
  - computes contribution margin (EUR and %), break-even units/month, payback months, and a ±30 % price × volume sensitivity table
  - missing inputs are listed, never guessed
  - VAT handling is explicit
  - output: `UnitEconomics`
- **Acceptance:** `tests/test_economics.py` on known inputs, including a negative margin (which sets `negative_contribution_margin` evidence for IF-302).

### IF-304 `score_run.py`
- **Scope:** `scripts/score_run.py <run_id>`:
  - load the proposed scores, drop cited claim ids that don't exist or aren't verified
  - apply `scoring.py` + `economics.py`
  - write `04_scores.json` and the `scores` table
- **Acceptance:** an end-to-end test on fixture files; a hand-crafted `permit_impossible` claim flips the verdict to NO_GO.

### IF-305 `render_report.py`: core report
- **Scope:** Jinja2 → `05_report.md`, with these sections:
  - Verdict & why
  - Score table
  - Kill triggers
  - Unit economics + sensitivity
  - Dimension sections (findings, cited claim ids, gaps)
  - Risk register
  - Sources (url, title, retrieved_at, verification)
  - Usage summary

  Store a row in the `reports` table. Reports are immutable: refuse to overwrite.
- **Acceptance:** snapshot test on fixtures; a dimension with < 3 sources shows as capped at 2 with a label.

### IF-306 Finland funding fit and Rääkkylä sections
- **Scope:** report sections for starttiraha / Leader (Jetina) / elinvoimakeskus / Finnvera eligibility, each backed by its official-source claim, or shown as "unverified – see gaps". Plus Rääkkylä location notes.
- **Acceptance:** a section without an official claim renders the gap, never a value from `finland.yaml`.

### IF-307 Starttiraha business-plan draft
- **Scope:** a liiketoimintasuunnitelma skeleton plus a kannattavuuslaskelma table from `economics.py`, in the language chosen in IF-150.
- **Acceptance:** renders on the IF-216 run; every figure in the calculation traces to a claim id or is marked as an assumption.

### IF-308 Versioning, `meta.json`, `/validate --from`
- **Scope:**
  - fill `meta.json` with the git commit of prompts/config, a models snapshot, the Claude Code version and timestamps
  - `/validate --from <run_id>` creates `<run_id>-v2` linked via `idea_versions.parent` (`new_run.py --from` already exists)
  - the old run stays immutable
- **Acceptance:** a v2 run has its own directory and its parent link; the v1 report is unchanged.

### IF-309 Phase 3 acceptance
- **Acceptance (§11):**
  - the report renders
  - a dimension with < 3 sources is capped at 2 and labelled
  - a `permit_impossible` claim flips the verdict to NO_GO
  - `scoring.py` coverage ≥ 90 %

---

## Phase 4: Debate

### IF-401 Debate persona and judge prompts
- **Scope:** finalize `prompts/debate_persona.md`, `debate_judge.md` and the lens blocks (§12): "Agreement is not a goal…"; the judge may not introduce facts and needs a claim id per accepted change. Build each persona's evidence-subset file from `agents.PERSONA_EVIDENCE`.
- **Acceptance:** `gen_agents.py --check` is clean; persona briefs reference only their evidence subset.

### IF-402 Anonymization
- **Scope:** `src/ideaforge/debate.py anonymize <run_id> <round>`: role → P1…P5 with a seeded shuffle (seed stored in the `debates` table), mapping kept in `debate/.mapping.json` (never shown to personas or the judge), output `positions_anon.json`.
- **Acceptance:** deterministic given the seed; no role names leak into the anonymized output (tested).

### IF-403 `debate_validate.py`
- **Scope:** `scripts/debate_validate.py <run_id> <round>`:
  - `agree`/`modify`, or any change to the persona's own proposal, needs `basis.new_claim_ids` that the role hasn't cited before, or a `basis.computation`
  - `disagree` needs `cited_claim_ids` or an `evidence_gap`
  - every claim id must exist and be verified
  - at most 1 mini-research request per round
  - rejections are written per role with a reason, so the persona can be re-prompted once; turns go into `debate_turns`
- **Acceptance (§11):** `tests/test_debate_validate.py`: a stance change without a new claim id is rejected; one with a new claim id is accepted.

### IF-404 Mini-research requests
- **Scope:** the orchestrator runs each `MiniResearchRequest` as a research subagent (same contract, output `02_research/mini-<n>-<dim>.md`), runs it through `verify_claims.py`, and makes the new claim ids available next round. At most 3 per debate (`budget.yaml`).
- **Acceptance:** a request in round 1 yields verified claims usable in round 2; a 4th request is refused.

### IF-405 Convergence and conformity flag
- **Scope:**
  - `scripts/debate_converged.py` exits 0 when any of these holds:
    - (a) no new claim ids were introduced and no proposed change moved
    - (b) the judge's interim projected scores moved < `convergence_score_delta` on every dimension
    - (c) round == `max_rounds`
  - `debate.conformity_flag()`: ≥ 4 of 5 personas `agree` on the same change while zero new claim ids entered → true
- **Acceptance:** unit tests for each exit condition and for the conformity flag (§11).

### IF-406 Judge verdict and revised plan
- **Scope:**
  - the judge writes `debate/verdict.json`
  - Python recomputes `conformity_flag` and checks that every accepted change's claim ids exist
  - `render_report.py --debate` writes `debate/revised_plan.md`: a diff-style comparison against `05_report.md`, the assumption register, and the experiments sorted by `info_value / cost`
  - persist the `assumptions` and `experiments` tables
- **Acceptance:** the verdict validates; ≥ 5 experiments, each with cost, days and a success threshold.

### IF-407 `/debate` skill orchestration
- **Scope:** `.claude/skills/debate/SKILL.md`:
  - **round 0:** the 5 personas in one message
  - **anonymize**
  - **rounds 1..N:** rebuttals → validate → re-prompt rejected personas once → mini-research → convergence check
  - **judge**
  - **render**, then offer `/validate --from <run_id>`
  - resumable per round
- **Acceptance:** a full debate runs unattended on the IF-216 run.

### IF-408 Phase 4 acceptance
- **Acceptance (§11):**
  - an unsupported stance change is rejected and re-prompted
  - a 3-round debate on the Phase 2 idea completes
  - the `conformity_flag` logic has a unit test
  - the output lists ≥ 5 experiments with cost, days and a success threshold

---

## Phase 5: Evaluation and hardening

### IF-501 Golden set (10 ideas)
- **Scope:** `tests/golden/*.yaml`, each with an idea, an expected verdict range and 2–3 must-find facts. Include obviously bad ideas, one real existing Rääkkylä business and one idea with a Finnish regulatory trap. Add a schema for the YAML files.
- **Acceptance:** 10 files validate.

### IF-502 `/eval` skill
- **Scope:** `.claude/skills/eval/SKILL.md` + `scripts/eval_check.py`. Runs the golden ideas **sequentially** (`--limit N` for spot checks) and checks three things: the verdict is in range, the must-find facts are among the verified claims, and zero unverified claims are cited in the score sheet. Writes a summary table.
- **Acceptance (§11):** passes on ≥ 8 of 10.

### IF-503 Back-test mode `--as-of`
- **Scope:** `new_run.py --as-of` (already stored in `meta.json`) → a research-prompt header that forbids later sources, and `verify_claims.py` rejecting claims with `published_date > as_of` (flag `after_as_of`).
- **Acceptance:** a test where a claim after the as-of date → `unverified` + flag.

### IF-504 Human review scores
- **Scope:** `/status <run_id> --review` asks the user to score each report section 1–5 and stores the scores in the `reviews` table. `/status --reviews` shows the trend across prompt and model versions (via `meta.json`).
- **Acceptance:** scores persist and show up in the trend view.

### IF-505 `/status --diff`
- **Scope:** diff two score sheets (versions of an idea, or the same idea under different models): per-dimension final score, verdict, kill triggers.
- **Acceptance:** works on a v1/v2 pair from IF-308.

### IF-506 `--preset` wiring
- **Scope:** `/validate --preset economy|standard|deep` → `new_run.py --preset` → budget lines in the agent briefs (the orchestrator passes them in the brief, since agent files are rendered from the default preset) and the usage hook's limits (already reads `meta.json`).
- **Acceptance:** an economy run flags `BUDGET_EXCEEDED` at 7 searches.

### IF-507 Crash-resume test
- **Scope:** kill the process mid-stage 2, re-run the run id, and confirm completed dimensions are skipped and the half-written file is re-researched. Automate the Python side in a test; document the manual Claude Code step.
- **Acceptance (§11):** resume works.

### IF-508 README: usage limits and model downgrade
- **Scope:** document:
  - checking `/usage` before a batch
  - the presets
  - the downgrade order from `models.yaml`
  - the procedure: edit config → `gen_agents.py` → `/eval` on 3 golden ideas → `/status --diff`
  - Fable models: counted faster against the weekly limit, capped at 50 %; use them only via `/model` for the synthesizer/judge on important ideas
- **Acceptance:** README section reviewed.

---

## Phase 6: v2 (optional)

### IF-601 Streamlit viewer
Read-only browser over SQLite: runs, claims (filter by verification), score sheets, debates.

### IF-602 Local competitor index
PRH data plus the yc-oss company list, with local embeddings (no paid API), as a `fi`-style CLI the competition and killcause agents can query.

### IF-603 Experiment tracker → claims
Record experiment results. A result enters idea version n+1 as a top-confidence claim (`source_type: official`-equivalent "experiment").

### IF-604 `claude -p` batch wrapper
A script that runs `/validate` headless for a list of ideas overnight, sequentially, with the strict guard on (no `.ideaforge-dev`).
