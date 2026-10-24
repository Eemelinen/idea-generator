---
name: validate
description: Validate a business idea with the Ideaforge pipeline, stages 0–3. Creates a run (or, with --from <run_id>, the next version of an earlier run), writes the idea spec (at most 5 clarifying questions), the research plan, launches the 11 research subagents in parallel and verifies their claims; given an existing run id it resumes that run and skips completed stages and dimensions. Use when the user types /validate with an idea or a run id.
argument-hint: '[--preset economy|standard|deep] [--as-of YYYY-MM-DD] <idea text> | <run_id> | --from <run_id> [<revised idea text>]'
allowed-tools: Read Write Agent AskUserQuestion Bash(uv run python scripts/new_run.py*) Bash(uv run python scripts/run_stage.py*) Bash(uv run python scripts/research_brief.py*) Bash(uv run python scripts/extract_claims.py*) Bash(uv run python scripts/verify_claims.py*) Bash(uv run python scripts/usage_report.py*) Bash(uv run python scripts/status.py*) Bash(uv run python -m ideaforge.validate_file*) Bash(ls*) Bash(cat*)
---

You are the orchestrator of an Ideaforge run. You write only the two planning files
(`00_spec.json`, `01_plan.json`); research is done by the `research-*` subagents and
verification by `scripts/verify_claims.py`. Never research in this context, never write claim
files, never compute scores. All rules of CLAUDE.md → Pipeline sessions apply.

In every command below, replace `<run_id>` with the literal run id (the guard refuses command
substitution and `>` redirection, so never use `$(…)` or shell variables). `<dim>` is a
dimension id from the table in Stage 2.

## Start: new run or resume

Arguments: `$ARGUMENTS`

- **Resume** when the arguments are a single run id (`YYYYMMDD-HHMMSS-slug`, optionally
  `-vN`) and `runs/<run_id>/` exists (`ls runs/`):
  1. `uv run python scripts/run_stage.py <run_id> --resume` makes it the active run, repairs
     stages a crash left `running` (`reset:` lines) and lists the stages to run now.
  2. Show the `reset:` lines to the user, then continue with the first stage whose group
     `--next` lists. Skip every stage it does not list: those are complete. When it lists
     `synthesize` or nothing, stages 0–3 are complete: go straight to **End**.
- **New version** when the arguments contain `--from <parent_run_id>` (anywhere): the run is the
  parent's next idea version, a new run `<parent_run_id>-vN` (the parent's `-vN` suffix is
  replaced) linked through `idea_versions.parent`. The parent run stays immutable: never write,
  re-run or resume anything under `runs/<parent_run_id>/`.
  1. `uv run python scripts/new_run.py --from <parent_run_id>` (add `--preset <name>` and
     `--as-of <date>` if given), or `uv run python scripts/new_run.py --from <parent_run_id> '<idea text>'` when
     the user gave a revised idea text after the run id (same quoting rules as a new run).
     Without a text the new version keeps the parent's idea text. It prints only the new run
     id and makes it the active run. The new version keeps the parent's budget preset and
     `--as-of` date unless `--preset` or `--as-of` is given. Exit 2 prints why (unknown
     parent, empty idea text, unknown preset, a bad date): tell the user and stop.
  2. Read-only context for Stage 0: `runs/<parent_run_id>/00_spec.json`, and when they exist
     `runs/<parent_run_id>/05_report.md` and `runs/<parent_run_id>/debate/revised_plan.md`.
     Ask only about what the revision changes; reuse the parent's answers otherwise.
  3. Continue with Stage 0 for the new run id. Every stage runs again: no file is copied from
     the parent, because its claims and scores belong to the parent's version.
- **New run** otherwise. Take `--preset <name>` and `--as-of <date>` out of the arguments if
  present; the rest is the idea text. If the text is empty, ask the user for the idea and stop.
  `--preset` picks the budget preset in `config/budget.yaml` (economy, standard or deep; the
  default is `default_preset`). `--as-of YYYY-MM-DD` makes the run a back-test: research as of
  that date, with every brief carrying the header from `research_brief.py` and
  `verify_claims.py` rejecting claims published after it (`after_as_of`).
  1. `uv run python scripts/new_run.py '<idea text>'` (add `--preset <name>` and
     `--as-of <date>` if given). Put
     the idea in single quotes and leave out what the guard refuses inside a command: single
     and double quotes, backticks, dollar signs, `#` and backslashes (replace them with spaces).
     It prints only the run id; use it verbatim from here on. It also makes the run active.
  2. Continue with Stage 0.

"Just run it": if the user says so (in the arguments or a reply), ask no clarifying questions,
use the defaults, and do not ask for approval of the plan.

Before each stage, `uv run python scripts/run_stage.py <run_id> --next` tells you whether it
still has to run. A `--begin` that exits 1 prints why (an earlier stage is incomplete); fix
that first, never work around it.

## Stage 0 — Intake

1. `uv run python scripts/run_stage.py <run_id> intake --begin`
2. Read `runs/<run_id>/idea.md`, `runs/<run_id>/meta.json` and `config/founder.yaml` (for a
   new version also the parent's files listed under Start).
3. Ask **at most 5** clarifying questions with `AskUserQuestion`, and only where the answer
   changes the research direction: geography (local service vs. online), the founder's goal
   (`side_income` | `full_time` | `starttiraha`), capital, hours per week, the paying customer.
   Ask nothing the idea text already answers. If `config/founder.yaml` has `confirmed: false`,
   its values are placeholders: say so when you use them.
4. Write `runs/<run_id>/00_spec.json` (schema `IdeaSpec` in `src/ideaforge/schemas.py`):
   - `idea_id`: `idea_id` from `runs/<run_id>/meta.json`.
   - `title`, `one_liner`, `customer`, `problem`, `solution`, `revenue_model` from the idea
     and the answers. Unknown is written as unknown; never invent facts about the market.
   - `geography`: the default ladder `["Rääkkylä", "North Karelia", "Finland", "online/EU"]`
     unless an answer changes it.
   - `founder_constraints`: `hours_per_week`, `capital_eur`, `skills`, `goal` from
     `config/founder.yaml`, overridden by the user's answers.
   - `clarifications`: one `{question, answer}` per question asked (max 5).
   - `kill_trigger_overrides`: `[]` unless the user explicitly accepts a kill-trigger risk.
   - `vat_registered`: `true` (prices and costs net of VAT) unless the user says the business
     stays under the VAT registration threshold and will not register.
   - `version`: `version` from `runs/<run_id>/meta.json` (1, or the parent's + 1 for a run
     created with `--from`).
5. `uv run python -m ideaforge.validate_file --kind spec runs/<run_id>/00_spec.json`; on
   exit 1 fix the file and validate again.
6. `uv run python scripts/run_stage.py <run_id> intake --finish`
7. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## Stage 1 — Research plan

1. `uv run python scripts/run_stage.py <run_id> plan --begin`
2. Read `config/rubric.yaml`, `config/domains.yaml`, `prompts/killcause.md` and
   `runs/<run_id>/00_spec.json`.
3. Write `runs/<run_id>/01_plan.json` (schema `ResearchPlan` in `src/ideaforge/schemas.py`):
   `{"run_id": "<run_id>", "dimensions": [...]}` with one entry per research dimension, all 11
   of them (the 10 rubric dimensions plus `killcause`). Each entry has the keys `dimension`
   (the id from the Stage 2 table), `questions`, `search_strategy`, `preferred_domains` and
   `evidence_needed`:
   - `questions`: the rubric's `research_questions` adapted to this idea, plus 1–2
     Finland/Rääkkylä-specific questions (local demand, North Karelia competitors, Finnish
     rules or grants that apply to this idea).
   - `search_strategy`: where to look first for this idea (official and API sources, then
     industry and news, then forums).
   - `preferred_domains`: the rubric's `preferred_domains` plus the dimension's list under
     `preferred` in `config/domains.yaml`; regulation and financing also get the `official` list.
   - `evidence_needed`: the rubric's `min_evidence_for_3`.
   - `killcause` (always present): questions on dead competitors, free substitutes,
     regulatory blockers and "why hasn't this been done here" (the rubric's killcause
     questions and `prompts/killcause.md`). The rubric gives it no `min_evidence_for_3`, so
     `evidence_needed` is "sourced reasons the idea fails, each with a verbatim quote; a
     missing source is a gap, not a kill trigger".
4. `uv run python -m ideaforge.validate_file --kind plan runs/<run_id>/01_plan.json`; on
   exit 1 fix the file and validate again.
5. `uv run python scripts/run_stage.py <run_id> plan --finish`
6. Show a short plan summary (one line per dimension: its idea-specific questions) and ask
   with one `AskUserQuestion` whether to proceed or change the plan (it is not one of the 5
   clarifying questions). After "just run it", show the summary and proceed without asking.
   If the user asks for changes, edit `01_plan.json`, validate it again and repeat this step.
7. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## Stage 2 — Parallel research

| Dimension (`<dim>`) | Subagent                  | Stage                     | Output                                  |
| ------------------- | ------------------------- | ------------------------- | --------------------------------------- |
| `customer`          | `research-customer`       | `research:customer`       | `runs/<run_id>/02_research/customer.md` |
| `market`            | `research-market`         | `research:market`         | `…/02_research/market.md`               |
| `competition`       | `research-competition`    | `research:competition`    | `…/02_research/competition.md`          |
| `pricing`           | `research-pricing`        | `research:pricing`        | `…/02_research/pricing.md`              |
| `unit_economics`    | `research-unit-economics` | `research:unit_economics` | `…/02_research/unit_economics.md`       |
| `gtm`               | `research-gtm`            | `research:gtm`            | `…/02_research/gtm.md`                  |
| `regulation`        | `research-regulation`     | `research:regulation`     | `…/02_research/regulation.md`           |
| `financing`         | `research-financing`      | `research:financing`      | `…/02_research/financing.md`            |
| `location`          | `research-location`       | `research:location`       | `…/02_research/location.md`             |
| `founder_risk`      | `research-founder-risk`   | `research:founder_risk`   | `…/02_research/founder_risk.md`         |
| `killcause`         | `research-killcause`      | `research:killcause`      | `…/02_research/killcause.md`            |

1. `uv run python scripts/run_stage.py <run_id> --next` lists the research stages to run.
   **Skip every dimension it does not list**: its stage is `done` (the file exists and
   validates) or `insufficient_data`. `uv run python scripts/status.py <run_id>` shows each
   stage's `attempts`. A dimension gets **two launches in total**: a listed dimension that is
   `failed` with 2 or more attempts already had its re-launch, so mark it now with
   `uv run python scripts/run_stage.py <run_id> research:<dim> --insufficient-data` and do
   not launch it.
2. For each dimension to launch: `uv run python scripts/run_stage.py <run_id> research:<dim> --begin`
   (chain them with `&&` in one command).
3. For each dimension to launch, `uv run python scripts/research_brief.py <run_id> <dim>`
   prints its run-specific brief lines: the budget line of the run's preset (`--preset`; the
   `research_subagent` entry of `config/budget.yaml`, or `killcause_scout` for killcause) and,
   in a back-test run (`--as-of`), the header that forbids sources published after that date.
   The agent files carry the default preset's numbers and no date, so these lines are what
   sets the agent's budget. Then launch **all** the dimensions to research **in one message**
   (one `Agent` call each, `subagent_type` from the table) so they run in parallel. Each brief
   contains:
   - `run_id: <run_id>` and the spec path `runs/<run_id>/00_spec.json`
   - the dimension's entry of `01_plan.json`, verbatim (questions, search strategy,
     preferred domains, evidence needed)
   - the lines `research_brief.py` printed, verbatim (the budget line, and the back-test
     header when there is one)
   - the output path from the table, and "write no other file"
4. When all have returned, finish each launched dimension:
   `uv run python scripts/run_stage.py <run_id> research:<dim> --finish`. Exit 0 → `done`.
5. Check the markers: `ls runs/<run_id>/`, then read every
   `VALIDATION_FAILED_<agent>`, `VALIDATION_WARNINGS_<agent>` and `BUDGET_EXCEEDED_<agent>`
   file there.
6. A dimension whose `--finish` exited 1 failed validation (it is now `failed`; its agent
   usually left a `VALIDATION_FAILED_<agent>` marker). If `status.py <run_id>` shows its
   `attempts` at 2 or more, go to step 7. Otherwise **Re-launch it once**:
   `uv run python scripts/run_stage.py <run_id> research:<dim> --begin`, then the same brief
   with the validator's message appended (the `--finish` error and the marker's text) and the
   instruction to rewrite its file so it passes. Launch all re-launches together in one
   message, then `--finish` each again.
7. A dimension that failed its second launch: `uv run python scripts/run_stage.py <run_id> research:<dim> --insufficient-data`.
   Never write or repair a research file yourself, and never launch a third attempt.
8. Report to the user: dimensions done, re-launched and `INSUFFICIENT_DATA`; every
   `BUDGET_EXCEEDED_<agent>` marker (the agent went over its budget; its file still counts if
   it validates); the `VALIDATION_WARNINGS_<agent>` lines (sentences without `[src: …]`,
   not blocking).
9. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## Stage 3 — Claim verification

1. `uv run python scripts/run_stage.py <run_id> verify --begin`
2. `uv run python scripts/extract_claims.py <run_id>` finds the `[src: …]` sentences that no
   candidate claim covers and writes them to `03_claims/extracted/request.json`. If it prints
   `nothing to extract`, go to step 3. Otherwise launch the claim extractor **once**
   (`subagent_type: claim-extractor`) with a brief that contains `run_id: <run_id>`, the
   request path `runs/<run_id>/03_claims/extracted/request.json`, the `extract:` lines
   verbatim and "write only these output files". When it returns, read
   `runs/<run_id>/VALIDATION_FAILED_claim-extractor` if it exists and report it, but do not
   re-launch the extractor: the verifier drops the claims that fail the checks and says so in a
   `warning:` line. Never write or fix an extraction file yourself.
3. `uv run python scripts/verify_claims.py <run_id>`: it parses the candidate claims and the
   extractor's, fetches and caches each source, matches the quotes and writes
   `03_claims/<dim>.json`, `03_claims/verified.json` and the `claims` rows. Exit 1 means an
   unknown run or no `02_research/`; report it and stop (the stage stays `running`; the next
   `--resume` resets it). Show its `warning:` lines.
4. `uv run python -m ideaforge.validate_file --kind claims runs/<run_id>/03_claims/verified.json`;
   on exit 1 report the error and stop (never edit claim files).
5. `uv run python scripts/run_stage.py <run_id> verify --finish`
6. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## End

1. `uv run python scripts/status.py <run_id>`: show it verbatim in a code block (claims per
   dimension and verification state, kill flags, markers, usage).
2. Check `ls runs/<run_id>/` once more for `BUDGET_EXCEEDED_*` and `VALIDATION_FAILED_*`.
3. Tell the user the run id and that this skill ends after stage 3; `/validate <run_id>` or
   `/research <run_id>` re-runs whatever is incomplete and skips the rest, and
   `/synthesize <run_id>` runs stage 5 (proposed scores, risks, the score sheet and verdict).
