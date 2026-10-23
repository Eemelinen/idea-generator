"""Validate pipeline files against their schemas. Used directly and by hooks.

    uv run python -m ideaforge.validate_file --kind spec runs/<id>/00_spec.json
    uv run python -m ideaforge.validate_file runs/<id>/01_plan.json        # kind inferred
    uv run python -m ideaforge.validate_file --auto                       # SubagentStop hook
    uv run python -m ideaforge.validate_file --auto --stop                # Stop hook

Exit 0 = valid, 1 = invalid (CLI), 2 = invalid (hook mode; stderr goes back to the model).
Heuristic research findings (sentences without [src: …]) are printed as warnings and never fail.

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

from ideaforge import agents, config, hookio, runs, usage
from ideaforge.fi import API_URL_PREFIXES
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
FENCED_RE = re.compile(r"```.*?```", re.DOTALL)
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# Research prose rules (§6 stage 2 output contract). They apply to the body sections; the
# title + summary before the first "##", "## Candidate claims" and "## Gaps" are exempt.
UNCHECKED_SECTIONS = {"candidate claims", "gaps"}
LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ])")
SRC_TAG_RE = re.compile(r"\[src:[^\]]*\]", re.IGNORECASE)
# English month names are matched capitalised only, so "30 may be" stays a figure.
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\b"
    r"|(?:[Tt]ammi|[Hh]elmi|[Mm]aalis|[Hh]uhti|[Tt]ouko|[Kk]esä|[Hh]einä|[Ee]lo|[Ss]yys|[Ll]oka|[Mm]arras|[Jj]oulu)kuu\w*"
)
_YEAR = r"(?:1[89]|20)\d{2}"
# A bare 4-digit number is a year only in a year context, never on its own: "1900 residents" is
# a figure. Contexts: a preceding in/since/until/during/before/after, year word or month,
# parentheses, a Finnish case ending (2024:n), a range or a season (2019–2024, 2024/25). Lists
# continue the context ("in 2023 and 2024"). "to", "by", "from" and "of" are left out, as in
# "grew to 2000 visitors", and a following EUR/€/% makes it a figure.
_YEAR_WORD = (
    rf"(?:[Ii]n|[Ss]ince|[Uu]ntil|[Dd]uring|[Bb]efore|[Aa]fter|[Yy]ears?"
    rf"|[Vv]uonna|[Vv]uodesta|[Vv]uoteen|[Vv]uoden|[Vv]uosina|[Vv]uosien|[Vv]uosi|[Vv]uodelle|Q[1-4]|H[12]|{_MONTH})"
)
_YEAR_LIST = rf"{_YEAR}(?:\s*(?:,|and|or|ja|tai)\s*{_YEAR}\b)*(?!\s*(?:EUR|€|%|euro))"
# Digit-bearing text that is not a figure, removed before looking for digits. Order matters:
# dates before years, because a date contains a year.
NOT_A_FIGURE_RES = [
    SRC_TAG_RE,
    usage.URL_RE,
    re.compile(r"\b[a-z_]+-\d{3,}\b"),  # claim ids (schemas.CLAIM_ID_RE)
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO date
    re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"),  # Finnish date 31.12.2024
    re.compile(r"\b\d{1,2}/\d{4}\b"),  # month/year 3/2025
    re.compile(rf"\b\d{{1,2}}\.?\s+(?:{_MONTH})(?:\s+{_YEAR}\b)?"),  # 1 March 2025, 1. maaliskuuta
    # March 1, March 31st 2025; not "In May 40 cabins were booked"
    re.compile(rf"\b(?:{_MONTH})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+{_YEAR})?(?=\s*(?:[,.;\[]|$))"),
    re.compile(rf"\b{_YEAR}\s*[–-]\s*(?:{_YEAR}|\d{{2}})\b|\b{_YEAR}/\d{{2}}\b"),  # range, season
    re.compile(rf"\b{_YEAR_WORD}\s+{_YEAR_LIST}\b"),  # in 2024, since 2019, March 2025
    re.compile(rf"\({_YEAR_LIST}\)|\b{_YEAR}:[^\W\d_]+"),  # (2024), 2024:n
    re.compile(r"\b[^\W\d_]+\d[^\W\d_][\w-]*|\b[^\W\d_]+-?\d{1,2}\b"),  # identifiers: B2B, Q1, COVID-19
]
DIGIT_RE = re.compile(r"\d")
# Sentences that report a gap rather than a fact need no source.
GAP_RE = re.compile(
    r"\b(?:no (?:data|source|sources|information|evidence)|not (?:found|available|published)"
    r"|could not|couldn't|cannot|unknown|unclear)\b",
    re.IGNORECASE,
)
MIN_FACT_WORDS = 4


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


def _units(section: str) -> list[tuple[str, str]]:
    """Split a section into ("prose", paragraph) and ("quote", block) units, in order.

    Blank lines, headings and list items start a new paragraph; consecutive '>' lines are one quote.
    """
    units: list[tuple[str, str]] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            units.append(("prose", " ".join(para)))
            para.clear()

    for line in FENCED_RE.sub("", section).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            flush()
        elif s.startswith(">"):
            flush()
            if units and units[-1][0] == "quote":
                units[-1] = ("quote", units[-1][1] + " " + s.lstrip("> "))
            else:
                units.append(("quote", s.lstrip("> ")))
        else:
            if LIST_ITEM_RE.match(s):
                flush()
                s = LIST_ITEM_RE.sub("", s)
            para.append(s)
    flush()
    return units


def has_figure(sentence: str) -> bool:
    """True if the sentence has a digit outside years, dates, claim ids, identifiers and URLs."""
    for pattern in NOT_A_FIGURE_RES:
        sentence = pattern.sub(" ", sentence)
    return bool(DIGIT_RE.search(sentence))


def _short(sentence: str, n: int = 80) -> str:
    return sentence if len(sentence) <= n else sentence[: n - 1] + "…"


def check_prose(md: str) -> tuple[list[str], list[str]]:
    """Bare-figure problems and missing-[src: …] warnings for the body sections of a research file."""
    problems: list[str] = []
    warnings: list[str] = []
    for name, body in _sections(md).items():
        if name in UNCHECKED_SECTIONS:
            continue
        units = _units(body)
        for i, (kind, text) in enumerate(units):
            if kind != "prose":
                continue
            sentences = SENTENCE_SPLIT_RE.split(text)
            quoted = i + 1 < len(units) and units[i + 1][0] == "quote"
            for j, sentence in enumerate(sentences):
                if has_figure(sentence) and not (quoted and j == len(sentences) - 1):
                    problems.append(
                        f"'## {name}': a figure without a '> quote' block right after its sentence: "
                        f"{_short(sentence)!r}"
                    )
                if (
                    not SRC_TAG_RE.search(sentence)
                    and len(sentence.split()) >= MIN_FACT_WORDS
                    and not GAP_RE.search(sentence)
                ):
                    warnings.append(f"'## {name}': a factual sentence without [src: …]: {_short(sentence)!r}")
    return problems, warnings


def normalize_url(url: str) -> str:
    return url.rstrip(".,;:`*").split("#", 1)[0].rstrip("/")


def seen_urls(run_dir: Path, agent: str) -> set[str]:
    """URLs the usage hook logged for this agent's WebSearch results and WebFetch calls."""
    try:
        lines = (run_dir / ".seen_urls.txt").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return set()
    seen = set()
    for line in lines:
        who, sep, url = line.partition("\t")
        if sep and who == agent:
            seen.add(normalize_url(url))
    return seen


def check_provenance(md: str, claims: list[CandidateClaim], seen: set[str], agent: str) -> list[str]:
    """Cited URLs (prose and claim source_url) that the agent never saw and that are not API URLs.

    '## Gaps' is skipped: it names sources that would answer an open question, unvisited by definition.
    """
    gaps = _sections(md).get("gaps")
    prose = FENCED_JSON_RE.sub("", md.replace(gaps, "\n") if gaps else md)
    cited = {normalize_url(u) for u in usage.URL_RE.findall(prose)}
    cited |= {normalize_url(c.source_url) for c in claims}
    unseen = sorted(u for u in cited if u not in seen and not u.startswith(API_URL_PREFIXES))
    return [
        f"cited URL never appeared in {agent}'s search results or fetches (do not invent URLs): {u}"
        for u in unseen
    ]


def candidate_claims(md: str) -> tuple[list[CandidateClaim], list[str]]:
    """Parse the ```json blocks of a research file's '## Candidate claims' section.

    Returns the claims of every block that validates and one problem line per block that does
    not. A file without the section yields no claims and no problems.
    """
    section = _sections(md).get("candidate claims")
    if section is None:
        return [], []
    claims: list[CandidateClaim] = []
    problems: list[str] = []
    adapter = TypeAdapter(list[CandidateClaim])
    for i, block in enumerate(FENCED_JSON_RE.findall(section), 1):
        try:
            data = json.loads(block)
        except json.JSONDecodeError as e:
            problems.append(f"candidate-claims JSON block {i} does not parse: {e}")
            continue
        try:
            claims.extend(adapter.validate_python(data if isinstance(data, list) else [data]))
        except ValidationError as e:
            problems.append(f"candidate-claims JSON block {i} is not a list of Claim:\n{_format_errors(e)}")
    if not claims and not problems:
        problems.append("the '## Candidate claims' section contains no ```json blocks")
    return claims, problems


def validate_research(
    path: Path,
    max_words: int | None = None,
    seen: set[str] | None = None,
    warnings: list[str] | None = None,
) -> list[CandidateClaim]:
    """Check a research subagent's Markdown against the output contract (§6 stage 2).

    `seen` is the set of URLs the agent saw; by default it is read from the run directory's
    .seen_urls.txt (path is runs/<run_id>/02_research/<dimension>.md). Heuristic findings that do
    not fail the file are appended to `warnings` when a list is given.
    """
    try:
        md = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Invalid(f"{path} does not exist") from None
    problems: list[str] = []
    dimension = path.stem
    spec = agents.research_agent(dimension)
    agent = spec.name if spec else f"research-{dimension}"

    sections = _sections(md)
    if "candidate claims" not in sections:
        problems.append("missing the '## Candidate claims' section")
    if "gaps" not in sections:
        problems.append("missing the '## Gaps' section")

    claims, claim_problems = candidate_claims(md)
    problems.extend(claim_problems)

    for c in claims:
        if c.dimension != dimension:
            problems.append(f"claim {c.claim_id} has dimension {c.dimension!r}, expected {dimension!r}")
    ids = [c.claim_id for c in claims]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append(f"duplicate claim ids: {', '.join(dupes)}")

    if max_words is None:
        # The run's preset (meta.json), as the brief and the usage hook use; else the default.
        key = "killcause_scout" if dimension == "killcause" else "research_subagent"
        budget, preset = config.budget(), usage.run_preset(path.parent.parent)
        max_words = getattr(budget.preset(preset if preset in budget.presets else None), key).max_output_words
    prose = FENCED_JSON_RE.sub("", md)
    words = len(prose.split())
    if words > max_words:
        problems.append(f"prose is {words} words; the limit is {max_words}")

    figure_problems, src_warnings = check_prose(md)
    problems.extend(figure_problems)
    if seen is None:
        seen = seen_urls(path.parent.parent, agent)
    problems.extend(check_provenance(md, claims, seen, agent))
    if warnings is not None:
        warnings.extend(src_warnings)

    if problems:
        raise Invalid(f"{path} violates the research output contract:\n" + "\n".join(f"  - {p}" for p in problems))
    return claims


def validate_path(path: Path, kind: str | None = None, warnings: list[str] | None = None) -> None:
    kind = kind or infer_kind(path)
    if kind == "research":
        validate_research(path, warnings=warnings)
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
        if spec is None or spec.kind == "harness":
            return hookio.OK  # not one of our pipeline agents
        agent = spec.name
        if spec.kind == "research":
            targets = [(agents.research_output(run_dir, spec), "research")]
        else:
            out = agents.latest_debate_output(run_dir, spec)
            targets = [] if out is None else [(out, None)]

    errors = []
    warnings: list[str] = []
    if not stop and not targets:
        errors.append(f"{agent} did not write its output file under {run_dir.name}/debate/")
    for path, kind in targets:
        try:
            validate_path(path, kind, warnings)
        except Invalid as e:
            errors.append(str(e))
    warning_text = "Warnings (not blocking):\n" + "\n".join(f"  - {w}" for w in warnings) if warnings else ""
    if not errors:
        (run_dir / f"VALIDATION_FAILED_{agent}").unlink(missing_ok=True)
        # Exit-0 stderr reaches nobody, so the orchestrator and /status read the warnings from a file.
        warnings_file = run_dir / f"VALIDATION_WARNINGS_{agent}"
        if warning_text:
            warnings_file.write_text(warning_text + "\n", encoding="utf-8")
            print(warning_text, file=sys.stderr)
        else:
            warnings_file.unlink(missing_ok=True)
        return hookio.OK

    message = "\n\n".join([*errors, warning_text] if warning_text else errors)
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
    warnings: list[str] = []
    try:
        validate_path(args.path, args.kind, warnings)
    except Invalid as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
    print(f"ok: {args.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
