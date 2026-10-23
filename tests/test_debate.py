"""Debate anonymization (IF-402): seeded role → P-id mapping, positions_anon.json, no role leaks.

The run, its claim ledger and the positions come from the synthetic `debate_run` fixture in
conftest.py (TICKETS.md plan note 14).
"""

import json

import pytest
from conftest import DEBATE_RUN, debate_position

from ideaforge import db, debate
from ideaforge.schemas import PERSONAS

def anon_file(run_dir, round_no=0):
    return json.loads((run_dir / "debate" / f"round{round_no}" / "positions_anon.json").read_text(encoding="utf-8"))


def write_role(run_dir, round_no, role, data):
    d = run_dir / "debate" / f"round{round_no}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{role}.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------- mapping


def test_mapping_is_a_deterministic_permutation():
    for seed in range(20):
        m = debate.mapping_for(seed)
        assert sorted(m) == sorted(PERSONAS)
        assert sorted(m.values()) == ["P1", "P2", "P3", "P4", "P5"]
        assert debate.mapping_for(seed) == m
    assert len({tuple(debate.mapping_for(s).items()) for s in range(20)}) > 1


def test_seed_is_stored_in_debates_table_and_mapping_file(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=42)
    with db.session() as conn:
        row = conn.execute("SELECT seed, rounds, status FROM debates WHERE run_id=?", (DEBATE_RUN,)).fetchone()
    assert row["seed"] == 42
    stored = json.loads((debate_run / "debate" / ".mapping.json").read_text(encoding="utf-8"))
    assert stored == {"seed": 42, "mapping": debate.mapping_for(42)}


def test_seed_is_generated_once_and_reused(debate_run):
    debate.anonymize(DEBATE_RUN, 0)
    seed = json.loads((debate_run / "debate" / ".mapping.json").read_text(encoding="utf-8"))["seed"]
    first = anon_file(debate_run)
    debate.anonymize(DEBATE_RUN, 0)
    assert anon_file(debate_run) == first
    assert debate.load_mapping(DEBATE_RUN) == debate.mapping_for(seed)


def test_conflicting_seed_is_refused(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=1)
    with pytest.raises(debate.DebateError, match="already has seed 1"):
        debate.anonymize(DEBATE_RUN, 0, seed=2)


def test_mapping_file_and_db_disagreeing_is_an_error(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=1)
    (debate_run / "debate" / ".mapping.json").write_text(
        json.dumps({"seed": 7, "mapping": debate.mapping_for(7)}), encoding="utf-8"
    )
    with pytest.raises(debate.DebateError, match="differs"):
        debate.anonymize(DEBATE_RUN, 0)


def test_lost_db_row_is_restored_from_mapping_file(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=5)
    with db.session() as conn:
        conn.execute("DELETE FROM debates")
    assert debate.load_mapping(DEBATE_RUN) == debate.mapping_for(5)
    with db.session() as conn:
        assert conn.execute("SELECT seed FROM debates").fetchone()["seed"] == 5


def test_load_mapping_before_anonymize_is_an_error(debate_run):
    with pytest.raises(debate.DebateError, match="anonymize"):
        debate.load_mapping(DEBATE_RUN)


# ---------------------------------------------------------------- positions_anon.json


def test_anonymize_is_deterministic_given_the_seed(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=1234)
    first = (debate_run / "debate" / "round0" / "positions_anon.json").read_bytes()
    with db.session() as conn:
        conn.execute("DELETE FROM debates")
    (debate_run / "debate" / ".mapping.json").unlink()
    debate.anonymize(DEBATE_RUN, 0, seed=1234)
    assert (debate_run / "debate" / "round0" / "positions_anon.json").read_bytes() == first


def test_positions_are_ordered_by_p_id_and_match_the_mapping(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=99)
    mapping = debate.mapping_for(99)
    data = anon_file(debate_run)
    assert data["round"] == 0
    assert [p["position_id"] for p in data["positions"]] == ["P1", "P2", "P3", "P4", "P5"]
    for role, pid in mapping.items():
        entry = next(p for p in data["positions"] if p["position_id"] == pid)
        assert entry["proposed_change"] == f"Synthetic change {role[:2]}."


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 17, 2**31 - 1])
def test_no_role_names_leak(debate_run, seed):
    debate.anonymize(DEBATE_RUN, 0, seed=seed)
    text = (debate_run / "debate" / "round0" / "positions_anon.json").read_text(encoding="utf-8")
    assert '"role"' not in text and "seed" not in text and "mapping" not in text
    for role in PERSONAS:
        assert role not in text.lower()


def test_self_labels_are_redacted(debate_run):
    write_role(debate_run, 0, "accountant", debate_position(
        "accountant",
        objections=[{"text": "As the accountant persona I see VAT risk; I'm the Accountant here.", "claim_ids": []}],
        proposed_change="Per my accountant lens, register for VAT (debate-accountant).",
    ))
    debate.anonymize(DEBATE_RUN, 0, seed=3)
    text = json.dumps(anon_file(debate_run))
    assert "accountant" not in text.lower()
    assert "[persona]" in text


SELF_LABELS = [
    ("As the investor, I would not fund this.", "[persona], I would not fund this."),
    ("As an accountant I flag VAT.", "[persona] I flag VAT."),
    ("From an investor's perspective the market is thin.", "[persona] the market is thin."),
    ("From the operator point of view, winter is hard.", "[persona], winter is hard."),
    ("Customer here: too pricey.", "[persona]: too pricey."),
    ("I, the founder, disagree.", "[persona], disagree."),
    ("Speaking as operator, no.", "[persona], no."),
    ("I'm the Accountant's voice.", "[persona] voice."),
    ("Sijoittajana en rahoittaisi tätä.", "[persona] en rahoittaisi tätä."),
    ("Minä olen kirjanpitäjä ja ALV on riski.", "[persona] ja ALV on riski."),
]


@pytest.mark.parametrize(("text", "redacted"), SELF_LABELS)
def test_scrub_self_labels(text, redacted):
    assert debate.scrub(text) == redacted


@pytest.mark.parametrize(
    "text",
    [
        "Test the customer price with ten bookings.",
        "The founder role needs 20 hours a week.",
        "Yrittäjänä toimiminen vaatii starttirahan.",
        "Asiakkaana mökkiläinen maksaa 90 euroa.",
        "Price it for the customer segment that drives.",
    ],
)
def test_scrub_keeps_plain_role_words(text):
    assert debate.scrub(text) == text


def test_role_bearing_text_is_redacted_in_every_field(debate_run):
    write_role(debate_run, 0, "investor", debate_position(
        "investor",
        objections=[{"text": "As the investor, I see a thin market.", "claim_ids": ["market-001"]}],
        proposed_change="From an investor's perspective, cut the build cost.",
    ))
    debate.anonymize(DEBATE_RUN, 0, seed=4)
    write_role(debate_run, 1, "investor", {
        "role": "investor",
        "round": 1,
        "responses": [{
            "target_position_id": "P1" if debate.mapping_for(4)["investor"] != "P1" else "P2",
            "stance": "disagree",
            "basis": {"evidence_gap": "As an investor I miss churn data.",
                      "computation": "I, the investor, compute pricing-001 * 2 = 180"},
        }],
        "updated_change": "Investor here: open in May only.",
        "updated_change_basis": {"evidence_gap": "Speaking as investor, none."},
        "mini_research": {"question": "As the investor: what is the churn?", "dimension": "market",
                          "requested_by": "investor"},
    })
    debate.anonymize(DEBATE_RUN, 1)
    for round_no in (0, 1):
        text = json.dumps(anon_file(debate_run, round_no), ensure_ascii=False)
        assert "investor" not in text.lower(), round_no
        assert "[persona]" in text


def test_mapping_file_that_does_not_match_its_seed_is_an_error(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=1)
    path = debate_run / "debate" / ".mapping.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mapping"] = debate.mapping_for(2)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(debate.DebateError, match="does not match its seed"):
        debate.anonymize(DEBATE_RUN, 0)


def test_plain_words_that_are_also_role_names_stay(debate_run):
    write_role(debate_run, 0, "founder", debate_position(
        "founder", proposed_change="Test the customer price with ten bookings before the founder quits.",
    ))
    debate.anonymize(DEBATE_RUN, 0, seed=3)
    assert any("the customer price" in p["proposed_change"] for p in anon_file(debate_run)["positions"])


def test_rebuttal_round_drops_requested_by_and_rejected_roles(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=8)
    mapping = debate.mapping_for(8)
    for role in PERSONAS:
        write_role(debate_run, 1, role, {
            "role": role,
            "round": 1,
            "responses": [],
            "mini_research": {"question": "Synthetic question?", "dimension": "market", "requested_by": role},
        })
    (debate_run / "debate" / "round1" / "REJECTED_customer").write_text("reason\n", encoding="utf-8")
    result = debate.anonymize(DEBATE_RUN, 1)
    data = anon_file(debate_run, 1)
    assert result.excluded == ["customer"]
    assert mapping["customer"] not in [p["position_id"] for p in data["positions"]]
    assert len(data["positions"]) == 4
    text = json.dumps(data)
    assert "requested_by" not in text and '"role"' not in text
    assert all(p["mini_research"] == {"question": "Synthetic question?", "dimension": "market"} for p in data["positions"])


def test_round0_positions_are_recorded_as_turns(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=8)
    debate.anonymize(DEBATE_RUN, 0)  # re-running does not add attempts
    with db.session() as conn:
        rows = conn.execute("SELECT role, anon_id, attempt, accepted FROM debate_turns WHERE round=0").fetchall()
    assert {(r["role"], r["anon_id"], r["attempt"], r["accepted"]) for r in rows} == {
        (role, pid, 1, 1) for role, pid in debate.mapping_for(8).items()
    }


def test_missing_persona_is_reported_not_fatal(debate_run):
    (debate_run / "debate" / "round0" / "operator.json").unlink()
    result = debate.anonymize(DEBATE_RUN, 0, seed=8)
    assert result.missing == ["operator"]
    assert debate.mapping_for(8)["operator"] not in result.position_ids


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda d: (d / "investor.json").write_text("{}", encoding="utf-8"), "not a valid Position"),
        (lambda d: (d / "investor.json").write_text(json.dumps(debate_position("founder")), encoding="utf-8"), "expected 'investor'"),
        (lambda d: [p.unlink() for p in d.glob("*.json")], "no usable persona files"),
    ],
)
def test_bad_inputs_are_errors(debate_run, change, match):
    change(debate_run / "debate" / "round0")
    with pytest.raises(debate.DebateError, match=match):
        debate.anonymize(DEBATE_RUN, 0, seed=1)


def test_unknown_run_and_missing_round(project, debate_run):
    (project / "runs" / "20261023-150000-other").mkdir()
    with pytest.raises(debate.DebateError, match="not in the database"):
        debate.anonymize("20261023-150000-other", 0)
    with pytest.raises(debate.DebateError, match="does not exist"):
        debate.anonymize(DEBATE_RUN, 4)


def test_cli(debate_run, capsys):
    assert debate.main(["anonymize", DEBATE_RUN, "0", "--seed", "11"]) == 0
    out = capsys.readouterr().out
    assert "debate/round0/positions_anon.json: P1, P2, P3, P4, P5" in out
    for role in PERSONAS:
        assert role not in out
    assert debate.main(["anonymize", DEBATE_RUN, "0", "--seed", "12"]) == 1
    assert "already has seed 11" in capsys.readouterr().err
