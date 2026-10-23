"""Validate pipeline files against their schemas. Used directly and by hooks.

    uv run python -m ideaforge.validate_file --kind spec runs/<id>/00_spec.json
    uv run python -m ideaforge.validate_file runs/<id>/01_plan.json        # kind inferred
    uv run python -m ideaforge.validate_file --auto                       # SubagentStop hook
    uv run python -m ideaforge.validate_file --auto --stop                # Stop hook

Exit 0 = valid, 1 = invalid (CLI), 2 = invalid (hook mode; stderr goes back to the model).

In hook mode a failing agent is blocked once so it can fix its own file. If the hook
already fired (stop_hook_active), the failure is recorded as
runs/<run_id>/VALIDATION_FAILED_<agent> for the orchestrator and the agent is let go.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ideaforge import agents, config, hookio, runs
from ideaforge.schemas import LIST_KINDS, SCHEMAS, CandidateClaim

KINDS = sorted([*SCHEMAS, *LIST_KINDS, "research"])

# Run-relative path → kind, for inference and the Stop hook.
STAGE_FILES: dict[str, str] = {
    "meta.json": "meta",
    "00_spec.json": "spec",
    "01_plan.json": "plan",
    "03_claims/verified.json": "claims",
    "04_scores_proposed.json": "scores_proposed",
    "04_risks.json": "risks",
    "04_scores.json": "scores",
    "debate/verdict.json": "verdict",
}

FENCED_JSON_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


class Invalid(Exception):
    pass


def infer_kind(path: Path) -> str:
    parts = path.as_posix().split("/")
    if len(parts) >= 2 and parts[-2] == "02_research" and path.suffix == ".md":
        return "research"
    if len(parts) >= 2 and parts[-2] == "03_claims" and path.name != "verified.json":
        return "claims"
    if len(parts) >= 2 and re.fullmatch(r"round\d+", parts[-2]) and path.name != "positions_anon.json":
        return "position" if parts[-2] == "round0" else "rebuttal"
    for rel, kind in STAGE_FILES.items():
        if path.as_posix().endswith(rel):
            return kind
    raise Invalid(f"cannot infer schema kind for {path}; pass --kind")


def _format_errors(e: ValidationError) -> str:
    lines = []
    for err in e.errors()[:20]:
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    more = len(e.errors()) - 20
    if more > 0:
        lines.append(f"  … and {more} more")
    return "\n".join(lines)


def validate_json(path: Path, kind: str) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Invalid(f"{path} does not exist") from None
    try:
        if kind in LIST_KINDS:
            TypeAdapter(list[LIST_KINDS[kind]]).validate_json(text)
        else:
            SCHEMAS[kind].model_validate_json(text)
    except ValidationError as e:
        raise Invalid(f"{path} is not a valid {kind}:\n{_format_errors(e)}") from None


def _sections(md: str) -> dict[str, str]:
    heads = list(HEADING_RE.finditer(md))
    return {
        h.group(1).strip().lower(): md[h.end() : heads[i + 1].start() if i + 1 < len(heads) else len(md)]
        for i, h in enumerate(heads)
    }


def validate_research(path: Path, max_words: int | None = None) -> list[CandidateClaim]:
    """Check a research subagent's Markdown against the output contract (§6 stage 2)."""
    try:
        md = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Invalid(f"{path} does not exist") from None
    problems: list[str] = []
    dimension = path.stem

    sections = _sections(md)
    if "candidate claims" not in sections:
        problems.append("missing the '## Candidate claims' section")
    if "gaps" not in sections:
        problems.append("missing the '## Gaps' section")

    claims: list[CandidateClaim] = []
    adapter = TypeAdapter(list[CandidateClaim])
    for i, block in enumerate(FENCED_JSON_RE.findall(sections.get("candidate claims", "")), 1):
        try:
            data = json.loads(block)
        except json.JSONDecodeError as e:
            problems.append(f"candidate-claims JSON block {i} does not parse: {e}")
            continue
        try:
            claims.extend(adapter.validate_python(data if isinstance(data, list) else [data]))
        except ValidationError as e:
            problems.append(f"candidate-claims JSON block {i} is not a list of Claim:\n{_format_errors(e)}")
    if "candidate claims" in sections and not claims and not problems:
        problems.append("the '## Candidate claims' section contains no ```json blocks")

    for c in claims:
        if c.dimension != dimension:
            problems.append(f"claim {c.claim_id} has dimension {c.dimension!r}, expected {dimension!r}")
    ids = [c.claim_id for c in claims]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append(f"duplicate claim ids: {', '.join(dupes)}")

    if max_words is None:
        key = "killcause_scout" if dimension == "killcause" else "research_subagent"
        max_words = getattr(config.budget().preset(), key).max_output_words
    prose = FENCED_JSON_RE.sub("", md)
    words = len(prose.split())
    if words > max_words:
        problems.append(f"prose is {words} words; the limit is {max_words}")

    if problems:
        raise Invalid(f"{path} violates the research output contract:\n" + "\n".join(f"  - {p}" for p in problems))
    return claims


def validate_path(path: Path, kind: str | None = None) -> None:
    kind = kind or infer_kind(path)
    if kind == "research":
        validate_research(path)
    else:
        validate_json(path, kind)


# ---------------------------------------------------------------- hook mode


def _record_failure(run_dir: Path, agent: str, message: str) -> None:
    (run_dir / f"VALIDATION_FAILED_{agent}").write_text(message + "\n", encoding="utf-8")


def auto(data: dict[str, Any], stop: bool) -> int:
    run_id = runs.active_run_id()
    if not run_id:
        return hookio.OK
    run_dir = config.RUNS_DIR / run_id
    retrying = bool(data.get("stop_hook_active"))

    if stop:
        agent = "main"
        targets = [(run_dir / rel, kind) for rel, kind in STAGE_FILES.items() if (run_dir / rel).exists()]
    else:
        spec = agents.get(hookio.agent_name(data))
        if spec is None:
            return hookio.OK  # not one of our pipeline agents
        agent = spec.name
        if spec.kind == "research":
            targets = [(agents.research_output(run_dir, spec), "research")]
        else:
            out = agents.latest_debate_output(run_dir, spec)
            targets = [] if out is None else [(out, None)]

    errors = []
    if not stop and not targets:
        errors.append(f"{agent} did not write its output file under {run_dir.name}/debate/")
    for path, kind in targets:
        try:
            validate_path(path, kind)
        except Invalid as e:
            errors.append(str(e))
    if not errors:
        (run_dir / f"VALIDATION_FAILED_{agent}").unlink(missing_ok=True)
        return hookio.OK

    message = "\n\n".join(errors)
    if retrying:
        _record_failure(run_dir, agent, message)
        print(f"validation failed again; recorded VALIDATION_FAILED_{agent}", file=sys.stderr)
        return hookio.OK
    hookio.block(message + "\n\nFix the file(s) above so they match the schema, then finish.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ideaforge.validate_file")
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--auto", action="store_true", help="hook mode: infer the file from hook JSON on stdin")
    parser.add_argument("--stop", action="store_true", help="with --auto: validate the main session's stage files")
    args = parser.parse_args(argv)

    if args.auto:
        try:
            return auto(hookio.read_input(), stop=args.stop)
        except Invalid as e:
            hookio.block(str(e))
    if args.path is None:
        parser.error("path is required unless --auto is given")
    try:
        validate_path(args.path, args.kind)
    except Invalid as e:
        print(e, file=sys.stderr)
        return 1
    print(f"ok: {args.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
