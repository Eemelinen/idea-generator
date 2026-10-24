# Progress log

Repository-local session log. Read it at clock-in, update it at clock-out (AGENTS.md).

## Current Verified State

- Repository root: `idea-generator/` (this directory; contains `AGENTS.md`, `feature_list.json`, `init.sh`, `harness.config.json`).
- Standard startup path: `./init.sh` (`FAST=1` skips the baseline). It needs node 24, pnpm and uv on `PATH`.
- Standard verification path: L1 `pnpm check` (Prettier, `pnpm harness:check`, `uv run pytest`). There is no L2/L3 (D-001). Per feature: `pnpm harness:verify F-NNN`.
- Phase 1 skeleton (F-001), the harness (F-000), the full research validator (F-006), claim verification (F-007), the usage report + basic `/status` (F-009), the stage state machine (F-010), the `/validate` + `/research` skills for stages 0–3 (F-011), scoring (F-014), unit economics (F-015), synthesis + `score_run.py` (F-016), the report (F-017), versioning (F-019), debate anonymization + rebuttal validation (F-021), debate convergence + conformity flag + revised plan (F-022) and the `/debate` skill with prompts and mini-research (F-023) are `passing`. Otherwise nothing in Phase 2+ is built: `fi/` clients are stubs, and there is no API re-query or conflict detection, starttiraha draft or eval code yet; no debate has run live (F-024).
- F-006: `validate_file --kind research` (and the SubagentStop hook) rejects figures without a following `>` quote and cited URLs missing from the agent's `.seen_urls.txt` (API URLs in `ideaforge.fi.API_URL_PREFIXES` exempt), and warns about factual sentences without `[src: …]` (hook mode also writes `VALIDATION_WARNINGS_<agent>`). The rule choices are TICKETS.md plan note 15; IF-216 (F-013) tunes them on real files.
- F-007: `uv run python scripts/verify_claims.py <run_id>` (`ideaforge.verify`, lxml + trafilatura, XHTML declarations stripped) parses the candidate claims of `02_research/*.md` into `03_claims/<dim>.json`, fetches each source once (robots.txt, 10 s timeout, UA, truststore; text cached in `cache/<sha256(url)>.txt`, `sources` rows), sets `verified` at normalized `partial_ratio ≥ 90`, flags `unfetchable` / `robots_disallowed`, types allow-listed URLs `official` (not `api`), and writes `03_claims/verified.json` + `claims` rows. Rules chosen unattended: TICKETS.md plan note 16.
- F-009: `uv run python scripts/usage_report.py <run_id>` (`ideaforge.usage.summarize` / `render_summary`) prints calls, searches, fetches and `~tokens` per stage and per agent from `usage.jsonl`, plus `BUDGET_EXCEEDED_*` markers. A research agent's calls are attributed to its own `research:<dim>`; other calls go to the latest-started `stages` window holding the timestamp, else `(no stage)`. `/status` (`.claude/skills/status/SKILL.md` → `scripts/status.py [run_id] [--limit N]`, `ideaforge.status`) lists recent runs with a folded stage line; with a run id: stages, claims per dimension × verification state, kill flags fired by verified claims (overrides marked), `VALIDATION_FAILED_*` / `VALIDATION_WARNINGS_*` / `BUDGET_EXCEEDED_*` markers and per-stage usage. Rules: TICKETS.md plan note 17.
- F-010: `runs.py` holds the stage state machine (`begin`, `finish`, `mark_insufficient`, `resume`, `next_stages`, `is_complete`, `STAGE_OUTPUTS`, `STAGE_GROUPS`); `scripts/run_stage.py <run_id> <stage> --begin|--finish|--insufficient-data` and `<run_id> --resume|--next` expose it to the skills. A stage is complete only when `insufficient_data`, or `done` with its output file(s) present and valid; `begin` needs every earlier group complete; `--finish` on an invalid output → `failed` (exit 1); `--resume` turns crashed `running` stages into `done` (valid file) or `pending`. Rules: TICKETS.md plan note 18; the manual crash test is in the IF-214 notes and runs in F-013.
- F-011: `.claude/skills/validate/SKILL.md` (`/validate [--preset p] <idea>` new run; `/validate <run_id>` resume) runs stage 0 (`new_run.py`, ≤ 5 `AskUserQuestion`s, `config/founder.yaml` defaults → `00_spec.json`), stage 1 (`01_plan.json`, 11 dimensions incl. killcause, plan approval unless "just run it"), stage 2 (all research agents in one message, brief with the run's preset budget, `--finish` exit 1 → one re-launch with the error, two launches in total by `attempts`, then `--insufficient-data`; markers checked) and stage 3 (`verify_claims.py`), each wrapped in `run_stage.py --begin/--finish` with `validate_file` before `--finish` and `usage_report.py` after. `/research <run_id>` resumes and follows the validate skill's Stage 1–3 and End sections. `run_stage.py --resume` also writes `runs/.active`; the research word limit follows the run's preset. `tests/test_skills.py` is the static consistency test. Rules: TICKETS.md plan note 19; the live run is F-013.
- F-014: `ideaforge.scoring.score(proposed, claims, overrides, *, unit_economics, computed_triggers, rubric)` → `ScoreSheet`. A dimension's evidence is the verified claims its score cites (unknown / unverified / conflict ids dropped, `dropped_citations` lists them); the rubric's `min_sources` (distinct registrable domains), `has_official_source` (`verify.is_official` on the URL) and `has_numeric` (`numeric_field` derives price / cost / unit_count from unit + statement + dimension) must all pass, else `final_score = min(proposed, 2)`, `cap_reason`, `insufficient_data`. Unscored rubric dimensions get 0, capped. Kill triggers fire from every verified claim's flags plus computed ones, minus overrides. Verdict: trigger → NO_GO, then > `max_insufficient_dimensions` → INSUFFICIENT_DATA, then `go`/`pivot`. Not wired into a script yet (IF-304). Rules: TICKETS.md plan note 20.
- F-015: `ideaforge.economics.unit_economics(claims, assignments=None, *, vat_registered=True)` → `UnitEconomics` (now also `purchases_per_customer_month`, `monthly_profit_eur`, `vat_registered`, `vat_rate_pct`, `notes`); `computed_triggers(ue)` → `["negative_contribution_margin"]` for a margin < 0, for `scoring.score`. Roles: price, variable cost (+ commission %), fixed costs/month, CAC, volume/month, purchases per customer/month, VAT rate. With `assignments` (role → verified claim ids) exactly those claims (cost roles summed; a dropped one makes the role missing); without, one pessimistic pick per role after period and VAT conversion (`volume`/`variable_cost` only from `unit_economics` claims). Margin, break-even, monthly profit, payback (CAC / (margin × frequency)), a 3×3 ±30 % price × volume table; absent inputs are listed in `missing_inputs`. VAT: net if registered, else price as quoted and costs grossed up; an unstated basis gets the pessimistic reading; conversion needs a verified VAT-rate claim. A season unit (a season stem in the first three words after `/` or `per`: `kesäkausi`, `seasons`, `off-season`, `high season`; not `kuukausi`, `kesäkuu`, `vuorokausi`) is dropped for every role with a note, and automatic mode also skips claims whose statement says `per <season>`; an automatic per-unit cost needs no `/` word or a per-unit-sold word (`EUR/h`, `EUR/event`, `EUR/2 weeks` are noted and not used); a variable cost or CAC per period alone (`EUR/month`) is dropped; a counted period (`/2 weeks`) gets no monthly conversion. Plan note 21 lists what stays unguarded (plain-`EUR` lump sums in automatic mode). Not wired into a script yet (IF-304). Rules: TICKETS.md plan note 21.
- F-016: `/synthesize <run_id>` (`.claude/skills/synthesize/SKILL.md`) runs stages `synthesize` and `score`. `scripts/synthesis_input.py <run_id>` writes `04_synthesis_input.json` (spec + verified/conflict claims + rubric + economics roles; `ideaforge.synthesis.synthesis_input`), the generated `synthesizer` subagent (role `synthesizer`, tools Read/Write, guard: writes only `04_scores_proposed.json` + `04_risks.json`, SubagentStop validates both) reads only that file and proposes scores, `unit_economics_inputs` (role → claim ids, new `ProposedScores` field) and risks. `scripts/score_run.py <run_id>` (`synthesis.score_run`) drops unknown/unverified citations, zeroes a proposal with no verified citation, runs `economics.unit_economics` on the assignments with `IdeaSpec.vat_registered` (new, default true) and `scoring.score`, writes `04_scores.json` and the `scores` rows (`db.replace_scores`). `negative_contribution_margin` fires only from assigned inputs whose `variable_cost`/`cac` units pass `economics.per_unit`. Rules: TICKETS.md plan note 22.
- F-017: `uv run python scripts/render_report.py <run_id>` (`ideaforge.report`, template `src/ideaforge/templates/report.md.j2`) writes the immutable `05_report.md` from `00_spec.json`, `verified.json`, `04_scores.json`, `04_risks.json`, the research files' `## Gaps` and `usage.jsonl`: verdict + why, score table with "**capped at 2**: insufficient data (…)" labels, kill triggers, unit economics + sensitivity, dimension sections, Finland funding fit (`report.PROGRAMMES`: backed only by verified `financing` claims on an official domain, else "unverified – see gaps"; `config/finland.yaml` is never read), Rääkkylä notes, risk register, sources, usage. `db.add_report` inserts the `reports` row and the file is hard-linked into place in one transaction; an existing file or row → exit 1, and the guard denies every tool write to `runs/<id>/05_report.md`. `/synthesize` runs it as stage 5c. Rules: TICKETS.md plan note 23.
- F-019: `ideaforge.meta` writes `meta.json` (HEAD `git_commit`, `config_commit` = last commit touching `config/` / `prompts/` / `agent_templates/`, `config_dirty`, `models` roles, `claude_code_version` from `claude --version` or `IDEAFORGE_CLAUDE_CODE_VERSION`, `idea_id`, `version`, `created_at`, `updated_at` refreshed by every `runs` stage transition; every probe fails soft to null). `new_run.py --from <parent> [<idea text>]` (`runs.child_run`) creates the next free `<parent base>-vN` with its own directory, the `idea_versions.parent` link and the parent's idea text, preset and `as_of` by default, and never touches the parent; `/validate --from <run_id>` runs it and reads the parent's spec / report / revised plan read-only. Rules: TICKETS.md plan note 24.
- F-021: `uv run python -m ideaforge.debate anonymize <run_id> <round> [--seed N]` maps the personas to P1…P5 with one seeded mapping per debate (seed in the `debates` row and `debate/.mapping.json`), writes `debate/round<N>/positions_anon.json` without `role`, `mini_research.requested_by` or self-labels (`as the investor`, `As investor,`, `from an investor's perspective`, `sijoittajana`, `kirjanpitäjänä` → `[persona]`), records round-0 positions in `debate_turns`, and leaves `REJECTED_<role>` roles out of later rounds. `scripts/debate_validate.py <run_id> <round>` (`debate.validate_round`) rejects `agree`/`modify` or a changed proposal without never-cited `new_claim_ids` or a computation naming a claim id, a `disagree` without a claim id or evidence gap, unknown / non-verified claim ids, own or unknown targets, and every mini-research request after the lowest P-id's in a round; reasons go to `round<N>/REJECTED_<role>`, turns to `debate_turns`; exit 0 / 2 (re-prompt) / 1. The guard denies subagent writes to `.mapping.json`, `positions_anon.json` and `REJECTED_*`. Rules: TICKETS.md plan note 25.
- F-022: `uv run python scripts/debate_converged.py <run_id> <round>` (`debate.check_convergence`) exits 0 to stop when (a) round N brought no new claim id into the debate, no moved proposal and no mini-research request, (b) the judge's `debate/round<N>/interim_scores.json` (`InterimScores`) moved < `convergence_score_delta` on every dimension against the previous interim (or `04_scores.json`), or (c) N ≥ the run preset's `max_rounds`; 2 = another round, 1 = bad input or a round not validated in its current form. `debate.conformity_flag` / `run_conformity_flag`: ≥ 4 of 5 personas (the author counts) back one change while no new claim id entered. `render_report.py <run_id> --debate` (`ideaforge.revised_plan`, template `revised_plan.md.j2`) refuses accepted changes citing unknown or unverified ids, writes the immutable `debate/revised_plan.md` (diff block vs `05_report.md`, projected total computed in Python, accepted / rejected changes, assumption register, ≥ 5 experiments by info value per euro), persists `assumptions`, `experiments`, the `reports` row and the finished `debates` row in one transaction, then writes the computed flag into `verdict.json`. Guard: no tool writes `revised_plan.md`; only the judge writes `interim_scores.json` / `verdict.json`. Rules: TICKETS.md plan note 26.
- F-023: `/debate <run_id>` (`.claude/skills/debate/SKILL.md`) runs round 0 (the 5 personas in one message), `debate anonymize`, rounds 1..N (rebuttals → `debate_validate.py` → `python -m ideaforge.debate reprompt` + one re-launch → mini-research → `anonymize N` → the judge's interim projection → `debate_converged.py`), the judge's verdict and `render_report.py --debate`, then offers `/validate --from`; `python -m ideaforge.debate status <run_id>` names the next step (`debate.STEPS`) so it resumes per round, and `debate skip-interim` sets aside a projection the judge failed twice. `debate evidence` writes `debate/evidence/<role>.json` (`agents.PERSONA_EVIDENCE` verified claims, every verified mini-research claim, the persona's own P-id); persona prompts read only the report and that file, the judge prompt has interim (every rubric dimension) and verdict modes. Mini-research: `python -m ideaforge.mini_research open|finish` (new `mini_research` table; at most `max_mini_research_tasks` per debate, refused by `debate_validate.py` and by `open`), the dimension's research agent writes `02_research/mini-<n>-<dim>.md` (guard, SubagentStop target, budget and validation markers `<agent>.mini-<n>`), `verify_claims.py <run_id> --only mini-<n>-<dim>` adds only its claims to the ledger. Rules: TICKETS.md plan note 27.
- Queue: 29 features (`pnpm harness:feature list`), 14 open: 7 unattended and 7 human-only (15 passing).
  - Ready now, unattended: F-025 (eval checker) and F-028 (review scores + status diff; now unblocked by F-019). F-018 (starttiraha draft) also needs F-002 (human). F-008 needs F-004/F-005 (behind F-003); F-012 and F-013 (the live Phase 2 run) also wait on F-003-era work.
  - Ready now, human-only: F-002 (§13 decisions), F-003 (record API fixtures). Both gate later work.
- Last verified: branch `feat/F-023` on 2026-10-24, `pnpm harness:verify F-023` green (`pnpm check` = Prettier, `harness:check` and 878 pytest tests passed, 1 Windows-only skip; the focused `tests/test_gen_agents.py` + `tests/test_debate.py` + `tests/test_skills.py` step passed) on commit 7474fc0 (first run on fe1c7c1). Evidence for the other passing features is in `feature_list.json`.
- Session 002 (interactive: shared harness): the copied harness is replaced by `@eemelinen/harness` (devDependency, tag `v0.2.0`; the CLI behind every `pnpm harness:*`, new `pnpm harness:doctor`, also run by `./init.sh`) and the plugin `harness@eemelinen-harness` (skills `/harness:clock-in`, `/harness:verify-feature`, `/harness:clock-out`, agent `harness:evaluator`, hooks); the pipeline hooks are unchanged. Project rules live in `harness.config.json` and `docs/harness/generator-notes.md`. The evaluator is no longer generated (`agents.AGENTS["harness:evaluator"]`, 17 generated agents). D-007.
- Current blocker: none in the repo.
  - Host: `uv`, `claude` and `gh` are installed but not on the Git Bash `PATH` (`~/.local/bin`, `C:\Program Files\GitHub CLI`). The pipeline hooks fail open without `uv`. `gh` is already logged in (account Eemelinen, keyring).
  - Loop merging: `main` is protected with the required check `L1 (pnpm check)` (no review requirement) and `harness.config.json` has `merge: "auto"`, so `pnpm harness:loop` opens a PR per feature and GitHub squash-merges it once CI passes.

## Next Steps

1. Human, once: add `%USERPROFILE%\.local\bin` and `C:\Program Files\GitHub CLI` to the user `Path`, then open a new terminal and restart VS Code. Run `claude` in the repository once and accept the trust dialog and the harness plugin marketplace.
2. GitHub is set up for unattended runs: `main` is pushed, auto-merge and squash merging are allowed, `main` requires `L1 (pnpm check)`, and the loop merges with `merge: "auto"`.
3. Human-only features, interactively: F-002 (answer the §13 questions) and F-003 (record the API fixtures with network). They unblock F-004/F-005/F-008, the Phase 2 run and the starttiraha draft.
4. Unattended: `pnpm harness:loop` continues with the next ready feature (`pnpm harness:feature next`). F-017 open points for IF-309 (plan note 23): on a real run, check whether the regex matching of funding programmes misses Finnish inflections or over-matches (`\bely\b`), and whether the dimension sections need the research prose rather than only the justification and cited claims. The F-015 carry-overs are closed by F-016 (plan note 22): no NO_GO from the automatic pick, and an assigned `variable_cost`/`cac` must pass `economics.per_unit` before its margin may fire a trigger. Still open for IF-309: the live `/synthesize` run (does the synthesizer fill `unit_economics_inputs` sensibly; is the "uncited proposal → 0" rule too harsh), and whether reads by the synthesizer need a mechanical guard. Inflected periods (`EUR/kuukaudelta`, `EUR/vuodelta`, `EUR/heinäkuu`) and `kuu` season compounds (`kesäkuukausi`) still pass as per unit. The skills of F-011 are only checked statically; their first real use is the F-013 live run (sauna idea; re-run skips completed dimensions; the IF-214 crash test), which should also judge the plan note 19 choices (plan approval question, idea-text quoting, two launches by `attempts`). The usage hook still writes `stage: null`. F-021 open points for IF-407 (plan note 25): the persona prompt should tell personas never to name their role and that a computation must name a claim id; decide what happens after a second rejection (the role is then left out of `positions_anon.json`); tool reads of `debate/.mapping.json` are not guarded. F-022's and F-021's IF-407 points are closed by F-023 (plan note 27). For the live debate F-024 / IF-408 (human, needs F-020): judge whether a pending mini-research request should block (a), whether the author should count towards conformity, and the note-27 open points (mini-research question size, use of `mini_research_claims`, interim stability, all personas seeing every mini-research claim, the re-prompted requester edge case). F-019 open points for IF-309 (plan note 24): `/validate --from` has never run live, and the parent stays read-only only through the skill's instructions (no guard rule, so an unfinished parent can still be resumed). Compare the evaluator's verdict with your own and add a row to the rubric's tuning log for each of the first 3–5 runs.

## Session Log

### Session 018 — 2026-10-24 (driver-run: F-023 debate skill, prompts and mini-research)

- Goal: F-023 / IF-407 (absorbs IF-401, IF-404): the `/debate` skill, final persona and judge prompts, evidence subsets, mini-research.
- Completed (fe1c7c1, 7474fc0):
  - `.claude/skills/debate/SKILL.md`; `src/ideaforge/mini_research.py`; `debate.py` (`write_evidence`, `stale_evidence`, `reprompt`, `progress` / `STEPS`, `skip_interim`, the per-debate cap in `validate_round`, CLI `evidence` / `reprompt` / `skip-interim` / `status`); `db` table `mini_research`; `agents.research_target` used by the guard, the SubagentStop hook and the usage counters; `validate_file` reads `mini-<n>-<dim>.md` (dimension from the name, no reused claim ids); `verify.verify_run(only=…)` + `verify_claims.py --only`; mini files ordered after stage-2 files.
  - Prompts: `debate_persona.md`, `debate_judge.md` (interim + verdict modes), lens blocks, `_debate_base` evidence line, a mini-research section in `research_base.md`; agents regenerated.
  - Tests: evidence subsets, the 4th request refused (validation and `open`), economy preset, round-1 claims usable in round 2, finish / re-launch / set aside, claim numbering, `--only`, re-prompts, the full `status` walk, interrupted verify, skipped interim; guard, validate_file, usage, gen_agents and skill wiring tests.
  - Docs: README, IMPLEMENTATION_PLAN §1 / §6 stage 7, TICKETS.md plan note 27.
- Choices (no one to ask), plan note 27. Notable: every persona gets every verified mini-research claim; the persona's own P-id is in its evidence file; re-prompts are recorded in `round<N>/.reprompted`; mini-research verifies only its file so the ledger under the score sheet never moves; the debate is not a `runs.STAGES` stage.
- Evaluator (fresh context) on fe1c7c1: Revise (correctness, reliability, handoff 1). An interrupted `--only` verify was taken as done on resume, and an invalid interim projection blocked convergence and `status` for good. Fixed in 7474fc0 with tests, along with the lost re-launch errors after a resume and mini-research validation markers clashing with stage-2 ones. The re-prompted-requester edge case is an open point in note 27. Not re-reviewed: the driver's own evaluator runs next.
- Verification run: `pnpm harness:verify F-023` on fe1c7c1 (873 passed, 1 skipped) and again on 7474fc0 (878 passed, 1 skipped), both steps green.
- Next best step: F-025 (eval checker) or F-028 (review scores + status diff); the live debate is F-024 (human).

### Session 017 — 2026-10-24 (driver-run: F-022 convergence, conformity flag, verdict and revised plan)

- Goal: F-022 / IF-405 (absorbs IF-406): `scripts/debate_converged.py`, `debate.conformity_flag()`, the verdict check and `render_report.py --debate`.
- Completed:
  - `src/ideaforge/debate.py` (`accepted_turns`, `summarize_rounds`, `backers`, `conformity_flag`, `run_conformity_flag`, `check_convergence`, `finalize_verdict`, `write_verdict`), `scripts/debate_converged.py`, `src/ideaforge/revised_plan.py` + `templates/revised_plan.md.j2`, `render_report.py --debate`, `db.add_revised_plan`; schemas: `InterimScores` (kind `interim_scores`), `Verdict.experiments` ≥ 5 with a non-blank `success_threshold`; the judge's hook target is its latest interim file until `verdict.json` exists; guard rules for `revised_plan.md` and the judge-only files.
  - Tests: `tests/test_debate_converged.py` (each exit condition and its negatives, delta boundary, preset `max_rounds`, rejected turns, bad input), conformity cases in `tests/test_debate.py`, `tests/test_revised_plan.py` (snapshot `tests/golden/revised_plan.synthetic.md`, ≥ 5 experiments with cost / days / threshold, ordering, diff, persisted tables, flag recompute, refusals, immutability, failed-write rollback); synthetic `tests/fixtures/debate/verdict.synthetic.json`; `tests/fixtures/verdict.json` now has 5 experiments; guard, schema and validate_file tests.
  - Docs: README, IMPLEMENTATION_PLAN §6 stage 7 steps 4–5, TICKETS.md plan note 26.
- Choices (no one to ask), plan note 26. Notable: the interim projection is a new judge file `round<N>/interim_scores.json` (the plan names no file); the author of a change counts towards "4 of 5"; a mini-research request blocks (a); accepted changes must cite _verified_ ids; the revised plan is immutable like the report; ≥ 5 experiments is enforced in the schema.
- Evaluator (fresh context) on the working tree: Revise (reliability 1): `verdict.json` was overwritten before the plan was committed, so a failed render lost the judge's disagreement. Fixed: the file is written after the commit (`write_verdict`), with a regression test; also a projection above the cap is marked, a round without persona files is an error, only the judge may write `interim_scores.json` / `verdict.json`, and the remaining points are open points in note 26 (the judge must project every dimension for (b)). Re-review: Revise only for two comments still describing the old write order; fixed (comment-only), now Accept-ready.
- Verification run: `pnpm harness:verify F-022` on ef2b5ce and again on ae7fc04 → `pnpm check` (832 passed, 1 skipped) and the focused step (138 passed).
- Next best step: F-023 (IF-407 debate skill: the judge prompt must ask for `interim_scores.json` covering every rubric dimension after each round), F-025 or F-028.

### Session 016 — 2026-10-24 (driver-run: F-021 attempt 2, review fixes)

- Goal: address the driver evaluator's Revise on attempt 1 (correctness 1): self-labels still leaking the persona.
- Completed (4b40e95, ef3ad0a):
  - `debate.py`: the Finnish essive follows vowel harmony (`n[aä]`), so `kirjanpitäjänä` is redacted; `minä / mä (olen / oon) <role>` also takes the essive (`minä olen kirjanpitäjänä` → `[persona]`); an article-less `as <role>` is redacted before a comma or at a sentence start (`As investor, …`), while "such as customer reviews" and "as operator costs" stay.
  - `tests/test_debate.py::SELF_LABELS` has a case for every form plan note 25 lists (38 new cases, 2 new keep-cases); PEP 8 blank lines and lines over 120 characters in the touched files fixed.
  - Docs: TICKETS.md plan note 25 lists exactly the redacted forms (incl. `<role>n näkökulmasta / silmin`) and points at `SELF_LABELS`.
- Choices (no one to ask): article-less `as <role>` only before a comma or sentence-initially, not everywhere, because "such as customer …" is ordinary plan prose (a sentence starting "As operator costs rise" is redacted too, fails safe); added the colloquial `oon` since it was a one-word change.
- Evaluator (fresh context) on 4b40e95: Revise (correctness 1, maintainability 1): note 25 claimed a test per form but `as my / our / this / your <role>` and some Finnish verb forms had none, the sentence-start rule allowed only one space after the punctuation (`thin.  As operator`, `(As investor` leaked), and Finnish `sijoittajan näkökulmasta` was not covered. Fixed in ef3ad0a: the sentence-start rule keeps any punctuation / bracket / quote / bullet prefix with any whitespace (a `keep` group, since Python lookbehinds are fixed width), `<role>n näkökulmasta / silmin` is redacted, note 25 names the fail-safe over-redaction, and `SELF_LABELS` covers every listed article, perspective noun and Finnish role and verb form. Not re-reviewed: the driver's own evaluator runs next.
- Verification run: `pnpm harness:verify F-021` on 4b40e95 → `pnpm check` (748 passed, 1 skipped) and the focused step (99 passed); re-run on ef3ad0a → `pnpm check` (767 passed, 1 skipped) and the focused step (118 passed).
- Next best step: F-022 (IF-405 convergence, conformity flag, verdict and revised plan), F-025 or F-028.

### Session 015 — 2026-10-23 (driver-run: F-021 debate anonymization and rebuttal validation)

- Goal: F-021 / IF-402 (absorbs IF-403): `debate.py anonymize` and `scripts/debate_validate.py`.
- Completed:
  - `src/ideaforge/debate.py` (`mapping_for`, `ensure_mapping`, `load_mapping`, `scrub`, `anonymize`, `record_turn`, `history`, `check_rebuttal`, `validate_round`, CLI `anonymize`), `scripts/debate_validate.py`; guard rule for the files debate.py owns.
  - Tests: `tests/test_debate.py` (deterministic mapping and file bytes for a seed, seed storage and conflicts, no role names or seed in the output, self-label redaction, rebuttal rounds, round-0 turns, bad inputs, CLI) and `tests/test_debate_validate.py` (accepted and rejected stance changes, computations, changed proposals, disagree rules, unknown / unverified / conflict / pending ids, the second mini-research request, targets, role/round mismatch, missing / invalid files, re-prompt attempts, history across rounds, exit codes); synthetic `debate_run` fixture in conftest; `test_guard.py` +1.
  - Docs: README, IMPLEMENTATION_PLAN §1 / §6 stage 7, TICKETS.md plan note 25.
- Choices (no one to ask), plan note 25. Notable: one mapping per debate (stable target ids); "cited before" = any earlier non-rejected turn (ticket wording over the plan's "previous turn"); a computation must name a claim id and a number; "1 mini-research per round" is across personas, lowest P-id keeps it; self-labels are redacted but plain role words stay (they are ordinary plan words); a missing file is a rejection.
- Evaluator (fresh context) on cf11fc0: Revise (correctness 1; the other five categories 2). The self-label redaction missed "As the investor, …", "From an investor's perspective", "Customer here:" and Finnish essives, and the leak test only ran on text without role words. Fixed in 12dc951: wider patterns (plain plan words still kept), a test with role-bearing text in every free-text field, a `.mapping.json` that does not match its seed is refused, missing roles are no longer also "excluded", plan §6 stage 7 matches the code. The minor points (computation regex false positives, the mini-research slot of a rejected requester, unchecked round-0 ids, the stance-persistence rule, …) are recorded in plan note 25 for IF-407 / IF-408. Not re-reviewed: the driver's own evaluator runs next.
- Verification run: `pnpm harness:verify F-021` on cf11fc0 → `pnpm check` (708 passed, 1 skipped) and the focused step (59 passed); re-run on 12dc951 after the fixes → `pnpm check` (725 passed, 1 skipped) and the focused step (76 passed).
- Next best step: F-022 (IF-405 convergence, conformity flag, verdict and revised plan; now unblocked), F-025 or F-028.

### Session 014 — 2026-10-23 (driver-run: F-019 versioning)

- Goal: F-019 / IF-308: `meta.json` provenance and `/validate --from <run_id>` → `<run_id>-v2` with the v1 run and report unchanged.
- Completed:
  - `src/ideaforge/meta.py` (`build`, `write`, `load`, `touch`, git / Claude Code probes); `RunMeta` gained `idea_id`, `version`, `updated_at`, `config_commit`, `config_dirty` and a version ↔ parent validator.
  - `runs.child_run` (next free `-vN`; a v1 slug ending in `-v2` is not stripped) and `meta.touch` on every stage transition; `scripts/new_run.py` uses both, takes the idea text from the parent when omitted, and refuses an existing run directory.
  - `/validate` skill: a "New version" branch (`new_run.py --from <parent_run_id> ['<idea text>']`, parent read-only) and `idea_id` / `version` from `meta.json` in Stage 0; `/synthesize` End points at `/validate --from`.
  - Tests: `tests/test_versioning.py` (meta fields against the real repo's git, soft-failing probes, CLI parsing, `updated_at`, the schema rule, v2 directory and parent link, revised text, `-v3` / `-v4` numbering, unknown parents, v1 files + db rows + report byte-identical after v2 is scored and rendered); `tests/test_skills.py` checks the `--from` branch.
  - Docs: README, IMPLEMENTATION_PLAN §1 / §6 stage 6, TICKETS.md plan note 24.
- Choices (no one to ask), plan note 24. Notable: "commit of prompts/config" = HEAD + last commit touching `config/` / `prompts/` / `agent_templates/` + a dirty flag; the models snapshot is the roles map; a new version copies nothing from its parent and re-runs every stage; no new guard rule (an unfinished parent must stay resumable).
- Evaluator (fresh context) on 1888d4d: Revise (reliability 1). Fixed:
  - `meta.write` uses a unique temp file, and `touch` catches write errors so a `--finish` never crashes after the stage is committed.
  - An autouse conftest fixture keeps every test off the real `claude --version`.
  - A new version inherits the parent's preset and `as_of`; pre-IF-308 child metas (parent, no version) stay valid.
  - The skill accepts `--from` anywhere in the arguments and explains exit 2.
  - The `config_commit` test asserts `PROVENANCE_PATHS`.
  - Not re-reviewed: the driver's own evaluator runs next.
- Verification run: `pnpm harness:verify F-019` on 1888d4d → `pnpm check` (643 passed, 1 skipped) and `uv run pytest tests/test_versioning.py` (20 passed); re-run on 9e54803 after the fixes → `pnpm check` (646 passed, 1 skipped) and the focused step (23 passed).
- Next best step: F-021, F-025 or F-028 (IF-504 `/status` diff between versions, now that versions exist).

### Session 013 — 2026-10-23 (driver-run: F-017 report rendering)

- Goal: F-017 / IF-305 (absorbs IF-306): `scripts/render_report.py` → the immutable `05_report.md` with the Finland funding fit and Rääkkylä sections.
- Completed:
  - `ideaforge.report` + `src/ideaforge/templates/report.md.j2`, `scripts/render_report.py`, `db.get_report` / `db.add_report`, `synthesis.load_scores`.
  - `/synthesize` gained Stage 5c (`run_stage.py report --begin`, `render_report.py`, `--finish`, usage report); `tests/test_skills.py` checks the wrapping.
  - Tests: `tests/test_report.py` (snapshot `tests/golden/report.synthetic.md`, regenerate with `IDEAFORGE_UPDATE_GOLDEN=1`; synthetic fixtures in `tests/fixtures/report/`): section order, the capped-at-2 label for a dimension with 2 of 3 sources, funding backed vs. unverified vs. non-official, no `finland.yaml` value in a gap-only funding section, Rääkkylä notes, triggers fired / overridden / computed, overwrite refused (file or row), failed write leaves neither, missing inputs, unknown runs.
  - Docs: README, IMPLEMENTATION_PLAN §1 / §6 stage 5, TICKETS.md plan note 23.
- Choices (no one to ask), plan note 23. Notable:
  - Only `financing` claims are matched to funding programmes, by regex on statement / title / quote or by the programme's own domain.
  - Only the verified ones on an official domain back an item.
  - Eligibility is not judged against the founder's goal.
  - The starttiraha draft stays in IF-307.
  - A `reports` row without a file still refuses a re-render.
- Evaluator (fresh context) on 3fff495: Revise (correctness 1; the other five categories 2). Funding matching ran over every dimension, so an off-topic official claim could back a programme: an ELY permit on elinvoimakeskus.fi, a "market leader" on ytj.fi, or "starttiraha is taxable" on vero.fi. Fixed in 453bece:
  - Only financing claims count; `\bely\b` became `ELY-keskus` / `ELY centre`, and `leader` must not be followed by `ship`.
  - Negative tests cover these off-topic claims.
  - The minor findings are also fixed: the guard denies tool writes to `05_report.md`, cited claims are re-checked as verified, the "computed" trigger label is used only for the negative margin, multi-line quotes are flattened, and the plan note 23 crash wording is corrected.
  - Not re-reviewed: the driver's own evaluator runs next.
- Verification run: `pnpm harness:verify F-017` on 453bece → `pnpm check` (622 passed, 1 skipped) and `uv run pytest tests/test_report.py` (31 passed); first run on 3fff495 also green.
- Next best step: F-019 (IF-308 versioning: a new run `-v2` instead of overwriting a report), F-021 or F-025.

### Session 012 — 2026-10-23 (driver-run: F-016 synthesis and score run)

- Goal: F-016 / IF-304 (absorbs IF-301): the synthesizer, `/synthesize` and `scripts/score_run.py`.
- Completed:
  - `ideaforge.synthesis` (`synthesis_input`, `write_synthesis_input`, `require_evidence`, `unchecked_per_unit`, `score_run`, `summary`), `scripts/synthesis_input.py`, `scripts/score_run.py`, `db.replace_scores`.
  - Generated `synthesizer` subagent (`agent_templates/synthesizer.md.j2` + `prompts/synthesizer.md`; 18 generated agents), guard write rule, SubagentStop validation of both files.
  - Schemas: `ProposedScores.unit_economics_inputs` (one id per non-additive role, no dimension twice), `IdeaSpec.vat_registered`.
  - `.claude/skills/synthesize/SKILL.md`; `/validate` End points at it and sets `vat_registered` at intake.
  - Tests: `tests/test_score_run.py` (synthetic fixtures in `tests/fixtures/score_run/`), plus additions to `test_skills.py`, `test_guard.py` and `test_validate_file.py`.
  - Docs: README, IMPLEMENTATION_PLAN §1/§5/§6 stage 5, TICKETS.md plan note 22.
- Choices (no one to ask): plan note 22. Notable:
  - The synthesizer is a subagent, not the orchestrator.
  - Its reads are restricted by the prompt only.
  - An uncited proposal is set to 0.
  - Only assigned, per-unit-checked inputs may fire `negative_contribution_margin`.
  - VAT status lives in the spec.
  - A broken `04_risks.json` is only a warning for scoring.
- Evaluator (fresh context) on the uncommitted tree: Revise (verification 1, no evidence yet; maintainability 1). The main finding: an assigned `EUR/h` or `EUR/kuukaudelta` `variable_cost` could force NO_GO. Fixed: `unchecked_per_unit` suppresses the trigger with a note, and a parametrized test covers it. Also fixed: plan §6 wording, the stale test name, the risks file as a warning, and the skill's `--finish` after a failed validation. Re-review: Accept (all categories 2). Two minor points remain for IF-309: no `cac` case in the per-unit test, and a non-per-unit CAC assignment also blocks a correct margin trigger (fails safe).
- Verification run: `pnpm harness:verify F-016` on 5955d0c → `pnpm check` (585 passed, 1 skipped) and the focused step (68 passed).
- Next best step: F-017 (IF-305 report rendering) on top of `04_scores.json`, or F-021.

### Session 011 — 2026-10-23 (driver-run: F-015 attempt 2, evaluator revisions)

- Goal: address the attempt-1 evaluator verdict (Revise, correctness 1): compound and plural season units slipped past `seasonal()` and produced a false `negative_contribution_margin` trigger.
- Completed:
  - `economics.seasonal` matches season stems inside any `/` or `per` word (`_SEASON_STEMS`; known periods and `kuukau…` month forms excluded), so `EUR/kesäkausi`, `EUR/talvikausi`, `EUR/seasons`, `EUR/sesonkiaika`, `EUR/off-season` are never an automatic role (noted) and are dropped with a note when assigned to any role, `variable_cost` included. The `/` word regex now allows hyphens.
  - New `economics.per_unit`: an automatic `variable_cost` needs a unit with no `/` word or only per-unit-sold words (`_PER_UNIT`); other costs from `unit_economics` (`EUR/h`, `EUR/event`) get a "neither per unit sold nor per period; not used" note.
  - A count before the period word (`EUR/2 weeks`) is kept with it, so it is no known period: an assigned fixed cost / volume / frequency with it is dropped with a note instead of read as per month.
  - `tests/test_economics.py` +30 cases (105): compound / plural / inflected season units, month forms that are not seasons, automatic and assigned `EUR/kesäkausi` and `EUR/seasons` with no trigger and the notes present, `per_unit`, unclear automatic cost units, counted periods.
  - Docs: TICKETS.md plan note 21 states the season, per-unit and counted-period rules as implemented.
- Evaluator (fresh context) on 1d34ca5: Revise (correctness 1). Every requested item was done, but multi-word season units (`EUR/high season`, `EUR per the season`) still passed when assigned to `variable_cost`, and `vuorokausi` (a day) was read as a season. Fixed in f1db150:
  - `seasonal(text, words=3)` scans the first words after each `/` or `per`. Words holding `kuu` or `vuorokau` never count (`kesäkuu` is June), and `vuorokausi` / `vuorokaudessa` / `vuorokaudelta` are day periods.
  - The automatic pick also checks the statement with a two-word window (`per summer season`).
  - `variable_cost` and `cac` (`PER_UNIT_ROLES`) drop a unit that names a period but no unit sold (`EUR/month`), in both modes.
  - +11 tests (116).
- Choices (no one to ask):
  - A counted period is dropped, not converted (simplest, never guesses).
  - An assigned `variable_cost` with a non-season, non-period `/` word (`EUR/h`) is still trusted, because the assignment is explicit.
  - Assigned statements are not season-checked.
  - The three-word window also reads `EUR per evening in summer` as seasonal (fails safe).
  - Automatic prices are unchanged (price per hour vs. cost per night stays the known crudeness).
  - A plain-`EUR` lump sum without `per <season>` still reads as a per-unit cost in automatic mode. Plan note 21 hands this to IF-304: no NO_GO from the automatic pick.
- Verification run: `pnpm harness:verify F-015` on commit f1db150 → `pnpm check` (539 passed, 1 skipped) and `uv run pytest tests/test_economics.py` (116 passed).
- Next best step: F-016 (IF-304 synthesis + `score_run.py`), using F-014 and F-015; use synthesizer assignments, and do not let a trigger from the automatic pick force NO_GO (plan note 21, "What remains unguarded").

### Session 010 — 2026-10-23 (driver-run: F-015 unit economics)

- Goal: F-015 / IF-303: `src/ideaforge/economics.py`.
- Completed:
  - `ideaforge.economics`: `vat_basis`, `period`, `vat_treated`, `auto_role`, `inputs_from_claims` (assigned or automatic), `compute`, `unit_economics`, `computed_triggers`; `UnitEconomics` gained five fields (defaults, so `ScoreSheet` files stay valid).
  - `tests/test_economics.py` (75, synthetic claims): known inputs, the sensitivity table, a negative margin through `scoring.score` to NO_GO, zero margin, commission, missing inputs, VAT registered / unregistered / unstated / no rate, unit parsing, automatic and assigned mapping, evaluator regressions.
  - Docs: TICKETS.md plan note 21.
- Choices (no one to ask): plan note 21. Notable: two mapping modes (assignments vs. a pessimistic automatic pick); seasonal units (`/season`, `/kausi`) are dropped for every role, not spread; an unstated VAT basis gets the reading that hurts the business; VAT registration is a caller argument; CAC is not in the monthly profit; VAT on the commission is not modelled.
- Evaluator (fresh context), three passes: Revise (correctness 1) → fixed picks compared after period/VAT conversion, a partial cost sum makes the role missing, unknown periods dropped, unstated price basis read as incl. VAT, subscription vs. assigned frequency, `per a night`, two-basis texts, the schema docstring, missing tests; Revise again → an automatic `EUR/season` cost became a per-unit variable cost (false negative margin), now dropped for every role with a note.
- Verification run: `pnpm harness:verify F-015` → `pnpm check` (498 passed, 1 skipped) and `uv run pytest tests/test_economics.py` (75 passed), re-run after the last fix.
- Next best step: F-016 (IF-304 synthesis + `score_run.py`), using F-014 and F-015.

### Session 009 — 2026-10-23 (driver-run: F-014 scoring)

- Goal: F-014 / IF-302: `src/ideaforge/scoring.py`.
- Completed:
  - `ideaforge.scoring`: evidence rules `min_sources`, `has_official_source`, `has_numeric` (driven by `rubric.yaml: evidence_rule` through `check_rule`; `check_rubric` validates the whole rubric up front), `domain`, `numeric_field`, `verified_citations`, `score_dimension` (caps), `fired_kill_triggers`, `weighted_total`, `verdict`, `score`, `dropped_citations`.
  - `tests/test_scoring.py` (90, synthetic claims): table-driven rules, caps, kill triggers and verdict boundaries; thresholds from a modified rubric; the Phase 3 acceptance case (a `permit_impossible` claim flips GO to NO_GO, an override restores it); unscored dimensions; a citation from another dimension.
  - Docs: TICKETS.md plan note 20.
- Choices (no one to ask): plan note 20. Notable: evidence = cited verified claims only (from any dimension); a failed rule labels the dimension `insufficient_data` even at ≤ 2; `has_numeric` fields come from a unit/keyword heuristic because claims have no field tag; a fired kill trigger outranks INSUFFICIENT_DATA.
- Evaluator (fresh context): Revise only for missing evidence and PROGRESS.md; code categories at 2. Applied its minor points: `euro`/`euroa` currency units, Finnish partitive count units, per-area units are not counts, a cross-dimension citation test, the keyword crudeness and the citation-trust caveat recorded in note 20.
- Verification run: `pnpm harness:verify F-014` → `pnpm check` and the focused coverage step (100 %).
- Next best step: F-015 (economics), then IF-304 (synthesizer + `score_run.py`) on top of both.

### Session 008 — 2026-10-23 (driver-run: F-011 validate and research skills, stages 0–3)

- Goal: F-011 / IF-206 (absorbs IF-207, IF-215): the `/validate` and `/research` skills for stages 0–3 and a static consistency test.
- Completed:
  - `.claude/skills/validate/SKILL.md`: new run or resume, Stage 0 intake, Stage 1 plan, Stage 2 parallel research (agent table, one-message launch, re-launch once, `--insufficient-data`, marker checks), Stage 3 verification, End (`status.py`). Every command is a literal `uv run …` the strict main-session guard allows.
  - `.claude/skills/research/SKILL.md`: `--resume` (activates the run), refuses a run without intake, then the validate skill's Stage 1–3 and End sections.
  - Supporting fixes: `run_stage.py --resume` writes `runs/.active` and prints `active: <run_id>` (the hooks only find a run through the marker); `validate_file.validate_research` takes the word limit from the run's preset (it used the default preset, so a `deep` brief would fail validation).
  - Tests: `tests/test_skills.py` (25: frontmatter, research agents and the Stage 2 table vs. `agents.AGENTS`, cited scripts/modules/paths exist, cited commands pass the strict guard and `allowed-tools`, flags and `--kind` values exist, real stage names, each stage wrapped in `--begin` … `--finish` + `validate_file` + `usage_report.py`, marker and retry text, `/research` reuses existing sections); `test_runs.py` resume sets the active run; `test_validate_file.py` word limit per preset.
  - Docs: README usage, TICKETS.md plan note 19.
- Choices (no one to ask): plan note 19. Notable: `/validate` ends after stage 3 for now; plan approval is one `AskUserQuestion` unless "just run it"; a dimension gets two launches in total by `attempts`; the idea text goes to `new_run.py` single-quoted without quote, backtick, `$`, `#` and backslash characters.
- Evaluator (fresh context) before verification: Revise (correctness, verification, maintainability and handoff at 1). Fixed: preset word limit in the validator, a `find() < find()` assertion that could not fail, a possible third launch, `ResearchPlan` field names and killcause `evidence_needed`, going to End when `--next` lists `synthesize`, idea-text quoting, the plan-approval reading, flag/kind checks in the test, PROGRESS.md. Mutation check: renaming a flag or a kind, or deleting the Stage 0 `validate_file` step, fails `test_skills.py`.
- Verification run: `pnpm harness:verify F-011` → `pnpm check` (333 passed, 1 skipped) and `uv run pytest tests/test_skills.py` (25 passed).
- Next best step: F-014 (scoring). F-013 is the first real run of these skills.

### Session 007 — 2026-10-23 (driver-run: F-010 stage state machine and resume)

- Goal: F-010 / IF-214 (absorbs the Python side of IF-507): `runs.py` state machine and `scripts/run_stage.py`.
- Completed:
  - `runs.py`: `STAGE_OUTPUTS` (stage → output file(s) + validator kind), `STAGE_GROUPS`, `StageError`, `statuses`, `output_problems`, `is_complete`, `next_stages`, `begin`, `finish`, `mark_insufficient`, `resume`. Validation reuses `validate_file.validate_path` (imported lazily; `validate_file` imports `runs`).
  - `scripts/run_stage.py <run_id> <stage> --begin|--finish|--insufficient-data`, `<run_id> --resume|--next` (exit 1 with `error:` on a refused transition or an invalid output).
  - `tests/test_runs.py` (16 tests, synthetic research files): transitions, earlier-group gating, done needs a valid file (also after the fact), synthesize needs both files, blank report, `insufficient_data`, crash reset, the IF-507 mid-stage-2 resume, `STAGE_OUTPUTS` agrees with `validate_file.STAGE_FILES`, CLI.
  - Docs: README usage line, §1 layout (`run_stage.py`), TICKETS.md plan note 18 and the IF-214 manual crash-test notes; `db.stage_done` docstring points at `runs.is_complete`.
- Choices (no one to ask): plan note 18. The notable ones: resume is an explicit `--resume`, not part of `--next` (research stages are legitimately running in parallel); a crashed `running` stage with a valid file becomes `done` instead of being re-run; `05_report.md` only has to be non-blank until IF-303 gives it a check; `--insufficient-data` is research-only.
- Evaluator (fresh context): Revise, with maintainability at 1 (an unused `COMPLETE` constant). Fixed in a second commit: `is_complete` uses `COMPLETE`; `output_problems` / `is_complete` raise `StageError` for a malformed run id; `_check_run` returns nothing; a test ties `STAGE_OUTPUTS` to `validate_file.STAGE_FILES`; plan note 18 says a reset does not cascade to later stages.
- Verification run: `pnpm harness:verify F-010` → `pnpm check` (304 passed, 1 skipped) and `uv run pytest tests/test_runs.py` (16 passed).
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
