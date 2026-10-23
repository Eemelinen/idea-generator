"""Synthesis input and the score run (IF-304), end to end on fixture files.

tests/fixtures/score_run/*.synthetic.json are synthetic (TICKETS.md plan note 14): invented
URLs and values that exercise the logic and are never presented as real sources. Every rubric
dimension has three verified claims that pass its evidence rules (an allow-listed price, a cost,
a count), plus unverified, conflict, pending and unknown citations to drop.
"""

import json
import shutil

import pytest
import score_run
import synthesis_input
from conftest import FIXTURES

from ideaforge import agents, db, economics, runs, synthesis, validate_file
from ideaforge.schemas import (
    ADDITIVE_ECONOMICS_ROLES,
    RUBRIC_DIMENSIONS,
    EconomicsRole,
    IdeaSpec,
    ProposedScores,
    ScoreSheet,
)

RUN = "20261023-130000-sauna-cabins"
SCORE_FIXTURES = FIXTURES / "score_run"


@pytest.fixture
def run(project):
    """A run at the end of stage 3 with the synthesizer's files already written."""
    db.init()
    run_dir = runs.create_run_dir(RUN, "Sauna-and-lake cabins for remote workers")
    db.create_run(RUN, "Sauna-and-lake cabins", idea_id="sauna-cabins", stages=runs.STAGES)
    (run_dir / "03_claims").mkdir(exist_ok=True)
    shutil.copy(FIXTURES / "spec.json", run_dir / "00_spec.json")
    shutil.copy(SCORE_FIXTURES / "verified.synthetic.json", run_dir / "03_claims" / "verified.json")
    shutil.copy(SCORE_FIXTURES / "04_scores_proposed.synthetic.json", run_dir / "04_scores_proposed.json")
    shutil.copy(SCORE_FIXTURES / "04_risks.synthetic.json", run_dir / "04_risks.json")
    return run_dir


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def add_claim(run_dir, **fields):
    claim = {
        "dimension": fields["claim_id"].rsplit("-", 1)[0],
        "statement": "A synthetic statement.",
        "source_url": "https://example.net/synthetic/extra",
        "source_title": "Synthetic source",
        "quote": "synthetic quote",
        "retrieved_at": "2026-10-23T10:30:00+00:00",
        "source_type": "news",
        "confidence": 0.8,
        "verification": "verified",
    } | fields
    edit_json(run_dir / "03_claims" / "verified.json", lambda data: data.append(claim))


def scores_file(run_dir) -> ScoreSheet:
    return ScoreSheet.model_validate_json((run_dir / "04_scores.json").read_text(encoding="utf-8"))


def by_dim(sheet):
    return {s.dimension: s for s in sheet.scores}


# ---------------------------------------------------------------- fixtures are valid


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("verified.synthetic.json", "claims"),
        ("04_scores_proposed.synthetic.json", "scores_proposed"),
        ("04_risks.synthetic.json", "risks"),
    ],
)
def test_fixture_files_validate(name, kind):
    validate_file.validate_path(SCORE_FIXTURES / name, kind)


# ---------------------------------------------------------------- synthesizer input


def test_synthesis_input_holds_only_spec_verified_and_conflict_claims_and_rubric(run, capsys):
    assert synthesis_input.main([RUN]) == 0
    out = capsys.readouterr().out
    assert "wrote runs/20261023-130000-sauna-cabins/04_synthesis_input.json" in out
    data = json.loads((run / agents.SYNTHESIS_INPUT).read_text(encoding="utf-8"))
    assert set(data) == {"run_id", "spec", "claims", "rubric", "economics_roles"}
    assert IdeaSpec.model_validate(data["spec"]).idea_id == "sauna-cabins-remote-work"
    states = {c["claim_id"]: c["verification"] for c in data["claims"]}
    assert set(states.values()) == {"verified", "conflict"}
    assert states["market-004"] == "conflict"
    for left_out in ("customer-004", "competition-004", "killcause-002"):  # unverified, pending
        assert left_out not in states
    assert [d["id"] for d in data["rubric"]["dimensions"]] == list(RUBRIC_DIMENSIONS)
    assert data["rubric"]["verdict_thresholds"]["go"] == 3.5
    assert set(data["economics_roles"]) == set(economics.ROLES)


def test_synthesis_input_flags_dimensions_without_verified_claims(run, capsys):
    edit_json(run / "03_claims" / "verified.json", lambda data: data.__setitem__(
        slice(None), [c for c in data if c["dimension"] != "financing"]))  # fmt: skip
    assert synthesis_input.main([RUN]) == 0
    assert "financing          0 verified   0 conflict  (no verified evidence)" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["00_spec.json", "03_claims/verified.json"])
def test_synthesis_input_needs_spec_and_claims(run, capsys, missing):
    (run / missing).unlink()
    assert synthesis_input.main([RUN]) == 1
    assert "does not exist" in capsys.readouterr().err
    assert not (run / agents.SYNTHESIS_INPUT).exists()


# ---------------------------------------------------------------- score run, end to end


def test_score_run_end_to_end(run, capsys):
    assert score_run.main([RUN]) == 0
    out = capsys.readouterr().out
    validate_file.validate_path(run / "04_scores.json", "scores")
    sheet = scores_file(run)
    scores = by_dim(sheet)

    assert [s.dimension for s in sheet.scores] == list(RUBRIC_DIMENSIONS)
    # unverified, conflict and unknown citations are dropped, reported and never count
    assert scores["customer"].supporting_claim_ids == ["customer-001", "customer-002", "customer-003"]
    assert scores["market"].supporting_claim_ids == ["market-001", "market-002", "market-003"]
    assert "dropped citations (customer): customer-004, customer-999" in out
    assert "dropped citations (market): market-004" in out
    # a proposal with no verified citation left is 0, whatever was proposed
    fr = scores["founder_risk"]
    assert fr.proposed_score == 0 and fr.final_score == 0 and fr.status == "insufficient_data"
    assert fr.justification.startswith("no verified evidence (proposed 2; dropped citations: founder_risk-404)")
    assert "no verified citation, set to 0: founder_risk" in out
    # every other dimension passes its rules
    assert all(s.status == "scored" and s.final_score == 4 for d, s in scores.items() if d != "founder_risk")
    assert sheet.weighted_total == pytest.approx(4 * 0.95)
    # the unverified permit_impossible claim (killcause-002) fires nothing
    assert sheet.kill_triggers_fired == []
    assert sheet.verdict == "GO"
    assert "verdict: GO" in out

    ue = sheet.unit_economics
    assert ue.price_eur == pytest.approx(25 / 1.255)  # unstated basis → read as incl. VAT
    assert ue.variable_cost_eur == 8
    assert ue.fixed_costs_month_eur == 400
    assert ue.volume_month == 60
    assert ue.contribution_margin_eur == pytest.approx(25 / 1.255 - 8)
    assert set(ue.input_claim_ids) >= {"pricing-001", "unit_economics-004", "unit_economics-002"}
    assert "unit economics (assigned)" in out
    assert synthesis.AUTOMATIC_PICK_NOTE not in ue.notes


def test_score_run_writes_the_scores_table(run):
    assert score_run.main([RUN]) == 0
    with db.session() as conn:
        rows = {r["dimension"]: r for r in conn.execute("SELECT * FROM scores WHERE run_id=?", (RUN,))}
    assert set(rows) == set(RUBRIC_DIMENSIONS)
    assert rows["customer"]["final_score"] == 4
    assert json.loads(rows["customer"]["claim_ids"]) == ["customer-001", "customer-002", "customer-003"]
    assert rows["founder_risk"]["status"] == "insufficient_data"
    assert rows["founder_risk"]["cap_reason"].startswith("min_sources: 0 of 2")
    # a re-run replaces the rows instead of duplicating them
    assert score_run.main([RUN]) == 0
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM scores WHERE run_id=?", (RUN,)).fetchone()[0] == 10


def test_permit_impossible_claim_flips_the_verdict_to_no_go(run, capsys):
    add_claim(run, claim_id="regulation-009", statement="The municipality refuses every shore permit.",
              flags=["permit_impossible"])  # fmt: skip
    assert score_run.main([RUN]) == 0
    sheet = scores_file(run)
    assert sheet.kill_triggers_fired == ["permit_impossible"]
    assert sheet.verdict == "NO_GO"
    assert sheet.weighted_total == pytest.approx(4 * 0.95)  # the total is unchanged; the trigger decides
    out = capsys.readouterr().out
    assert "kill triggers fired: permit_impossible" in out and "verdict: NO_GO" in out


def test_spec_override_keeps_permit_impossible_from_forcing_no_go(run):
    add_claim(run, claim_id="regulation-009", flags=["permit_impossible"])
    edit_json(run / "00_spec.json", lambda spec: spec.__setitem__("kill_trigger_overrides", ["permit_impossible"]))
    assert score_run.main([RUN]) == 0
    sheet = scores_file(run)
    assert sheet.kill_triggers_fired == [] and sheet.verdict == "GO"


def test_unverified_citations_cannot_lift_a_cap(run):
    # customer cites one verified claim and two unverified ones: 1 of 3 sources → capped at 2
    add_claim(run, claim_id="customer-005", verification="unverified", source_url="https://example.net/a")
    add_claim(run, claim_id="customer-006", verification="conflict", source_url="https://example.org/b")
    edit_json(run / "04_scores_proposed.json", lambda data: data["scores"][0].update(
        proposed_score=5, supporting_claim_ids=["customer-001", "customer-005", "customer-006"]))  # fmt: skip
    assert score_run.main([RUN]) == 0
    customer = by_dim(scores_file(run))["customer"]
    assert customer.final_score == 2 and customer.status == "insufficient_data"
    assert customer.supporting_claim_ids == ["customer-001"]
    assert customer.cap_reason == "min_sources: 1 of 3 independent source domains"


def test_assigned_negative_margin_forces_no_go(run):
    add_claim(run, claim_id="unit_economics-006", value=30, unit="EUR/person",
              statement="Cleaning and linen cost 30 EUR per guest excl. VAT.")  # fmt: skip
    edit_json(run / "04_scores_proposed.json", lambda data: data["unit_economics_inputs"].__setitem__(
        "variable_cost", ["unit_economics-004", "unit_economics-006"]))  # fmt: skip
    assert score_run.main([RUN]) == 0
    sheet = scores_file(run)
    assert sheet.unit_economics.variable_cost_eur == 38
    assert sheet.unit_economics.contribution_margin_eur < 0
    assert sheet.kill_triggers_fired == ["negative_contribution_margin"]
    assert sheet.verdict == "NO_GO"


@pytest.mark.parametrize(
    ("role", "unit", "statement"),
    [
        ("variable_cost", "EUR/h", "A cleaner costs 30 EUR per hour."),
        ("variable_cost", "EUR/kuukaudelta", "Siivous maksaa 30 euroa kuukaudelta."),
        ("variable_cost", "EUR/event", "Cleaning costs 30 EUR per event."),
    ],
)
def test_assigned_cost_not_per_unit_sold_never_forces_no_go(run, role, unit, statement):
    add_claim(run, claim_id="unit_economics-006", value=30, unit=unit, statement=statement)
    edit_json(run / "04_scores_proposed.json", lambda data: data["unit_economics_inputs"].__setitem__(
        role, ["unit_economics-004", "unit_economics-006"]))  # fmt: skip
    assert score_run.main([RUN]) == 0
    sheet = scores_file(run)
    assert sheet.unit_economics.contribution_margin_eur < 0  # reported…
    assert sheet.kill_triggers_fired == []  # …but the model's assignment cannot force NO_GO
    assert sheet.verdict == "GO"
    assert any("unit_economics-006" in n and "fires no kill trigger" in n for n in sheet.unit_economics.notes)


def test_automatic_pick_never_forces_no_go(run, capsys):
    # Without assignments economics.py picks pessimistically; its margin is reported only.
    add_claim(run, claim_id="unit_economics-006", value=30, unit="EUR",
              statement="Cleaning costs 30 EUR per stay.")  # fmt: skip
    edit_json(run / "04_scores_proposed.json", lambda data: data.__setitem__("unit_economics_inputs", {}))
    assert score_run.main([RUN]) == 0
    sheet = scores_file(run)
    assert sheet.unit_economics.contribution_margin_eur is not None
    assert sheet.unit_economics.contribution_margin_eur < 0
    assert sheet.kill_triggers_fired == []
    assert sheet.verdict == "GO"
    assert synthesis.AUTOMATIC_PICK_NOTE in sheet.unit_economics.notes
    assert "unit economics (automatic pick)" in capsys.readouterr().out


def test_vat_registration_comes_from_the_spec(run):
    edit_json(run / "00_spec.json", lambda spec: spec.__setitem__("vat_registered", False))
    assert score_run.main([RUN]) == 0
    ue = scores_file(run).unit_economics
    assert ue.vat_registered is False
    assert ue.price_eur == 25  # no VAT charged: the price as quoted
    assert ue.variable_cost_eur == pytest.approx(8 * 1.255)  # VAT on purchases is not deductible


def test_missing_dimension_is_scored_zero(run):
    edit_json(run / "04_scores_proposed.json", lambda data: data.__setitem__(
        "scores", [s for s in data["scores"] if s["dimension"] != "gtm"]))  # fmt: skip
    assert score_run.main([RUN]) == 0
    gtm = by_dim(scores_file(run))["gtm"]
    assert gtm.final_score == 0 and gtm.justification == "no proposed score"


def test_invalid_or_missing_risks_file_is_only_a_warning(run, capsys):
    (run / "04_risks.json").write_text('{"risks": [{"risk": "no fields"}]}', encoding="utf-8")
    assert score_run.main([RUN]) == 0
    assert "warning: risks not checked:" in capsys.readouterr().err
    (run / "04_risks.json").unlink()
    assert score_run.main([RUN]) == 0
    assert (run / "04_scores.json").exists()


def test_risks_citing_unknown_ids_are_warned_about(run, capsys):
    assert score_run.main([RUN]) == 0
    err = capsys.readouterr().err
    assert "warning: risk 'Synthetic: cites an id that does not exist.' cites unknown claim ids: market-404" in err
    assert "killcause-001" not in err


@pytest.mark.parametrize(
    ("args", "setup", "message"),
    [
        (["not-a-run"], None, "not a valid run id"),
        (["20261023-130001-nope"], None, "does not exist"),
        ([RUN], lambda run_dir: (run_dir / "04_scores_proposed.json").unlink(), "04_scores_proposed.json does not exist"),
        ([RUN], lambda run_dir: (run_dir / "04_scores_proposed.json").write_text('{"scores": [{"dimension": "x"}]}'), "is not valid"),
        ([RUN], lambda run_dir: (run_dir / "03_claims" / "verified.json").unlink(), "verified.json does not exist"),
        ([RUN], lambda run_dir: (run_dir / "00_spec.json").write_text("{}"), "00_spec.json is not valid"),
    ],
)  # fmt: skip
def test_score_run_errors(run, capsys, args, setup, message):
    if setup:
        setup(run)
    assert score_run.main(args) == 1
    assert message in capsys.readouterr().err
    assert not (run / "04_scores.json").exists()


def test_score_run_needs_the_run_in_the_database(project, capsys):
    db.init()
    runs.create_run_dir(RUN, "idea")
    assert score_run.main([RUN]) == 1
    assert "not in the database" in capsys.readouterr().err


# ---------------------------------------------------------------- stage state machine


def test_synthesize_and_score_stages_finish_on_the_written_files(run):
    for stage in runs.STAGES[: runs.STAGES.index("synthesize")]:
        db.stage_set(RUN, stage, "insufficient_data" if stage.startswith("research:") else "done")
    (run / "01_plan.json").write_text((FIXTURES / "plan.json").read_text(encoding="utf-8"), encoding="utf-8")
    runs.begin(RUN, "synthesize")
    runs.finish(RUN, "synthesize")
    runs.begin(RUN, "score")
    assert score_run.main([RUN]) == 0
    runs.finish(RUN, "score")
    assert runs.is_complete(RUN, "score")
    assert runs.next_stages(RUN) == ["report"]


# ---------------------------------------------------------------- schema rules for the proposal


def test_proposed_scores_reject_a_dimension_scored_twice():
    s = {"dimension": "gtm", "proposed_score": 1, "justification": "x", "supporting_claim_ids": ["gtm-001"]}
    with pytest.raises(ValueError, match="scored only once"):
        ProposedScores.model_validate({"scores": [s, s]})


def test_proposed_scores_allow_several_claims_only_for_additive_roles():
    ok = {"fixed_costs": ["a-001", "b-001"], "variable_cost": ["a-002", "b-002"], "price": ["a-003"]}
    assert ProposedScores.model_validate({"scores": [], "unit_economics_inputs": ok})
    with pytest.raises(ValueError, match="price takes at most one claim id"):
        ProposedScores.model_validate({"scores": [], "unit_economics_inputs": {"price": ["a-001", "a-002"]}})
    with pytest.raises(ValueError):
        ProposedScores.model_validate({"scores": [], "unit_economics_inputs": {"revenue": ["a-001"]}})


def test_schema_roles_match_economics():
    assert EconomicsRole.__args__ == economics.ROLES
    assert ADDITIVE_ECONOMICS_ROLES == economics.ADDITIVE_ROLES
