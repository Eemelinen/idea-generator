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
│       └── evaluator.md             # harness reviewer (role harness_evaluator, §14)
├── agent_templates/               # source templates for the above (edit these, not .claude/agents)
├── prompts/                       # long prompt bodies, versioned in git
├── src/ideaforge/
│   ├── __init__.py
│   ├── schemas.py                 # Pydantic models (IdeaSpec, ResearchPlan, Claim, Scores, Position, Rebuttal, Verdict…)
│   ├── db.py                      # SQLite schema + helpers
│   ├── runs.py                    # run lifecycle, stage state machine, resume
│   ├── verify.py                  # quote verification, conflict detection, source typing
│   ├── scoring.py                 # weighted score, caps, kill triggers, verdict
│   ├── economics.py               # unit economics calculator
│   ├── report.py                  # Markdown report renderer
│   ├── debate.py                  # debate protocol validator + convergence check
│   ├── usage.py                   # JSONL log of tool calls; per-run tallies
│   ├── validate_file.py           # CLI: validate a JSON file against a schema (used by hooks)
│   └── fi/                        # free Finnish data tools
│       ├── pxweb.py               # Statistics Finland + Luke PxWeb client
│       ├── prh.py                 # PRH open data (YTJ) client
│       └── eurostat.py
├── scripts/
│   ├── gen_agents.py              # render agent_templates/* with config/models.yaml → .claude/agents/
│   ├── new_run.py                 # create run dir + db row, print run_id
│   ├── verify_claims.py           # stage 3 verification over a run
│   ├── score_run.py               # stage 5 scoring
│   ├── render_report.py
│   ├── debate_validate.py         # validate a round's rebuttals; reject unsupported stance changes
│   ├── debate_converged.py        # exit code 0 if converged
│   ├── usage_report.py
│   └── harness-*.ts, validate-feature-list.ts, verify-feature.ts, clean-state-check.sh   # harness (§14)
├── runs/                          # one folder per run (gitignored)
│   └── <run_id>/
│       ├── idea.md
│       ├── 00_spec.json
│       ├── 01_plan.json
│       ├── 02_research/<dimension>.md          # subagent prose with inline citations
│       ├── 03_claims/<dimension>.json          # extracted claims
│       ├── 03_claims/verified.json
│       ├── 04_scores.json
│       ├── 05_report.md
│       ├── debate/round0/<role>.json
│       ├── debate/round1/<role>.json
│       ├── debate/verdict.json
│       ├── debate/revised_plan.md
│       └── usage.jsonl
├── cache/                         # fetched pages keyed by sha256(url) (gitignored)
├── tests/
│   ├── test_scoring.py
│   ├── test_verify.py
│   ├── test_economics.py
│   ├── test_debate_validate.py
│   ├── fixtures/api/              # recorded Finnish API responses (IF-200, the only source of API fixtures)
│   ├── unit/harness/              # Vitest tests of the harness scripts
│   └── golden/                    # 10–20 test ideas with expected verdict ranges
├── ideaforge.db                   # SQLite (gitignored)
├── pyproject.toml                 # managed with uv
└── .gitignore
```

---

## 2. Stack

- Python 3.12, `uv` for env/deps.
- Deps: `pydantic>=2`, `pyyaml`, `requests`, `rapidfuzz` (quote matching), `trafilatura` (HTML → text for verification), `pandas` (PxWeb tables), `pytest`, `jinja2` (report + agent templates).
- SQLite with WAL mode; FTS5 virtual table over `claims.statement` and `claims.quote`.
- No web framework for v1. Output is Markdown in `runs/<id>/` plus a `/status` skill. A Streamlit viewer is an optional v2 item.
- Development-only tooling (§14): Node ≥ 22 with pnpm 10 for the harness scripts (TypeScript: zod, tsx, Vitest), Prettier, and husky + lint-staged + commitlint for the commit gates. The pipeline never calls Node.

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

- `IdeaSpec`: `idea_id`, `title`, `one_liner`, `customer`, `problem`, `solution`, `revenue_model`, `geography` (default: Rääkkylä → North Karelia → Finland → online), `founder_constraints` {hours_per_week, capital_eur, skills[], goal: side_income|full_time|starttiraha}, `clarifications[]` (Q/A pairs), `version`.
- `ResearchPlan`: per dimension: `questions[]`, `search_strategy`, `preferred_domains[]`, `evidence_needed`.
- `Claim`: `claim_id` (e.g. `competition-007`), `dimension`, `statement`, `value: float|None`, `unit`, `source_url`, `source_title`, `quote` (≤ 60 words), `published_date|None`, `retrieved_at`, `source_type` (official|industry|news|forum|vendor|api), `confidence` (0–1), `flags[]` (kill-trigger names), `verification` (pending|verified|unverified|conflict).
- `DimensionScore`: `dimension`, `proposed_score` (0–5, model), `justification`, `supporting_claim_ids[]`, `final_score` (Python), `cap_reason|None`, `status` (scored|insufficient_data).
- `ScoreSheet`: `scores[]`, `weighted_total`, `kill_triggers_fired[]`, `verdict` (GO|PIVOT|NO_GO|INSUFFICIENT_DATA), `unit_economics` (output of `economics.py`).
- `Position` (debate round 0): `role`, `objections[]` {text, claim_ids[]}, `proposed_change`, `expected_score_impact` {dimension: delta}, `confidence`.
- `Rebuttal` (rounds ≥1): `role`, `responses[]` {target_position_id, stance: agree|disagree|modify, basis: {new_claim_ids[] | computation | evidence_gap}}, `updated_change|None`.
- `MiniResearchRequest`: `question`, `dimension`, `requested_by`.
- `Verdict`: `accepted_changes[]`, `rejected_changes[]` (with reasons), `assumption_register[]` {assumption, evidence_state, risk_if_wrong}, `experiments[]` {name, cost_eur, days, success_threshold, info_value: 1–5}, `projected_scores`, `conformity_flag: bool`.

SQLite tables mirror these: `runs`, `idea_versions`, `stages` (run_id, stage, status, started_at, finished_at, attempts), `claims`, `sources` (url, domain, content_sha, cache_path, fetched_at), `scores`, `reports`, `debates`, `debate_turns`, `assumptions`, `experiments`, `usage` (ts, run_id, stage, agent, tool, model, approx_tokens).

`db.py` exposes `init()`, `upsert_claims(run_id, claims)`, `stage_set(run_id, stage, status)`, `stage_done(run_id, stage) -> bool`.

---

## 6. Pipeline stages and the skills that drive them

### Stage 0 — Intake (`/validate`, main session)

1. `uv run python scripts/new_run.py "<idea text>"` → prints `run_id`, writes `runs/<run_id>/idea.md`.
2. Orchestrator produces `00_spec.json` (IdeaSpec). It must ask the user **up to 5 clarifying questions** via `AskUserQuestion` only where the answer changes research direction (geography, goal, capital, time). Store Q/A in `clarifications`.
3. Hook validates `00_spec.json` against `IdeaSpec`.

### Stage 1 — Research plan (main session)

1. Read `config/rubric.yaml` and `00_spec.json`; write `01_plan.json` (ResearchPlan). For each dimension adapt the generic questions to this idea and add 1–2 Finland/Rääkkylä-specific questions.
2. Always include the **kill-cause** task: dead competitors, free substitutes, regulatory blockers, "why hasn't this been done here".
3. Show the plan summary to the user; proceed unless they object (don't block on approval if the user said "just run it").

### Stage 2 — Parallel research (subagents)

- Orchestrator launches all 11 research subagents **in one message** (parallel). Each subagent brief contains: the IdeaSpec, its dimension's section of the plan, its budget line, the preferred-domain list, and the output contract.
- Subagent tools: `WebSearch`, `WebFetch`, `Bash(uv run python -m ideaforge.fi.*)`, `Read`, `Write` (only to its own `runs/<run_id>/02_research/<dimension>.md`).
- **Output contract** (in every research agent prompt):
  - Markdown, ≤ `max_output_words`.
  - Every factual sentence ends with `[src: <url>]`. Every number appears with a **verbatim quote ≤ 60 words** from the page in a `> quote` block immediately after it.
  - A final section `## Candidate claims` listing each claim in a fenced JSON block that already matches the `Claim` schema minus `verification` and `retrieved_at` (the script fills those). This makes extraction mostly mechanical.
  - A section `## Gaps` listing what could not be found.
  - Never invent a URL. Only cite URLs that appeared in a search result or were fetched.
- Finland data tools exposed to subagents (free):
  - `python -m ideaforge.fi.pxweb search "<keyword>"` → candidate StatFin/Luke tables; `... get <table_path> --filter Alue=Rääkkylä,Pohjois-Karjala` → CSV. Output includes the API URL to cite as `source_type: api`.
  - `python -m ideaforge.fi.prh search --name "<text>" | --industry <TOL> --municipality Rääkkylä` → companies in that industry/area (count, names, registration dates, status). Use for competition density and "has this been tried here".
  - `python -m ideaforge.fi.eurostat get <dataset> --geo FI`.
- `SubagentStop` hook: runs `validate_file.py --kind research runs/<run_id>/02_research/<dimension>.md` (checks the JSON block parses as `list[Claim]`, word limit, no bare numbers without a quote). On failure the orchestrator re-launches that subagent once with the validator's error message appended; second failure → `INSUFFICIENT_DATA` for that dimension.

### Stage 3 — Claim extraction and verification (Python + one subagent pass)

1. `scripts/verify_claims.py <run_id>`:
   - Parse the candidate-claims blocks → `03_claims/<dimension>.json`.
   - For each claim: fetch `source_url` with `requests` (10 s timeout, UA string, respect robots.txt via `urllib.robotparser`), extract text with `trafilatura`, cache to `cache/<sha>.txt`. Fuzzy-match the quote (`rapidfuzz.fuzz.partial_ratio ≥ 90`). Set `verified` / `unverified`. If the page can't be fetched (JS-only, 403), set `unverified` and `flags += ["unfetchable"]`.
   - For `source_type: api` claims, re-run the query and compare the value (exact for counts, ±1% for floats).
   - Conflict detection: same `dimension` + similar `statement` (FTS + fuzz ≥ 80) with `value` differing by > 25% → both `conflict`; keep both; preference order official > api > industry > news > forum > vendor, then newest.
   - Write `03_claims/verified.json` and upsert into SQLite.
2. Optional model pass (`claim_extractor` role) only if a research file has prose claims that the mechanical parser missed; it emits additional `Claim` JSON which goes through the same verification.

### Stage 4 — Evidence store

Already written by stage 3. `/status <run_id>` prints: claims per dimension (verified / unverified / conflict), kill flags, usage so far.

### Stage 5 — Synthesis and scoring

1. Orchestrator (role `synthesizer`) receives **only** `00_spec.json` + `verified.json` (verified and conflict claims; unverified excluded) + rubric. It writes `04_scores_proposed.json` (`list[DimensionScore]` with `proposed_score`, `justification`, `supporting_claim_ids`) and `04_risks.json`. Rule in prompt: every justification must cite at least one `claim_id`; scores for dimensions with no verified claims must be proposed as 0 with justification "no verified evidence".
2. `scripts/score_run.py <run_id>`:
   - Validates that every cited `claim_id` exists and is verified; drops citations that aren't.
   - Applies evidence rules → caps (`final_score = min(proposed, 2)` + `cap_reason`, `status = insufficient_data`).
   - Fires kill triggers from claim flags; any fired trigger forces verdict `NO_GO` unless the user has explicitly overridden in the spec.
   - Computes `weighted_total` (0–5) and verdict: ≥3.5 GO, 2.5–3.5 PIVOT, <2.5 NO_GO; if ≥3 dimensions are `insufficient_data` → `INSUFFICIENT_DATA`.
   - Runs `economics.py` on numeric claims (price, COGS, CAC proxy, fixed costs, volume assumptions) → contribution margin, break-even units/month, payback months, and a sensitivity table (±30% on price and volume). Missing inputs are listed, not guessed.
   - Writes `04_scores.json`.
3. `scripts/render_report.py <run_id>` → `05_report.md` with sections: Verdict & one-paragraph why · Score table · Kill triggers · Unit economics · Dimension sections (findings, cited claim ids, gaps) · Finland funding fit (starttiraha / Leader / elinvoimakeskus / Finnvera eligibility notes, each with its official-source claim) · Rääkkylä location notes · Risk register · Starttiraha-format business plan draft (liiketoimintasuunnitelma skeleton + kannattavuuslaskelma from `economics.py`) · Sources (url, title, retrieved_at, verification state) · Usage summary.
4. Orchestrator shows the verdict and offers `/debate <run_id>`.

### Stage 6 — Persistence/versioning

- Reports are immutable. Re-running creates `runs/<run_id>-v2/` linked via `idea_versions.parent`. `/status` can diff score sheets between versions.
- Record in `runs/<id>/meta.json`: git commit of prompts/config, `models.yaml` snapshot, Claude Code version, timestamps.

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

1. **Round 0 (independent).** Launch the 5 personas in one message. Each gets: the report, its evidence subset, and the `Position` schema. Writes `debate/round0/<role>.json`. Hook validates.
2. **Anonymize.** `debate.py anonymize round0` → `debate/round0/positions_anon.json` (role names replaced with P1…P5, order shuffled with a seeded RNG; mapping stored privately).
3. **Rounds 1..N.** Each persona receives all anonymized positions and writes a `Rebuttal`. Rules enforced by `scripts/debate_validate.py`:
   - `stance: modify|agree` on another position, or any change to its own `proposed_change`, **must** carry `basis.new_claim_ids` (ids that were _not_ cited in that role's previous turn) **or** `basis.computation` (a number derived from existing claims, shown); otherwise the response is rejected and the persona is re-prompted once with the rejection reason. `disagree` needs only a claim id or an explicit `evidence_gap`.
   - A persona may emit up to 1 `MiniResearchRequest` per round (max 3 per debate). The orchestrator runs it as a research subagent (same contract as stage 2), the result passes through `verify_claims.py`, and new claim ids become available next round. This is the only way new information enters the debate.
4. **Convergence** (`scripts/debate_converged.py`, exit 0 = stop): stop after a round if (a) no new claim ids were introduced and no `proposed_change` changed, or (b) the judge's interim projected scores moved < 0.25 on every dimension, or (c) round == `max_rounds`.
5. **Conformity flag.** If stances converged (≥ 4 of 5 personas `agree` on the same change) while zero new claim ids entered the debate → `conformity_flag = true`, shown prominently in the output.
6. **Judge.** Receives anonymized positions and rebuttals, the verified ledger, and the score sheet. Writes `debate/verdict.json` (`Verdict`). Must cite claim ids for every accepted change; may not introduce new facts. Then `render_report.py --debate` produces `debate/revised_plan.md` (diff-style vs `05_report.md`), the assumption register, and the experiments list ordered by `info_value / cost`.
7. Offer to re-submit the revised plan as `idea_version` n+1 (`/validate --from <run_id>`).

---

## 7. Hooks (`.claude/settings.json`)

- **PostToolUse** (all tools): `uv run python -m ideaforge.usage log` — appends `{ts, run_id (from env/cwd marker), agent, tool, approx_tokens}` to `runs/<run_id>/usage.jsonl`. Also increments per-agent search/fetch counters; if a counter exceeds `budget.yaml`, writes `runs/<run_id>/BUDGET_EXCEEDED_<agent>` (the orchestrator checks for these files after each stage).
- **SubagentStop**: `uv run python -m ideaforge.validate_file --auto` — infers which file the subagent was supposed to write from its name and validates it. Non-zero exit returns the error text to the orchestrator.
- **Stop** (main session, after a stage): same validator for stage files.
- **PreToolUse on `Write`/`Edit`**: deny writes outside `runs/`, `cache/`, and the project source unless the user is in an explicit "development" session (simple path check). Research subagents must never modify prompts, config or scripts.
- **PreToolUse on `Bash`**: allow only `uv run …`, `python -m ideaforge…`, `git …`, `ls/cat`. Deny `curl|wget` (all fetching goes through WebFetch or the Python tools so it is logged and cached).

Permissions in `settings.json`: pre-approve `WebSearch`, `WebFetch`, `Read`, `Write` (scoped), the allowed `Bash` patterns, and the `Agent` tool so the pipeline runs unattended with `claude -p`.

The development harness (§14) adds its own hooks to the same `settings.json`: `SessionStart` summary, a second PreToolUse guard (`.claude/hooks/guard.sh`), a PostToolUse Prettier hook and an opt-in Stop guard. Both guards run on every call and either can block. "Development session" means the `.ideaforge-dev` marker exists **or** `HARNESS_LOOP=1` is set by the loop driver (D-005); subagents are strict either way.

---

## 8. Finnish data tools (`src/ideaforge/fi/`)

All free, no keys. Thin wrappers with on-disk caching (24 h) and a `--json` flag.

- `pxweb.py`: base URLs for StatFin (`https://pxdata.stat.fi/PXWeb/api/v1/{lang}/StatFin/`) and Luke (`https://statdb.luke.fi/PXWeb/api/v1/{lang}/LUKE/`). Functions: `list_tables(path)`, `metadata(table)`, `query(table, filters) -> DataFrame`. Handle the 100 000-cell limit by refusing with a helpful message. Wrap the base URL so the newer API can be swapped in.
- `prh.py`: `https://avoindata.prh.fi/opendata-ytj-api/v3/companies` — search by name, TOL industry code, municipality, registration date; return count + rows. Note in docstring: no sole traders, no contact details.
- `eurostat.py`: JSON-stat endpoint; `get(dataset, filters)`.
- Each tool prints the exact request URL so the subagent can cite it as `source_url` with `source_type: api`.

`config/finland.yaml` holds _hints_ (VAT small-activity threshold, starttiraha daily amount and max months, Leader group name and contact, employment-area contact, elinvoimakeskus grant URL, municipality facts) each with `verify_at_runtime: true` and `verify_url`. The regulation/financing subagents are instructed to confirm every hint against its `verify_url` before citing it.

---

## 9. Testing and evaluation

- **Unit tests** (`pytest`): scoring caps and kill triggers (table-driven); verification fuzzy-match thresholds; conflict detection; economics on known inputs; debate validator (rejects unsupported stance change, accepts one with a new claim id).
- **Schema tests**: every example JSON in `tests/fixtures/` validates.
- **Golden set** (`tests/golden/*.yaml`, 10 ideas for v1, 20 for v2): a short idea, expected verdict range, and 2–3 "must-find" facts (e.g. an existing local competitor, a known regulatory requirement). `/eval` runs the pipeline on each (sequentially, to respect usage limits), then checks: verdict within range, must-find facts present among verified claims, zero unverified claims cited in the score sheet. Include obviously bad ideas, one real existing Rääkkylä business, and one with a Finnish regulatory trap.
- **Back-test mode**: `--as-of YYYY-MM-DD` adds a header to every research prompt forbidding sources after that date and makes `verify_claims.py` reject claims with `published_date` after it.
- **Human review**: `/status` lets the user score each report section 1–5; stored in `reviews` table to track drift after prompt or model changes.
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

### Phase 6 — v2 (optional)

- Streamlit viewer over SQLite; local competitor index (PRH + yc-oss company list with local embeddings); experiment tracker that feeds results back as top-confidence claims into version n+1; `claude -p` wrapper script for overnight batches.

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

The remaining work is built with an agent harness ported from Metsävahti (D-001–D-006). It is development tooling and never runs the pipeline.

- **State:** `feature_list.json` is the queue. There is one feature per ticket in `docs/TICKETS.md`, with `depends_on`, `verification[]` and `evidence[]`. Only `pnpm harness:feature` and `pnpm harness:verify` change it. `PROGRESS.md` is the session log; `docs/DECISIONS.md` holds the decisions.
- **Loop:**
  - `/clock-in` reads the state, runs `./init.sh` and activates exactly one feature (WIP=1).
  - Implement the feature.
  - `/verify-feature` runs the feature's steps in order and records dated evidence.
  - `/clock-out` runs the clean-state check, updates `PROGRESS.md` and commits.
- **Verification:** one layer, L1 `pnpm check` (`tsc`, Prettier, the Vitest harness tests, `uv run pytest`). Steps that need the network, a real Claude run or a decision by the user are `manual:` and keep the feature human-only.
- **Unattended:** `pnpm harness:loop` runs one fresh `claude -p` session per ready feature in its own git worktree, with `HARNESS_LOOP=1` and caps from `harness.config.json`. It re-checks the result, has a fresh-context evaluator grade it against `docs/harness/evaluator-rubric.md`, then opens a PR that CI (`L1 (pnpm check)`) must pass.
- **Sizing:** a feature fits one session. Tightly coupled tickets are merged, and the survivor lists what it absorbs.

Details: [docs/harness/README.md](docs/harness/README.md).
