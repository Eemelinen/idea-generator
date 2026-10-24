"""The run-specific lines of one research brief.

    uv run python scripts/research_brief.py <run_id> <dim>

Prints the budget line of the run's preset for the dimension's agent (`research_subagent`, or
`killcause_scout` for killcause: web searches, web fetches and words, as the usage hook and the
research validator apply them) and, for a back-test run (`new_run.py --as-of`), the header that
forbids sources published after the as-of date. The orchestrator pastes them into the brief
verbatim. Exit 0 once printed, 1 for an unknown run, dimension or preset.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import brief, runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("dimension")
    args = parser.parse_args(argv)

    try:
        runs.run_dir(args.run_id)
        lines = brief.brief_lines(args.run_id, args.dimension)
    except (ValueError, brief.BriefError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
