"""Rebuttal validation (IF-403): scripts/debate_validate.py and debate.validate_round.

The run, the claim ledger and the round-0 positions (each citing market-001) come from the
synthetic `debate_run` fixture in conftest.py (TICKETS.md plan note 14).
"""

import json

import debate_validate
import pytest
from conftest import DEBATE_RUN

from ideaforge import db, debate
from ideaforge.schemas import PERSONAS

SEED = 2026
MAP = debate.mapping_for(SEED)
GAP = {"evidence_gap": "No verified claim on winter occupancy."}


@pytest.fixture
def run(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=SEED)
    return debate_run


def other(role):
    """The P-id of a position that is not the role's own."""
    return next(pid for r, pid in MAP.items() if r != role)


def disagree(role):
    return {"target_position_id": other(role), "stance": "disagree", "basis": GAP}


def rebuttal(role, *responses, round_no=1, **fields):
    return {"role": role, "round": round_no, "responses": list(responses) or [disagree(role)]} | fields


def write(run_dir, role, data, round_no=1):
    d = run_dir / "debate" / f"round{round_no}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{role}.json").write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def write_round(run_dir, round_no=1, **overrides):
    """Every persona writes a plain disagree, except the roles given as keyword overrides."""
    for role in PERSONAS:
        write(run_dir, role, overrides.get(role) or rebuttal(role, disagree(role), round_no=round_no), round_no)


def reasons(result, role):
    return "\n".join(result.rejected.get(role, []))


# ---------------------------------------------------------------- accepted


def test_plain_disagreements_are_accepted(run):
    write_round(run)
    result = debate.validate_round(DEBATE_RUN, 1)
    assert result.accepted == list(PERSONAS) and result.rejected == {}
    assert not list((run / "debate" / "round1").glob("REJECTED_*"))


def test_stance_change_with_a_new_claim_id_is_accepted(run):
    agree = {"target_position_id": other("founder"), "stance": "agree", "basis": {"new_claim_ids": ["market-002"]}}
    write_round(run, founder=rebuttal("founder", agree))
    assert "founder" in debate.validate_round(DEBATE_RUN, 1).accepted


def test_stance_change_with_a_computation_is_accepted(run):
    modify = {
        "target_position_id": other("investor"),
        "stance": "modify",
        "basis": {"computation": "pricing-001 (90 EUR) - unit_economics-001 (35 EUR) = 55 EUR margin per night"},
    }
    write_round(run, investor=rebuttal("investor", modify))
    assert "investor" in debate.validate_round(DEBATE_RUN, 1).accepted


def test_disagree_with_an_already_cited_claim_is_accepted(run):
    response = {"target_position_id": other("customer"), "stance": "disagree",
                "basis": GAP, "cited_claim_ids": ["market-001"]}
    write_round(run, customer=rebuttal("customer", response))
    assert "customer" in debate.validate_round(DEBATE_RUN, 1).accepted


def test_disagree_backed_by_cited_claim_without_gap_is_accepted(run):
    response = {"target_position_id": other("customer"), "stance": "disagree",
                "basis": {"new_claim_ids": ["gtm-001"]}}
    write_round(run, customer=rebuttal("customer", response))
    assert "customer" in debate.validate_round(DEBATE_RUN, 1).accepted


def test_unchanged_proposal_needs_no_basis(run):
    write_round(run, operator=rebuttal("operator", updated_change="  Synthetic   change op. "))
    assert "operator" in debate.validate_round(DEBATE_RUN, 1).accepted


def test_changed_proposal_with_new_claim_is_accepted(run):
    write_round(run, operator=rebuttal(
        "operator", updated_change="Open in May only.", updated_change_basis={"new_claim_ids": ["gtm-001"]},
    ))
    assert "operator" in debate.validate_round(DEBATE_RUN, 1).accepted


def test_one_mini_research_request_is_accepted(run):
    request = {"question": "Synthetic question?", "dimension": "market", "requested_by": "accountant"}
    write_round(run, accountant=rebuttal("accountant", mini_research=request))
    assert debate.validate_round(DEBATE_RUN, 1).rejected == {}


# ---------------------------------------------------------------- rejected


@pytest.mark.parametrize("stance", ["agree", "modify"])
def test_stance_change_without_new_claim_id_is_rejected(run, stance):
    response = {"target_position_id": other("founder"), "stance": stance, "basis": GAP}
    write_round(run, founder=rebuttal("founder", response))
    result = debate.validate_round(DEBATE_RUN, 1)
    assert "founder" not in result.accepted
    assert "needs basis.new_claim_ids" in reasons(result, "founder")
    marker = run / "debate" / "round1" / "REJECTED_founder"
    assert "needs basis.new_claim_ids" in marker.read_text(encoding="utf-8")
    assert set(result.accepted) == set(PERSONAS) - {"founder"}


@pytest.mark.parametrize("stance", ["agree", "modify"])
def test_stance_change_citing_an_old_claim_as_new_is_rejected(run, stance):
    response = {"target_position_id": other("founder"), "stance": stance, "basis": {"new_claim_ids": ["market-001"]}}
    write_round(run, founder=rebuttal("founder", response))
    assert "market-001 already cited in an earlier turn" in reasons(debate.validate_round(DEBATE_RUN, 1), "founder")


@pytest.mark.parametrize(
    "computation",
    ["about half of what the others assume", "pricing-001 is too optimistic", "90 - 35 = 55"],
)
def test_computation_without_a_number_from_a_claim_is_rejected(run, computation):
    response = {"target_position_id": other("founder"), "stance": "agree", "basis": {"computation": computation}}
    write_round(run, founder=rebuttal("founder", response))
    assert "computation must show a number" in reasons(debate.validate_round(DEBATE_RUN, 1), "founder")


def test_changed_proposal_without_basis_is_rejected(run):
    write_round(run, operator=rebuttal("operator", updated_change="Open in May only."))
    assert "updated_change: needs a basis" in reasons(debate.validate_round(DEBATE_RUN, 1), "operator")


def test_changed_proposal_with_old_claim_is_rejected(run):
    write_round(run, operator=rebuttal(
        "operator", updated_change="Open in May only.", updated_change_basis={"new_claim_ids": ["market-001"]},
    ))
    assert "updated_change: market-001 already cited" in reasons(debate.validate_round(DEBATE_RUN, 1), "operator")


def test_disagree_with_only_a_computation_is_rejected(run):
    response = {"target_position_id": other("investor"), "stance": "disagree",
                "basis": {"computation": "pricing-001 (90 EUR) / 2 = 45 EUR"}}
    write_round(run, investor=rebuttal("investor", response))
    assert "a disagree needs a claim id" in reasons(debate.validate_round(DEBATE_RUN, 1), "investor")


@pytest.mark.parametrize(
    ("claim_id", "message"),
    [
        ("market-999", "market-999 does not exist"),
        ("competition-001", "competition-001 is unverified"),
        ("competition-002", "competition-002 is conflict"),
        ("location-001", "location-001 is pending"),
    ],
)
def test_unknown_or_unverified_claim_ids_are_rejected(run, claim_id, message):
    for where in ("new", "cited", "computation", "change"):
        response = {"target_position_id": other("founder"), "stance": "agree", "basis": {"new_claim_ids": ["market-002"]}}
        extra = {}
        if where == "new":
            response["basis"] = {"new_claim_ids": [claim_id]}
        elif where == "cited":
            response = {"target_position_id": other("founder"), "stance": "disagree", "basis": GAP, "cited_claim_ids": [claim_id]}
        elif where == "computation":
            response["basis"] = {"computation": f"{claim_id} (40) * 2 = 80"}
        else:
            extra = {"updated_change": "Other change.", "updated_change_basis": {"new_claim_ids": [claim_id]}}
        write_round(run, founder=rebuttal("founder", response, **extra))
        assert message in reasons(debate.validate_round(DEBATE_RUN, 1), "founder"), where


def test_second_mini_research_request_in_a_round_is_rejected(run):
    requesters = sorted(["founder", "operator", "customer"], key=lambda r: int(MAP[r][1:]))
    overrides = {
        r: rebuttal(r, mini_research={"question": f"Synthetic {r}?", "dimension": "gtm", "requested_by": r})
        for r in requesters
    }
    write_round(run, **overrides)
    result = debate.validate_round(DEBATE_RUN, 1)
    assert requesters[0] in result.accepted
    for r in requesters[1:]:
        assert f"{MAP[requesters[0]]} already requested one this round" in reasons(result, r)
        assert "at most 1 per round" in (run / "debate" / "round1" / f"REJECTED_{r}").read_text(encoding="utf-8")


def test_mini_research_for_another_role_is_rejected(run):
    request = {"question": "Synthetic?", "dimension": "gtm", "requested_by": "investor"}
    write_round(run, founder=rebuttal("founder", mini_research=request))
    assert "requested_by is 'investor'" in reasons(debate.validate_round(DEBATE_RUN, 1), "founder")


def test_targets_must_be_another_known_position(run):
    own = {"target_position_id": MAP["founder"], "stance": "disagree", "basis": GAP}
    unknown = {"target_position_id": "P9", "stance": "disagree", "basis": GAP}
    write_round(run, founder=rebuttal("founder", own, unknown))
    text = reasons(debate.validate_round(DEBATE_RUN, 1), "founder")
    assert "targets your own position" in text and "unknown position id" in text


def test_role_and_round_must_match_the_file(run):
    write_round(run, founder=rebuttal("investor", disagree("founder"), round_no=2))
    text = reasons(debate.validate_round(DEBATE_RUN, 1), "founder")
    assert "role is 'investor'" in text and "round is 2" in text


def test_missing_and_invalid_files_are_rejected(run):
    write_round(run)
    (run / "debate" / "round1" / "customer.json").unlink()
    write(run, "investor", '{"role": "investor", "round": 1, "responses": [{"stance": "agree"}]}')
    result = debate.validate_round(DEBATE_RUN, 1)
    assert "no rebuttal file" in reasons(result, "customer")
    assert "not a valid Rebuttal" in reasons(result, "investor")
    with db.session() as conn:
        rows = conn.execute("SELECT role, accepted FROM debate_turns WHERE round=1").fetchall()
    assert {r["role"]: r["accepted"] for r in rows} == {
        "founder": 1, "accountant": 1, "operator": 1, "investor": 0,
    }


# ---------------------------------------------------------------- re-prompt, turns and history


def test_reprompt_clears_the_marker_and_counts_an_attempt(run):
    bad = {"target_position_id": other("founder"), "stance": "agree", "basis": GAP}
    write_round(run, founder=rebuttal("founder", bad))
    debate.validate_round(DEBATE_RUN, 1)
    debate.validate_round(DEBATE_RUN, 1)  # unchanged file: same attempt
    marker = run / "debate" / "round1" / "REJECTED_founder"
    assert marker.exists()
    good = {"target_position_id": other("founder"), "stance": "agree", "basis": {"new_claim_ids": ["pricing-002"]}}
    write(run, "founder", rebuttal("founder", good))
    assert "founder" in debate.validate_round(DEBATE_RUN, 1).accepted
    assert not marker.exists()
    with db.session() as conn:
        rows = conn.execute(
            "SELECT attempt, accepted, reject_reason, anon_id FROM debate_turns WHERE round=1 AND role='founder'"
            " ORDER BY attempt"
        ).fetchall()
    assert [(r["attempt"], r["accepted"]) for r in rows] == [(1, 0), (2, 1)]
    assert "needs basis.new_claim_ids" in rows[0]["reject_reason"] and rows[1]["reject_reason"] is None
    assert {r["anon_id"] for r in rows} == {MAP["founder"]}


def test_claims_cited_in_an_earlier_round_are_not_new(run):
    first = {"target_position_id": other("founder"), "stance": "agree", "basis": {"new_claim_ids": ["pricing-002"]}}
    write_round(run, founder=rebuttal("founder", first))
    assert debate.validate_round(DEBATE_RUN, 1).rejected == {}
    write_round(run, 2, founder=rebuttal("founder", first, round_no=2))
    assert "pricing-002 already cited" in reasons(debate.validate_round(DEBATE_RUN, 2), "founder")


def test_rejected_turn_does_not_count_as_cited(run):
    bad = {"target_position_id": "P9", "stance": "agree", "basis": {"new_claim_ids": ["pricing-002"]}}
    write_round(run, founder=rebuttal("founder", bad))
    assert "founder" in debate.validate_round(DEBATE_RUN, 1).rejected
    good = {"target_position_id": other("founder"), "stance": "agree", "basis": {"new_claim_ids": ["pricing-002"]}}
    write_round(run, 2, founder=rebuttal("founder", good, round_no=2))
    assert "founder" in debate.validate_round(DEBATE_RUN, 2).accepted


def test_accepted_updated_change_is_the_next_rounds_proposal(run):
    write_round(run, operator=rebuttal(
        "operator", updated_change="Open in May only.", updated_change_basis={"new_claim_ids": ["gtm-001"]},
    ))
    assert debate.validate_round(DEBATE_RUN, 1).rejected == {}
    write_round(run, 2, operator=rebuttal("operator", round_no=2, updated_change="Open in May only."))
    assert "operator" in debate.validate_round(DEBATE_RUN, 2).accepted
    write_round(run, 2, operator=rebuttal("operator", round_no=2, updated_change="Synthetic change op."))
    assert "updated_change: needs a basis" in reasons(debate.validate_round(DEBATE_RUN, 2), "operator")


# ---------------------------------------------------------------- errors and CLI


def test_round_zero_and_unanonymized_debates_are_errors(debate_run):
    write_round(debate_run)
    with pytest.raises(debate.DebateError, match="start at 1"):
        debate.validate_round(DEBATE_RUN, 0)
    with pytest.raises(debate.DebateError, match="anonymize"):
        debate.validate_round(DEBATE_RUN, 1)


def test_missing_ledger_is_an_error(run):
    write_round(run)
    (run / "03_claims" / "verified.json").unlink()
    with pytest.raises(debate.DebateError, match="verify_claims"):
        debate.validate_round(DEBATE_RUN, 1)


def test_cli_exit_codes(run, capsys):
    write_round(run)
    assert debate_validate.main([DEBATE_RUN, "1"]) == 0
    assert "founder: accepted" in capsys.readouterr().out
    bad = {"target_position_id": other("founder"), "stance": "agree", "basis": GAP}
    write(run, "founder", rebuttal("founder", bad))
    assert debate_validate.main([DEBATE_RUN, "1"]) == 2
    out = capsys.readouterr().out
    assert "founder: rejected\n  - response 1 (agree" in out
    assert debate_validate.main([DEBATE_RUN, "3"]) == 1
    assert "does not exist" in capsys.readouterr().err
