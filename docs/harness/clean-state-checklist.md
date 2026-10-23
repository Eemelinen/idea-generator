# Clean-state checklist

Run through this at clock-out, before committing. A session is not finished until every
box is ticked; `/harness:clock-out` in Claude Code walks the same list, and the loop driver refuses
to open a PR until the machine-checked part passes.

## Machine-checked — `pnpm harness:clean-state`

`pnpm harness:clean-state` (the shared harness CLI; the project checks below the core ones come
from `harness.config.json` → `cleanState`) exits 0 only when all of these hold. Flags: `--allow-state-dirty` (state files may be uncommitted), `--quick` (skip `init.sh`,
used by the Stop hook), `--require-terminal` (no feature may be left `in_progress`; used
for driver-run sessions), `--base <ref>` (diff base, default `origin/main`).

- [ ] Working tree is clean (or only `feature_list.json`, `PROGRESS.md`, `docs/harness/**` are dirty).
- [ ] `feature_list.json` is valid: `pnpm harness:check` exits 0 (WIP=1, evidence before `passing`, dependencies resolve).
- [ ] No skip was added under `tests/` (`.only`/`.skip`, `@pytest.mark.skip`/`skipif`/`xfail`, `pytest.skip(`/`pytest.xfail(`).
- [ ] No coverage threshold was removed from `pyproject.toml` (`fail_under`, `--cov-fail-under`).
- [ ] No debugger call (`breakpoint()`, `pdb.set_trace()`, `import pdb`) was added under `src/` or `scripts/`.
- [ ] `PROGRESS.md` was updated on this branch.
- [ ] `.env` is neither tracked nor staged.
- [ ] The standard startup path still works: `FAST=1 ./init.sh` exits 0.
- [ ] (driver-run) The active feature ended `passing` or `blocked`, not `in_progress`.

## Judgement — checked by the person or agent clocking out

- [ ] The standard verification path ran for the feature: `pnpm check` plus the feature's focused steps (`pnpm harness:verify` records the evidence).
- [ ] `PROGRESS.md` content is truthful: Current Verified State, session entry, concrete Next Steps.
- [ ] No half-finished step is left undocumented (notes on the feature, or a handoff in `docs/harness/session-handoff.md`).
- [ ] No debug artefacts: temporary files, commented-out code, stray prints outside CLI output.
- [ ] Tests stay offline: no test opens a network connection; new fixtures were recorded by a human feature, not invented.
- [ ] Generated files were regenerated, not edited: `uv run python scripts/gen_agents.py` after changes to `config/models.yaml`, `agent_templates/` or `prompts/`.
- [ ] Every number the pipeline emits still has a source (non-negotiable 3) and Python, not the model, still decides scores and verdicts (non-negotiable 4).
- [ ] Docs affected by the change were updated in the same commit (README, `IMPLEMENTATION_PLAN.md`, `docs/TICKETS.md` plan notes when the plan is deviated from, `docs/DECISIONS.md`).
- [ ] Commit subject follows conventional commits, the body explains why, and there is no AI attribution.
- [ ] The next session can continue without manual repair.
