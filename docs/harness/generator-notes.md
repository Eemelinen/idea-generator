- Before implementing, read the `spec` section the feature links in `docs/TICKETS.md` and the
  `IMPLEMENTATION_PLAN.md` sections that ticket cites. The pipeline non-negotiables in AGENTS.md
  apply to every change.
- Record a deviation from the plan under "Plan notes and deviations" in `docs/TICKETS.md`.
- Never fetch live data (no live API calls, no recording fixtures): tests use the committed
  fixtures, and a feature that needs the network has a `manual:` step and is not yours.
- If `uv` is not found or the network or credentials are missing, describe it in `PROGRESS.md` and
  block the feature; a human fixes the host.
