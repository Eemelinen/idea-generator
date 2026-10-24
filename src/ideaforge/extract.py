"""Stage 3 claim-extraction pass (IF-211): research sentences that no candidate claim covers.

A `[src: …]` sentence of a research file (the sections the prose rules check) is *covered* when
one of the file's candidate claims cites one of the sentence's URLs and, for a sentence followed
by a `> quote` block (every figure sentence is), quotes that block (`verify.quote_matches`, either
way round). `write_request` lists the uncovered sentences of every 02_research/*.md in
03_claims/extracted/request.json (scripts/extract_claims.py); only when it lists a file does the
orchestrator launch the `claim-extractor` agent, which writes one JSON list of candidate claims
per listed file to 03_claims/extracted/<stem>.json. `verify.parse_run` adds the claims that pass
`extracted_claims` to the file's parsed ones, so they are fetched, quote-matched, re-queried and
conflict-checked exactly like them.

A request entry records the sha256 of the research file it was made from, and an extraction is
used only for that version of the file: a re-written research file drops its old extraction and
is listed again. A file whose extraction exists for its current version is never listed again, so
a resumed stage 3 does not launch the extractor twice for one file.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ideaforge import agents, runs
from ideaforge.schemas import (
    RESEARCH_DIMENSIONS,
    CandidateClaim,
    ExtractionFile,
    ExtractionRequest,
    ExtractionSentence,
)
from ideaforge.validate_file import (
    SourcedSentence,
    _format_errors,
    candidate_claims,
    claim_ids_elsewhere,
    normalize_url,
    sourced_sentences,
)

_CANDIDATES = TypeAdapter(list[CandidateClaim])


def research_files(run_dir: Path) -> list[Path]:
    """02_research/*.md in verification order: stage-2 files by name, then debate mini-research
    files (mini-<n>-<dim>.md) in task order, so a reused claim id never displaces a stage-2 claim."""

    def order(p: Path) -> tuple[int, str]:
        mini = agents.parse_mini_stem(p.stem)
        return (mini[0], p.name) if mini else (0, p.name)

    return sorted((run_dir / "02_research").glob("*.md"), key=order)


def dimension_of(stem: str) -> str | None:
    """The dimension of a research file stem (`pricing`, `mini-2-pricing`), or None."""
    mini = agents.parse_mini_stem(stem)
    if mini:
        return mini[1]
    return stem if stem in RESEARCH_DIMENSIONS else None


def digest(md: str) -> str:
    return hashlib.sha256(md.encode("utf-8")).hexdigest()


def covers(claim: CandidateClaim, sentence: SourcedSentence) -> bool:
    from ideaforge import verify  # verify imports this module

    if normalize_url(claim.source_url) not in sentence.urls:
        return False
    if sentence.quote is None:
        return True
    return verify.quote_matches(claim.quote, sentence.quote) or verify.quote_matches(sentence.quote, claim.quote)


def uncovered(md: str, extra: Iterable[CandidateClaim] = ()) -> list[SourcedSentence]:
    """The `[src: …]` sentences of a research file that none of its candidate claims (plus
    `extra`) covers."""
    claims = [*candidate_claims(md)[0], *extra]
    return [s for s in sourced_sentences(md) if not any(covers(c, s) for c in claims)]


def load_request(run_dir: Path) -> ExtractionRequest | None:
    """03_claims/extracted/request.json, or None when it is missing or does not validate."""
    path = agents.extract_request(run_dir)
    try:
        return ExtractionRequest.model_validate_json(path.read_bytes())
    except (FileNotFoundError, ValidationError):
        return None


def requested_outputs(run_dir: Path) -> list[Path]:
    """The output file of every entry of the run's request (what the extractor must write)."""
    request = load_request(run_dir)
    return [run_dir / f.output_file for f in request.files] if request else []


def pending(run_dir: Path, request: ExtractionRequest) -> list[ExtractionFile]:
    """The request's entries whose output the extractor has not written yet."""
    return [f for f in request.files if not (run_dir / f.output_file).exists()]


def _first_number(taken: set[str], dimension: str, reserved: dict[str, int]) -> int:
    """Past every `<dimension>-NNN` id the run has and every block already handed out, rounded
    up to the next hundred plus one, like a debate mini-research task (pricing-012 → pricing-101)."""
    pattern = re.compile(rf"^{re.escape(dimension)}-(\d+)$")
    numbers = [int(m.group(1)) for i in taken if (m := pattern.match(i))]
    return (max([*numbers, reserved.get(dimension, 0)]) // 100 + 1) * 100 + 1


def write_request(run_id: str) -> tuple[ExtractionRequest, list[str]]:
    """Find every research file with uncovered sentences, write request.json and return it with
    note lines (stale extractions removed, files with an unknown dimension skipped)."""
    run_dir = runs.run_dir(run_id)
    if not (run_dir / "02_research").is_dir():
        raise FileNotFoundError(f"{run_dir / '02_research'} does not exist")
    old = load_request(run_dir)
    previous = {f.stem: f for f in old.files} if old else {}
    taken = claim_ids_elsewhere(run_dir, "")
    reserved: dict[str, int] = {}
    files: list[ExtractionFile] = []
    notes: list[str] = []
    for path in research_files(run_dir):
        md = path.read_text(encoding="utf-8")
        sha = digest(md)
        out = agents.extracted_output(run_dir, path.stem)
        prev = previous.get(path.stem)
        if out.exists() and (prev is None or prev.research_sha256 != sha):
            out.unlink()
            notes.append(f"{out.name}: removed, {path.name} changed since it was extracted")
        if out.exists() and prev is not None:
            files.append(prev)  # extracted for this version of the file already
            continue
        sentences = uncovered(md)
        if not sentences:
            continue
        dimension = dimension_of(path.stem)
        if dimension is None:
            notes.append(f"{path.name}: not a research dimension, skipped")
            continue
        start = _first_number(taken, dimension, reserved)
        reserved[dimension] = start + 98
        files.append(
            ExtractionFile(
                stem=path.stem,
                dimension=dimension,
                research_file=path.relative_to(run_dir).as_posix(),
                research_sha256=sha,
                output_file=out.relative_to(run_dir).as_posix(),
                first_claim_id=f"{dimension}-{start:03d}",
                sentences=[
                    ExtractionSentence(section=s.section, sentence=s.sentence, urls=list(s.urls), quote=s.quote)
                    for s in sentences
                ],
            )
        )
    request = ExtractionRequest(run_id=run_id, files=files)
    target = agents.extract_request(run_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return request, notes


def extracted_claims(run_dir: Path, stem: str, md: str) -> tuple[list[CandidateClaim], list[str]]:
    """The claim extractor's candidate claims for research file `stem` (whose text is `md`) that
    may join its parsed claims, and one problem line per claim (or file) that may not.

    No output file → no claims, no problems. The output must be for the current version of the
    research file, and each claim must have the file's dimension, cite a URL of one of its
    `[src: …]` tags and carry an id that neither the file nor the rest of the run already has.
    """
    out = agents.extracted_output(run_dir, stem)
    if not out.is_file():
        return [], []
    name = f"03_claims/extracted/{out.name}"
    request = load_request(run_dir)
    entry = next((f for f in request.files if f.stem == stem), None) if request else None
    if entry is None or entry.research_sha256 != digest(md):
        return [], [f"{name} is not for the current {stem}.md; re-run scripts/extract_claims.py"]
    try:
        claims = _CANDIDATES.validate_json(out.read_bytes())
    except ValidationError as e:
        return [], [f"{name} is not a list of candidate claims:\n{_format_errors(e)}"]
    cited = {u for s in sourced_sentences(md) for u in s.urls}
    taken = {c.claim_id for c in candidate_claims(md)[0]} | claim_ids_elsewhere(run_dir, stem)
    seen: set[str] = set()
    kept: list[CandidateClaim] = []
    problems: list[str] = []
    for c in claims:
        if c.dimension != entry.dimension:
            why = f"dimension {c.dimension!r}, expected {entry.dimension!r}"
        elif normalize_url(c.source_url) not in cited:
            why = f"source_url {c.source_url} is not in a [src: …] tag of {stem}.md"
        elif c.claim_id in seen:
            why = "duplicate claim id"
        elif c.claim_id in taken:
            why = "claim id already in the run; number new ids up from first_claim_id"
        else:
            why = None
        seen.add(c.claim_id)
        if why is None:
            kept.append(c)
        else:
            problems.append(f"{name}: claim {c.claim_id}: {why}")
    return kept, problems


def extracted_problems(path: Path) -> list[str]:
    """Validator for one extractor output file runs/<run_id>/03_claims/extracted/<stem>.json."""
    run_dir = path.parent.parent.parent
    if not path.is_file():
        return [f"{path} does not exist; write a JSON list (`[]` when the sentences hold no claim)"]
    research = run_dir / "02_research" / f"{path.stem}.md"
    if not research.is_file():
        return [f"{research} does not exist"]
    return extracted_claims(run_dir, path.stem, research.read_text(encoding="utf-8"))[1]
