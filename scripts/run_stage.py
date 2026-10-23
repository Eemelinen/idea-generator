"""Drive a run's stage state machine (the stages table) from the skills.

    uv run python scripts/run_stage.py <run_id> <stage> --begin              # pending|failed -> running
    uv run python scripts/run_stage.py <run_id> <stage> --finish             # running -> done | failed
    uv run python scripts/run_stage.py <run_id> <stage> --insufficient-data  # research dimension only
    uv run python scripts/run_stage.py <run_id> --resume   # repair after a crash ("reset: ..." lines), then --next
    uv run python scripts/run_stage.py <run_id> --next     # the stages to run now, one per line

A stage is done only when its output file(s) exist and validate; --finish on an invalid output
marks the stage failed and prints why. Exit 0 on success, 1 when the transition is refused.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import db, runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("stage", nargs="?", help=f"one of: {', '.join(runs.STAGES)}")
    action = parser.add_mutually_exclusive_group(required=True)
    for flag in ("--begin", "--finish", "--insufficient-data", "--resume", "--next"):
        action.add_argument(flag, dest="action", action="store_const", const=flag.lstrip("-"))
    args = parser.parse_args(argv)

    needs_stage = args.action in ("begin", "finish", "insufficient-data")
    if needs_stage and not args.stage:
        parser.error(f"--{args.action} needs a stage")
    if not needs_stage and args.stage:
        parser.error(f"--{args.action} takes no stage")

    db.init()
    try:
        if args.action == "begin":
            runs.begin(args.run_id, args.stage)
            print(f"{args.stage}: running")
        elif args.action == "finish":
            runs.finish(args.run_id, args.stage)
            print(f"{args.stage}: done")
        elif args.action == "insufficient-data":
            runs.mark_insufficient(args.run_id, args.stage)
            print(f"{args.stage}: insufficient_data")
        else:
            if args.action == "resume":
                for stage, old, new in runs.resume(args.run_id):
                    print(f"reset: {stage}: {old} -> {new}")
            for stage in runs.next_stages(args.run_id):
                print(stage)
    except runs.StageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
