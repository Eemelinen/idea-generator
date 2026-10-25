# Ideaforge — Implementation Plan

A local business-idea validator built as a **Claude Code project**: Claude Code skills, subagents and hooks for the AI work; Python + SQLite for everything deterministic. Runs entirely on a Claude Max subscription. No paid third-party services.

This document is written for Claude Code. It is the design; the work is broken into tickets in [docs/TICKETS.md](docs/TICKETS.md) and queued as features in `feature_list.json`, ordered by `depends_on`. Each phase still ends with acceptance criteria (§11), now carried by a phase-acceptance feature. That feature gates only the work that needs its real-run output, so pure-Python work is not held up by a human-only run (D-006 in [docs/DECISIONS.md](docs/DECISIONS.md)). The development session loop (one feature per session, evidence before `passing`) is in [AGENTS.md](AGENTS.md); see §14.

---

## 0. Goals and non-negotiables

**Goal.** The user types a business idea. The system (1) researches its feasibility online following standard start-a-business checklists, adapted to Finland and to Rääkkylä / North Karelia, and produces a scored, evidence-backed report; then (2) on request, runs a structured multi-agent debate that tries to improve the plan and outputs a revised plan plus assumptions and experiments.

**Non-negotiables**

1. **No paid services.** Only Claude Code's built-in `WebSearch` and `WebFetch`, free public APIs (Statistics Finland, Luke, PRH open data, Eurostat), Python standard library + pip packages, SQLite. No Tavily/Brave/Exa/Firecrawl/Langfuse/hosted anything.
2. **Model choice lives in one place.** `config/models.yaml`. Default everything to `opus` (Claude Opus 5.5). The user will downgrade individual roles to `sonnet`/`haiku` later if usage limits bite. Never hardcode a model name in an agent file or script; agent frontmatter `model:` fields are generated from the config (see §4.3).
3. **Every number has a source.** A claim without a URL, a retrieval timestamp and a verified quote does not count toward any score.
4. **Python decides, the model proposes.** Scores, caps, kill triggers, weighted totals and unit economics are computed in Python from structured data the model emits. The model never computes the final verdict.
5. **Resumable.** Every stage writes its output to disk/SQLite before the next stage starts. Re-running a run id skips completed stages.
6. **Validated outputs.** Every structured file the model writes is validated against a Pydantic schema by a hook. Invalid → the stage fails loudly and is re-prompted once.
7. **Anti-sycophancy debate.** Round 0 positions are written in isolated subagent contexts; a stance change is accepted only if it cites a new claim id or a computed number; the judge is author-blind; max 3 rounds.

---

## 1. Repository layout

```
ideaforge/
├── AGENTS.md                      # development operating manual (harness, §14)
├── CLAUDE.md                      # @AGENTS.md + Claude Code wiring + pipeline-session rules (see §3)
├── IMPLEMENTATION_PLAN.md         # this file
├── README.md
├── PROGRESS.md                    # harness session log (§14)
├── feature_list.json              # harness feature queue; changed only by pnpm harness:* (§14)
├── harness.config.json            # loop-driver caps, models, allowed tools (§14)
├── init.sh                        # standard startup path: tooling checks, installs, L1 baseline
├── package.json                   # Node dev tooling for the harness only (§2)
├── docs/
│   ├── TICKETS.md                 # tickets (the spec of each feature) + plan notes and deviations
│   ├── DECISIONS.md               # decision records
│   └── harness/                   # how the harness works, prompts, rubric, checklists
├── config/
│   ├── models.yaml                # role → model mapping (single source of truth)
│   ├── rubric.yaml                # dimensions, weights, evidence requirements, kill triggers
│   ├── finland.yaml               # thresholds, grants, URLs — with "verify_at_runtime: true" flags
│   ├── domains.yaml               # official-source allow-lists per dimension
│   ├── founder.yaml               # founder constraints applied to every idea (IF-150)
│   ├── report.yaml                # report and business-plan draft language (IF-150)
│   └── budget.yaml                # max searches/fetches per subagent, max rounds, etc.
├── .claude/
│   ├── settings.json              # hooks, permissions (pipeline + harness, §7)
│   ├── hooks/                     # harness hooks: session-start, guard, format, stop-guard (§14)
│   ├── skills/
│   │   ├── clock-in/ verify-feature/ clock-out/   # harness session loop (§14)
│   │   ├── validate/SKILL.md      # /validate <idea>   — full pipeline
│   │   ├── research/SKILL.md      # /research <run_id> — stages 1–3 only
│   │   ├── synthesize/SKILL.md    # /synthesize <run_id>
│   │   ├── debate/SKILL.md        # /debate <run_id>
│   │   ├── status/SKILL.md        # /status [run_id]
│   │   └── eval/SKILL.md          # /eval — run golden set
│   └── agents/                    # GENERATED from templates by scripts/gen_agents.py
│       ├── research-customer.md
│       ├── research-market.md
│       ├── research-competition.md
│       ├── research-pricing.md
│       ├── research-unit-economics.md
│       ├── research-gtm.md
│       ├── research-regulation.md
│       ├── research-financing.md
│       ├── research-location.md
│       ├── research-founder-risk.md
│       ├── research-killcause.md
│       ├── debate-founder.md
│       ├── debate-investor.md
│       ├── debate-customer.md
│       ├── debate-accountant.md
│       ├── debate-operator.md
│       ├── debate-judge.md
│       ├── claim-extractor.md     # stage 3 optional pass (IF-211); runs only when extract_claims.py lists files
│       └── synthesizer.md         # stage 5 (IF-304); reads only 04_synthesis_input.json
├── agent_templates/               # source templates for the above (edit these, not .claude/agents)
├── prompts/                       # long prompt bodies, versioned in git
├── src/ideaforge/
│   ├── __init__.py
│   ├── schemas.py                 # Pydantic models (IdeaSpec, ResearchPlan, Claim, Scores, Position, Rebuttal, Verdict…)
│   ├── db.py                      # SQLite schema + helpers, schema_version migrations, `backup` CLI
│   ├── runs.py                    # run lifecycle, stage state machine, resume, child run ids
│   ├── meta.py                    # meta.json: git/config commit, models snapshot, Claude Code version, timestamps
│   ├── verify.py                  # quote verification, conflict detection, source typing
│   ├── extract.py                 # stage 3 claim-extraction pass: uncovered [src:] sentences, request, output checks
│   ├── scoring.py                 # weighted score, caps, kill triggers, verdict
│   ├── economics.py               # unit economics calculator
│   ├── synthesis.py               # stage 5: synthesizer input, score run (score_run.py)
│   ├── report.py                  # Markdown report renderer (render_report.py)
│   ├── templates/report.md.j2     # Jinja2 template of 05_report.md
│   ├── debate.py                  # anonymization (P1…P5, seeded), rebuttal validation, evidence subsets, resume status
│   ├── mini_research.py           # debate mini-research tasks: open (≤ max per debate) and finish
│   ├── usage.py                   # JSONL log of tool calls; per-run tallies
│   ├── brief.py                   # run-specific brief lines: scope lines from the spec, preset budget line, back-test header
│   ├── status.py                  # /status text: recent runs, one run's claims, flags, markers, usage; score-sheet diff (also the UI's compare)
│   ├── review.py                  # /status --review / --reviews: report-section scores 1–5, trend by prompt/model version
│   ├── golden.py                  # eval golden set: load + validate, find each idea's run, the three checks
│   ├── validate_file.py           # CLI: validate a JSON file against a schema (used by hooks)
│   ├── jobs.py                    # job queue + headless worker (IF-604): enqueue/list/show/cancel/retry/worker, `claude -p`
│   ├── web/                       # local web UI (D-008): `python -m ideaforge.web`, 127.0.0.1 only
│   │   ├── __init__.py            # create_app(): FastAPI app, routes
│   │   ├── dashboard.py           # runs dashboard rows, lineages, runs/ ↔ DB mismatch (IF-601)
│   │   ├── run_detail.py          # run page tabs: stages, idea, claims, scores, economics, report, usage, files (IF-605)
│   │   ├── debate_view.py         # run page debate tab: next step, rounds, verdict, revised plan (IF-606)
│   │   ├── reviews.py             # review form entries, compare choices; trend and diff from review/status (IF-606)
│   │   ├── control.py             # new-idea/version forms, run actions by state, eval, log tail, server worker (IF-607)
│   │   ├── settings.py            # settings editor: config/*.yaml forms, validated round-trip saves, history, revert (IF-608)
│   │   ├── templates/             # Jinja2 page templates
│   │   └── static/                # CSS, the job log-tail poller (HTMX not vendored yet, plan notes 37 and 41)
│   └── fi/                        # free Finnish data tools
│       ├── http.py                # shared transport, 24 h cache and request printing
│       ├── pxweb.py               # Statistics Finland + Luke PxWeb client
│       ├── prh.py                 # PRH open data (YTJ) client
│       ├── eurostat.py            # Eurostat JSON-stat client
│       └── requery.py             # cited API URL → client call, re-run for claim verification
├── scripts/
│   ├── gen_agents.py              # render agent_templates/* with config/models.yaml → .claude/agents/
│   ├── new_run.py                 # create run dir + db row + meta.json, print run_id; --from = next version; --intake → intake.json
│   ├── run_stage.py               # stage state machine: --begin/--finish/--insufficient-data/--resume/--next
│   ├── research_brief.py          # print a research brief's scope, budget and back-test lines for <run_id> <dim>; --scope: scope lines only
│   ├── extract_claims.py          # stage 3: list the research sentences no candidate claim covers (request.json)
│   ├── verify_claims.py           # stage 3 verification over a run
│   ├── synthesis_input.py         # stage 5: the synthesizer's only input file
│   ├── score_run.py               # stage 5 scoring
│   ├── render_report.py           # stage 5: the immutable 05_report.md + its reports row
│   ├── debate_validate.py         # validate a round's rebuttals; reject unsupported stance changes
│   ├── debate_converged.py        # exit code 0 if converged
│   ├── usage_report.py
│   ├── status.py                  # /status [run_id] [--review] | --reviews | --diff <a> <b>
│   └── eval_check.py              # /eval: check the golden runs, print the summary table
├── runs/                          # one folder per run (gitignored)
│   └── <run_id>/
│       ├── idea.md
│       ├── intake.json                         # clarifications answered up front (new_run.py --intake, IF-604)
│       ├── meta.json                           # provenance (ideaforge.meta)
│       ├── 00_spec.json
│       ├── 01_plan.json
│       ├── 02_research/<dimension>.md          # subagent prose with inline citations
│       ├── 03_claims/<dimension>.json          # extracted claims
│       ├── 03_claims/verified.json
│       ├── 03_claims/conflicts.json            # conflict groups in preference order (IF-210)
│       ├── 03_claims/extracted/                # claim-extractor pass (IF-211): request.json + <stem>.json
│       ├── 04_synthesis_input.json             # spec + verified/conflict claims + conflicts + rubric
│       ├── 04_scores_proposed.json
│       ├── 04_risks.json
│       ├── 04_scores.json
│       ├── 05_report.md
│       ├── 02_research/mini-<n>-<dim>.md       # debate mini-research task n (same contract)
│       ├── debate/.mapping.json                # seed + role → P-id (never shown to agents)
│       ├── debate/evidence/<role>.json         # the persona's evidence subset + its own P-id
│       ├── debate/round0/<role>.json
│       ├── debate/round0/positions_anon.json
│       ├── debate/round1/<role>.json
│       ├── debate/round1/REJECTED_<role>       # debate_validate.py reasons, for the re-prompt
│       ├── debate/round1/.reprompted           # roles already sent back once this round
│       ├── debate/round1/interim_scores.json   # the judge's projection after the round
│       ├── debate/verdict.json
│       ├── debate/revised_plan.md
│       └── usage.jsonl
│   └── .jobs/                       # job logs <job_id>.log and the worker's worker.pid (IF-604)
├── cache/                         # fetched pages keyed by sha256(url) (gitignored)
├── tests/
│   ├── test_scoring.py
│   ├── test_verify.py
│   ├── test_economics.py
│   ├── test_debate.py
│   ├── test_debate_validate.py
│   ├── fixtures/api/              # recorded Finnish API responses (IF-200, the only source of API fixtures)
│   ├── unit/harness/              # Vitest tests of the harness scripts
│   ├── fixtures/eval/             # synthetic golden ideas for the eval_check.py tests
│   └── golden/                    # 10–20 test ideas with expected verdict ranges (schema GoldenIdea)
├── ideaforge.db                   # SQLite (gitignored)
├── backups/                       # `python -m ideaforge.db backup` copies (gitignored)
├── pyproject.toml                 # managed with uv
└── .gitignore
```

---

## 2. Stack

- Python 3.12, `uv` for env/deps.
- Deps: `pydantic>=2`, `pyyaml`, `requests`, `rapidfuzz` (quote matching), `trafilatura` (HTML → text for verification), `pandas` (PxWeb tables), `pytest`, `jinja2` (report + agent templates and the web UI pages). Web UI (Phase 6, D-008): `fastapi`, `uvicorn`, `python-multipart`, `markdown-it-py`, `ruamel.yaml`; dev group `httpx` for FastAPI's `TestClient`.
- SQLite with WAL mode; FTS5 virtual table over `claims.statement` and `claims.quote`. The schema is versioned: `db.init()` applies the ordered, idempotent migrations a database has not seen and records them in `schema_version` (IF-601).
- No web framework for v1. Output is Markdown in `runs/<id>/` plus a `/status` skill. Phase 6 adds a local web UI (FastAPI + Jinja2 + HTMX, `ideaforge.web`) that controls the pipeline through headless `claude -p` jobs and edits the settings (D-008, TICKETS.md IF-601, IF-604–IF-609).
- Development-only tooling (§14): Node ≥ 22 with pnpm 10 for the shared harness (`@eemelinen/harness`, §14), Prettier, and husky + lint-staged + commitlint for the commit gates. The pipeline never calls Node.

---

## 3. `CLAUDE.md` (write this first)

Since the harness (§14), `CLAUDE.md` starts with `@AGENTS.md` (the development manual) and a "Claude Code specifics" section, followed by a **Pipeline sessions** section that holds items 2–6 below. The non-negotiables (item 1) are constraints in `AGENTS.md`.

Contents, in this order:

1. One-paragraph description of the project and the non-negotiables from §0.
2. **How to run**: `uv sync`, `uv run python scripts/gen_agents.py`, then `/validate <idea text>`.
3. **Rules for the orchestrator (main session)**:
   - Never do research yourself in the main context. Delegate every dimension to its subagent. The main context stays small.
   - Never write claim files by hand; subagents write prose, `scripts/verify_claims.py` extracts and verifies.
   - After each stage, run the stage's validator script and read its exit code before continuing.
   - Report usage from `scripts/usage_report.py <run_id>` at the end of every stage.
   - If a subagent fails validation twice, mark that dimension `INSUFFICIENT_DATA` and continue; never fabricate.
4. **Where things are**: config, prompts, runs, scripts (one line each).
5. **Model policy**: "All roles default to `opus` per `config/models.yaml`. Do not change models in agent files; change the config and run `gen_agents.py`."
6. **Finland policy**: regulatory, tax and grant claims must cite an allow-listed official domain from `config/domains.yaml` (vero.fi, prh.fi, ytj.fi, suomi.fi, tyomarkkinatori.fi, finlex.fi, elinvoimakeskus.fi, finnvera.fi, businessfinland.fi, luotsipohjoiskarjala.fi, jetina.fi, maaseutu.fi, raakkyla.fi, stat.fi, luke.fi, ec.europa.eu/eurostat). Values in `config/finland.yaml` are _hints to verify_, not facts.

---

## 4. Configuration files

### 4.1 `config/models.yaml`

```yaml
# Single source of truth. Values: opus | sonnet | haiku (Claude Code aliases).
roles:
  orchestrator: opus # main session; the user sets this with /model
  research_subagent: opus
  killcause_scout: opus
  claim_extractor: opus # downgrade candidate #1 (haiku) when limits bite
  synthesizer: opus
  debate_persona: opus # downgrade candidate #2 (sonnet)
  debate_judge: opus
  harness_generator: opus # development harness only (§14); harness.config.json must match
  harness_evaluator: opus
notes: |
  Downgrade order if usage limits are hit: claim_extractor → debate_persona → research_subagent.
  Keep synthesizer and debate_judge on opus longest.
```

### 4.2 `config/rubric.yaml`

Ten dimensions. For each: `id`, `name`, `weight`, `research_questions` (3–6), `min_evidence_for_3` (plain-language rule), `evidence_rule` (machine rule, see below), `kill_triggers` (list of boolean checks the extractor can set), `preferred_domains`.

| id             | name                                    | weight |
| -------------- | --------------------------------------- | ------ |
| customer       | Customer & problem (JTBD)               | 0.15   |
| market         | Market size (bottom-up beachhead)       | 0.10   |
| competition    | Competition & substitutes               | 0.15   |
| pricing        | Pricing & willingness to pay            | 0.10   |
| unit_economics | Unit economics & costs                  | 0.15   |
| gtm            | Go-to-market & channels                 | 0.10   |
| regulation     | Regulation, permits, tax                | 0.10   |
| financing      | Financing & funding fit                 | 0.05   |
| location       | Location fit (Rääkkylä / North Karelia) | 0.05   |
| founder_risk   | Founder fit & risk register             | 0.05   |

Machine evidence rules (examples; implement as small named functions in `scoring.py`):

- `min_sources(n=3, independent=True)` — ≥ n verified claims from distinct domains.
- `has_official_source()` — ≥1 verified claim whose domain is in the allow-list.
- `has_numeric(field="price")`, `has_numeric(field="unit_count")`.

Kill triggers (set by extractor as flags on claims, enforced in Python): `free_good_enough_substitute`, `permit_impossible`, `negative_contribution_margin`, `beachhead_below_founder_income`, `no_evidence_anyone_pays`.

### 4.3 Agent generation

`agent_templates/*.md.j2` contain the frontmatter with `model: {{ roles.research_subagent }}` etc. `scripts/gen_agents.py` renders them into `.claude/agents/`. Commit the templates; gitignore nothing in `.claude/agents/` (keeping generated files committed makes the project work immediately after clone, but always regenerate after editing config).

### 4.4 `config/budget.yaml`

```yaml
research_subagent:
  max_web_searches: 8
  max_web_fetches: 8
  max_output_words: 1200
killcause_scout:
  max_web_searches: 10
debate:
  max_rounds: 3
  max_mini_research_tasks: 3
  convergence_score_delta: 0.25
```

Claude Code has no hard `max_uses` for built-in tools, so these are enforced two ways: stated as instructions in the subagent prompt, and counted by the PostToolUse hook, which writes a warning file when exceeded that the orchestrator checks.

---

## 5. Data model (`src/ideaforge/schemas.py` and `db.py`)

Pydantic models (all with `model_config = ConfigDict(extra="forbid")`):

- `IdeaSpec`: `idea_id`, `title`, `one_liner`, `customer`, `problem`, `solution`, `revenue_model`, `geography` (the target markets, nearest first; default: Rääkkylä → North Karelia → Finland → online/EU), `business_mode` (`online`|`local`|`hybrid`, default `local`), `base_location` {municipality, municipality_code?, region, region_code?, nearby[], official_domains[], leader_group? {name, domain}} (default Rääkkylä / North Karelia; D-009), `founder_constraints` {hours_per_week, capital_eur, skills[], goal: side_income|full_time|starttiraha}, `clarifications[]` (Q/A pairs), `kill_trigger_overrides[]`, `vat_registered` (default true; economics.py), `version`.
- `ResearchPlan`: per dimension: `questions[]`, `search_strategy`, `preferred_domains[]`, `evidence_needed`.
- `Claim`: `claim_id` (e.g. `competition-007`), `dimension`, `statement`, `value: float|None`, `unit`, `source_url`, `source_title`, `quote` (≤ 60 words), `published_date|None`, `retrieved_at`, `source_type` (official|industry|news|forum|vendor|api), `confidence` (0–1), `flags[]` (kill-trigger names), `verification` (pending|verified|unverified|conflict).
- `DimensionScore`: `dimension`, `proposed_score` (0–5, model), `justification`, `supporting_claim_ids[]`, `final_score` (Python), `cap_reason|None`, `status` (scored|insufficient_data).
- `ScoreSheet`: `scores[]`, `weighted_total`, `kill_triggers_fired[]`, `verdict` (GO|PIVOT|NO_GO|INSUFFICIENT_DATA), `unit_economics` (output of `economics.py`).
- `Position` (debate round 0): `role`, `objections[]` {text, claim_ids[]}, `proposed_change`, `expected_score_impact` {dimension: delta}, `confidence`.
- `Rebuttal` (rounds ≥1): `role`, `responses[]` {target_position_id, stance: agree|disagree|modify, basis: {new_claim_ids[] | computation | evidence_gap}}, `updated_change|None`.
- `MiniResearchRequest`: `question`, `dimension`, `requested_by`.
- `Verdict`: `accepted_changes[]`, `rejected_changes[]` (with reasons), `assumption_register[]` {assumption, evidence_state, risk_if_wrong}, `experiments[]` {name, cost_eur, days, success_threshold, info_value: 1–5}, `projected_scores`, `conformity_flag: bool`.

SQLite tables mirror these: `runs`, `idea_versions`, `stages` (run_id, stage, status, started_at, finished_at, attempts), `claims`, `sources` (url, domain, content_sha, cache_path, fetched_at), `scores`, `reports`, `debates`, `debate_turns`, `assumptions`, `experiments`, `usage` (ts, run_id, stage, agent, tool, model, approx_tokens). Phase 6 migrations add `jobs` (IF-604) and `settings_history` (ts, file, sha_before, sha_after, content_before, content_after; every settings save from the UI, IF-608).

`db.py` exposes `init()`, `upsert_claims(run_id, claims)`, `stage_set(run_id, stage, status)`, `stage_done(run_id, stage) -> bool`.

---

## 6. Pipeline stages and the skills that drive them

### Stage 0 — Intake (`/validate`, main session)

1. `uv run python scripts/new_run.py "<idea text>"` → prints `run_id`, writes `runs/<run_id>/idea.md`.
2. Orchestrator produces `00_spec.json` (IdeaSpec). It must ask the user **up to 5 clarifying questions** via `AskUserQuestion` only where the answer changes research direction (scope: business mode, base location and target markets; goal, capital, time). The scope defaults to `config/founder.yaml`'s. Store Q/A in `clarifications`.
   A run created with `new_run.py --intake '<json>'` (a headless job, IF-604) has `runs/<run_id>/intake.json` (schema `Intake`: goal, capital, hours, skills, geography, business mode, base location, free-text answers, kill-trigger overrides) instead: the orchestrator builds the spec from it, asks nothing and treats the run as "just run it" (no plan approval either), so `claude -p` never needs `AskUserQuestion`.
3. Hook validates `00_spec.json` against `IdeaSpec`.

### Stage 1 — Research plan (main session)

1. Read `config/rubric.yaml` and `00_spec.json`; write `01_plan.json` (ResearchPlan). For each dimension adapt the generic questions to this idea and add 1–2 Finland/Rääkkylä-specific questions.
2. Always include the **kill-cause** task: dead competitors, free substitutes, regulatory blockers, "why hasn't this been done here".
3. Show the plan summary to the user; proceed unless they object (don't block on approval if the user said "just run it").

### Stage 2 — Parallel research (subagents)

- Orchestrator launches all 11 research subagents **in one message** (parallel). Each subagent brief contains: the IdeaSpec, its dimension's section of the plan, the run's scope lines (business mode, base location, target markets; the prompts name no place and mark their steps "Local or hybrid:" / "Online or hybrid:", IF-702), its budget line, the preferred-domain list, and the output contract.
- Subagent tools: `WebSearch`, `WebFetch`, `Bash(uv run python -m ideaforge.fi.*)`, `Read`, `Write` (only to its own `runs/<run_id>/02_research/<dimension>.md`).
- **Output contract** (in every research agent prompt):
  - Markdown, ≤ `max_output_words`.
  - Every factual sentence ends with `[src: <url>]`. Every number appears with a **verbatim quote ≤ 60 words** from the page in a `> quote` block immediately after it.
  - A final section `## Candidate claims` listing each claim in a fenced JSON block that already matches the `Claim` schema minus `verification` and `retrieved_at` (the script fills those). This makes extraction mostly mechanical.
  - A section `## Gaps` listing what could not be found.
  - Never invent a URL. Only cite URLs that appeared in a search result or were fetched.
- Finland data tools exposed to subagents (free):
  - `python -m ideaforge.fi.pxweb search "<keyword>"` → candidate StatFin/Luke tables; `... get <table_path> --filter Alue=Rääkkylä,Pohjois-Karjala` → CSV. Output includes the `cite:` URL (the table URL with the selection in its query string) to cite as `source_type: api`.
  - `python -m ideaforge.fi.prh search --name "<text>" | --industry <TOL 2025 code or prefix> --municipality Rääkkylä` → companies in that industry/area (count, names, registration dates, status). Use for competition density and "has this been tried here".
  - `python -m ideaforge.fi.eurostat get <dataset> --geo FI`.
- `SubagentStop` hook: runs `validate_file.py --kind research runs/<run_id>/02_research/<dimension>.md` (checks the JSON block parses as `list[Claim]`, word limit, no bare numbers without a quote, every cited URL in the agent's `.seen_urls.txt` or an `ideaforge.fi` API URL; sentences without `[src: …]` are warnings). On failure the orchestrator re-launches that subagent once with the validator's error message appended; second failure → `INSUFFICIENT_DATA` for that dimension.

### Stage 3 — Claim extraction and verification (Python + one subagent pass)

1. `scripts/verify_claims.py <run_id>`:
   - Parse the candidate-claims blocks → `03_claims/<dimension>.json`.
   - For each claim: fetch `source_url` with `requests` (10 s timeout, UA string, respect robots.txt via `urllib.robotparser`), extract text with `trafilatura`, cache to `cache/<sha>.txt`. Fuzzy-match the quote (`rapidfuzz.fuzz.partial_ratio ≥ 90`). Set `verified` / `unverified`. If the page can't be fetched (JS-only, 403), set `unverified` and `flags += ["unfetchable"]`.
   - For `source_type: api` claims citing a `fi` tool URL, re-run the query (`ideaforge.fi.requery`) and compare the value (exact for counts, ±1% for floats); a mismatch → `unverified` + `api_mismatch`.
   - Conflict detection: same `dimension` + similar `statement` (fuzz ≥ 80; pairwise, TICKETS.md plan note 33) with `value` differing by > 25% → both `conflict`; keep both; preference order official > api > industry > news > forum > vendor, then newest, recorded in `03_claims/conflicts.json` and passed to the synthesizer.
   - Write `03_claims/verified.json` and upsert into SQLite.
2. Optional model pass (`claim_extractor` role) only if a research file has prose claims that the mechanical parser missed; it emits additional `Claim` JSON which goes through the same verification. It runs **before** `verify_claims.py`: `scripts/extract_claims.py <run_id>` lists the `[src: …]` sentences no candidate claim covers in `03_claims/extracted/request.json`, the `claim-extractor` agent writes `03_claims/extracted/<stem>.json`, and `verify_claims.py` verifies those claims with the parsed ones (TICKETS.md plan note 35).

### Stage 4 — Evidence store

Already written by stage 3. `/status <run_id>` prints: claims per dimension (verified / unverified / conflict), kill flags, usage so far.

### Stage 5 — Synthesis and scoring

1. The `synthesizer` subagent (role `synthesizer`; a generated agent, not the orchestrator, see TICKETS.md plan note 22) receives **only** `04_synthesis_input.json`, which `scripts/synthesis_input.py <run_id>` builds from `00_spec.json` + `verified.json` (verified and conflict claims; unverified and pending excluded) + the conflict groups in preference order (`conflicts.json`) + rubric. It writes `04_scores_proposed.json` (`list[DimensionScore]` with `proposed_score`, `justification`, `supporting_claim_ids`, plus `unit_economics_inputs`: economics role → claim ids) and `04_risks.json`. Rule in prompt: every justification must cite at least one `claim_id`; scores for dimensions with no verified claims must be proposed as 0 with justification "no verified evidence".
2. `scripts/score_run.py <run_id>`:
   - Validates that every cited `claim_id` exists and is verified; drops citations that aren't. A proposal with no verified citation left is set to 0 ("no verified evidence").
   - Applies evidence rules → caps (`final_score = min(proposed, 2)` + `cap_reason`, `status = insufficient_data`).
   - Fires kill triggers from claim flags; any fired trigger forces verdict `NO_GO` unless the user has explicitly overridden in the spec.
   - Computes `weighted_total` (0–5) and verdict: ≥3.5 GO, 2.5–3.5 PIVOT, <2.5 NO_GO; if ≥3 dimensions are `insufficient_data` → `INSUFFICIENT_DATA`.
   - Runs `economics.py` on numeric claims (price, COGS, CAC proxy, fixed costs, volume assumptions) → contribution margin, break-even units/month, payback months, and a sensitivity table (±30% on price and volume). Missing inputs are listed, not guessed. The inputs are the synthesizer's `unit_economics_inputs`; a negative margin fires `negative_contribution_margin` only when they were assigned and every assigned per-unit cost reads as per unit sold (otherwise economics.py's automatic pick or an odd unit is reported but cannot force NO_GO).
   - Writes `04_scores.json`.
3. `scripts/render_report.py <run_id>` (`ideaforge.report`, run by `/synthesize` as stage `report`) → `05_report.md` with sections: Verdict & one-paragraph why · Score table (cap labels) · Kill triggers · Unit economics + sensitivity · Dimension sections (findings, cited claim ids, gaps from the research file's `## Gaps`) · Finland funding fit (starttiraha / the spec's Leader group, left out when the base location names none / elinvoimakeskus / Finnvera eligibility notes, each with its verified official-source claim, or "unverified – see gaps"; never a `config/finland.yaml` value) · Location notes (the location claims plus the claims naming the spec's base municipality, region or a nearby town) · Risk register · Sources (url, title, retrieved_at, verification state) · Usage summary. It stores a `reports` row and refuses to overwrite an existing report. It ends with the starttiraha-format business plan draft (IF-307, `ideaforge.business_plan`): a liiketoimintasuunnitelma skeleton + a kannattavuuslaskelma from `economics.py`, in `config/report.yaml: business_plan_language`, every figure tracing to claim ids (`UnitEconomics.input_claims`) or marked as an assumption; its section 8 asks for premises (`local`), storage, fulfilment and the webshop platform (`online`) or both (`hybrid`). Rules: TICKETS.md plan notes 23, 34 and 46.
4. Orchestrator shows the verdict and offers `/debate <run_id>`.

### Stage 6 — Persistence/versioning

- Reports are immutable. Re-running creates `runs/<run_id>-v2/` linked via `idea_versions.parent` (`/validate --from <run_id>` → `new_run.py --from`; a later version of the same parent gets the next free `-vN`). The parent run's files and rows are never touched. `/status --diff <a> <b>` compares the score sheets of two versions (IF-504).
- Record in `runs/<id>/meta.json` (`ideaforge.meta`): git commit of prompts/config (the repository HEAD, the last commit touching `config/`, `prompts/`, `agent_templates/`, and an uncommitted-changes flag), `models.yaml` roles snapshot, Claude Code version, idea id and version, timestamps (`created_at`, `updated_at` per stage transition). Rules: TICKETS.md plan note 24.

### Stage 7 — Debate (`/debate <run_id>`)

**Roles** (one subagent file each; model from `debate_persona`, judge from `debate_judge`):

| role       | lens                                                      | evidence subset given                       |
| ---------- | --------------------------------------------------------- | ------------------------------------------- |
| founder    | improve, pivot, cheaper MVP                               | all verified claims                         |
| investor   | market size, competition, kill causes, returns            | market, competition, pricing, killcause     |
| customer   | JTBD, willingness to pay, switching cost                  | customer, pricing, competition              |
| accountant | tax, VAT, permits, starttiraha/Leader rules, cash flow    | regulation, financing, unit_economics       |
| operator   | costs, logistics from Rääkkylä, seasonality, founder time | unit_economics, gtm, location, founder_risk |
| judge      | author-blind scoring against the claim ledger             | all                                         |

**Protocol**

1. **Round 0 (independent).** `uv run python -m ideaforge.debate evidence <run_id>` writes each persona's evidence subset (`agents.PERSONA_EVIDENCE`: the verified claims of its dimensions, every verified mini-research claim and its own P-id) to `debate/evidence/<role>.json`. Launch the 5 personas in one message. Each gets: the report, its evidence file, the run's scope lines (`scripts/research_brief.py <run_id> --scope`, IF-702) and the `Position` schema (in its prompt). Writes `debate/round0/<role>.json`. Hook validates (schema; every claim id verified and in the persona's evidence file, as for rebuttals).
2. **Anonymize.** `uv run python -m ideaforge.debate anonymize <run_id> 0` → `debate/round0/positions_anon.json` (role names replaced with P1…P5, order shuffled with a seeded RNG; seed in the `debates` table, mapping in `debate/.mapping.json`; one mapping for the whole debate). Later rounds are anonymized the same way for the judge. Rules: TICKETS.md plan note 25.
3. **Rounds 1..N.** Each persona receives all anonymized positions and writes a `Rebuttal`. Rules enforced by `scripts/debate_validate.py`:
   - `stance: modify|agree` on another position, or any change to its own `proposed_change`, **must** carry `basis.new_claim_ids` (ids that were _not_ cited in any of that role's earlier turns) **or** `basis.computation` (a number derived from existing claims, shown); otherwise the response is rejected and the persona is re-prompted once with the rejection reason (`python -m ideaforge.debate reprompt <run_id> <N>` records who was sent back; a second rejection leaves the turn out of the round). `disagree` needs only a claim id or an explicit `evidence_gap`.
   - At most 1 `MiniResearchRequest` per round across the personas (the lowest P-id keeps it) and at most the preset's `max_mini_research_tasks` per debate, enforced in Python (`debate_validate.py` sends further requests back, `python -m ideaforge.mini_research open` refuses them). The orchestrator runs it as a research subagent (same contract as stage 2) writing `02_research/mini-<n>-<dim>.md`, `mini_research finish` validates it, `verify_claims.py <run_id> --only mini-<n>-<dim>` adds its verified claims to the ledger without touching the others, and `debate evidence` gives them to every persona for the next round. This is the only way new information enters the debate. After each round the judge writes its interim projection. Rules: TICKETS.md plan note 27.
4. **Convergence** (`scripts/debate_converged.py`, exit 0 = stop): stop after a round if (a) no new claim ids were introduced and no `proposed_change` changed, or (b) the judge's interim projected scores (`debate/round<N>/interim_scores.json`, `InterimScores`) moved < 0.25 on every dimension, or (c) round == `max_rounds`. Rules: TICKETS.md plan note 26.
5. **Conformity flag.** If stances converged (≥ 4 of 5 personas `agree` on the same change; the change's author counts as backing it) while zero new claim ids entered the debate → `conformity_flag = true`, shown prominently in the output.
6. **Judge.** Receives anonymized positions and rebuttals, the verified ledger, and the score sheet. Writes `debate/verdict.json` (`Verdict`). Must cite claim ids for every accepted change; may not introduce new facts. Then `render_report.py --debate` produces `debate/revised_plan.md` (diff-style vs `05_report.md`), the assumption register, and the experiments list ordered by `info_value / cost`.
7. Offer to re-submit the revised plan as `idea_version` n+1 (`/validate --from <run_id>`).

`/debate <run_id>` (`.claude/skills/debate/SKILL.md`) runs these steps and resumes per round: `python -m ideaforge.debate status <run_id>` names the next step from the debate's files and rows, and every step is idempotent.

---

## 7. Hooks (`.claude/settings.json`)

- **PostToolUse** (all tools): `uv run python -m ideaforge.usage log` — appends `{ts, run_id (from env/cwd marker), agent, tool, approx_tokens}` to `runs/<run_id>/usage.jsonl`. Also increments per-agent search/fetch counters; if a counter exceeds `budget.yaml`, writes `runs/<run_id>/BUDGET_EXCEEDED_<agent>` (the orchestrator checks for these files after each stage).
- **SubagentStop**: `uv run python -m ideaforge.validate_file --auto` — infers which file the subagent was supposed to write from its name and validates it. Non-zero exit returns the error text to the orchestrator.
- **Stop** (main session, after a stage): same validator for stage files.
- **PreToolUse on `Write`/`Edit`**: deny writes outside `runs/`, `cache/`, and the project source unless the user is in an explicit "development" session (simple path check). Research subagents must never modify prompts, config or scripts.
- **PreToolUse on `Bash`**: allow only `uv run …`, `python -m ideaforge…`, `git …`, `ls/cat`. Deny `curl|wget` (all fetching goes through WebFetch or the Python tools so it is logged and cached).

Permissions in `settings.json`: pre-approve `WebSearch`, `WebFetch`, `Read`, `Write` (scoped), the allowed `Bash` patterns, and the `Agent` tool so the pipeline runs unattended with `claude -p`.

The development harness (§14) adds its own hooks through its Claude Code plugin: `SessionStart` summary, a second PreToolUse guard, a PostToolUse Prettier hook and an opt-in Stop guard. Both guards run on every call and either can block. "Development session" means the `.ideaforge-dev` marker exists **or** `HARNESS_LOOP=1` is set by the loop driver (D-005); subagents are strict either way.

---

## 8. Finnish data tools (`src/ideaforge/fi/`)

All free, no keys. Thin wrappers with on-disk caching (24 h) and a `--json` flag.

- `pxweb.py`: base URLs for StatFin (`https://pxdata.stat.fi/PXWeb/api/v1/{lang}/StatFin/`) and Luke (`https://statdb.luke.fi/PXWeb/api/v1/{lang}/LUKE/`). Functions: `list_tables(path)`, `metadata(table)`, `query(table, filters) -> DataFrame`. Handle the 100 000-cell limit by refusing with a helpful message. Wrap the base URL so the newer API can be swapped in. CLI: `search`, `meta` (variables and value codes) and `get` (CSV on stdout, the request on stderr); details in TICKETS.md plan note 31.
- `prh.py`: `https://avoindata.prh.fi/opendata-ytj-api/v3/companies` — search by name, TOL industry code, municipality, registration date; return count + rows. Note in docstring: no sole traders, no contact details. CLI `search` (the count and CSV rows on stdout, the request on stderr); industry codes are TOL 2025 since 2026-01-01, details in TICKETS.md plan note 32.
- `eurostat.py`: JSON-stat endpoint; `get(dataset, filters)`. CLI `get <dataset> --geo FI [--filter dim=code] [--since …]` (CSV on stdout, the request on stderr).
- `requery.py`: parses a cited URL of the three tools back into the client call and re-runs it for claim verification (IF-209); details in TICKETS.md plan note 33.
- `http.py`: the transport (`requests` + `truststore`), the 24 h cache under `cache/<tool>/` and the request lines every tool prints.
- Each tool prints the exact request URL so the subagent can cite it as `source_url` with `source_type: api`.

`config/finland.yaml` holds _hints_ (VAT small-activity threshold, starttiraha daily amount and max months, Leader group name and contact, employment-area contact, elinvoimakeskus grant URL, municipality facts) each with `verify_at_runtime: true` and `verify_url`. The regulation/financing subagents are instructed to confirm every hint against its `verify_url` before citing it.

---

## 9. Testing and evaluation

- **Unit tests** (`pytest`): scoring caps and kill triggers (table-driven); verification fuzzy-match thresholds; conflict detection; economics on known inputs; debate validator (rejects unsupported stance change, accepts one with a new claim id).
- **Schema tests**: every example JSON in `tests/fixtures/` validates.
- **Golden set** (`tests/golden/*.yaml`, 10 ideas for v1, 20 for v2): a short idea, expected verdict range, and 2–3 "must-find" facts (e.g. an existing local competitor, a known regulatory requirement). `/eval` runs the pipeline on each (sequentially, to respect usage limits), then checks: verdict within range, must-find facts present among verified claims, zero unverified claims cited in the score sheet. Include obviously bad ideas, one real existing Rääkkylä business, and one with a Finnish regulatory trap.
- **Back-test mode**: `--as-of YYYY-MM-DD` adds a header to every research prompt forbidding sources after that date and makes `verify_claims.py` reject claims with `published_date` after it. The header goes in the research brief (`scripts/research_brief.py`), since the agent files are rendered without a run; a claim with no `published_date` is not rejected (TICKETS.md plan note 29).
- **Human review**: `/status <run_id> --review` lets the user score each report section 1–5; stored in `reviews` table to track drift after prompt or model changes. `/status --reviews` shows the mean per section for each prompt/config and model version (from `meta.json`); `/status --diff <a> <b>` compares two score sheets (TICKETS.md plan note 30).
- **Harness verification layer (§14)**: L1 `pnpm check` runs the full pytest suite plus the harness checks, and is the gate for every feature. Tests are **offline**. Finnish API responses are recorded once from the live APIs by a human feature (IF-200, `tests/fixtures/api/`) and never invented. Anything that needs a real Claude run or the network (the golden-set `/eval`, phase acceptance runs) is a `manual:` step done interactively.

---

## 10. Usage-limit management (this replaces "cost control")

- `scripts/usage_report.py <run_id>` summarizes tool calls, searches, fetches and approximate tokens per stage and per agent. Print it at the end of every stage.
- Three presets in `config/budget.yaml`: `economy` (6 searches/agent, 2 debate rounds), `standard` (8, 3), `deep` (12, 3 + 3 mini-research). `/validate --preset economy`.
- Run heavy stages one idea at a time; `/eval` is sequential by design.
- Document in README: check `/usage` in Claude Code before a batch; Fable models count against the weekly limit faster and are capped at 50% of it, so use Fable only via `/model` for the synthesizer/judge on ideas that matter.
- When the user later wants to downgrade: edit `config/models.yaml`, run `gen_agents.py`, run `/eval` on 3 golden ideas, compare score sheets with `/status --diff`.

---

## 11. Phased build

The phases describe the shape of the build; the order of work is `depends_on` in `feature_list.json`. Each **Accept** line below is the verification of a phase-acceptance feature: Phase 2 → IF-216 (F-013), Phase 3 → IF-309 (F-020), Phase 4 → IF-408 (F-024), Phase 5 → IF-501 (F-026). Checks that can run offline are also unit-tested in the feature that builds the code.

### Phase 1 — Skeleton (target: one evening)

- Repo layout, `pyproject.toml`, `CLAUDE.md`, configs with placeholder content, `schemas.py`, `db.py`, `gen_agents.py`, hooks wired, `new_run.py`.
- **Accept:** `uv run pytest` passes schema tests; `gen_agents.py` produces 17 agent files with `model: opus`; a `Write` outside allowed paths is blocked by the hook.

### Phase 2 — Research pipeline (MVP)

- `/validate` skill through stages 0–2 with 11 subagents; `verify_claims.py`; `/status`.
- **Accept:** on the idea "sauna-and-lake cabin rentals for remote workers in Rääkkylä", all 11 research files exist, ≥ 60% of claims verify, no claim has an invented URL (spot-check 10), usage report prints.

### Phase 3 — Scoring and report

- Stage 5 synthesis, `score_run.py`, `economics.py`, `render_report.py`, Finland funding section, starttiraha-format business plan draft.
- **Accept:** report renders; a dimension with < 3 sources is capped at 2 and labeled; a hand-crafted claim with `permit_impossible` flips the verdict to NO_GO; unit test coverage of `scoring.py` ≥ 90%.

### Phase 4 — Debate

- Persona agents, anonymization, `debate_validate.py`, mini-research, convergence, judge, revised plan, assumption register, experiments.
- **Accept:** a rebuttal that changes stance without a new claim id is rejected and re-prompted; a 3-round debate on the Phase 2 idea completes; `conformity_flag` logic has a unit test; output lists ≥ 5 experiments with cost, days and success threshold.

### Phase 5 — Evaluation and hardening

- Golden set of 10, `/eval`, back-test mode, review scores, `/status --diff`, resume-from-crash test (kill the process mid-stage 2, re-run, confirm completed dimensions are skipped).
- **Accept:** `/eval` passes on ≥ 8/10; resume works; README documents usage-limit presets and model downgrade procedure.

### Phase 6 — Web UI

- Local web UI (D-008): runs dashboard and run detail over SQLite and `runs/`, debate, reviews and comparison views, a persistent job queue that runs the skills headless with `claude -p`, pipeline control and a settings editor with history.
- **Accept:** IF-609: a real idea runs validate → synthesize → debate from the UI alone, and the jobs, logs, settings history and results survive a restart and a restore from backup.
- Backlog (not queued): local competitor index (PRH + yc-oss company list with local embeddings); experiment tracker that feeds results back as top-confidence claims into version n+1.

---

## 12. Prompt-writing guidance for Claude Code (apply when writing `prompts/` and agent templates)

- Each subagent brief is self-contained: objective, the dimension's questions, output contract, budget, preferred domains, what _not_ to do (no invented URLs, no summarizing competitors from memory, no numbers without quotes).
- Research agents are told to look for **reasons the idea fails** (dead competitors, free substitutes, regulatory blockers, thin local demand) at least as hard as reasons it works.
- Debate personas are told explicitly: "Agreement is not a goal. Changing your position without new evidence is a failure."
- The judge prompt forbids introducing facts and requires a claim id per accepted change.
- Keep all prompts in `prompts/*.md` and reference them from templates with `{% include %}`; never inline long prompts in skills.

---

## 13. Open decisions for the user (ask before Phase 2)

1. Default geography ladder for market sizing: Rääkkylä → Keski-Karjala → North Karelia → Finland → online/EU. Confirm.
2. Founder constraints to store once in `config/founder.yaml` (hours/week, capital, skills, goal) so every idea is evaluated against them. Confirm values.
3. Verdict thresholds (3.5 / 2.5) and dimension weights — accept defaults or adjust.
4. Language of the final report: English, Finnish, or both (business-plan draft in Finnish for starttiraha use is recommended).

These are ticket IF-150 (feature F-002), a human-only feature.

---

## 14. Development harness

The remaining work is built with the shared agent harness (`Eemelinen/harness`: the `@eemelinen/harness` package and its Claude Code plugin; D-001–D-007). It is development tooling and never runs the pipeline.

- **State:** `feature_list.json` is the queue. There is one feature per ticket in `docs/TICKETS.md`, with `depends_on`, `verification[]` and `evidence[]`. Only `pnpm harness:feature` and `pnpm harness:verify` change it. `PROGRESS.md` is the session log; `docs/DECISIONS.md` holds the decisions.
- **Loop:**
  - `/harness:clock-in` reads the state, runs `./init.sh` and activates exactly one feature (WIP=1).
  - Implement the feature.
  - `/harness:verify-feature` runs the feature's steps in order and records dated evidence.
  - `/harness:clock-out` runs the clean-state check, updates `PROGRESS.md` and commits.
- **Verification:** one layer, L1 `pnpm check` (Prettier, `pnpm harness:check`, `uv run pytest`). Steps that need the network, a real Claude run or a decision by the user are `manual:` and keep the feature human-only.
- **Unattended:** `pnpm harness:loop` runs one fresh `claude -p` session per ready feature in its own git worktree, with `HARNESS_LOOP=1` and caps from `harness.config.json`. It re-checks the result, has a fresh-context evaluator grade it against `docs/harness/evaluator-rubric.md`, then opens a PR that CI (`L1 (pnpm check)`) must pass.
- **Sizing:** a feature fits one session. Tightly coupled tickets are merged, and the survivor lists what it absorbs.

Details: [docs/harness/README.md](docs/harness/README.md).
