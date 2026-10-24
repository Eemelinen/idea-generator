# Ideaforge

A local business-idea validator for founders in Rääkkylä / North Karelia, Finland. It runs on Claude Code with a Claude Max subscription and uses no paid third-party services.

You type an idea. Ideaforge researches it across ten feasibility dimensions with parallel subagents, verifies every quoted claim against its source, scores the idea in Python and writes an evidence-backed report. If you ask, it also runs a structured debate that tries to improve the plan.

- Design: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- Work breakdown: [docs/TICKETS.md](docs/TICKETS.md)
- Instructions for Claude Code: [CLAUDE.md](CLAUDE.md)

## Setup

1. Install [uv](https://docs.astral.sh/uv/). uv downloads Python 3.12 for the project.
2. `uv sync`
3. `uv run python scripts/gen_agents.py`
4. `uv run pytest`

If downloads fail with `invalid peer certificate: UnknownIssuer`, something on the machine (antivirus or a proxy) is intercepting TLS. `pyproject.toml` already sets `[tool.uv] system-certs = true`, so commands run inside the project use the system certificate store. Commands run outside the project need `--system-certs`.

## Usage

Inside Claude Code, in this directory:

```
/validate [--preset economy|standard|deep] <idea text>   # stages 0–3 (intake → claim verification)
/validate <run_id>           # resume a run: skips completed stages and research dimensions
/validate --from <run_id> [<revised idea text>]   # a new version <run_id>-vN; the old run and report stay unchanged
/research <run_id>           # stages 1–3 of an existing run
/synthesize <run_id>         # stage 5: proposed scores and risks, the score sheet and verdict, the report
/status [run_id]
/status <run_id> --review     # score the report's sections 1–5 (stored in the reviews table)
/status --reviews            # review-score trend across prompt and model versions
/status --diff <run_a> <run_b>   # compare two score sheets: dimensions, verdict, kill triggers
/debate <run_id>             # Phase 4
/eval [--limit N] [--fresh]  # Phase 5: the golden set, one idea at a time, then eval_check.py
```

Status: Phase 1 (the skeleton) is done; of Phase 2, the recorded Finnish API fixtures (`uv run python scripts/record_fixtures.py`, run by hand with network; `tests/fixtures/api/`), the StatFin/Luke PxWeb client (`uv run python -m ideaforge.fi.pxweb search|meta|get`), the PRH company search and the Eurostat client (`uv run python -m ideaforge.fi.prh search`, `uv run python -m ideaforge.fi.eurostat get`), the research validator, claim verification (`uv run python scripts/verify_claims.py <run_id>`), the usage report, basic `/status`, the stage state machine and the `/validate` and `/research` skills for stages 0–3 are built; of Phase 3, scoring, unit economics, `/synthesize` (stage 5), the report and versioning (`meta.json`, `/validate --from`) are built; of Phase 4, the `/debate` skill with its persona and judge prompts, debate anonymization, rebuttal validation, mini-research, the convergence check, the conformity flag and the revised plan (the first live debate is still to come); of Phase 5, the golden-set schema, `scripts/eval_check.py` and the `/eval` skill (the golden set itself is IF-501), back-test mode (`--as-of`), the preset budget lines in the research briefs (`scripts/research_brief.py`), review scores and `/status --diff`. See `docs/TICKETS.md` for what comes next.

- `uv run python scripts/run_stage.py <run_id> <stage> --begin|--finish|--insufficient-data` moves one stage through `pending → running → done | failed` (`insufficient_data` for a research dimension that failed twice); a stage is done only when its output file(s) exist and validate. `run_stage.py <run_id> --resume` makes the run active for the hooks, repairs the stages a crash left `running` and prints the stages to run next (`--next` prints them without repairing).
- `uv run python scripts/usage_report.py <run_id>`: tool calls, searches, fetches and approximate tokens per stage and per agent, plus the run's `BUDGET_EXCEEDED_*` markers.
- `/synthesize <run_id>`: `uv run python scripts/synthesis_input.py <run_id>` writes `04_synthesis_input.json` (the spec, the verified and conflict claims, the rubric), the `synthesizer` subagent reads only that file and writes `04_scores_proposed.json` (scores, citations, unit-economics inputs) and `04_risks.json`, and `uv run python scripts/score_run.py <run_id>` drops unverified citations, applies the caps, kill triggers and unit economics and writes `04_scores.json` and the `scores` rows. Then `uv run python scripts/render_report.py <run_id>` writes the immutable `05_report.md`: verdict and why, score table with cap labels, kill triggers, unit economics and sensitivity, dimension sections, Finland funding fit (each item backed by a verified official-source claim or shown as a gap), Rääkkylä notes, risk register, sources and usage. It never overwrites an existing report.
- `uv run python scripts/new_run.py --from <run_id> [<idea text>]` (what `/validate --from` runs) creates the next version `<run_id>-vN` with its own directory, linked through `idea_versions.parent`; the idea text, budget preset and `--as-of` date default to the parent's and the parent run is never touched. Every run's `meta.json` records the repository HEAD, the last commit that changed `config/`, `prompts/` or `agent_templates/` (and whether they had uncommitted changes), the `config/models.yaml` roles, the Claude Code version (`claude --version`), the idea version and `created_at` / `updated_at` (refreshed by each stage transition).
- `/debate <run_id>` runs the debate on a run with a report and resumes per round (`uv run python -m ideaforge.debate status <run_id>` prints the next step). Each persona sees the report and its own evidence subset, `debate/evidence/<role>.json` (`uv run python -m ideaforge.debate evidence <run_id>`). A mini-research request becomes a task (`uv run python -m ideaforge.mini_research open <run_id> <round>`, at most `max_mini_research_tasks` per debate) for the dimension's research agent, which writes `02_research/mini-<n>-<dim>.md`; `mini_research finish` validates it and `uv run python scripts/verify_claims.py <run_id> --only mini-<n>-<dim>` verifies only its claims, which every persona gets next round. Its building blocks: `uv run python -m ideaforge.debate anonymize <run_id> <round>` maps the five personas to P1…P5 with a seed stored in the `debates` table and `debate/.mapping.json` (never shown to personas or the judge) and writes `debate/round<N>/positions_anon.json` without role names. `uv run python scripts/debate_validate.py <run_id> <round>` rejects a stance change without a new claim id or a computation, a disagree without a claim id or an evidence gap, unknown or unverified claim ids and a second mini-research request in a round, writes the reasons to `debate/round<N>/REJECTED_<role>` and records each turn in `debate_turns` (exit 2 when a persona must be re-prompted). `uv run python scripts/debate_converged.py <run_id> <round>` exits 0 when the debate should stop: no new claim id and no moved proposal in the round, the judge's interim projected scores (`debate/round<N>/interim_scores.json`) moved less than `convergence_score_delta` on every dimension, or the preset's `max_rounds` is reached (exit 2: run another round). After the judge, `uv run python scripts/render_report.py <run_id> --debate` checks that every accepted change cites verified claims, recomputes `conformity_flag` into `debate/verdict.json` (≥ 4 of 5 personas backing one change while no new claim id entered), writes the immutable `debate/revised_plan.md` (a diff against `05_report.md`, the assumption register and at least five experiments ordered by info value per euro) and stores the `assumptions` and `experiments` tables.
- `/eval [--limit N] [--fresh]` runs each golden idea in `tests/golden/*.yaml` (schema `GoldenIdea`: the idea, `expected_verdicts`, 2–3 `must_find` facts with source URLs and optional keywords) through stages 0–5, sequentially, reusing a finished run and resuming an unfinished one unless `--fresh`. `uv run python scripts/eval_check.py [--limit N]` then checks each idea's newest run (found by its idea text): the verdict is one of `expected_verdicts`, every must-find fact is found by a verified claim (same source URL, or every keyword in its statement or quote) and the score sheet cites no claim that is not verified; it prints a Markdown summary table and `passed: X of N` (exit 2 when one fails). `--plan` lists the golden ideas and their runs without the answer key.
- `/status` (`uv run python scripts/status.py [run_id] [--limit N]`): the recent runs and their stages; with a run id, its stages, claims per dimension by verification state, kill flags fired, validation and budget markers and the usage summary. `/status <run_id> --review` lists the sections of the run's `05_report.md`, asks you to score each 1–5 (an optional note each) and stores them in the `reviews` table (`scripts/status.py <run_id> --review verdict=4 'risks=2:too generic' …`); `/status --reviews` shows the mean score per section for each prompt/config and model version from the runs' `meta.json`, so drift after a prompt or model change shows. `/status --diff <run_a> <run_b>` compares two runs' `04_scores.json`: final score per dimension, weighted total, verdict, kill triggers fired, and the config and model changes between the runs.
- `/validate --as-of YYYY-MM-DD <idea text>` is a back-test: the research briefs carry a header that allows only sources published on or before that date, and `verify_claims.py` marks a claim whose `published_date` is later `unverified` with the flag `after_as_of` (without fetching it). An undated claim is not rejected. `uv run python scripts/research_brief.py <run_id> <dim>` prints the lines every research brief gets: the run's budget line and, in a back-test, that header.

## Usage limits, presets and model downgrades

Ideaforge runs on a Claude Max subscription and nothing else, so the limit that matters is the subscription's usage limit, not money.

- **Before a batch** (several `/validate` runs, `/eval`, a debate), check `/usage` in Claude Code. Run heavy stages one idea at a time; `/eval` is sequential by design. After every stage the skills print `uv run python scripts/usage_report.py <run_id>`.
- **Presets** (`config/budget.yaml`, chosen with `/validate --preset economy|standard|deep`; the default is `standard`). A new version made with `--from` keeps its parent's preset unless `--preset` is given.

  | Preset     | Searches / fetches per research agent | Words | Killcause searches / fetches | Debate rounds | Mini-research tasks |
  | ---------- | ------------------------------------- | ----- | ---------------------------- | ------------- | ------------------- |
  | `economy`  | 6 / 6                                 | 1000  | 8 / 6                        | 2             | 1                   |
  | `standard` | 8 / 8                                 | 1200  | 10 / 8                       | 3             | 3                   |
  | `deep`     | 12 / 12                               | 1600  | 14 / 12                      | 3             | 3                   |

  The generated agent files carry the default preset's numbers, so the orchestrator pastes the run's budget line from `research_brief.py` into every research brief. The usage hook counts each research agent's `WebSearch` and `WebFetch` calls against the run's preset (from `meta.json`) and writes `runs/<run_id>/BUDGET_EXCEEDED_<agent>` when one goes over (an economy research agent at its 7th search); the research validator applies the preset's word limit.

- **Model downgrade order** (`config/models.yaml`, every role defaults to `opus`): `claim_extractor` (→ `haiku`) first, then `debate_persona` (→ `sonnet`), then `research_subagent`. Keep `synthesizer` and `debate_judge` on `opus` longest.
- **Downgrade procedure**: edit the role in `config/models.yaml` (never a model in an agent file) → `uv run python scripts/gen_agents.py` → `/eval --limit 3` (3 golden ideas) → compare the score sheets with the previous model's runs with `/status --diff <old_run> <new_run>`. Every run's `meta.json` records the roles it ran with.
- **Fable models** count against the weekly limit faster and are capped at 50 % of it. Use them only through `/model`, and only for the synthesizer or the judge on ideas that matter; never put them in `config/models.yaml`.

## Development

The project's hooks block writes outside `runs/` and `cache/` and allow only a short list of shell commands. To work on the code itself, create an empty `.ideaforge-dev` file at the project root (it is gitignored). Subagents are always held to the strict rules.

After editing `config/models.yaml`, `agent_templates/` or `prompts/`, run `uv run python scripts/gen_agents.py`. The tests fail if the generated agent files are stale.

The remaining work is built with an agent harness: one feature per Claude Code session, verified by scripts before it counts as done. You need Node 24 (`.nvmrc`) with pnpm, plus uv, and on Windows Git Bash. `uv`, `claude` and `gh` must be on `PATH`.

- `./init.sh` installs both toolchains and runs the L1 check, `pnpm check`.
- In Claude Code: `/harness:clock-in` picks and activates the next feature, `/harness:verify-feature F-NNN` runs its checks, and `/harness:clock-out` commits. The skills, hooks and loop come from the shared harness ([Eemelinen/harness](https://github.com/Eemelinen/harness)), configured in `harness.config.json`.
- `pnpm harness:feature list` shows the queue (`feature_list.json`; tickets in `docs/TICKETS.md`).
- `pnpm harness:loop --once` runs one ready feature unattended in its own worktree and opens a PR.

The session loop is described in [AGENTS.md](AGENTS.md) and the driver in [docs/harness/README.md](docs/harness/README.md).
