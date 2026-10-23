"""Report rendering (IF-305, IF-306), end to end on fixture files.

The run is the score_run fixture (tests/fixtures/score_run/*.synthetic.json) plus
tests/fixtures/report/extra_claims.synthetic.json (funding and Rääkkylä claims in several
verification states) and two synthetic research files that supply Gaps sections. All are
synthetic (TICKETS.md plan note 14): invented URLs and values that exercise the logic.

The snapshot is tests/golden/report.synthetic.md. After a deliberate change to the report,
regenerate it with `IDEAFORGE_UPDATE_GOLDEN=1 uv run pytest tests/test_report.py` and review the diff.
"""

import json
import os
import re
import shutil
from datetime import UTC, datetime

import pytest
import render_report
import score_run
import yaml
from conftest import FIXTURES, REPO

from ideaforge import config, db, report, runs

RUN = "20261023-130000-sauna-cabins"
NOW = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
REPORT_FIXTURES = FIXTURES / "report"
GOLDEN = REPO / "tests" / "golden" / "report.synthetic.md"


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def scored(project):
    """A run at the end of stage 5 (score_run.py has written 04_scores.json); no report yet."""
    db.init()
    run_dir = runs.create_run_dir(RUN, "Sauna-and-lake cabins for remote workers")
    db.create_run(RUN, "Sauna-and-lake cabins", idea_id="sauna-cabins", stages=runs.STAGES)
    shutil.copy(FIXTURES / "spec.json", run_dir / "00_spec.json")
    shutil.copy(FIXTURES / "score_run" / "verified.synthetic.json", run_dir / "03_claims" / "verified.json")
    extra = json.loads((REPORT_FIXTURES / "extra_claims.synthetic.json").read_text(encoding="utf-8"))
    edit_json(run_dir / "03_claims" / "verified.json", lambda data: data.extend(extra))
    shutil.copy(FIXTURES / "score_run" / "04_scores_proposed.synthetic.json", run_dir / "04_scores_proposed.json")
    shutil.copy(FIXTURES / "score_run" / "04_risks.synthetic.json", run_dir / "04_risks.json")
    for md in (REPORT_FIXTURES / "02_research").iterdir():
        shutil.copy(md, run_dir / "02_research" / md.name)
    shutil.copy(FIXTURES / "status" / "usage.synthetic.jsonl", run_dir / "usage.jsonl")
    return run_dir


def rescore(run_dir):
    assert score_run.main([RUN]) == 0


def section(text, heading):
    """The body of a `## heading` section, up to the next `## `."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"no section {heading!r}"
    return m.group(1)


def subsection(text, heading):
    m = re.search(rf"^### {re.escape(heading)}\n(.*?)(?=^##+ |\Z)", text, re.M | re.S)
    assert m, f"no subsection {heading!r}"
    return m.group(1)


def render(run_dir):
    rescore(run_dir)
    return report.render(RUN, now=NOW).path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- snapshot


def test_fixture_claims_validate():
    from ideaforge import validate_file

    validate_file.validate_path(REPORT_FIXTURES / "extra_claims.synthetic.json", "claims")


def test_report_matches_the_snapshot(scored):
    text = render(scored)
    if os.environ.get("IDEAFORGE_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    assert GOLDEN.is_file(), f"missing {GOLDEN}; see this module's docstring"
    assert text == GOLDEN.read_text(encoding="utf-8")


def test_report_has_every_section_in_order(scored):
    text = render(scored)
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert [h.split(":")[0] for h in headings] == [
        "Verdict", "Score table", "Kill triggers", "Unit economics", "Dimensions",
        "Finland funding fit", "Rääkkylä location notes", "Risk register", "Sources", "Usage summary",
    ]  # fmt: skip
    dims = re.findall(r"^### .*\(`(\w+)`\)$", section(text, "Dimensions"), re.M)
    assert dims == [*(d.id for d in config.rubric().dimensions), "killcause"]


def test_report_stage_output_is_complete_and_row_is_stored(scored, capsys):
    rescore(scored)
    capsys.readouterr()
    assert render_report.main([RUN]) == 0
    out = capsys.readouterr().out
    assert f"wrote runs/{RUN}/05_report.md" in out
    assert runs.output_problems(RUN, "report") == []
    row = db.get_report(RUN)
    sheet = json.loads((scored / "04_scores.json").read_text(encoding="utf-8"))
    assert row["path"] == f"runs/{RUN}/05_report.md"
    assert row["verdict"] == sheet["verdict"] and row["weighted_total"] == sheet["weighted_total"]
    assert f"verdict: {sheet['verdict']}" in out


# ---------------------------------------------------------------- caps


def test_dimension_under_three_sources_is_capped_at_two_with_a_label(scored):
    # customer cites three verified claims on three domains; drop one → two independent sources
    edit_json(scored / "04_scores_proposed.json", lambda data: data["scores"][0].__setitem__(
        "supporting_claim_ids", ["customer-001", "customer-002"]))  # fmt: skip
    text = render(scored)
    row = next(line for line in section(text, "Score table").splitlines() if line.startswith("| `customer`"))
    cells = [c.strip() for c in row.strip("|").split(" | ")]
    assert cells[2:4] == ["4", "2"]  # proposed 4, final 2
    assert "**capped at 2**: insufficient data (min_sources: 2 of 3 independent source domains)" in cells[4]
    body = subsection(section(text, "Dimensions"), "Customer & problem (JTBD) (`customer`)")
    assert "Score: 2 of 5 (proposed 4), **capped at 2**: insufficient data (min_sources: 2 of 3" in body
    capped = re.search(r"Capped at 2 for missing evidence: ([^.]*)\.", text)
    assert capped and "customer" in capped.group(1).split(", ")


def test_capped_proposal_at_or_below_two_still_carries_the_label(scored):
    text = render(scored)
    # the fixture's founder_risk cites only an unknown id: zeroed and capped
    row = next(line for line in section(text, "Score table").splitlines() if line.startswith("| `founder_risk`"))
    assert "**capped at 2**" in row


# ---------------------------------------------------------------- Finland funding fit


def finland_values():
    """Every scalar in config/finland.yaml that is not a description: the hints the report must
    never show as facts."""
    out = set()

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif node is not None and key not in ("description", "verify_at_runtime"):
            out.add(str(node))

    walk(yaml.safe_load((config.CONFIG_DIR / "finland.yaml").read_text(encoding="utf-8"))["hints"])
    return out


def test_funding_backed_only_by_verified_official_claims(scored):
    funding = section(render(scored), "Finland funding fit")
    starttiraha = subsection(funding, "Starttiraha (start-up grant)")
    assert "- `financing-004`: Starttiraha can be granted" in starttiraha
    assert "> synthetic starttiraha quote" in starttiraha
    assert "(<https://tyomarkkinatori.fi/synthetic/starttiraha>)" in starttiraha
    assert report.UNVERIFIED_GAP not in starttiraha
    finnvera = subsection(funding, "Finnvera loans and guarantees")
    assert f"**{report.UNVERIFIED_GAP}**" in finnvera
    assert "Not counted: `financing-005` (unverified)" in finnvera
    leader = subsection(funding, "Leader (Jetina)")
    assert f"**{report.UNVERIFIED_GAP}**" in leader
    assert "Not counted: `financing-006` (not on an allow-listed official domain)" in leader
    assert "- No official page found on Leader (Jetina) funding" in subsection(funding, "Funding gaps (financing research)")


def synthetic_claim(claim_id, statement, url, **fields):
    return {
        "claim_id": claim_id, "dimension": claim_id.rsplit("-", 1)[0], "statement": statement,
        "source_url": url, "source_title": "Synthetic page", "quote": "synthetic quote",
        "retrieved_at": "2026-10-23T10:36:00+00:00", "source_type": "official", "confidence": 0.8,
        "verification": "verified",
    } | fields  # fmt: skip


def test_off_topic_official_claims_never_back_a_programme(scored):
    off_topic = [
        synthetic_claim("regulation-005", "A shoreline building permit is applied for from the ELY-keskus.",
                        "https://www.elinvoimakeskus.fi/synthetic/shoreline-permit"),
        synthetic_claim("competition-005", "The market leader in cabin rentals is registered in Joensuu.",
                        "https://www.ytj.fi/synthetic/market-leader"),
        synthetic_claim("regulation-006", "Starttiraha is taxable income.", "https://www.vero.fi/synthetic/starttiraha-tax"),
        synthetic_claim("location-005", "Finnvera has an office in Joensuu.", "https://www.finnvera.fi/synthetic/office"),
    ]  # fmt: skip
    edit_json(scored / "03_claims" / "verified.json", lambda data: data.extend(off_topic))
    funding = section(render(scored), "Finland funding fit")
    for name in ("Leader (Jetina)", "Elinvoimakeskus business development grants", "Finnvera loans and guarantees"):
        assert f"**{report.UNVERIFIED_GAP}**" in subsection(funding, name), name
    for cid in ("regulation-005", "competition-005", "regulation-006", "location-005"):
        assert cid not in funding, cid
    assert "`financing-004`" in subsection(funding, "Starttiraha (start-up grant)")  # the financing claim still backs it


def test_financing_claim_on_a_programme_site_backs_it(scored):
    claim = synthetic_claim("financing-007", "Business development grants support new small companies.",
                            "https://www.elinvoimakeskus.fi/synthetic/grants")  # fmt: skip
    edit_json(scored / "03_claims" / "verified.json", lambda data: data.append(claim))
    body = subsection(section(render(scored), "Finland funding fit"), "Elinvoimakeskus business development grants")
    assert "- `financing-007`: Business development grants support new small companies." in body
    assert report.UNVERIFIED_GAP not in body


def test_funding_gap_never_shows_a_finland_yaml_value(scored):
    # no claim about any programme: every item is a gap
    edit_json(scored / "03_claims" / "verified.json", lambda data: data.__setitem__(
        slice(None), [c for c in data if c["claim_id"] not in ("financing-004", "financing-005", "financing-006")]))  # fmt: skip
    funding = section(render(scored), "Finland funding fit")
    for p in report.PROGRAMMES:
        body = subsection(funding, p.name)
        assert f"- **{report.UNVERIFIED_GAP}**: no verified financing claim on an official domain covers this." in body
        assert "Not counted" not in body
    values = finland_values()
    assert {"20000", "25.5", "12", "https://tyomarkkinatori.fi/", "https://www.jetina.fi/"} <= values
    for value in values - {"Jetina", "Rääkkylä", "Pohjois-Karjala", "Keski-Karjala"}:  # names in fixed headings / gaps
        assert value not in funding, f"funding section shows the finland.yaml hint {value!r}"


def test_report_never_reads_finland_yaml():
    source = (REPO / "src" / "ideaforge" / "report.py").read_text(encoding="utf-8")
    template = (REPO / "src" / "ideaforge" / "templates" / "report.md.j2").read_text(encoding="utf-8")
    assert "finland()" not in source and "finland.yaml\"" not in source
    assert "finland" not in template.lower().replace("finland funding fit", "")


# ---------------------------------------------------------------- Rääkkylä, kill triggers, sources


def test_location_notes_list_verified_local_claims_and_gaps(scored):
    notes = section(render(scored), "Rääkkylä location notes")
    assert "- `location-004`: Rääkkylä has a synthetic number of summer residents (3000 persons)." in notes
    assert "- `location-001`" in notes
    assert "`gtm-004` (conflict)" in notes  # names North Karelia, not verified
    assert "- No data on broadband coverage by village in Rääkkylä." in notes


def test_fired_kill_trigger_shows_its_evidence(scored):
    edit_json(scored / "03_claims" / "verified.json", lambda data: data[0]["flags"].append("permit_impossible"))
    text = render(scored)
    assert "## Verdict: NO_GO" in text
    assert "Kill trigger(s) fired: permit_impossible." in section(text, "Verdict: NO_GO")
    assert "| `permit_impossible` | **fired** | customer-001 | killcause-002 (unverified) |" in text


def test_overridden_trigger_is_listed_as_overridden(scored):
    edit_json(scored / "03_claims" / "verified.json", lambda data: data[0]["flags"].append("permit_impossible"))
    edit_json(scored / "00_spec.json", lambda data: data.__setitem__("kill_trigger_overrides", ["permit_impossible"]))
    text = render(scored)
    assert "| `permit_impossible` | overridden in the spec | customer-001 |" in text
    assert "Overridden by the founder in the spec: permit_impossible." in text


def test_table_cells_escape_pipes(scored):
    sources = section(render(scored), "Sources")
    assert "[Synthetic (blog) about Leader](<https://example.net/synthetic/leader-blog>)" in sources
    unfetched = next(line for line in sources.splitlines() if "finnvera.fi/synthetic" in line)
    assert "unverified ×1; unfetchable" in unfetched and "| yes |" in unfetched


def test_missing_research_file_is_a_gap_not_an_error(scored):
    body = subsection(section(render(scored), "Dimensions"), "Market size (bottom-up beachhead) (`market`)")
    assert "- No research file for this dimension." in body


# ---------------------------------------------------------------- immutability and errors


def test_overwrite_is_refused(scored, capsys):
    rescore(scored)
    assert render_report.main([RUN]) == 0
    first = (scored / "05_report.md").read_bytes()
    capsys.readouterr()
    assert render_report.main([RUN]) == 1
    assert "already exists; reports are immutable" in capsys.readouterr().err
    assert (scored / "05_report.md").read_bytes() == first
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reports WHERE run_id=?", (RUN,)).fetchone()[0] == 1


def test_report_row_without_file_still_refuses(scored, capsys):
    rescore(scored)
    assert render_report.main([RUN]) == 0
    (scored / "05_report.md").unlink()
    capsys.readouterr()
    assert render_report.main([RUN]) == 1
    assert "already has a report row" in capsys.readouterr().err
    assert not (scored / "05_report.md").exists()


def test_failed_write_leaves_no_row_and_no_file(scored, monkeypatch):
    rescore(scored)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(report.os, "link", boom)
    with pytest.raises(OSError):
        report.render(RUN, now=NOW)
    assert db.get_report(RUN) is None and not (scored / "05_report.md").exists()
    assert not list(scored.glob(".05_report.md.*"))


def test_needs_the_score_sheet(scored, capsys):
    assert render_report.main([RUN]) == 1  # score_run.py has not run
    assert "04_scores.json does not exist" in capsys.readouterr().err
    assert not (scored / "05_report.md").exists() and db.get_report(RUN) is None


@pytest.mark.parametrize("run_id", ["not-a-run", "20261023-130000-unknown"])
def test_unknown_run(project, capsys, run_id):
    assert render_report.main([run_id]) == 1
    assert "error:" in capsys.readouterr().err


def test_run_only_on_disk_is_refused(project, capsys):
    runs.create_run_dir(RUN, "x")
    assert render_report.main([RUN]) == 1
    assert "not in the database" in capsys.readouterr().err


# ---------------------------------------------------------------- verdict paragraph (unit)


def sheet(total, verdict, *, capped=0, fired=(), ue=None):
    from ideaforge.schemas import DimensionScore, ScoreSheet, UnitEconomics

    scores = [
        DimensionScore(
            dimension=d, proposed_score=3, justification="synthetic", final_score=2 if i < capped else 3,
            status="insufficient_data" if i < capped else "scored", cap_reason="synthetic" if i < capped else None,
        )
        for i, d in enumerate(d.id for d in config.rubric().dimensions)
    ]  # fmt: skip
    return ScoreSheet(
        scores=scores, weighted_total=total, kill_triggers_fired=list(fired), verdict=verdict,
        unit_economics=ue or UnitEconomics(missing_inputs=["price"]),
    )  # fmt: skip


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((3.0, "PIVOT"), "No kill trigger fired and the weighted total is 3.00 of 5 (GO ≥ 3.5, PIVOT ≥ 2.5). That is PIVOT"),
        ((2.0, "NO_GO"), "No kill trigger fired, but the weighted total is 2.00 of 5 (GO ≥ 3.5, PIVOT ≥ 2.5). That is below PIVOT."),
        ((2.6, "INSUFFICIENT_DATA", 3), "3 of 10 dimensions lack the evidence their rubric rules require (at most 2 may)"),
    ],
)
def test_why_follows_the_verdict_precedence(args, expected):
    total, verdict, *capped = args
    text = report.why(sheet(total, verdict, capped=capped[0] if capped else 0), config.rubric(), 10)
    assert text.startswith(expected)
    assert "Unit economics incomplete: missing price." in text
    assert "Note:" not in text


def test_why_flags_a_verdict_the_rubric_would_not_give():
    text = report.why(sheet(3.0, "GO"), config.rubric(), 10)
    assert text.endswith("Note: 04_scores.json says GO, but the current rubric gives PIVOT; re-run score_run.py.")


def test_computed_trigger_and_missing_sensitivity():
    s = sheet(3.0, "NO_GO", fired=["negative_contribution_margin"])
    rows = {r["trigger"]: r for r in report.kill_trigger_rows(s, [], [])}
    assert rows["negative_contribution_margin"]["state"] == "**fired**"
    assert rows["negative_contribution_margin"]["evidence"] == "computed: contribution margin below 0"
    assert report.sensitivity_grid(s) is None


def test_research_gaps_without_a_gaps_section(tmp_path):
    (tmp_path / "02_research").mkdir()
    (tmp_path / "02_research" / "gtm.md").write_text("# GTM\n\nNo gaps heading.\n", encoding="utf-8")
    assert report.research_gaps(tmp_path, "gtm") == []
    assert report.research_gaps(tmp_path, "pricing") is None


def test_fired_trigger_without_evidence_is_called_stale():
    s = sheet(3.0, "NO_GO", fired=["permit_impossible"])
    rows = {r["trigger"]: r for r in report.kill_trigger_rows(s, [], [])}
    assert rows["permit_impossible"]["evidence"].startswith("no verified claim carries it now")


def test_multi_line_quote_stays_in_its_block_quote(scored):
    edit_json(scored / "03_claims" / "verified.json", lambda data: next(
        c for c in data if c["claim_id"] == "financing-004").__setitem__("quote", "first line\nsecond line"))  # fmt: skip
    assert "  > first line second line\n" in section(render(scored), "Finland funding fit")
