"""Debate convergence (IF-405): scripts/debate_converged.py and debate.check_convergence.

The run, the claim ledger and the round-0 positions (each citing `DEBATE_OWN_CLAIM[role]`) come from
the synthetic `debate_run` fixture in conftest.py; the score sheet is tests/fixtures/scores.json
(market 2). All synthetic (TICKETS.md plan note 14).
"""

import json
import shutil

import debate_converged
import pytest
from conftest import DEBATE_RUN, FIXTURES
from test_debate_validate import MAP, SEED, disagree, other, rebuttal, write, write_round

from ideaforge import db, debate

NEW = {"new_claim_ids": ["market-002"]}


@pytest.fixture
def run(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=SEED)
    shutil.copy(FIXTURES / "scores.json", debate_run / "04_scores.json")
    return debate_run


def validated_round(run_dir, round_no=1, **overrides):
    write_round(run_dir, round_no, **overrides)
    return debate.validate_round(DEBATE_RUN, round_no)


def agree(role, basis=None):
    return {"target_position_id": other(role), "stance": "agree", "basis": basis or NEW}


def interim(run_dir, round_no, **scores):
    d = run_dir / "debate" / f"round{round_no}"
    d.mkdir(parents=True, exist_ok=True)
    data = {"round": round_no, "projected_scores": scores}
    (d / debate.INTERIM_NAME).write_text(json.dumps(data), encoding="utf-8")


def check(round_no=1):
    return debate.check_convergence(DEBATE_RUN, round_no)


def met(result, letter):
    return any(m.startswith(f"({letter})") for m in result.met)


# ---------------------------------------------------------------- (a) nothing new


def test_a_no_new_claims_and_no_moved_change_stops(run, capsys):
    assert not validated_round(run).rejected
    result = check()
    assert result.stop and met(result, "a") and not met(result, "c")
    assert debate_converged.main([DEBATE_RUN, "1"]) == 0
    assert "met: (a)" in capsys.readouterr().out


def test_a_new_claim_id_continues(run, capsys):
    assert not validated_round(run, founder=rebuttal("founder", agree("founder"))).rejected
    result = check()
    assert not result.stop
    assert "new claim ids market-002" in "\n".join(result.notes)
    assert debate_converged.main([DEBATE_RUN, "1"]) == 2
    assert "run round 2" in capsys.readouterr().out


def test_a_claim_new_to_the_role_but_cited_before_in_the_debate_is_not_new(run):
    # market-001 is in the round-0 positions; citing it again brings nothing new into the debate
    turn = rebuttal("founder", {**disagree("founder"), "cited_claim_ids": ["market-001"]})
    assert not validated_round(run, founder=turn).rejected
    assert met(check(), "a")


def test_a_moved_proposal_continues(run):
    turn = rebuttal("investor", updated_change="A different change.", updated_change_basis={"new_claim_ids": ["pricing-001"]})
    assert not validated_round(run, investor=turn).rejected
    result = check()
    assert not met(result, "a")
    assert "proposed change moved for 1 position(s)" in "\n".join(result.notes)


def test_a_restated_proposal_is_not_a_move(run):
    turn = rebuttal("investor", updated_change="  synthetic CHANGE in.  ")
    assert not validated_round(run, investor=turn).rejected
    assert met(check(), "a")


def test_a_mini_research_request_continues(run):
    request = {"question": "Winter occupancy?", "dimension": "market", "requested_by": "operator"}
    assert not validated_round(run, operator=rebuttal("operator", mini_research=request)).rejected
    result = check()
    assert not met(result, "a")
    assert "mini-research" in "\n".join(result.notes)


def test_a_rejected_turn_brings_nothing_in(run):
    # competition-001 is unverified, so the turn is rejected and its ids never enter the debate
    turn = rebuttal("founder", agree("founder", {"new_claim_ids": ["competition-001"]}))
    assert "founder" in validated_round(run, founder=turn).rejected
    assert met(check(), "a")


# ---------------------------------------------------------------- (b) interim scores


def test_b_projection_close_to_the_score_sheet_stops(run):
    assert not validated_round(run, founder=rebuttal("founder", agree("founder"))).rejected
    interim(run, 1, market=2.2)
    result = check()
    assert result.stop and met(result, "b") and not met(result, "a")
    assert "against 04_scores.json" in result.met[0]


def test_b_projection_that_moved_continues(run):
    assert not validated_round(run, founder=rebuttal("founder", agree("founder"))).rejected
    interim(run, 1, market=2.25)  # exactly the delta: moved
    result = check()
    assert not result.stop
    assert "(b) not met: moved ≥ 0.25 against 04_scores.json on market" in result.notes


def test_b_compares_with_the_previous_interim(run):
    assert not validated_round(run, founder=rebuttal("founder", agree("founder"))).rejected
    interim(run, 1, market=3.5)
    assert not check(1).stop
    turn2 = rebuttal("founder", agree("founder", {"new_claim_ids": ["pricing-002"]}), round_no=2)
    assert not validated_round(run, 2, founder=turn2).rejected
    interim(run, 2, market=3.4)
    result = check(2)
    assert met(result, "b") and "against round 1" in result.met[0]


def test_b_a_dimension_projected_on_one_side_only_has_moved(run):
    assert not validated_round(run, founder=rebuttal("founder", agree("founder"))).rejected
    interim(run, 1, market=2.0, pricing=3.0)
    result = check()
    assert not met(result, "b")
    assert "on pricing" in "\n".join(result.notes)


def test_b_without_an_interim_file_is_not_met(run):
    assert not validated_round(run, founder=rebuttal("founder", agree("founder"))).rejected
    assert "(b) not met: no round1/interim_scores.json" in check().notes


def test_b_interim_with_the_wrong_round_is_an_error(run, capsys):
    validated_round(run)
    interim(run, 1, market=2.0)
    path = run / "debate" / "round1" / debate.INTERIM_NAME
    path.write_text(json.dumps({"round": 2, "projected_scores": {"market": 2.0}}), encoding="utf-8")
    assert debate_converged.main([DEBATE_RUN, "1"]) == 1
    assert "expected 1" in capsys.readouterr().err


# ---------------------------------------------------------------- (c) max rounds


def test_c_max_rounds_stops_even_with_new_evidence(run):
    for n, cid in enumerate(["market-002", "unit_economics-001", "pricing-002"], start=1):
        turn = rebuttal("founder", agree("founder", {"new_claim_ids": [cid]}), round_no=n)
        assert not validated_round(run, n, founder=turn).rejected
        result = check(n)
        assert result.stop == (n == 3)
    assert result.met == ["(c) round 3 reached max_rounds 3"]


def test_c_follows_the_runs_budget_preset(run):
    with db.session() as conn:
        conn.execute("UPDATE runs SET budget_preset='economy' WHERE run_id=?", (DEBATE_RUN,))
    for n, cid in enumerate(["market-002", "unit_economics-001"], start=1):
        turn = rebuttal("founder", agree("founder", {"new_claim_ids": [cid]}), round_no=n)
        assert not validated_round(run, n, founder=turn).rejected
    assert check(2).met == ["(c) round 2 reached max_rounds 2"]


def test_round_is_recorded_in_the_debates_row(run):
    validated_round(run)
    check()
    with db.session() as conn:
        assert conn.execute("SELECT rounds FROM debates WHERE run_id=?", (DEBATE_RUN,)).fetchone()["rounds"] == 1


# ---------------------------------------------------------------- bad input


def test_unvalidated_round_is_an_error(run, capsys):
    write_round(run)
    assert debate_converged.main([DEBATE_RUN, "1"]) == 1
    assert "debate_validate.py" in capsys.readouterr().err


def test_file_changed_after_validation_is_an_error(run, capsys):
    validated_round(run)
    write(run, "founder", rebuttal("founder", agree("founder")))
    assert debate_converged.main([DEBATE_RUN, "1"]) == 1
    assert "founder.json was not checked in its current form" in capsys.readouterr().err


@pytest.mark.parametrize("round_no", ["0", "-1"])
def test_round_zero_is_an_error(run, capsys, round_no):
    assert debate_converged.main([DEBATE_RUN, round_no]) == 1
    assert "rebuttal round" in capsys.readouterr().err


def test_unknown_run_and_missing_round(project, run, capsys):
    assert debate_converged.main(["20261023-000000-nope", "1"]) == 1
    assert debate_converged.main([DEBATE_RUN, "2"]) == 1
    assert "round2 does not exist" in capsys.readouterr().err


def test_unknown_preset_is_an_error(run, capsys):
    validated_round(run)
    with db.session() as conn:
        conn.execute("UPDATE runs SET budget_preset='lavish' WHERE run_id=?", (DEBATE_RUN,))
    assert debate_converged.main([DEBATE_RUN, "1"]) == 1
    assert "lavish" in capsys.readouterr().err


def test_mapping_is_the_debates(run):
    assert debate.load_mapping(DEBATE_RUN) == MAP


def test_round_without_persona_files_is_an_error(run, capsys):
    interim(run, 1, market=2.0)  # the judge's file alone is not a round
    assert debate_converged.main([DEBATE_RUN, "1"]) == 1
    assert "round1/ has no persona file" in capsys.readouterr().err
