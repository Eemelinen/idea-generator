"""The debate tab, review form and trend, and run comparison in the UI (IF-606), on synthetic runs:
a finished debate (test_revised_plan's `debated` run with a validated, conforming round 1, an
interim projection and the rendered revised plan), debates stopped mid-round (test_debate's
helpers), and test_status's v1/v2 pair for reviews and the diff. Every file and row is synthetic
(TICKETS.md plan note 14); nothing touches the network."""

import re
import shutil

import pytest
import render_report
from conftest import DEBATE_RUN, FIXTURES, debate_position
from fastapi.testclient import TestClient
from test_debate import MINI_MAP, MINI_SEED, debating, plain, request, write_role  # noqa: F401  (debating is a fixture)
from test_report import scored  # noqa: F401  (a fixture)
from test_revised_plan import MAP, RUN, debate_round, debated  # noqa: F401  (debated is a fixture)
from test_status import RUN_V1, RUN_V2, make_run, version_pair  # noqa: F401  (version_pair is a fixture)

from ideaforge import debate, mini_research, review, revised_plan, status
from ideaforge.schemas import PERSONAS, Verdict
from ideaforge.web import create_app

LOCAL = "http://127.0.0.1:8765"
ROLE_RE = re.compile(rf"(?<![\w-])({'|'.join(PERSONAS)})(?![\w-])")
AGREEING = ("investor", "customer", "accountant")  # with the founder: 4 of 5 behind one change


@pytest.fixture
def client(project):
    return TestClient(create_app(project), base_url=LOCAL)  # POSTs need a loopback Host (IF-607)


def attrs(html, attr):
    return re.findall(rf'{attr}="([^"]+)"', html)


def section(html, element_id):
    m = re.search(rf'<section[^>]*id="{element_id}"[^>]*>(.*?)</section>', html, re.S)
    assert m, f"no section {element_id!r}"
    return m.group(1)


def cells(html, attr):
    """{attr value: [cell text, …]} for every `<tr attr="…">` row."""
    return {
        key: [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td>(.*?)</td>", row, re.S)]
        for key, row in re.findall(rf'<tr {attr}="([^"]+)"[^>]*>(.*?)</tr>', html, re.S)
    }


def text_rows(text, keys):
    """The rows of a /status text table whose first column is one of `keys`, split into cells."""
    return {
        cols[0]: cols
        for line in text.splitlines()
        if (cols := re.split(r"\s{2,}", line.strip()))[0] in keys and len(cols) > 1
    }


# ---------------------------------------------------------------- debate tab: finished


@pytest.fixture
def finished(debated):
    debate_round(debated, agreeing=AGREEING)
    debate.anonymize(RUN, 1)
    (debated / "debate" / "round1" / debate.INTERIM_NAME).write_text(
        '{"round": 1, "projected_scores": {"market": 3.5, "pricing": 3.0}}', encoding="utf-8"
    )
    assert render_report.main([RUN, "--debate"]) == 0
    return debated


def test_finished_debate(finished, client):
    resp = client.get(f"/runs/{RUN}/debate")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="next-step">next: done<' in html
    assert attrs(html, "data-round") == ["0", "1"]
    # round 0 as the judge saw it, in P-id order, with the roles shown now that the verdict exists
    round0 = section(html, "round-0")
    assert attrs(round0, "data-position") == [f"P{i}" for i in range(1, 6)]
    for role, pid in MAP.items():
        assert f'<strong>{pid}</strong> <span class="muted">({role})</span>' in html
    assert "Synthetic change fo." in round0 and 'href="/runs/' in round0  # claim ids are linked
    # round 1: the rebuttals' responses and the judge's interim projection
    round1 = section(html, "round-1")
    agreeing = re.findall(rf'<tr data-target="{MAP["founder"]}"><td>{MAP["founder"]}</td><td>agree</td>', round1)
    assert len(agreeing) == len(AGREEING)
    assert "computation:" in round1 and "evidence gap: Synthetic gap." in round1
    assert cells(round1, "data-dimension") == {"market": ["market", "3.50"], "pricing": ["pricing", "3.00"]}
    # the computed conformity flag, prominently, with the judge's disagreement
    assert 'id="conformity-flag"' in html
    assert "The judge wrote <code>conformity_flag: false</code>" in html


def test_finished_debate_verdict_assumptions_experiments_and_plan(finished, client):
    html = client.get(f"/runs/{RUN}/debate").text
    verdict = Verdict.model_validate_json((finished / "debate" / "verdict.json").read_bytes())
    part = section(html, "verdict")
    for c in (*verdict.accepted_changes, *verdict.rejected_changes):
        assert c.change in part and c.reason in part
    assert '<a href="/runs/{}/claims#claim-market-001">market-001</a>'.format(RUN) in part
    assert "market-999?" in part  # a rejected change's unknown id is marked
    for a in verdict.assumption_register:
        assert f"<td>{a.assumption}</td><td>{a.evidence_state}</td>" in part
    # experiments by info value per cost, as in the revised plan
    expected = [e.name for e in revised_plan.experiment_order(verdict.experiments)]
    assert attrs(part, "data-experiment") == expected
    assert expected[0] == "Remote-work forum post"  # free and the most informative free one
    plan_part = section(html, "revised-plan")
    assert "<h1>" in plan_part and "Conformity flag" in plan_part
    assert f"/runs/{RUN}/raw/debate/revised_plan.md" in plan_part


def test_verdict_before_the_plan_shows_the_computed_flag(debated, client):
    debate_round(debated, agreeing=AGREEING)
    html = client.get(f"/runs/{RUN}/debate").text
    assert 'id="next-step">next: render<' in html
    assert 'id="conformity-flag"' in html and "the computed flag is shown" in html
    assert 'id="revised-plan"' not in html and "render_report.py --debate" in html


def test_judge_flag_without_conformity_is_not_a_banner(debated, client):
    debate_round(debated)
    path = debated / "debate" / "verdict.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"conformity_flag": false', '"conformity_flag": true'))
    html = client.get(f"/runs/{RUN}/debate").text
    assert 'id="conformity-flag"' not in html and 'id="judge-flag-corrected"' in html


def test_invalid_verdict_is_reported_not_a_500(debated, client):
    debate_round(debated)
    (debated / "debate" / "verdict.json").write_text('{"accepted_changes": []}', encoding="utf-8")
    resp = client.get(f"/runs/{RUN}/debate")
    assert resp.status_code == 200
    assert "debate/verdict.json is not valid" in resp.text and 'id="verdict"' not in resp.text


# ---------------------------------------------------------------- debate tab: stopped mid-round


@pytest.fixture
def midround(debating):
    """Round 1 validated with two rejections (both re-prompted, one of them for naming the wrong
    role) and the operator's mini-research request open as task 1."""
    (debating / "05_report.md").write_text("# Synthetic report\n", encoding="utf-8")
    debate.write_evidence(DEBATE_RUN, seed=MINI_SEED)
    bad = {"target_position_id": MINI_MAP["investor"], "stance": "agree", "basis": {"evidence_gap": "Synthetic."}}
    for role in PERSONAS:
        data = plain(role, 1)
        if role == "founder":
            data = {"role": "founder", "round": 1, "responses": [bad]}
        elif role == "accountant":
            data = plain("operator", 1)  # the accountant's file names another role
        elif role == "operator":
            data = plain(role, 1, mini_research=request(role))
        write_role(debating, 1, role, data)
    result = debate.validate_round(DEBATE_RUN, 1)
    assert sorted(result.rejected) == ["accountant", "founder"]
    assert debate.reprompt(DEBATE_RUN, 1)[0] == ["founder", "accountant"]
    assert mini_research.open_task(DEBATE_RUN, 1).n == 1
    return debating


def test_midround_debate_hides_roles(midround, client):
    resp = client.get(f"/runs/{DEBATE_RUN}/debate")
    assert resp.status_code == 200
    html = resp.text
    assert debate.progress(DEBATE_RUN).line() == "next: mini-research round 1"
    assert 'id="next-step">next: mini-research round 1<' in html and "task 1 is running" in html
    assert "roles as P-ids until the verdict" in html
    # round 0 anonymized; round 1 validated but not anonymized yet
    assert attrs(section(html, "round-0"), "data-position") == [f"P{i}" for i in range(1, 6)]
    round1 = section(html, "round-1")
    assert "Not anonymized yet: 5 of 5 persona files written." in round1
    # rejected turns by P-id, their reasons with every role name replaced by its P-id
    rejected = re.findall(r'<tr class="rejected"><td>(P\d)</td>', round1)
    assert sorted(rejected) == sorted([MINI_MAP["founder"], MINI_MAP["accountant"]])
    assert f"role is &#39;{MINI_MAP['operator']}&#39; but the file belongs to &#39;{MINI_MAP['accountant']}&#39;" in round1
    assert f"Re-prompted once: {', '.join(sorted([MINI_MAP['founder'], MINI_MAP['accountant']]))}." in round1
    # the mini-research task, requested by a P-id, its claims not verified yet
    assert 'data-task="1"' in round1 and "market · running" in round1
    assert f"Requested by {MINI_MAP['operator']}: Synthetic question?" in round1 and "none yet" in round1
    # no role name anywhere on the tab, and no verdict
    tab = html.split('<section class="tab"', 1)[1]
    assert not ROLE_RE.search(tab), ROLE_RE.search(tab)
    assert 'id="verdict"' not in html and 'id="conformity-flag"' not in html


def test_debate_waiting_for_rebuttals(debate_run, client):
    (debate_run / "05_report.md").write_text("# Synthetic report\n", encoding="utf-8")
    shutil.copy(FIXTURES / "scores.json", debate_run / "04_scores.json")
    debate.write_evidence(DEBATE_RUN, seed=MINI_SEED)
    debate.anonymize(DEBATE_RUN, 0)
    for role in PERSONAS[:3]:
        write_role(debate_run, 1, role, plain(role, 1))
    html = client.get(f"/runs/{DEBATE_RUN}/debate").text
    waiting = ", ".join(MINI_MAP[r] for r in PERSONAS[3:])
    assert f'id="next-step">next: rebuttals round 1 {waiting}<' in html
    assert "Not anonymized yet: 3 of 5 persona files written." in section(html, "round-1")
    assert not ROLE_RE.search(html.split('<section class="tab"', 1)[1])


def test_debate_not_started_and_no_report(debate_run, client):
    for path in (debate_run / "debate" / "round0").iterdir():
        path.unlink()
    (debate_run / "debate" / "round0").rmdir()
    html = client.get(f"/runs/{DEBATE_RUN}/debate").text
    assert "Not started." in html and 'id="next-step">next: report<' in html
    assert "no 05_report.md: run /synthesize first" in html and "data-round" not in html


def test_broken_round_file_is_reported(debating, client):
    (debating / "debate" / "round0" / debate.ANON_NAME).write_text("[]", encoding="utf-8")
    write_role(debating, 0, "founder", debate_position("founder", proposed_change="Changed."))
    resp = client.get(f"/runs/{DEBATE_RUN}/debate")
    assert resp.status_code == 200
    assert "round0/positions_anon.json is not valid" in resp.text


# ---------------------------------------------------------------- reviews


def post_review(client, run_id, **fields):
    return client.post(f"/runs/{run_id}/review", data=fields, follow_redirects=False)


def test_review_form_stores_the_same_rows_as_status(version_pair, client):
    html = client.get(f"/runs/{RUN_V1}/review").text
    assert attrs(html, "data-section") == list(review.SECTIONS)
    resp = post_review(client, RUN_V1, score_verdict="4", note_verdict="  clear\n call ", score_risks="2", note_usage="ignored")
    assert resp.status_code == 303 and resp.headers["location"] == f"/runs/{RUN_V1}/review?stored=1"
    assert review.stored(RUN_V1) == {"verdict": (4, "clear call"), "risks": (2, None)}
    html = client.get(resp.headers["location"]).text
    assert 'id="review-stored"' in html and 'data-score="4"' in html and 'value="clear call"' in html
    # a section left out keeps its score; scoring it again replaces it
    post_review(client, RUN_V1, score_risks="3", note_risks="generic")
    assert review.stored(RUN_V1) == {"verdict": (4, "clear call"), "risks": (3, "generic")}
    # the same rows /status --review writes
    review.store(RUN_V2, ["verdict=4:clear call", "risks=3:generic"])
    with review.db.session() as conn:
        rows = conn.execute("SELECT run_id, section, score, note FROM reviews ORDER BY run_id, section").fetchall()
    by_run = {}
    for r in rows:
        by_run.setdefault(r["run_id"], []).append((r["section"], r["score"], r["note"]))
    assert by_run[RUN_V1] == by_run[RUN_V2]


@pytest.mark.parametrize(
    ("fields", "message"),
    [({"score_verdict": "7"}, "the score must be a whole number 1–5"), ({}, "no section scores given")],
)
def test_bad_review_stores_nothing(version_pair, client, fields, message):
    resp = post_review(client, RUN_V1, score_risks="", **fields)
    assert resp.status_code == 400 and 'id="review-error"' in resp.text and message in resp.text
    assert review.stored(RUN_V1) == {}


def test_review_needs_a_report(version_pair, client):
    make_run(run_id := "20261025-090000-no-report", created="2026-10-25T09:00:00+00:00", report=False)
    html = client.get(f"/runs/{run_id}/review").text
    assert "has no 05_report.md to review yet" in html and "<form" not in html.split('<section class="tab"')[1]
    resp = post_review(client, run_id, score_verdict="3")
    assert resp.status_code == 400 and "has no 05_report.md to review yet" in resp.text
    assert review.stored(run_id) == {}


def test_trend_matches_status_reviews(version_pair, client):
    assert "No reviews yet" in client.get("/reviews").text
    post_review(client, RUN_V1, score_verdict="4", score_score_table="4", score_risks="2")
    post_review(client, RUN_V2, score_verdict="3", score_score_table="4", score_risks="2", note_risks="generic")
    html = client.get("/reviews").text
    text = review.trend()
    keys = [*review.SECTIONS, "all sections", "runs"]
    assert cells(html, "data-section") == {k: v for k, v in text_rows(text, keys).items()}
    assert cells(html, "data-run") == text_rows(text, [RUN_V1, RUN_V2])
    for v in review.versions():
        line = re.sub(r"<[^>]+>", "", re.search(rf'<li data-version="{v.label}">(.*?)</li>', html).group(1))
        assert line == review.version_line(v)
        assert line in text


# ---------------------------------------------------------------- compare


def test_compare_matches_status_diff(version_pair, client):
    html = client.get("/compare").text
    assert set(attrs(html, "value")) >= {RUN_V1, RUN_V2} and "<table" not in html
    resp = client.get("/compare", params={"a": RUN_V1, "b": RUN_V2})
    assert resp.status_code == 200
    html = resp.text
    text = status.diff_runs(RUN_V1, RUN_V2)
    assert text == (FIXTURES / "status" / "status_diff.golden.txt").read_text(encoding="utf-8").rstrip("\n")
    lines = text.splitlines()
    dims = [r.dimension for r in status.score_diff(RUN_V1, RUN_V2).rows]
    assert cells(html, "data-dimension") == text_rows(text, dims)
    for element_id in ("config-line", "models-line", "verdict-line", "total-line"):
        shown = re.search(rf'id="{element_id}">(.*?)<', html).group(1)
        assert shown.replace("&gt;", ">") in lines
    kill = [re.sub(r"<[^>]+>", "", li) for li in re.findall(r"<li data-group=[^>]*>(.*?)</li>", html)]
    assert kill == ["only in A: free_good_enough_substitute", "only in B: beachhead_below_founder_income"]
    assert all(k in lines for k in kill)
    assert "capped: the evidence rules capped the final score at 2 (insufficient data)" in html


def test_compare_errors(version_pair, client):
    make_run(run_id := "20261025-090000-no-scores", created="2026-10-25T09:00:00+00:00")
    resp = client.get("/compare", params={"a": RUN_V1, "b": run_id})
    assert resp.status_code == 400 and f"run {run_id} has no valid 04_scores.json" in resp.text
    assert "(not scored)" in resp.text
    resp = client.get("/compare", params={"a": RUN_V1, "b": "not a run id"})
    assert resp.status_code == 400 and 'id="compare-error"' in resp.text
    assert "choose two runs" in client.get("/compare", params={"a": RUN_V1}).text
