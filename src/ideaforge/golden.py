"""The eval golden set (plan §9, IF-502): golden ideas, their runs and the three checks.

    load_all(dir)          → every `<golden_id>.yaml` in file-name order, validated (GoldenIdea)
    latest_run(idea)       → the newest run whose idea text is the golden idea, or None
    check(golden_id, g)    → the result of the three checks on that run

A golden idea passes when its run has a score sheet and (1) the verdict is one of
`expected_verdicts`, (2) every must-find fact is found by a `verified` claim of
`03_claims/verified.json`, and (3) the score sheet cites no claim id that is not `verified`
(each dimension's `supporting_claim_ids` and the unit economics' `input_claim_ids`).
Runs are found by their idea text (`runs.idea_text`), which `/eval` passes to new_run.py verbatim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import TypeAdapter, ValidationError

from ideaforge import config, db, guard, runs
from ideaforge.schemas import Claim, GoldenIdea, MustFindFact, ScoreSheet


class GoldenError(Exception):
    """A golden file that does not parse or validate, or two golden ideas with the same text."""


def golden_dir() -> Path:
    return config.ROOT / "tests" / "golden"


def load(path: Path) -> GoldenIdea:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise GoldenError(f"{path.name}: {e}") from None
    try:
        idea = GoldenIdea.model_validate(data)
    except ValidationError as e:
        raise GoldenError(f"{path.name}: {e}") from None
    denial = guard.command_denial(new_run_command(idea.idea))
    if denial:
        raise GoldenError(f"{path.name}: /eval could not pass the idea to new_run.py: {denial}")
    return idea


def new_run_command(idea: str) -> str:
    """The command /eval runs to create a golden idea's run (`.claude/skills/eval/SKILL.md`)."""
    return f"uv run python scripts/new_run.py '{idea}'"


def load_all(directory: Path | None = None, limit: int | None = None) -> list[tuple[str, GoldenIdea]]:
    """(golden_id, idea) for every `*.yaml` in `directory`, in file-name order; the first `limit`.

    Every file is validated, also those past the limit, so a broken file is never hidden.
    """
    directory = directory or golden_dir()
    ideas = [(p.stem, load(p)) for p in sorted(directory.glob("*.yaml"))]
    seen: dict[str, str] = {}
    for gid, g in ideas:
        if g.idea in seen:
            raise GoldenError(f"{gid}.yaml has the same idea text as {seen[g.idea]}.yaml")
        seen[g.idea] = gid
    return ideas[:limit] if limit is not None else ideas


def latest_run(idea: str) -> str | None:
    """The newest run created with exactly this idea text."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE trim(idea_text)=? ORDER BY created_at DESC, run_id DESC LIMIT 1",
            (idea.strip(),),
        ).fetchone()
    return row["run_id"] if row else None


def run_state(run_id: str | None) -> str:
    """`none` (no run), `complete` (every stage complete) or `incomplete`."""
    if run_id is None:
        return "none"
    current = runs.statuses(run_id)
    return "complete" if all(runs.is_complete(run_id, s, current[s]) for s in runs.STAGES) else "incomplete"


def normalize_url(url: str) -> str:
    """Scheme, `www.`, case of the host, a trailing slash and the fragment do not matter."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


def finds(fact: MustFindFact, claim: Claim) -> bool:
    """Whether a verified claim finds the fact (see MustFindFact)."""
    if claim.verification != "verified":
        return False
    if fact.dimensions and claim.dimension not in fact.dimensions:
        return False
    if normalize_url(claim.source_url) in {normalize_url(u) for u in fact.source_urls}:
        return True
    text = f"{claim.statement}\n{claim.quote}".casefold()
    return bool(fact.keywords) and all(k.casefold() in text for k in fact.keywords)


def cited_claim_ids(sheet: ScoreSheet) -> list[str]:
    """Every claim id the score sheet cites, in order of first appearance."""
    ids = [cid for s in sheet.scores for cid in s.supporting_claim_ids]
    return list(dict.fromkeys([*ids, *sheet.unit_economics.input_claim_ids]))


@dataclass
class Result:
    golden_id: str
    golden: GoldenIdea
    run_id: str | None = None
    verdict: str | None = None
    weighted_total: float | None = None
    found: dict[str, list[str]] = field(default_factory=dict)  # fact → claim ids that find it
    unverified_cited: list[str] = field(default_factory=list)  # "id (state)"
    error: str | None = None  # why the run could not be checked

    @property
    def verdict_ok(self) -> bool:
        return self.verdict is not None and self.verdict in self.golden.expected_verdicts

    @property
    def missing_facts(self) -> list[str]:
        return [f.fact for f in self.golden.must_find if not self.found.get(f.fact)]

    @property
    def passed(self) -> bool:
        return self.error is None and self.verdict_ok and not self.missing_facts and not self.unverified_cited


def _read(run_dir: Path, rel: str, adapter: TypeAdapter):
    try:
        return adapter.validate_python(json.loads((run_dir / rel).read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise GoldenError(f"no {rel}") from None
    except (json.JSONDecodeError, ValidationError) as e:
        raise GoldenError(f"invalid {rel}: {e}") from None


def check(golden_id: str, golden: GoldenIdea, run_id: str | None = None) -> Result:
    """Run the three checks for one golden idea on `run_id` (default: its latest run)."""
    run_id = run_id or latest_run(golden.idea)
    result = Result(golden_id, golden, run_id)
    if run_id is None:
        result.error = "no run with this idea text"
        return result
    run_dir = runs.run_dir(run_id)
    try:
        sheet = _read(run_dir, "04_scores.json", TypeAdapter(ScoreSheet))
        claims = _read(run_dir, "03_claims/verified.json", TypeAdapter(list[Claim]))
    except GoldenError as e:
        result.error = str(e)
        return result
    result.verdict, result.weighted_total = sheet.verdict, sheet.weighted_total
    for fact in golden.must_find:
        result.found[fact.fact] = [c.claim_id for c in claims if finds(fact, c)]
    by_id = {c.claim_id: c for c in claims}
    for cid in cited_claim_ids(sheet):
        claim = by_id.get(cid)
        if claim is None or claim.verification != "verified":
            result.unverified_cited.append(f"{cid} ({'unknown' if claim is None else claim.verification})")
    return result


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def summary(results: list[Result]) -> str:
    """The Markdown summary table, one row per golden idea, the failures, and the pass count."""
    lines = [
        "| golden idea | run | verdict | expected | verdict ok | must-find | unverified cited | result |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        total = len(r.golden.must_find)
        found = total - len(r.missing_facts)
        checked = r.error is None
        lines.append(
            "| "
            + " | ".join(
                _cell(c)
                for c in (
                    r.golden_id,
                    r.run_id or "-",
                    (f"{r.verdict} ({r.weighted_total:.2f})" if checked else "-"),
                    ", ".join(r.golden.expected_verdicts),
                    ("yes" if r.verdict_ok else "no") if checked else "-",
                    f"{found}/{total}" if checked else "-",
                    str(len(r.unverified_cited)) if checked else "-",
                    "PASS" if r.passed else "FAIL",
                )
            )
            + " |"
        )
    problems = []
    for r in results:
        if r.error:
            problems.append(f"- {r.golden_id}: {r.error}")
            continue
        if not r.verdict_ok:
            problems.append(f"- {r.golden_id}: verdict {r.verdict} not in {', '.join(r.golden.expected_verdicts)}")
        for fact in r.missing_facts:
            problems.append(f"- {r.golden_id}: must-find fact not among the verified claims: {fact}")
        if r.unverified_cited:
            problems.append(f"- {r.golden_id}: score sheet cites claims that are not verified: {', '.join(r.unverified_cited)}")
    if problems:
        lines += ["", "Failures:", *problems]
    lines += ["", f"passed: {sum(r.passed for r in results)} of {len(results)}"]
    return "\n".join(lines)
