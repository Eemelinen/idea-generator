"""The run-specific lines of one research brief, or the scope lines of a debate persona's brief.

    uv run python scripts/research_brief.py <run_id> <dim>
    uv run python scripts/research_brief.py <run_id> --scope

Prints the run's scope lines from `00_spec.json` (the business mode, the base location with its
codes, nearby towns and official sites, the target markets and one line of mode guidance), then
the budget line of the run's preset for the dimension's agent (`research_subagent`, or
`killcause_scout` for killcause: web searches, web fetches and words, as the usage hook and the
research validator apply them) and, for a back-test run (`new_run.py --as-of`), the header that
forbids sources published after the as-of date. `--scope` prints the scope lines alone, for the
debate personas. The orchestrator pastes them into the brief verbatim. Exit 0 once printed, 1 for
an unknown run, dimension or preset, or a run without a valid spec.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import brief, runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("dimension", nargs="?")
    parser.add_argument("--scope", action="store_true", help="print only the scope lines (debate personas)")
    args = parser.parse_args(argv)
    if args.scope == (args.dimension is not None):
        parser.error("give either a dimension or --scope")

    try:
        run_dir = runs.run_dir(args.run_id)
        lines = brief.scope_lines(run_dir) if args.scope else brief.brief_lines(args.run_id, args.dimension)
    except (ValueError, brief.BriefError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
