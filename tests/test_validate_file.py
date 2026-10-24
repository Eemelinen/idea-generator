import shutil

import pytest

from conftest import FIXTURES
from ideaforge import validate_file as vf

RESEARCH_FIXTURE = FIXTURES / "02_research" / "pricing.md"


def research_file(tmp_path, text=None):
    path = tmp_path / "02_research" / "pricing.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else RESEARCH_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_research_fixture_is_valid():
    claims = vf.validate_research(RESEARCH_FIXTURE)
    assert [c.claim_id for c in claims] == ["pricing-001"]


def test_research_missing_sections(tmp_path):
    text = RESEARCH_FIXTURE.read_text(encoding="utf-8").replace("## Gaps", "## Other")
    with pytest.raises(vf.Invalid, match="Gaps"):
        vf.validate_research(research_file(tmp_path, text))


def test_research_bad_json(tmp_path):
    text = RESEARCH_FIXTURE.read_text(encoding="utf-8").replace('"flags": []', '"flags": [],')
    with pytest.raises(vf.Invalid, match="does not parse"):
        vf.validate_research(research_file(tmp_path, text))


def test_research_wrong_dimension(tmp_path):
    text = RESEARCH_FIXTURE.read_text(encoding="utf-8").replace('"dimension": "pricing"', '"dimension": "market"')
    with pytest.raises(vf.Invalid):
        vf.validate_research(research_file(tmp_path, text))


def test_research_word_limit(tmp_path):
    with pytest.raises(vf.Invalid, match="words"):
        vf.validate_research(research_file(tmp_path), max_words=20)


def word_problem(path):
    try:
        vf.validate_research(path, seen=None)
    except vf.Invalid as e:
        return "words" in str(e)
    return False


@pytest.mark.parametrize("preset,too_long", [(None, True), ("standard", True), ("deep", False), ("nope", True)])
def test_research_word_limit_follows_the_run_preset(tmp_path, preset, too_long):
    # 1400 words of summary: over the standard limit (1200), under deep (1600).
    text = RESEARCH_FIXTURE.read_text(encoding="utf-8").replace("\n## ", "\n" + "word " * 1400 + "\n\n## ", 1)
    path = research_file(tmp_path, text)
    if preset:
        (tmp_path / "meta.json").write_text(f'{{"budget_preset": "{preset}"}}', encoding="utf-8")
    assert word_problem(path) is too_long


def test_research_requires_claim_blocks(tmp_path):
    text = "# pricing\n\n## Candidate claims\n\nnone\n\n## Gaps\n\n- everything\n"
    with pytest.raises(vf.Invalid, match="no ```json"):
        vf.validate_research(research_file(tmp_path, text))


@pytest.mark.parametrize("rel,kind", [
    ("runs/r/00_spec.json", "spec"),
    ("runs/r/01_plan.json", "plan"),
    ("runs/r/02_research/gtm.md", "research"),
    ("runs/r/03_claims/gtm.json", "claims"),
    ("runs/r/03_claims/verified.json", "claims"),
    ("runs/r/03_claims/conflicts.json", "conflicts"),
    ("runs/r/04_scores_proposed.json", "scores_proposed"),
    ("runs/r/debate/round0/investor.json", "position"),
    ("runs/r/debate/round2/investor.json", "rebuttal"),
    ("runs/r/debate/round2/interim_scores.json", "interim_scores"),
    ("runs/r/debate/verdict.json", "verdict"),
])
def test_infer_kind(rel, kind, tmp_path):
    assert vf.infer_kind(tmp_path / rel) == kind


def test_cli_validates_json(tmp_path):
    target = tmp_path / "runs" / "r" / "00_spec.json"
    target.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "spec.json", target)
    assert vf.main([str(target)]) == 0
    target.write_text('{"title": "x"}', encoding="utf-8")
    assert vf.main([str(target)]) == 1


# ---------------------------------------------------------------- hook mode


def test_auto_without_active_run_is_noop(project):
    assert vf.auto({"agent_type": "research-pricing"}, stop=False) == 0


def test_auto_ignores_unknown_agents(active_run):
    assert vf.auto({"agent_type": "general-purpose"}, stop=False) == 0


def test_auto_ignores_the_harness_evaluator(active_run):
    assert vf.auto({"agent_id": "e", "agent_type": "harness:evaluator"}, stop=False) == 0
    assert not list(active_run.glob("VALIDATION_FAILED_*"))


def test_auto_blocks_once_then_records_failure(active_run):
    hook = {"agent_id": "a", "agent_type": "research-pricing"}
    with pytest.raises(SystemExit) as exc:
        vf.auto(hook, stop=False)
    assert exc.value.code == 2

    assert vf.auto(hook | {"stop_hook_active": True}, stop=False) == 0
    marker = active_run / "VALIDATION_FAILED_research-pricing"
    assert "does not exist" in marker.read_text(encoding="utf-8")

    shutil.copy(RESEARCH_FIXTURE, active_run / "02_research" / "pricing.md")
    with pytest.raises(SystemExit):
        vf.auto(hook, stop=False)  # the cited URL is not in the run's .seen_urls.txt yet
    shutil.copy(FIXTURES / ".seen_urls.txt", active_run / ".seen_urls.txt")
    assert vf.auto(hook, stop=False) == 0
    assert not marker.exists()


def test_auto_debate_agent_validates_latest_round(active_run):
    hook = {"agent_id": "a", "agent_type": "debate-investor"}
    with pytest.raises(SystemExit):
        vf.auto(hook, stop=False)  # nothing written yet
    (active_run / "debate" / "round0").mkdir()
    shutil.copy(FIXTURES / "position.json", active_run / "debate" / "round0" / "investor.json")
    assert vf.auto(hook, stop=False) == 0
    (active_run / "debate" / "round1").mkdir()
    (active_run / "debate" / "round1" / "investor.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        vf.auto(hook, stop=False)


def test_auto_synthesizer_validates_both_files(active_run):
    hook = {"agent_id": "a", "agent_type": "synthesizer"}
    with pytest.raises(SystemExit):
        vf.auto(hook, stop=False)  # nothing written yet
    shutil.copy(FIXTURES / "scores_proposed.json", active_run / "04_scores_proposed.json")
    with pytest.raises(SystemExit):
        vf.auto(hook, stop=False)  # 04_risks.json is still missing
    shutil.copy(FIXTURES / "risks.json", active_run / "04_risks.json")
    assert vf.auto(hook, stop=False) == 0
    (active_run / "04_risks.json").write_text('{"risks": [{"risk": "no fields"}]}', encoding="utf-8")
    assert vf.auto(hook | {"stop_hook_active": True}, stop=False) == 0
    assert "04_risks.json is not a valid risks" in (active_run / "VALIDATION_FAILED_synthesizer").read_text(
        encoding="utf-8"
    )


def test_auto_stop_validates_existing_stage_files(active_run):
    assert vf.auto({}, stop=True) == 0
    (active_run / "00_spec.json").write_text('{"title": "only"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        vf.auto({}, stop=True)
    shutil.copy(FIXTURES / "spec.json", active_run / "00_spec.json")
    assert vf.auto({}, stop=True) == 0


# ---------------------------------------------------------------- prose and provenance rules
# Synthetic research files (example.fi URLs, made-up figures) for the IF-205 rules.

URL = "https://example.fi/mokki-123"
CLAIM = """```json
[{{"claim_id": "pricing-001", "dimension": "pricing", "statement": "A cabin is listed at 650 EUR per week.",
  "value": 650, "unit": "EUR/week", "source_url": "{url}", "source_title": "Mökki", "quote": "Hinta 650 €",
  "published_date": null, "source_type": "vendor", "confidence": 0.7, "flags": []}}]
```"""


def doc(findings, summary="Cabins near the lake rent for 600–900 EUR a week.", claim_url=URL, extra=""):
    return (
        f"# pricing\n\n{summary}\n\n## Findings\n\n{findings}\n\n{extra}"
        f"## Candidate claims\n\n{CLAIM.format(url=claim_url)}\n\n## Gaps\n\n- No 2024 occupancy data for 12 cabins.\n"
    )


def check(tmp_path, text, seen=frozenset({URL})):
    warnings = []
    vf.validate_research(research_file(tmp_path, text), seen=set(seen), warnings=warnings)
    return warnings


Q = "\n> Hinta 650 € / viikko."
S = f"[src: {URL}]"

BARE_NUMBER_CASES = [
    # (id, findings, ok)
    ("figure-with-quote", f"A cabin is listed at 650 EUR per week {S}.{Q}", True),
    ("figure-without-quote", f"A cabin is listed at 650 EUR per week {S}.", False),
    ("quote-after-blank-line", f"A cabin is listed at 650 EUR per week {S}.\n{Q}", True),
    ("quote-not-right-after", f"A cabin is listed at 650 EUR per week {S}.\n\nIt has a sauna {S}.{Q}", False),
    ("two-figures-one-quote", f"A cabin costs 650 EUR {S}. Another costs 700 EUR {S}.{Q}", False),
    ("each-figure-own-quote", f"A cabin costs 650 EUR {S}.{Q}\n\nAnother costs 700 EUR {S}.\n> 700 €", True),
    ("decimal-percent", f"Occupancy is 1.5 % higher in July {S}.", False),
    ("finnish-thousands", f"The region had 3 000 visitors {S}.", False),
    ("list-item-without-quote", f"- A cabin costs 650 EUR {S}.\n- It has a sauna {S}.", False),
    ("list-item-with-quote", f"- A cabin costs 650 EUR {S}.\n  > Hinta 650 €\n- It has a sauna {S}.", True),
    ("season-with-a-count", f"The 2024/25 season had 40 bookings {S}.", False),
    ("year", f"The harbour opened in 2024 {S}.", True),
    ("year-range-and-season", f"Prices rose between 2019–2024 and in 2024/25 {S}.", True),
    ("iso-date", f"The page was updated on 2025-03-01 {S}.", True),
    ("finnish-date", f"The price list is valid from 1.6.2025 {S}.", True),
    ("month-year", f"The listing was posted in 3/2025 {S}.", True),
    ("english-day-month", f"Bookings open on 1 March 2025 and close March 31 {S}.", True),
    ("finnish-day-month", f"Varaukset alkavat 1. maaliskuuta 2025 {S}.", True),
    ("claim-id", f"See pricing-001 for the listed weekly price {S}.", True),
    ("identifiers", f"The B2B and Q1 offers target COVID-19 recovery {S}.", True),
    ("digits-only-in-url", f"The listing page is the main source {S}.", True),
    ("figure-in-inline-code", f"It costs `650 EUR` per week {S}.", False),
    ("currency-led-figure", f"It costs EUR650 per week {S}.", False),
    ("count-that-looks-like-a-year", f"Rääkkylä had 1900 residents {S}.", False),
    ("price-that-looks-like-a-year", f"Rent is 1950 EUR a month {S}.", False),
    ("visitors-that-look-like-a-year", f"The region had 2000 visitors {S}.", False),
    ("grew-to-is-not-a-year-context", f"Visitors grew to 2000 last summer {S}.", False),
    ("year-then-count", f"In 2024 there were 1900 residents {S}.", False),
    ("year-context-with-currency", f"The grant is paid in 2000 EUR instalments {S}.", False),
    ("since-year", f"Prices have risen since 2019 {S}.", True),
    ("year-list", f"The fair was held in 2023 and 2024 {S}.", True),
    ("parenthesised-year", f"The municipal strategy (2024) targets tourism {S}.", True),
    ("month-and-year", f"The listing was updated in March 2025 {S}.", True),
    ("finnish-year", f"Vuonna 2024 kunta avasi uuden sataman {S}.", True),
    ("finnish-case-ending", f"Kunnan 2024:n strategia painottaa matkailua {S}.", True),
    ("may-the-verb", f"Some 30 may be seasonal {S}.", False),
    ("may-the-month-then-count", f"In May 40 cabins were booked {S}.", False),
    ("extra-section-checked", f"It has a sauna {S}.", False),
]


@pytest.mark.parametrize("case,findings,ok", BARE_NUMBER_CASES, ids=[c[0] for c in BARE_NUMBER_CASES])
def test_bare_numbers(tmp_path, case, findings, ok):
    extra = f"## Notes\n\nThe owner has 12 cabins {S}.\n\n" if case == "extra-section-checked" else ""
    text = doc(findings, extra=extra)
    if ok:
        check(tmp_path, text)
    else:
        with pytest.raises(vf.Invalid, match="a figure without a '> quote' block"):
            check(tmp_path, text)


def test_summary_and_gaps_are_exempt_from_figure_rule(tmp_path):
    assert check(tmp_path, doc(f"A cabin is listed at 650 EUR per week {S}.{Q}")) == []


SRC_CASES = [
    # (id, findings, warns)
    ("with-src", f"The lakeside cabin market is busy in summer {S}.", False),
    ("src-after-period", f"The lakeside cabin market is busy in summer. {S}", False),
    ("without-src", "The lakeside cabin market is busy in summer.", True),
    ("second-sentence-without-src", f"Cabins are busy in summer {S}. Winter demand is much lower.", True),
    ("short-sentence", f"See below. Cabins are busy in summer {S}.", False),
    ("gap-sentence", "No data was found for Rääkkylä cabins.", False),
    ("could-not", "I could not find winter prices for the area.", False),
]


@pytest.mark.parametrize("case,findings,warns", SRC_CASES, ids=[c[0] for c in SRC_CASES])
def test_src_tag_warnings(tmp_path, case, findings, warns):
    warnings = check(tmp_path, doc(findings))  # warnings never fail the file
    assert bool(warnings) is warns
    assert all("without [src: …]" in w for w in warnings)


def test_has_figure():
    assert vf.has_figure("costs 650 EUR")
    assert not vf.has_figure("in 2024 [src: https://pxdata.stat.fi/x/11ra.px]")


PROVENANCE_CASES = [
    # (id, findings, claim_url, seen, ok)
    ("seen", f"A cabin has a sauna {S}.", URL, {URL}, True),
    ("unseen-src", "A cabin has a sauna [src: https://example.fi/invented].", URL, {URL}, False),
    ("unseen-claim-url", f"A cabin has a sauna {S}.", "https://example.fi/invented", {URL}, False),
    ("unseen-markdown-link", f"A cabin has a [sauna](https://example.fi/invented) {S}.", URL, {URL}, False),
    ("nothing-seen", f"A cabin has a sauna {S}.", URL, set(), False),
    ("trailing-slash-and-fragment", f"A cabin has a sauna [src: {URL}/#price].", URL, {URL}, True),
    ("backticks-and-bold", f"A cabin has a sauna [src: `{URL}`], see **{URL}** {S}.", URL, {URL}, True),
    ("statfin-api", "Residents [src: https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/11ra.px].",
     URL, {URL}, True),
    ("prh-api", "", "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?location=R%C3%A4%C3%A4kkyl%C3%A4",
     set(), True),
    ("luke-api", "", "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/x.px", set(), True),
    ("eurostat-api", "", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tour_occ",
     set(), True),
    ("not-an-api-path", "", "https://pxdata.stat.fi/PxWeb/pxweb/fi/StatFin/", set(), False),
]


@pytest.mark.parametrize("case,findings,claim_url,seen,ok", PROVENANCE_CASES, ids=[c[0] for c in PROVENANCE_CASES])
def test_url_provenance(tmp_path, case, findings, claim_url, seen, ok):
    text = doc(findings, claim_url=claim_url)
    if ok:
        check(tmp_path, text, seen)
    else:
        with pytest.raises(vf.Invalid, match="never appeared in research-pricing's"):
            check(tmp_path, text, seen)


def test_gaps_may_name_unvisited_sources(tmp_path):
    text = doc(f"A cabin has a sauna {S}.").replace(
        "- No 2024 occupancy data", "- Ask https://example.fi/never-fetched for 2024 occupancy data"
    )
    check(tmp_path, text)


def test_seen_urls_are_read_per_agent_from_the_run_dir(tmp_path):
    path = research_file(tmp_path)
    with pytest.raises(vf.Invalid, match="never appeared"):
        vf.validate_research(path)  # no .seen_urls.txt
    (tmp_path / ".seen_urls.txt").write_text(f"research-market\t{URL}\n", encoding="utf-8")
    with pytest.raises(vf.Invalid, match="never appeared"):
        vf.validate_research(path)  # another agent's URL
    (tmp_path / ".seen_urls.txt").write_text(f"research-market\t{URL}\nresearch-pricing\t{URL}.\n", encoding="utf-8")
    assert [c.claim_id for c in vf.validate_research(path)] == ["pricing-001"]


def test_seen_urls_use_the_agent_name_of_the_dimension(tmp_path):
    (tmp_path / ".seen_urls.txt").write_text(
        "research-founder-risk\thttps://a.fi/x\nresearch-pricing\thttps://b.fi/y\n", encoding="utf-8"
    )
    assert vf.seen_urls(tmp_path, "research-founder-risk") == {"https://a.fi/x"}


def test_cli_prints_warnings_but_passes(tmp_path, capsys):
    path = research_file(tmp_path, doc(f"Cabins are busy in summer {S}. Winter demand is much lower."))
    shutil.copy(FIXTURES / ".seen_urls.txt", tmp_path / ".seen_urls.txt")
    assert vf.main(["--kind", "research", str(path)]) == 0
    assert "warning: '## findings': a factual sentence without [src: …]" in capsys.readouterr().err


def test_auto_reports_warnings_without_blocking(active_run, capsys):
    shutil.copy(FIXTURES / ".seen_urls.txt", active_run / ".seen_urls.txt")
    (active_run / "02_research" / "pricing.md").write_text(
        doc(f"Cabins are busy in summer {S}. Winter demand is much lower."), encoding="utf-8"
    )
    hook = {"agent_id": "a", "agent_type": "research-pricing"}
    assert vf.auto(hook, stop=False) == 0
    assert "Warnings (not blocking)" in capsys.readouterr().err
    marker = active_run / "VALIDATION_WARNINGS_research-pricing"
    assert "without [src: …]" in marker.read_text(encoding="utf-8")

    shutil.copy(RESEARCH_FIXTURE, active_run / "02_research" / "pricing.md")
    assert vf.auto(hook, stop=False) == 0
    assert not marker.exists()


def test_judge_output_is_its_latest_interim_until_the_verdict(tmp_path):
    from ideaforge import agents

    judge = agents.get("debate-judge")
    debate_dir = tmp_path / "debate"
    assert agents.latest_debate_output(tmp_path, judge) is None
    for n in (1, 2):
        (debate_dir / f"round{n}").mkdir(parents=True)
        (debate_dir / f"round{n}" / "interim_scores.json").write_text("{}", encoding="utf-8")
    (debate_dir / "round2" / "founder.json").write_text("{}", encoding="utf-8")
    assert agents.latest_debate_output(tmp_path, judge) == debate_dir / "round2" / "interim_scores.json"
    (debate_dir / "verdict.json").write_text("{}", encoding="utf-8")
    assert agents.latest_debate_output(tmp_path, judge) == debate_dir / "verdict.json"
    assert agents.latest_debate_output(tmp_path, agents.get("debate-founder")) == debate_dir / "round2" / "founder.json"


def test_auto_research_agent_validates_its_running_mini_research_file(active_run):
    from test_guard import open_mini_task

    open_mini_task(active_run)
    hook = {"agent_id": "a", "agent_type": "research-pricing"}
    with pytest.raises(SystemExit):
        vf.auto(hook | {"stop_hook_active": False}, stop=False)
    assert vf.auto(hook | {"stop_hook_active": True}, stop=False) == 0
    assert "mini-1-pricing.md does not exist" in (active_run / "VALIDATION_FAILED_research-pricing.mini-1").read_text(
        encoding="utf-8"
    )
    shutil.copy(FIXTURES / ".seen_urls.txt", active_run / ".seen_urls.txt")
    shutil.copy(RESEARCH_FIXTURE, active_run / "02_research" / "mini-1-pricing.md")
    assert vf.auto(hook, stop=False) == 0  # dimension taken from the name, pricing-001 is still free


def test_mini_research_file_may_not_reuse_a_ledger_claim_id(active_run):
    shutil.copy(FIXTURES / ".seen_urls.txt", active_run / ".seen_urls.txt")
    mini = active_run / "02_research" / "mini-1-pricing.md"
    shutil.copy(RESEARCH_FIXTURE, mini)
    vf.validate_research(mini)
    shutil.copy(RESEARCH_FIXTURE, active_run / "02_research" / "pricing.md")
    with pytest.raises(vf.Invalid, match="already in the run's ledger: pricing-001"):
        vf.validate_research(mini)
    (active_run / "02_research" / "pricing.md").unlink()
    (active_run / "03_claims" / "verified.json").write_text('[{"claim_id": "pricing-001"}]', encoding="utf-8")
    with pytest.raises(vf.Invalid, match="already in the run's ledger: pricing-001"):
        vf.validate_research(mini)
    # its own claims, once verified, are not "elsewhere"
    (active_run / "03_claims" / "mini-1-pricing.json").write_text('[{"claim_id": "pricing-001"}]', encoding="utf-8")
    vf.validate_research(mini)


def test_mini_research_validation_markers_do_not_touch_stage_2_markers(active_run):
    from test_guard import open_mini_task

    stage2 = active_run / "VALIDATION_FAILED_research-pricing"
    stage2.write_text("stage-2 failure\n", encoding="utf-8")
    open_mini_task(active_run)
    hook = {"agent_id": "a", "agent_type": "research-pricing", "stop_hook_active": True}
    assert vf.auto(hook, stop=False) == 0  # no mini file: recorded under the task's own name
    assert "mini-1-pricing.md" in (active_run / "VALIDATION_FAILED_research-pricing.mini-1").read_text(encoding="utf-8")
    shutil.copy(FIXTURES / ".seen_urls.txt", active_run / ".seen_urls.txt")
    shutil.copy(RESEARCH_FIXTURE, active_run / "02_research" / "mini-1-pricing.md")
    assert vf.auto(hook, stop=False) == 0
    assert not (active_run / "VALIDATION_FAILED_research-pricing.mini-1").exists()
    assert stage2.read_text(encoding="utf-8") == "stage-2 failure\n"
