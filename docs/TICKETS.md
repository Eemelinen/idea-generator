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

16. **Claim verification rules (IF-208).** Interpretations made unattended, to be tuned in IF-216:
    - `verify_claims.py` parses every `02_research/*.md` and writes `03_claims/<file stem>.json` (claims `pending`, `retrieved_at` = parse time). A candidate-claims block that does not parse is a `warning:` and is skipped; the other blocks and files still run, and the script exits 0 once `verified.json` is written (exit 1 only for an unknown run or a missing `02_research/`). A claim id seen in an earlier file is skipped with a warning (its `<stem>.json` still lists it). Re-runs upsert; a claim deleted from a research file keeps its old DB row. The printed summary has one line per research file stem (its claims, whatever `dimension` they name) plus a total. Stage bookkeeping is left to `run_stage.py` (IF-214).
    - `verified.json` holds every claim with its final state; `retrieved_at` there is the source's fetch time (the cache file's mtime on a cache hit). The flags `unfetchable` and `robots_disallowed` belong to the script: values an agent wrote are dropped and recomputed; kill-trigger flags are kept.
    - Cache: `cache/<sha256(url)>.txt` holds the extracted text of successful fetches only, is written via a per-process temp file and rename (the temp file is removed if either fails), and never expires (delete the file to refetch). A hit skips robots.txt and the network. Failures are not cached, so a re-run retries them. Each URL is fetched once per run, robots.txt once per origin.
    - robots.txt follows `urllib.robotparser`: 401/403 → everything disallowed, other 4xx → everything allowed. A robots.txt that cannot be fetched (network error, 5xx) allows the page fetch; stricter readings (RFC 9309: unreachable → disallow) are for IF-216 to weigh.
    - `unfetchable`: any exception from the fetch or the text extraction (one bad source never costs the run its output), HTTP ≥ 400, a non-text, non-HTML type (PDF, images), or no extractable text, including a JS-only page whose only text (≤ 300 chars) asks for JavaScript. HTML text is the whole visible page (`script`/`style`/`template` dropped with lxml, then `trafilatura.html2txt(clean=False)`), so a quote from an info box or sidebar still matches. A leading `<?xml … encoding=…?>` declaration (XHTML) is stripped first, because lxml refuses an already-decoded string that declares an encoding; `trafilatura.extract` is the fallback when lxml cannot parse the page or finds no text. Other `text/*`, JSON, XML and `+json`/`+xml` bodies are matched as they are. The 10 s timeout is per socket read; there is no total-time or size cap yet. PDFs being unfetchable may cost official evidence; IF-216 decides whether to add a PDF extractor.
    - Matching normalizes both sides (NFKD with combining marks removed, so `ä` = `a`; casefold; typographic quotes and dashes; soft hyphens; whitespace) and uses `partial_ratio ≥ 90`. A page text shorter than the quote uses the plain `ratio`, so a tiny page cannot "contain" a long quote.
    - Source typing: an allow-listed URL becomes `official` unless the claim is `api` (IF-209 re-queries those; until then `api` claims are fetched and quote-matched like any page). A model-declared `official` on a non-listed domain is left as declared, so `has_official_source` in scoring (IF-302) must test the domain with `verify.is_official`, not `source_type`.

17. **Usage report and `/status` (IF-212).** Interpretations made unattended, to be tuned in IF-216:
    - The report logic lives in `ideaforge.usage` (`summarize`, `render_summary`) and the `/status` text in a new module `ideaforge.status`; `scripts/usage_report.py` and `scripts/status.py` (added to the §1 layout with `status.py`) are thin CLIs. `usage.jsonl` is the source; the `usage` table is not read.
    - Stage attribution: a row's own `stage` wins (the hook writes `null` today; IF-214 may fill it). Otherwise a research agent's call goes to its own `research:<dim>` by identity, not by time: research stages overlap, and a retry moves `started_at` past the first attempt's calls. Every other row (main session, debate agents) goes to the latest-started stage whose `stages` window (`started_at` ≤ ts ≤ `finished_at`, inclusive) holds the timestamp; the main session's calls during parallel research therefore land on the latest-started research stage. A `running` stage, or one whose `finished_at` is older than its `started_at` (restarted; `stage_set` keeps the old value), is open-ended. Rows no window holds are `(no stage)`. Unparseable lines are skipped and counted in a `warning:` line; invalid UTF-8 is replaced, not fatal.
    - "Searches" = `WebSearch` calls and "fetches" = `WebFetch` calls; tokens are the hook's `approx_tokens` (note 7). Budget markers print with their lines joined by `; `.
    - `/status` lists the 10 newest runs (`--limit N`) with one stage line each, the 11 research stages folded into counts per status. A kill flag is "fired" when a `verified` claim carries it (the `config/rubric.yaml` rule); flags on other claims are listed as not fired; a trigger in `00_spec.json` `kill_trigger_overrides` is still listed, marked overridden (scoring decides, IF-302). Markers are `VALIDATION_FAILED_*`, `VALIDATION_WARNINGS_*` and `BUDGET_EXCEEDED_*`, each with its first line (≤ 100 chars) and a count of further lines. A run that exists only on disk or only in the DB still prints what is there; neither → exit 1.

18. **Stage state machine (IF-214).** Interpretations made unattended, to be tuned in IF-216 / IF-206:
    - Outputs per stage (`runs.STAGE_OUTPUTS`): `intake` → `00_spec.json`, `plan` → `01_plan.json`, `research:<dim>` → `02_research/<dim>.md` (the full IF-205 research validator, provenance included), `verify` → `03_claims/verified.json`, `synthesize` → `04_scores_proposed.json` **and** `04_risks.json`, `score` → `04_scores.json`, `report` → `05_report.md`. The report has no schema, so it only has to exist and be non-blank; IF-303 may tighten that.
    - Stages run in groups (`runs.STAGE_GROUPS`): intake, plan, the 11 research stages together, verify, synthesize, score, report. `begin` refuses a stage while any stage of an earlier group is incomplete. "Complete" is `insufficient_data`, or `done` **and** the output validates now, so a file that is deleted or broken after its stage finished makes the stage incomplete again everywhere (`next_stages`, `begin`, `resume`).
    - Transitions: `begin` pending | failed (or a `done` stage whose output no longer validates) → running; `finish` running → done if the output validates, else → failed with the validator's message (exit 1); `--insufficient-data` is allowed for research stages only, from any incomplete status. `begin` on a running stage is refused: a re-launch after a validation failure goes `--finish` (→ failed), then `--begin` again, so `attempts` counts launches.
    - `resume` is explicit (`run_stage.py <run_id> --resume`), never implied by `--next`, because research stages are legitimately `running` in parallel during stage 2. It turns a `running` stage `done` when its output validates (the agent finished, the bookkeeping died with the session) and `pending` otherwise, and a `done` stage with a missing or invalid output `pending`. `failed` and `insufficient_data` are left alone; `next_stages` re-queues `failed`. Resetting a stage does not cascade: if `01_plan.json` vanished, `plan` is redone but the research stages that already validate stay `done` (they were researched against the old plan); IF-216 may decide to invalidate later groups instead.
    - `next_stages` returns the pending and failed stages of the first incomplete group; it is empty while that group only has running stages, and when the run is complete. A stage without a `stages` row counts as `pending`.
    - Usage attribution (note 17) is unchanged: a stage reset to `pending` keeps its `started_at` and has no newer `finished_at`, so `usage.stage_windows` treats it as open-ended until it begins again. The usage hook still writes `stage: null`.

19. **Validate and research skills (IF-206).** Interpretations made unattended, to be tuned in IF-216:
    - `/validate` ends after stage 3 until the synthesize/score/report skills exist. `/validate <run_id>` (a single argument that is an existing run id) resumes that run instead of creating one; `/validate [--preset <name>] <idea text>` starts a new one. `/research <run_id>` refuses a run whose intake is incomplete (it points at `/validate <run_id>`) and follows the validate skill's Stage 1–3 and End sections instead of repeating them, so the two cannot drift.
    - `run_stage.py <run_id> --resume` now also writes `runs/.active` (and prints `active: <run_id>` first): the hooks find the run only through the marker, so `/research` on an older run would otherwise log usage and validate files for whatever run was created last. `--next` stays read-only.
    - The orchestrator validates `00_spec.json` and `01_plan.json` with `validate_file` before `--finish`, so it can fix its own file instead of failing the stage.
    - "Failed validation" for a research dimension is `--finish` exiting 1; the `VALIDATION_FAILED_<agent>` marker's text is appended to the re-launch brief with the `--finish` error. A dimension gets two launches in total, counted by the stage's `attempts` (from `status.py`), also across sessions: a `failed` dimension already at 2 is marked `insufficient_data` instead of launched again.
    - The research brief carries the run's preset budget (`meta.json` → `budget.yaml`), because the generated agent files have the default preset's numbers baked in. A key the `killcause_scout` entry omits (`max_output_words`) keeps the agent file's value. The research validator's word limit now also follows the run's preset (`usage.run_preset`, as the budget counters already did; the default preset when `meta.json` is missing or names an unknown preset), so a `--preset deep` agent that writes 1600 words is not rejected against the standard 1200.
    - Clarifying questions: none after "just run it"; `config/founder.yaml` values are named as placeholders while `confirmed: false`. `idea_id` is the run id without its timestamp prefix and `-vN` suffix.
    - Plan approval ("proceed unless they object"): the skill shows the plan summary and asks one `AskUserQuestion` (proceed or change; not one of the 5 clarifying questions). After "just run it" it shows the summary and proceeds. The killcause entry has no rubric `min_evidence_for_3`; its `evidence_needed` is "sourced reasons the idea fails, each with a verbatim quote".
    - The idea text goes to `new_run.py` in single quotes, without quotes, backticks, `$`, `#` or backslashes: the guard refuses command substitution even inside quotes, and a `#` stops it from discounting quoted `>` or `|`. `idea.md` therefore lacks those characters; the spec is written from the user's original text.
    - `tests/test_skills.py` checks every skill under `.claude/skills/`: the frontmatter, every cited script, module and repo path exists, every cited `uv run …` command passes the strict main-session guard and the skill's `allowed-tools`, every `run_stage.py` stage is real, each validate stage section wraps its stage in `--begin` … `--finish` followed by `usage_report.py`, and the Stage 2 table matches `agents.AGENTS`.

20. **Scoring (IF-302).** Interpretations made unattended, to be tuned in IF-304 / IF-309:
    - `ideaforge.scoring.score(proposed, claims, overrides, *, unit_economics, computed_triggers, rubric)` returns a `ScoreSheet`; `score_run.py` (IF-304) passes `04_scores_proposed.json`, every claim of `verified.json` and `00_spec.json` `kill_trigger_overrides`, and reports `dropped_citations` (cited ids that are unknown or not `verified`, conflicts included, which `score` drops).
    - A dimension's evidence is only the verified claims its score cites, from any dimension (so `unit_economics` may cite a `pricing` price). Claims the synthesizer did not cite do not count, so a score is backed by what it names. A rubric dimension without a proposed score gets 0 with justification "no proposed score" and is capped like any other. The cap therefore trusts the synthesizer to cite relevant claims (three official regulation claims cited under `customer` would pass it); IF-304/IF-309 may restrict evidence to the dimension's own claims plus named neighbours.
    - Any failed rule labels the dimension `insufficient_data` with a `cap_reason` (the failed rules joined by `; `), even when the proposal is already ≤ 2, as the rubric comment says. A missing or malformed rule parameter raises `ValueError` (`check_rubric` checks the whole rubric; a test runs it on `config/rubric.yaml`).
    - `min_sources(n, independent)`: with `independent: true` it counts distinct registrable domains (the last two host labels, three under `co`/`com`/`org`/`gov`/`ac`/`edu`/`net` with a two-letter TLD), so `pxdata.stat.fi` and `stat.fi` are one source; with `false` it counts claims. `has_official_source` tests the URL with `verify.is_official` (note 16), not `source_type`.
    - `has_numeric(field)`: the claim schema has no field tag, so `numeric_field(claim)` derives it from `value`, `unit` and `statement`. A currency unit (`EUR…`, `€…`) is `price` when the statement says price/hinta or the claim is a `pricing` claim, else `cost` when it names a cost (cost, expense, fee, commission, rent, wage, salary, insurance, kustannus, kulu, vuokra, palkka, vakuutus, maksu) or is a `unit_economics` claim. A count unit (persons, companies, households, visitors, nights, kpl, henkilö, … with an optional `/period`) is `unit_count`. Currency also matches `euro`/`euroa`; a count may be per period (`visitors/year`, `nights/season`) but not per area (`henkilöä/km²`). `%`, `km` and other units supply nothing. Known crudeness: "a sauna evening costs 25 EUR" outside `pricing` reads as a cost, and "Rent costs 400 EUR" inside `pricing` as a price. IF-303 (economics) may reuse this mapping or add an explicit claim field.
    - Kill triggers fire from the flags of every verified claim in the run (not only cited ones; the `/status` rule, note 17) plus `computed_triggers` (IF-303's negative margin), minus the spec's overrides.
    - `weighted_total` = Σ weight × `final_score`, rounded to 6 places against float noise, and the verdict uses that stored value. Precedence: any fired trigger → `NO_GO`, then more than `max_insufficient_dimensions` insufficient dimensions → `INSUFFICIENT_DATA`, then `go` / `pivot`. Verified kill evidence outranks missing data; the plan does not order the two.

21. **Unit economics (IF-303).** Interpretations made unattended, to be tuned in IF-304 / IF-309:
    - `ideaforge.economics.unit_economics(claims, assignments=None, *, vat_registered=True)` → `UnitEconomics`; `computed_triggers(ue)` returns `["negative_contribution_margin"]` when the margin is below 0 (zero is no trigger, but has no break-even) and `score_run.py` (IF-304) passes it to `scoring.score(..., computed_triggers=…)`. Only `verified` claims are used.
    - Input roles: `price`, `variable_cost`, `variable_cost_pct` (commission, % of price), `fixed_costs` (per month), `cac`, `volume` (units per month), `purchases_per_customer` (per month), `vat_rate`. `UnitEconomics` gained `purchases_per_customer_month`, `monthly_profit_eur`, `vat_registered`, `vat_rate_pct` and `notes`.
    - Claims have no field tag (note 20), so there are two mapping modes. With `assignments` (role → claim ids; IF-304 can have the synthesizer emit them) exactly those claims are used: cost roles sum their claims, every other role takes one (more raises `ValueError`); unknown, unverified, valueless or wrong-unit (`%` vs. not) claims are dropped with a note, and a cost role that loses any claim is listed in `missing_inputs` with no total, since a partial sum would understate the cost. Without, each role gets one claim by unit and keywords (`scoring.numeric_field` for price / cost / count, a CAC keyword list, `%` + VAT/ALV or commission words), and the most pessimistic candidate wins (lowest price and volume, highest costs, CAC and VAT rate), compared after the period conversion and the VAT treatment (the VAT rate is picked first; without a verified rate candidates are compared on their quoted values, and `vat_rate` is listed missing only if the chosen one needs a conversion); separate cost items are not summed because duplicate sources would double-count. Automatic `volume` and `variable_cost` come only from `unit_economics` claims (market-size counts and one-off permit fees elsewhere are not the business's own), `cac` from `unit_economics`/`gtm`, commission from `unit_economics`/`pricing`/`gtm`; a fixed cost is a cost with a period in its unit, and a variable cost one whose unit has no `/` or `per` word (`EUR`) or only per-unit-sold words (`economics._PER_UNIT`: person, guest, night, visit, order, session, kpl, henkilö, hlö, yö, käynti, kerta, …, plural `s` dropped). A cost from `unit_economics` with any other `/` word (`EUR/h`, `EUR/event`, `EUR/2 weeks`) is not a candidate and gets a note (`… is neither per unit sold nor per period; not used`), so an unclear unit never becomes a per-unit cost. The automatic mode is crude (price per person vs. cost per session is not reconciled), so IF-304 should prefer assignments before it lets the computed trigger force NO_GO.
    - Periods come from the unit (`/month`, `/kk`, `per year`, `/vuosi`, `/week`, `/day`, …; a year is 1/12 month, a week 52/12, a day 365/12). A quarter is 1/3 month. An assigned fixed cost, volume or frequency with no `/` or `per` word is used as per month and noted; one whose `/` or `per` word has no monthly conversion (`/season`, `/site`) is dropped with a note. A count before the word (`EUR/2 weeks`) is not converted: the unit has no known period, so such a fixed cost, volume or frequency is dropped too. A per-season unit has no monthly or per-unit reading, because seasonal figures cannot be spread without knowing the season length: `economics.seasonal` looks at the first three words after each `/` or `per` and matches any that contains a season stem (`season`, `summer`, `winter`, `spring`, `autumn`, `kausi`/`kausa`/`kaude`, `sesonk`/`sesong`, `kesä`, `talvi`/`talve`, `kevät`/`kevää`, `syksy`, `vuodenaika`), so compounds, plurals, inflections and phrases count (`kesäkausi`, `talvikausi`, `seasons`, `off-season`, `sesonkiaika`, `kesällä`, `kaudet`, `high season`, `per the season`, `koko kesä`); known period words and words holding `kuu` or `vuorokau` never do (`kuukausi`, `kuukauden`, `kesäkuu` is June; `vuorokausi` / `vuorokaudessa` / `vuorokaudelta` are days, like `vrk`). Because of the three-word window a unit such as `EUR per evening in summer` is also read as seasonal (fails safe: the claim is dropped). Such a claim is dropped with a note when assigned to any role (including `variable_cost`, `price` and `cac`) and is never an automatic candidate (noted `… has no monthly conversion; not used`). In automatic mode the statement is checked too, with a two-word window, so a plain-`EUR` claim stated `per summer season` is not a candidate (noted `… statement names a per-season amount; not used`); assignments are trusted and their statements are not checked. An assigned or automatic `variable_cost` or `cac` whose unit names a period but no unit sold (`EUR/month`, `EUR/year`) is dropped with a note (`… is per month, not per unit sold; dropped`), because a running cost is not a per-unit cost; `EUR/guest/month` is kept. What remains unguarded: a seasonal or one-off lump sum whose unit is plain `EUR` and whose statement does not say `per <season>` is still read as a per-unit cost in automatic mode (the research contract asks for plain `EUR`), and an assigned `variable_cost` with any other `/` word (`EUR/h`, `EUR/event`) is used per unit; so IF-304 must not let a trigger computed from the automatic pick force NO_GO, and should check assignments. `per a night` is per unit, not per annum. A price per month or year is a subscription: one unit sold is one customer-month, so the purchase frequency is 1 and an assigned frequency is ignored (noted, and left out of `input_claim_ids`); prices per day, night or person are per unit.
    - VAT: the basis comes from the unit or statement (`excl. VAT`, `+ alv`, `alv 0 %`, `veroton`, `ilman alv` → excl; `incl. VAT`, `sis. alv`, `verollinen` → incl); a text that states both is unstated. VAT-registered (default): every amount net of VAT. Not registered (under the small-business threshold): the price is used as quoted (no VAT is charged) and costs are grossed up (VAT on purchases is not deductible). A conversion needs a verified `%` VAT-rate claim, never `config/finland.yaml`; without one the converted amount and its outputs stay `None` and `vat_rate` is missing. An amount with no stated basis gets the reading that hurts the business, and a note: a price is read as incl. VAT (a lower net price), a cost as excl. VAT (kept as is when registered, grossed up when not), so it still needs the rate when it has to be converted. The commission is a share of the price as booked; VAT on the commission itself is not modelled. Registration status is a caller argument because `IdeaSpec` has no field for it; IF-304 decides where it comes from.
    - Outputs: margin = price − (unit costs + commission % × price); margin % of price; break-even = fixed / margin (only for a positive margin); monthly profit = margin × volume − fixed; payback months = CAC / (margin × purchases per customer per month). CAC is not in the monthly profit (no churn data). Sensitivity: price and volume each at −30 / 0 / +30 % (9 rows), commission scaling with the price. `missing_inputs` lists every absent input in role order plus `vat_rate` when a conversion needed it; dependent outputs stay `None`.

22. **Synthesis and score run (IF-304).** Interpretations made unattended, to be tuned in IF-309:
    - The synthesizer is a generated subagent (`agent_templates/synthesizer.md.j2` → `.claude/agents/synthesizer.md`, `agents.AGENTS["synthesizer"]`, kind `synthesizer`, role `synthesizer`, tools `Read, Write`), not the orchestrator as §6 stage 5 says. Reasons: `config/models.yaml` already has a `synthesizer` role that only an agent file can honour; a fresh context is the only way to give it **only** the allowed inputs after `/validate` filled the main context with research; and the SubagentStop hook then validates both files (block once, then `VALIDATION_FAILED_synthesizer`). The guard lets it write only `04_scores_proposed.json` and `04_risks.json` of the active run (19 agents incl. the harness evaluator, 18 generated).
    - Its input is one file, `runs/<run_id>/04_synthesis_input.json`, written by `scripts/synthesis_input.py <run_id>` (`ideaforge.synthesis.synthesis_input`): the spec, the `verified` and `conflict` claims of `verified.json` (unverified and pending left out), the rubric (weights, `min_evidence_for_3`, evidence rules, kill triggers, verdict thresholds) and the unit-economics roles. The prompt forbids reading anything else; reads are not mechanically blocked (a `Read` guard would run a hook on every read of every session). `tests/test_skills.py` checks that the skill's brief and the prompt name only that input and the two outputs, and never the research or claim files.
    - `ProposedScores` gained `unit_economics_inputs` (role → claim ids; `economics.ROLES`; one id per role except the summed cost roles) and rejects a dimension scored twice. `score_run` passes them to `economics.unit_economics` as `assignments`. **Only assigned inputs may fire `negative_contribution_margin`**: without assignments the automatic pick still runs and its figures are reported, but no computed trigger is passed to `scoring.score` and a note says so (note 21, "What remains unguarded"). Assigned inputs are used as note 21 describes (an assigned `variable_cost` in `EUR/h` is still used per unit), but a trigger needs every assigned `variable_cost` and `cac` claim to pass `economics.per_unit` (no `/` word, or only per-unit-sold words): an `EUR/h`, `EUR/event` or `EUR/kuukaudelta` assignment keeps its margin in the sheet with a note and fires nothing (`EUR/guest/month` fails safe the same way). The prompt tells the synthesizer what each role accepts.
    - VAT registration is `IdeaSpec.vat_registered` (default `true`): the founder's choice, not research, so it belongs in the spec; `/validate` sets it to `false` only when the user says the business stays under the threshold.
    - `score_run` sets a proposal with no verified citation left (none cited, or all dropped) to `proposed_score: 0` with "no verified evidence (proposed N; dropped citations: …)" before scoring: the synthesizer rule "a dimension without verified evidence is 0", applied mechanically, so an uncited proposal cannot keep up to 2 points. `scoring.score_dimension` itself is unchanged (it still caps an uncited proposal at 2).
    - `score_run` writes `04_scores.json` via a temp file and rename and replaces the run's `scores` rows (`db.replace_scores`); it needs the run's DB row (exit 1 otherwise, like `verify_claims.py`). Dropped citations (`scoring.dropped_citations`), zeroed dimensions, fired triggers, the verdict, the unit economics and their notes are printed; risk `claim_ids` that do not exist, and a missing or invalid `04_risks.json`, are only warned about (the synthesize stage owns that file and `run_stage.py` validates it; scoring does not need it).
    - `/synthesize <run_id>` runs stages `synthesize` and `score` (wrapped in `run_stage.py --begin/--finish`, `validate_file` before each `--finish`, `usage_report.py` after). A synthesizer that fails validation is re-launched once; a second failure stops the skill with the stage `failed` (no `insufficient_data` outside research). `/validate` still ends after stage 3 and points at `/synthesize`; the report (IF-305) comes next.

23. **Report rendering (IF-305, absorbs IF-306).** Interpretations made unattended, to be tuned in IF-309:
    - `ideaforge.report` (`render`, `render_text`) renders `src/ideaforge/templates/report.md.j2` (Jinja2, `StrictUndefined`) from `00_spec.json`, `03_claims/verified.json`, `04_scores.json`, `04_risks.json`, each research file's `## Gaps` section and `usage.jsonl` (`usage.render_summary`, the `usage_report.py` text). It decides nothing: scores, caps, triggers, the verdict and the unit economics are read from `04_scores.json`. The verdict paragraph explains the verdict in `scoring.verdict`'s precedence (trigger → insufficient data → thresholds), names the capped, strongest and weakest dimensions and the margin, and adds a note when the stored verdict differs from what the current rubric gives.
    - The cap label is "**capped at 2**: insufficient data (<cap_reason>)" on every `insufficient_data` dimension, in the score table and its section, also when the final score is below 2 (the rubric labels every failed rule).
    - Dimension sections: the synthesizer's justification as the findings, the cited verified claims with their sources, the other verified claims of the dimension (ids), the claims not counted (not verified) and the research gaps; "no research file" when the dimension has none. `killcause` gets a section without a score.
    - **Finland funding fit**: four fixed programmes in `report.PROGRAMMES` (starttiraha; Leader (Jetina); elinvoimakeskus; Finnvera). Only `financing` claims count: elinvoimakeskus.fi also hosts environmental and shoreline permits, and "leader" or "starttiraha" also appear in competition and tax claims, so an off-topic official claim must not fill a funding gap (a test checks this). A financing claim is about a programme when its statement, source title or quote names it (`starttirah`, `start-up grant`; `jetina`, `leader` not followed by `ship`; `elinvoimakesk`, `ELY-keskus`, `ELY centre`; `finnvera`) or its URL is on the programme's own site (jetina.fi, elinvoimakeskus.fi, finnvera.fi). Only `verified` ones on an allow-listed domain (`verify.is_official`) back an item, shown with statement, quote, source and retrieval time; otherwise the item reads "**unverified – see gaps**", followed by the financing claims about it that do not count and why, and the financing research gaps. `report.py` never reads `config/finland.yaml`, so no hint value can appear (a test checks the rendered section against every hint value). Eligibility is not judged against the founder's goal: the founder line at the top shows the goal and the reader decides.
    - **Rääkkylä notes**: the location score, the verified `location` claims plus verified claims of any dimension naming Rääkkylä, Keski-Karjala or North Karelia (Pohjois-Karjala), the ones not counted, and the location research gaps.
    - Sources: one row per claim URL (title of its first claim, earliest `retrieved_at`, verification counts, `unfetchable` / `robots_disallowed`, whether the domain is official, claim ids); the `sources` table is not read. Risks are sorted by likelihood × impact; unknown claim ids are marked. Cited claims are re-checked against the current `verified.json` (only `verified` ones are listed as cited), and a fired trigger with no verified claim carrying it is labelled computed only for `negative_contribution_margin`, otherwise as possibly stale.
    - Immutability: `render` refuses (`ReportExists`, exit 1) when `05_report.md` or the run's `reports` row (kind `report`) exists, even if the other is missing. The row is inserted and the file created in one transaction (`db.add_report(..., then=…)`; the file is written to a temp file and hard-linked into place, which fails if it exists), so a failed write leaves neither; a crash after the link but before the commit leaves a file without a row, which still refuses a re-render. The pipeline guard denies every tool write to `runs/<run_id>/05_report.md`, in every mode, so only the script writes it. Re-scoring a run after its report does not change the report; a new version is a new run (IF-308).
    - `/synthesize` runs the report as stage 5c (`run_stage.py <run_id> report --begin`, `render_report.py`, `--finish`, usage report). The starttiraha business-plan draft that §6 lists in the report is IF-307 (F-018), and `render_report.py --debate` is the debate tickets'.

24. **Versioning (IF-308).** Interpretations made unattended, to be tuned in IF-309:
    - "Git commit of prompts/config" is recorded three ways in `meta.json` (`ideaforge.meta`): `git_commit` (HEAD), `config_commit` (the last commit touching `config/`, `prompts/` or `agent_templates/`, the sources of every prompt and agent file) and `config_dirty` (uncommitted changes there at creation, since a commit alone would then not describe what ran). Git runs in the repository that holds `config/`.
    - The "models.yaml snapshot" is the `roles` mapping (`models`), not the file text: the roles are what a run used; `notes` are comments.
    - The Claude Code version comes from `claude --version` (first `N.N…` token; 15 s timeout), overridable with `IDEAFORGE_CLAUDE_CODE_VERSION`. Every probe fails soft to `null`, so a run starts without git or `claude` on PATH. The version is that of the CLI on PATH when `new_run.py` runs, which is the session's own in practice.
    - Timestamps: `created_at` (never changes) and `updated_at`, refreshed by every stage transition in `runs.begin` / `finish` / `mark_insufficient` / `resume` (written via a unique temp file and `os.replace`, so parallel `run_stage.py --finish` calls never truncate it; `touch` never raises, so a missing, foreign or unwritable `meta.json` (a reader holding it open on Windows) only loses that `updated_at`, after the stage state is already committed). Per-stage times stay in the `stages` table. `meta.json` also carries `idea_id` and `version`, and the schema requires a `parent_run_id` when `version > 1` (a parent with version 1 stays valid: child runs made before IF-308 have no `version`); `/validate` copies `idea_id` and `version` into the spec from it.
    - `new_run.py --from <parent> [<idea text>]` (`runs.child_run`): the parent must have a db row and a directory; the id is the parent's id without its `-vN` suffix (only stripped when the parent's version is > 1, so a v1 slug like `product-v2` is kept) plus `-v<parent version + 1>`, raised past any id already taken by a directory or a `runs` row, so a second revision of v1 becomes `-v3` (version 3, parent v1). The idea text, budget preset and `as_of` default to the parent's (a revised back-test stays a back-test); `--preset` / `--as-of` override them. Nothing is copied from the parent: the new version re-runs every stage, since its claims and scores belong to its own version. `new_run.py` also refuses an existing run directory (a same-second id collision).
    - Parent immutability is by construction (nothing writes under the parent) plus the existing report guard (note 23); the skill tells the orchestrator to read the parent's spec, report and revised plan only. No guard rule blocks tool writes to other parts of an older run, because `/validate <run_id>` must still resume an unfinished parent.
    - Tests never spawn the real CLI: an autouse fixture in `tests/conftest.py` sets `IDEAFORGE_CLAUDE_CODE_VERSION`; the parser is tested with a patched `subprocess.run`.

25. **Debate anonymization and rebuttal validation (IF-402, absorbs IF-403).** Interpretations made unattended, to be tuned in IF-407 / IF-408:
    - One mapping per debate, not per round: `ideaforge.debate.mapping_for(seed)` shuffles `PERSONAS` with `random.Random(seed)` and numbers them P1…P5 in shuffled order, so a `target_position_id` names the same persona in every round. The seed is generated (`SystemRandom`) on the first `python -m ideaforge.debate anonymize <run_id> <round>` (or given with `--seed`, which must match a stored one), stored in the `debates` row and with the mapping in `debate/.mapping.json`; the two must agree, and a lost row is restored from the file.
    - `debate/round<N>/positions_anon.json` = `{"round": N, "positions": [...]}` in P-id order, each entry `position_id` + the persona's fields without `role` and without `mini_research.requested_by`. Round 0 reads `Position` files and records them as accepted `debate_turns`; later rounds read `Rebuttal` files and leave out roles with a `REJECTED_<role>` marker. A missing persona file is a warning; an invalid one is an error (exit 1).
    - "Leaks no role names": structural fields are dropped, and self-labels in any free-text field become `[persona]`: `debate-<role>`, `<role> persona` / `<role> lens`, `<role> here`, `as the / a / an / my / our / this / your <role>`, an article-less `as <role>` only before a comma or at the start of a sentence, line, bracket, quote or bullet (`As investor, …`, `… thin.  As operator I …`, `(As investor …`; mid-sentence "such as customer reviews" and "treat them as operator costs" stay, but a sentence that starts "As customer demand grows" or "As operator costs rise" is redacted too, which fails safe), `I am / I'm / I, / speaking as (the) <role>`, `from (the / an) <role>('s) perspective / point of view / view / side / standpoint / angle`, and the Finnish `minä / mä (olen / oon) <role>` (also with the essive, `minä olen kirjanpitäjänä`; `yrittäjä` and `asiakas` included), `<role>n näkökulmasta / silmin` (`sijoittajan näkökulmasta`) and essives `perustajana`, `sijoittajana`, `kirjanpitäjänä`, `tilintarkastajana`, `operaattorina` (the ending follows vowel harmony, `-na` / `-nä`). Each listed form (every article, every perspective noun, each Finnish role and verb form) has a case in `tests/test_debate.py::SELF_LABELS`; add one there when a form is added here. Persona names as plain words stay, because "customer", "founder" and "operator" are ordinary plan words (and `customer` is a dimension): "the customer price" and "the founder role" are kept, and so are `yrittäjänä` and `asiakkaana`, which Finnish plans use for the real founder and customers. "As the customer expects" is redacted too (fails safe). IF-407's persona prompt should still tell personas never to name their role. The judge and personas must not be given `.mapping.json`: the guard denies subagent writes to `.mapping.json`, `positions_anon.json` and `REJECTED_*`, but tool reads are not guarded. `.mapping.json` must hold the mapping its seed gives, or every command refuses.
    - `scripts/debate_validate.py <run_id> <round>` (`debate.validate_round`, rounds ≥ 1, after round 0 is anonymized) checks each persona's `round<N>/<role>.json`:
      - "Cited before" = every claim id in the role's round-0 objections and its earlier rebuttals that were not rejected (cited, `basis.new_claim_ids`, ids written in a computation). The ticket's "hasn't cited before" (any earlier turn) is used rather than the plan's "previous turn".
      - `agree` / `modify` and a changed `updated_change` (compared to round 0's `proposed_change` or the last accepted `updated_change`, whitespace- and case-insensitive) need `new_claim_ids` of which none was cited before, or a `computation` that names at least one claim id and has a digit outside the ids. Listing an old id as new is a rejection even with a computation. An evidence gap alone is not enough.
      - `disagree` needs a claim id (`cited_claim_ids` or `basis.new_claim_ids`, no novelty) or `basis.evidence_gap`; a computation alone does not count.
      - Every claim id anywhere in the rebuttal must be in `03_claims/verified.json` with `verification: verified` (conflict and pending ids are rejected).
      - A response may not target the role's own P-id or an id missing from round 0's `positions_anon.json`; `role`, `round` and `mini_research.requested_by` must match the file.
      - "At most 1 mini-research request per round" is per round across personas (the schema already allows one per rebuttal): the requester with the lowest P-id keeps it, the others are rejected with a reason to drop theirs. The per-debate cap (`max_mini_research_tasks`) is IF-404's.
      - A missing or schema-invalid file is a rejection. Reasons go to `round<N>/REJECTED_<role>` (one per line, removed when the role passes) and stdout; every checked file is a `debate_turns` row (attempt + 1 per changed file; re-validating an unchanged file updates its attempt). Exit 0 all accepted, 2 any rejected, 1 bad input. Re-prompting once and what happens after a second rejection are the skill's (IF-407).
    - Open points for IF-407 / IF-408 (from the evaluator, to judge on a live debate): a lowercase token such as `iso-9001` in a computation is read as a claim id and rejected as unknown; any digit outside an id passes as "a number" (`see page 3`); a computation-only `disagree` is rejected; an `agree` kept from the previous round needs fresh evidence again; the lowest-P-id requester keeps the mini-research slot even when its turn is rejected for another reason (chosen so an accepted role never flips to rejected on re-validation); round-0 objection ids are not checked against the ledger; `updated_change` comparison ignores only case and whitespace; a re-prompt answered with an identical file reuses its `debate_turns` attempt; `anonymize` for a round > 0 does not check that the round was validated.

26. **Convergence, conformity flag, verdict and revised plan (IF-405, absorbs IF-406).** Interpretations made unattended, to be tuned in IF-407 / IF-408:
    - Only turns that entered the debate count (`debate.accepted_turns`): a persona file's latest `debate_turns` row must hold the file's current text and be accepted. A file never anonymized (round 0) or validated (rounds ≥ 1) in its current form is an error (exit 1), not a silent skip; rejected turns bring nothing in.
    - `scripts/debate_converged.py <run_id> <round>` (`debate.check_convergence`, round ≥ 1): exit 0 stop, 2 run another round, 1 bad input; it prints which conditions hold and why the others do not, and stores N in `debates.rounds`.
      - (a) "New claim ids" are ids cited in round N's accepted turns (cited, `new_claim_ids`, ids inside a computation) that no accepted turn of rounds 0…N−1 cited, by any persona: an id new to one role but already in the debate is not new. An accepted mini-research request in round N also blocks (a), since its claims enter next round (plan §6: the only way new information enters). "Moved" = an `updated_change` that differs (case and whitespace ignored) from the role's current proposal; restating it is not a move.
      - (b) The judge's interim projection is a new file, `debate/round<N>/interim_scores.json` (`InterimScores`: `round`, `projected_scores`; kind `interim_scores`; the judge's SubagentStop target until `verdict.json` exists; the guard lets only the judge write it and `verdict.json`, so a persona cannot end the debate). It is compared with the latest earlier interim file, or with `04_scores.json`'s final scores before the first. A dimension present on one side only counts as moved, a move of exactly `convergence_score_delta` counts as moved, and a round without an interim file does not meet (b). When and how the judge writes it is IF-407's.
      - (c) `round >= max_rounds` of the run's own preset (`runs.budget_preset`), so an economy run stops after round 2.
    - `debate.conformity_flag(turns, mapping, new_claim_ids)`: "≥ 4 of 5 personas agree on the same change" counts the change's author as backing it, also when its own turn that round was rejected or missing or it moved the change (validation never lets a persona target its own position, so without the author ≥ 4 could only mean all four others), plus every persona with an accepted `agree` on that position id; `modify` and `disagree` do not count. `run_conformity_flag` applies it to the last rebuttal round's accepted turns with the new claim ids of all rounds ≥ 1 (a debate without a rebuttal round: false).
    - `render_report.py <run_id> --debate` (`ideaforge.revised_plan`): `debate.finalize_verdict` refuses (exit 1) an accepted change that cites a claim id missing from the ledger or not `verified` (stricter than "exist", as everywhere else in the pipeline); the plan uses the computed `conformity_flag` and says so when the judge's value differed, and `verdict.json` gets the computed value only after the plan and its rows are committed (`debate.write_verdict`), so a failed render leaves the judge's file and a re-render still shows the disagreement (if that last write fails, the plan and the `debates` row hold the computed flag and only `verdict.json` keeps the judge's). `Verdict.experiments` now needs at least 5 entries with a non-empty `success_threshold` (`schemas.MIN_EXPERIMENTS`; §11), so the SubagentStop hook re-prompts a judge that lists fewer.
    - `debate/revised_plan.md` (`templates/revised_plan.md.j2`) needs `05_report.md` and compares with the current `04_scores.json` (a note appears when the report's row shows a different verdict or total). "Diff-style" is a fenced `diff` block: each dimension's report score as context, or `-` report / `+` projection where the judge projected another value ("(not projected)" otherwise; a projection above 2 on an `insufficient_data` dimension is marked "above the cap", since only new verified evidence in a new version lifts it); the weighted total `-` / `+`, where the projection is computed in Python from the projected scores and labelled a projection, not a new score; and the accepted changes as `+` lines with their claim ids. Then the accepted changes with their verified claims and sources, the rejected changes with reasons (ids missing from the ledger are named), the assumption register in the judge's order, and the experiments by `info_value / cost_eur`, highest first, a free experiment first (ties: higher info value, cheaper, faster, name), shown as info value per 100 EUR.
    - Like the report, the plan is immutable: an existing file or `reports` row (kind `revised_plan`, no total or verdict stored) refuses a re-render; the guard denies tool writes to `runs/<run_id>/debate/revised_plan.md` in every mode. The row, the `assumptions` and `experiments` tables (experiments stored in plan order, idx 1…) and the finished `debates` row (`status done`, `rounds`, `conformity_flag`, `finished_at`) are written in one transaction with the file.
    - Open points for IF-407 / IF-408: the judge prompt does not yet ask for `interim_scores.json` after each round, nor does the skill launch the judge between rounds; the judge must project every rubric dimension in it, or (b) never holds on a real 10-dimension sheet (an unprojected dimension counts as moved); whether a pending mini-research request should block (a) and whether the author should count towards conformity are to be judged on the live debate.

27. **Debate skill, prompts and mini-research (IF-407, absorbs IF-401 and IF-404).** Interpretations made unattended, to be tuned in IF-408:
    - **Evidence subsets.** `python -m ideaforge.debate evidence <run_id>` writes `debate/evidence/<role>.json`: `role`, the persona's own `position_id` (so it can avoid targeting itself without seeing the mapping; the command creates the debate's seed on first use), `dimensions` (`agents.PERSONA_EVIDENCE`; the founder's "all" is every research dimension), `ledger_sha256`, `claims` (only `verified` ones of those dimensions) and `mini_research_claims` (every verified claim from a `03_claims/mini-*.json`, given to **all** personas whatever their subset, since mini-research is how new information enters the debate for everyone). The persona prompt names only its own evidence file and the report, never the ledger, the mapping or another persona's file; the guard denies subagent writes to `debate/evidence/` and `.reprompted`, but reads are not guarded (as for `.mapping.json`, note 25). The report itself carries every dimension's evidence; the plan gives it to every persona. **The subset is enforced in Python** (attempt 2, after the evaluator found it advisory only): `debate.allowed_claim_ids` (the ids of the role's evidence file, computed from the current ledger) bounds every claim id a turn cites. `check_rebuttal` rejects a rebuttal citing a verified id outside it ("not in your evidence file"), so it gets the one re-prompt; a round-0 position is checked by `validate_file --kind position` (the SubagentStop hook and skill step 3, which also reject unknown and non-verified ids now) and `anonymize <run_id> 0` refuses it as a backstop. A persona may therefore not cite an id it only saw in the report or in `positions_anon.json`; it argues against such a position with its own claims or an evidence gap. `agents.research_target` reads the `mini_research` table, so `agents` imports `db` and the guard and usage hooks open SQLite on research-agent writes (a missing database or table falls back to the stage-2 file); a later refactor could pass the task in instead. These interpretations stay in this note rather than `docs/DECISIONS.md` (smaller deviations belong in the plan notes); promote any that IF-408 confirms.
    - **Prompts.** The persona prompt adds what note 25 asked for: never name your role, a computation must name a claim id and show its numbers, never target your own `position_id`, cite only ids from your evidence file. The judge prompt has two modes: `interim` after each round writes `round<N>/interim_scores.json` projecting **every** rubric dimension (note 26), `verdict` writes `verdict.json`; it reads only the anonymized rounds, the ledger, the score sheet and its own interim files. The lens blocks stay one paragraph each.
    - **Re-prompts.** `python -m ideaforge.debate reprompt <run_id> <N>` lists the rejected roles not yet sent back and records them in `round<N>/.reprompted` before the launch, so a resumed session never re-prompts twice (a crash between record and launch loses that re-prompt, which fails safe). A role still rejected after its re-prompt stays out of the round (`anonymize` leaves it out) and keeps its last accepted position. Round 0 has no Python re-prompt record: the SubagentStop hook re-prompts an invalid position once and the skill re-launches a persona once; a persona that still wrote nothing is left out, one whose file is still invalid stops the debate (anonymize refuses an invalid file, note 25, and the orchestrator never repairs files).
    - **Mini-research.** A task is a `mini_research` row (new table: `n`, `round`, `role`, `anon_id`, `dimension`, `question`, `claim_start`, `status` running / done / failed, `attempts`). `python -m ideaforge.mini_research open <run_id> <N>` opens the round's accepted request (one per round after validation; idempotent per round; refuses while another task is running) and prints the brief. The per-debate cap is enforced twice: `debate_validate.py` rejects every request once earlier rounds used `max_mini_research_tasks` (so the persona is told), and `open` refuses with exit 3 as a backstop. A failed task still counts. The file is `02_research/mini-<n>-<dim>.md`; while the task runs, the guard lets the dimension's research agent write only that file, the SubagentStop hook validates it (`agents.research_target`), and the usage hook counts its searches under `<agent>.mini-<n>` with a fresh budget (markers `BUDGET_EXCEEDED_<agent>.mini-<n>` and `VALIDATION_FAILED_<agent>.mini-<n>`, so a task never clears or fakes a stage-2 marker); its usage rows still go to the agent, so the usage report attributes them to `research:<dim>`. `finish` validates it like a stage-2 file (dimension taken from the name) plus "no claim id the run already has" (the brief gives a first id, the dimension's highest number rounded up to the next hundred + 1, e.g. `pricing-101`); valid → done, invalid → one re-launch (exit 2), invalid twice → failed (exit 3), the file renamed to `.md.failed` so `verify_claims.py` never reads it.
    - **Verification.** `verify_claims.py <run_id> --only <stem>` (`verify.verify_run(only=…)`) parses and verifies only that file and appends its claims to the existing `verified.json`, replacing only claims that file contributed before; every other claim keeps its state and `retrieved_at`. Re-running the whole verifier mid-debate would re-stamp every `retrieved_at` and could flip claims the score sheet and the report already rest on. A full `verify_claims.py` run also orders `mini-*` files after the stage-2 files, so a reused id never displaces a stage-2 claim.
    - **"Usable in round 2"**: a round-N request is researched between rounds N and N + 1; its verified claims are new to every persona (never cited before), so `agree` on them passes the novelty rule in round N + 1. A claim id cited before verification is rejected as unknown.
    - **Resume.** `python -m ideaforge.debate status <run_id>` names the next step (`debate.STEPS`) from files and rows: `report` (none yet), `verify` (a done task's candidate claim ids not all in `verified.json`: `--only` writes the task's `03_claims/<stem>.json` before it fetches, so that file proves nothing), `evidence` (an evidence file built from another ledger), `positions` / `anonymize` round 0, then per round `rebuttals` (roles without a file and without a rejection), `validate`, `reprompt`, `mini-research` (`open` repeats a running task's last validator errors for the re-launch), `anonymize`, `interim` (until the file validates or `python -m ideaforge.debate skip-interim <run_id> <N>` set it aside as `interim_scores.skipped` after the judge failed twice; (b) then does not hold for that round and later rounds compare with the latest valid interim or the score sheet), then it runs the convergence check: `judge` or the next round's `rebuttals`; `render` once `verdict.json` exists, `done` once `revised_plan.md` does. The debate is not a `runs.STAGES` stage: its state lives in the `debates`, `debate_turns` and `mini_research` rows and the debate files.
    - Open points for IF-408: whether the mini-research brief's question is answerable within one research budget; whether personas use `mini_research_claims` well; whether the judge's interim projections stay stable enough for (b); whether all personas should see every mini-research claim or only the requester's lens; a re-prompted persona with a lower P-id that adds a mini-research request takes the round's slot from an already accepted requester, which re-validation then rejects without a re-prompt of its own (the note-25 slot rule; `status` would list it under `reprompt` on a resume).

28. **Eval checker and eval skill (IF-502).** Interpretations made unattended, to be tuned in IF-501:
    - **Golden file** (`schemas.GoldenIdea`, `tests/golden/<golden_id>.yaml`, the id is the file stem): `idea` (one line, no quote, backtick, `$`, `#` or backslash, so `/eval` passes it to `new_run.py '<idea text>'` verbatim; `golden.load` also rejects an idea whose command the strict guard would refuse, through `guard.command_denial`, split out of `check_bash` for this), `expected_verdicts` (the "verdict range" as a non-empty set of `GO` / `PIVOT` / `NO_GO` / `INSUFFICIENT_DATA`, not an ordered min–max, because `INSUFFICIENT_DATA` has no place on the scale), `must_find` (2–3 `MustFindFact`: `fact` in words, `source_urls` ≥ 1 where a person found it, optional `keywords`, optional `dimensions`) and optional `notes`. Two golden files with the same idea text are an error. It is YAML, so it is validated by `ideaforge.golden.load`, not `validate_file` (whose kinds are JSON).
    - **Must-find match** (`golden.finds`): only `verified` claims of the run's `03_claims/verified.json` count (`conflict` does not), limited to `dimensions` when given. A claim finds the fact when its source URL equals one of `source_urls` (ignoring scheme, `www.`, host case, a trailing slash and the fragment; path and query kept) **or** its statement or quote contains every keyword (case-insensitive substrings, so a Finnish stem matches its inflections). The OR lets the pipeline find the fact on another page than the person did; a URL match alone may be a different claim from the same page. IF-501 should judge whether keywords need alternatives (Finnish and English wording).
    - **"Cited in the score sheet"** is each dimension's `supporting_claim_ids` plus `unit_economics.input_claim_ids`; an id missing from the ledger counts as unverified. `score_run.py` already drops such citations, so this check guards against a regression.
    - **Which run**: the newest run (`runs.created_at`, then run id) whose idea text is the golden idea, so `eval_check.py` needs no mapping file and can be re-run later; a revised version with the same text replaces its parent, and so does a later non-eval `/validate` of the same text. "A finished run" is read as one with `04_scores.json` and `03_claims/verified.json`: the checks need nothing else, so a run whose `report` stage failed is still checked (`--plan` shows it as `incomplete`). `--plan` prints `<golden_id> <state> <run_id> <idea text>` (`none` / `incomplete` / `complete`, the latter meaning every stage complete) and never the expected verdicts or facts, and the skill forbids reading `tests/golden/`, so the orchestrator never sees the answer key.
    - **The skill** runs stages 0–5 per idea, never the debate: `/validate` in "just run it" mode (no clarifying questions, no plan approval, the spec from the idea text and `config/founder.yaml`), then `/synthesize`, one idea at a time. A `complete` run is reused and an `incomplete` one resumed, so a crashed eval continues where it stopped; `--fresh` (not in the ticket) starts new runs, for a re-evaluation after a model or prompt change. An idea whose pipeline stops is noted and the eval moves on; it then fails the check.
    - **Output**: a Markdown table on stdout (golden idea, run, verdict with total, expected, verdict ok, must-find found/total, unverified cited, PASS/FAIL), then the failures and `passed: X of N`. Exit 0 all pass (or no golden files), 2 one fails, 1 an invalid golden file. Every golden file is validated even past `--limit`. The table is not written to a file: the guard allows writes only under `runs/` and `cache/`, and IF-501 records it under its ticket by hand.
29. **Back-test as-of, preset wiring and usage-limit docs (IF-503, absorbs IF-506 and IF-508).** Interpretations made unattended, to be tuned in IF-216 / IF-501:
    - **The back-test header goes in the brief, not the agent file.** `.claude/agents/` is rendered once from `config/`, so an `{% if as_of %}` template hook (IF-204) could never see a run's date. Instead `scripts/research_brief.py <run_id> <dim>` (`ideaforge.brief`) prints the run-specific brief lines, the preset's budget line and, for a run with `as_of`, the `Back-test as of YYYY-MM-DD` header, and the validate skill (stage 2) and the debate skill (mini-research) paste them verbatim. `prompts/research_base.md` tells agents that the brief's budget line replaces their own numbers and what the header means. IF-204 needs no as-of hook any more.
    - **The budget line comes from a script** rather than the orchestrator reading `config/budget.yaml`, so the numbers in the brief are the ones the usage hook counts and the research validator applies (killcause: `killcause_scout`, whose omitted `max_output_words` is the schema default 1200, which is what the validator uses too). The brief reads the run's `runs` row (`budget_preset`, `as_of`), like `debate.debate_budget`; the hook keeps reading `meta.json`; `new_run.py` writes both.
    - **`after_as_of`** (`verify.after_as_of`): a claim whose `published_date` is **after** `as_of` (same day passes) is `unverified` with the flag and its source is **not fetched**; a warning line names it and the summary counts it. A claim with no `published_date` is **not** rejected: its date is unknown, not later, and rejecting it would drop most pages, which rarely show a date. The header asks for dated sources instead. IF-216 / a real back-test should judge whether undated claims need a flag of their own. Like the fetch flags, `after_as_of` is recomputed on every verification and an agent-set one is dropped. The report's sources table lists it with the fetch flags.
    - **`/validate --as-of YYYY-MM-DD`** is taken out of the arguments like `--preset` and passed to `new_run.py` (also with `--from`, where it overrides the parent's date).
    - **README**: the preset table and the downgrade order are checked against `config/` by `tests/test_config.py`. `/status --diff` (IF-504) did not exist yet, so the README said to compare `04_scores.json` by hand (superseded by note 30). "`/eval` on 3 golden ideas" is written as `/eval --limit 3`.
30. **Review scores and status diff (IF-504, absorbs IF-505).** Interpretations made unattended, to be tuned once real reports are reviewed:
    - **Sections** are the ten `## ` sections of `templates/report.md.j2` (`review.SECTIONS`: `verdict`, `score_table`, `kill_triggers`, `unit_economics`, `dimensions`, `funding`, `location`, `risks`, `sources`, `usage`); `tests/test_status.py` fails if the template's headings and the list drift apart. The debate's `revised_plan.md` is not reviewed: the ticket says report sections.
    - **Asking**: `scripts/status.py <run_id> --review` with no entries lists the sections and stored scores; the skill asks the user in one chat message (not `AskUserQuestion`, which offers at most four options) and stores the answer with `--review section=score[:note] …`. Partial reviews are allowed; scoring a section again replaces its score and note (`reviews` keeps one row per run and section, as §5 defines it). The whole entry list is validated before anything is stored. A run needs its DB row and `05_report.md`.
    - **Version** of a reviewed run = the `meta.json` `config_commit` (7 characters, `+dirty` when `config_dirty`) plus the `models` roles; versions are labelled A, B, … in order of their first reviewed run (`runs.created_at`). A run without a valid `meta.json` (made before IF-308) goes into an `unknown` version. The trend shows the mean score per section per version, then each reviewed run. Reviews never feed a score or the verdict.
    - **`--diff <a> <b>`** compares the two `04_scores.json` files (B relative to A): final score per dimension (`capped` when `cap_reason` is set, `n/a` without a final score, `-` when the dimension is missing), the weighted total, the verdict and the kill triggers fired (in both / only in A / only in B), plus the config commit and the model roles that changed. It works for any two runs, not only versions of one idea, so it also covers "the same idea under different models". The README's by-hand fallback from note 29 is gone.
31. **PxWeb client (IF-201).** Interpretations made unattended, to be tuned in IF-204 / IF-216:
    - **Table path** is `<database>/<path>` (`statfin/vaerak/11ra.px`, `luke/maa/muuyri/0100_muuyri.px`; database case-insensitive, `.px` optional), so one CLI covers both databases.
    - **Filters** match a variable by code or text and a value by code, text, or text without its code prefix (case-insensitive), because StatFin's variable codes are versioned (`alue_23_20260101`, IF-200) and agents know names, not codes. The plan's example `Alue=Rääkkylä,Pohjois-Karjala` is ambiguous in `11ra` (`MK12`, `TA29`, `FI1DC`): the first value in table order is used (the maakunta, `MK12`) and the others are named on stderr; the CSV carries the code. `*` selects every value. A variable without a filter selects **every** value (`"filter": "all"`), not the API's elimination total, so the cell count is the full product (the 5 105 916 of `11re` in IF-200).
    - **Cell limit**: counted from the metadata before any data request; over 100 000 → exit 2 and a message with every variable's size and a `--filter` example for the largest unfiltered one.
    - **Output**: `get` prints CSV (a label and a `_code` column per variable, `value`, `status`; `..` cells have an empty value and their status) on stdout and the request (method, URL, query body, retrieval time, `(from cache)`) on stderr, so the CSV stays machine-readable; `--json` puts everything in one object. A cache hit reports the original retrieval time.
    - **Search**: `search <keyword>` uses each database's own search (`GET <base>?query=`); `--path <db>/<folder>/` filters that folder's listing instead (every word must appear in the id or title). IF-200 recorded no search response, so the API search is tested for its request URLs and, on hits labelled synthetic in `tests/test_pxweb.py` that follow the documented PxWeb v1 shape (`id`, `path`, `title`, `published`), for the `<db>/<path>/<id>` table paths in text and `--json` output; the folder listing is tested on the recording. A response that is not a list, or a hit without a string `id`, exits 1 with a message naming the URL (and pointing to `--path`) instead of a traceback. If the live response shape differs, fix it in IF-204 and record one.
    - **Added**: `meta <table_path>` lists a table's variables and value codes, so an agent can build a filter without guessing. Cache: `cache/pxweb/<sha256>.json` keyed by method, URL and body, 24 h from retrieval; an unreadable entry (not JSON, not an object, no `data`, no time-zone-aware `retrieved_at`) is fetched again and overwritten. The `Api` dataclass holds the v1 URL scheme and query body; a newer API is another `DATABASES` entry.

32. **PRH and Eurostat clients (IF-202, absorbs IF-203).** Interpretations made unattended, to be tuned in IF-204 / IF-216:
    - **Acceptance deviation**: the ticket's `search --industry 55201 --municipality Rääkkylä` is tested as `--industry 55`, the request IF-200 recorded, because PRH industry codes are TOL 2025 (`TOIMI4`) since 2026-01-01 and 55201 finds nothing. A search with a code longer than two digits that finds nothing prints a note on stderr suggesting the 2-digit prefix (tested on a synthetic empty answer). Whether the research brief should say "TOL 2025 code or prefix" is for IF-204.
    - **PRH output**: `count: <totalResults>` then CSV rows (`name`, `business_id`, `registration_date`, `status`, `end_date`, `industry_code`, `industry`, `company_form`) on stdout, the request on stderr, like `pxweb get`; `--json` puts everything in one object. The name is the current company name (type `1`, no end date); `status` is the description of the trade-register entry matching `tradeRegisterStatus` (`Rekisterissä` / `Lakannut` in the recordings), descriptions in `--lang` (fi default). Street addresses are left out. The count is the whole match and the rows one page (`--page`; a note says when more exist). The registration-date (`registrationDateStart` / `registrationDateEnd`) and `page` parameters follow the YTJ v3 documentation; IF-200 recorded neither, so they are tested for their URLs only.
    - **Eurostat**: filters are Eurostat dimension and category codes (`--filter unit=NR`, a dimension repeated per code in the URL), `--geo FI` is `geo=FI`, `--since` / `--until` map to `sinceTimePeriod` / `untilTimePeriod`, and `lang` (EN default) is always sent, so the CLI rebuilds the recorded URL exactly. The frame is `pxweb.jsonstat_frame` (a missing cell of the sparse `value` object is empty); a body without a dataset (Eurostat's `error` object) exits 1 with its label and the URL.
    - **Shared code**: the transport, the 24 h cache (one `cache/<tool>/` directory each) and the request lines moved from `pxweb.py` into `src/ideaforge/fi/http.py`, so the three clients cache and print the same way; `pxweb`'s behaviour and tests are unchanged.

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
- **Answers (2026-10-24):**
  1. Geography ladder: Rääkkylä → North Karelia → Finland → online/EU. Keski-Karjala is dropped: the founder does not live in a Keski-Karjala municipality. The same ladder is in `config/finland.yaml`, the `IdeaSpec.geography` default, `prompts/research_base.md` and the validate skill; `tests/test_config.py` keeps them equal.
  2. Founder constraints: 20 h/week, 5 000 EUR capital, goal `side_income`; skills are software engineering (web/backend, 8 years), building and running websites, booking systems and online shops, automation and data analysis, English (fluent), Finnish (native), driving licence B, customer service / sales experience and marketing (social media, SEO). `confirmed: true`.
  3. Verdict thresholds and weights: the user has no preference yet, so the defaults stay (GO ≥ 3.5, PIVOT ≥ 2.5, at most 2 insufficient dimensions; weights as in `config/rubric.yaml`). Revisit after the Phase 2 run (F-013).
  4. Report language: either is fine for the user, so the recommendation is taken: the report in English (`config/report.yaml: language: en`, the existing templates) and the starttiraha business-plan draft in Finnish (`business_plan_language: fi`, used by IF-307).

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
- **Recorded (2026-10-24):** nine responses, 93 kB, reviewed by the user. StatFin: the `vaerak` listing, `11ra` metadata, the `11ra` population of Rääkkylä (`KU707`) and Pohjois-Karjala (`MK12`) 2021–2025, and `11re` metadata (5 105 916 cells unfiltered). StatFin's variable codes carry a classification version (`alue_23_20260101`, `timeperiod_y`, `contentscode`), not `Alue` / `Vuosi`. Luke: `maa/muuyri/0100_muuyri.px` metadata and a query with `..` cells in `status`. PRH: TOL 55 in Rääkkylä (1 company) and a name search (the first 10 of 54 kept, said in the meta file). PRH industry codes are TOL 2025 (`typeCodeSet` `TOIMI4`) since 2026-01-01, so the TOL 2008 example 55201 finds nothing; a 2-digit prefix matches. Eurostat: `tour_occ_ninat` for `geo=FI`, 2019 onwards.

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
- **Built (2026-10-24):** `src/ideaforge/fi/pxweb.py` (`search`, `meta`, `get`) and `tests/test_pxweb.py`; choices in plan note 31.

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
- **Built (2026-10-24):** `src/ideaforge/fi/prh.py`, `src/ideaforge/fi/eurostat.py`, the shared `src/ideaforge/fi/http.py`, `tests/test_prh.py` and `tests/test_eurostat.py`; choices and the 55201 → 55 deviation in plan note 32.

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
- **Notes (manual crash test, checked in IF-216):** during stage 2 of a real `/validate` run, after at least one research agent has finished and while others are still writing, kill the Claude Code session (close the terminal). Start a new session and re-run the same run id. Expected: `run_stage.py <run_id> --resume` prints a `reset:` line for each dimension left `running` (`running -> done` where the agent's file validates, `running -> pending` otherwise) and then lists only the unfinished dimensions; the orchestrator launches agents for those alone, and the finished dimensions keep their files and `attempts`. Plan note 18 has the rules.

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
  - ~~an `{% if as_of %}` back-test header hook for IF-503~~: not needed, IF-503 puts the header in the research brief (plan note 29)
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
