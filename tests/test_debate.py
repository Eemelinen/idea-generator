"""Debate anonymization (IF-402): seeded role → P-id mapping, positions_anon.json, no role leaks.

The run, its claim ledger and the positions come from the synthetic `debate_run` fixture in
conftest.py (TICKETS.md plan note 14).
"""

import json

import pytest
from conftest import DEBATE_RUN, debate_position

from ideaforge import db, debate
from ideaforge.schemas import PERSONAS, Rebuttal


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
    # Every form TICKETS.md plan note 25 lists, so the note and the patterns cannot drift apart.
    ("See debate-founder.", "See [persona]."),
    ("The investor persona says no.", "[persona] says no."),
    ("Through an operator lens, staffing fails.", "Through [persona], staffing fails."),
    ("As a customer, I would book once.", "[persona], I would book once."),
    ("I am the operator.", "[persona]."),
    ("Speaking as the accountant, VAT applies.", "[persona], VAT applies."),
    ("From the founder's side, time is short.", "[persona], time is short."),
    ("From an accountant's standpoint it adds up.", "[persona] it adds up."),
    ("From the customer's view it is cheap.", "[persona] it is cheap."),
    ("From the investor's angle it is small.", "[persona] it is small."),
    ("As investor, I would pass.", "[persona], I would pass."),
    ("Margins are thin. As operator I would hire.", "Margins are thin. [persona] I would hire."),
    ("As customer I would pay 40 EUR.", "[persona] I would pay 40 EUR."),
    ("Too slow!  As investor I pass.", "Too slow!  [persona] I pass."),
    ("Risk? As accountant I see VAT.", "Risk? [persona] I see VAT."),
    ("Verdict: as founder I stay.", "Verdict: [persona] I stay."),
    ("Fine; as customer I book.", "Fine; [persona] I book."),
    ("(As investor I pass.)", "([persona] I pass.)"),
    ("- As operator I hire.", "- [persona] I hire."),
    ("Line one\nAs accountant I warn.", "Line one\n[persona] I warn."),
    ("As my accountant role, I flag VAT.", "[persona] role, I flag VAT."),
    ("Speaking as our investor: no.", "[persona]: no."),
    ("As our founder, I would wait.", "[persona], I would wait."),
    ("As this operator, I would hire.", "[persona], I would hire."),
    ("As your customer I pay less.", "[persona] I pay less."),
    ("From investor's perspective, it is thin.", "[persona], it is thin."),
    ("From the founders' point of view, no.", "[persona], no."),
    ("Perustajana jaksan 20 tuntia.", "[persona] jaksan 20 tuntia."),
    ("Kirjanpitäjänä näen riskin.", "[persona] näen riskin."),
    ("Minä olen kirjanpitäjänä huolissani.", "[persona] huolissani."),
    ("Tilintarkastajana vaadin kuitit.", "[persona] vaadin kuitit."),
    ("Operaattorina palkkaisin apua.", "[persona] palkkaisin apua."),
    ("Mä oon sijoittaja. Minä sijoittaja en maksa.", "[persona]. [persona] en maksa."),
    ("Minä olen asiakas ja maksan 40 euroa.", "[persona] ja maksan 40 euroa."),
    ("Minä yrittäjä teen kaiken.", "[persona] teen kaiken."),
    ("Mä olen operaattori, en myyjä.", "[persona], en myyjä."),
    ("Minä oon tilintarkastaja.", "[persona]."),
    ("Mä perustajana jaksan.", "[persona] jaksan."),
    ("Sijoittajan näkökulmasta markkina on pieni.", "[persona] markkina on pieni."),
    ("Kirjanpitäjän silmin ALV on riski.", "[persona] ALV on riski."),
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
        "Collect proof such as customer reviews.",
        "Treat them as operator costs.",
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
    expected = {"question": "Synthetic question?", "dimension": "market"}
    assert all(p["mini_research"] == expected for p in data["positions"])


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
        (
            lambda d: (d / "investor.json").write_text(json.dumps(debate_position("founder")), encoding="utf-8"),
            "expected 'investor'",
        ),
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


# ---------------------------------------------------------------- conformity flag (IF-405)

CONF_SEED = 2026
CONF_MAP = debate.mapping_for(CONF_SEED)
TARGET = "founder"  # the position the others agree on
COMPUTATION = {"computation": "market-001 gives 1200 nights x 0.3 = 360 bookable nights"}


def stance(role, stance_name, basis=None, target=TARGET):
    basis = basis or ({"evidence_gap": "No verified claim."} if stance_name == "disagree" else COMPUTATION)
    return {"target_position_id": CONF_MAP[target], "stance": stance_name, "basis": basis}


def conf_rebuttal(role, *responses, round_no=1):
    if not responses:
        responses = (stance(role, "disagree", target="investor" if role != "investor" else "customer"),)
    return Rebuttal.model_validate({"role": role, "round": round_no, "responses": list(responses)})


def turns(*agreeing, stance_name="agree"):
    out = {role: conf_rebuttal(role) for role in PERSONAS}
    for role in agreeing:
        out[role] = conf_rebuttal(role, stance(role, stance_name))
    return out


def test_conformity_four_of_five_backing_one_change_without_new_claims():
    # the author backs its own change, so three agreeing personas make four of five
    assert debate.conformity_flag(turns("investor", "customer", "accountant"), CONF_MAP, set())
    assert debate.conformity_flag(turns("investor", "customer", "accountant", "operator"), CONF_MAP, set())


def test_conformity_needs_four_backers():
    assert not debate.conformity_flag(turns("investor", "customer"), CONF_MAP, set())
    assert debate.backers(turns("investor", "customer"), CONF_MAP)[CONF_MAP[TARGET]] == {"founder", "investor", "customer"}


def test_conformity_is_off_when_a_new_claim_id_entered():
    assert not debate.conformity_flag(turns("investor", "customer", "accountant", "operator"), CONF_MAP, {"market-002"})


@pytest.mark.parametrize("stance_name", ["modify", "disagree"])
def test_conformity_counts_only_agree(stance_name):
    assert not debate.conformity_flag(turns("investor", "customer", "accountant", stance_name=stance_name), CONF_MAP, set())


def test_conformity_agreement_split_over_two_changes_is_not_conformity():
    t = turns("investor", "customer")
    t["accountant"] = conf_rebuttal("accountant", stance("accountant", "agree", target="operator"))
    t["operator"] = conf_rebuttal("operator", stance("operator", "agree", target="investor"))
    assert not debate.conformity_flag(t, CONF_MAP, set())


def write_conf_round(run_dir, round_no, data):
    for role, turn in data.items():
        write_role(run_dir, round_no, role, turn if isinstance(turn, dict) else turn.model_dump(mode="json"))
    return debate.validate_round(DEBATE_RUN, round_no)


def test_run_conformity_flag_from_the_validated_last_round(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=CONF_SEED)
    assert not debate.run_conformity_flag(DEBATE_RUN)  # no rebuttal round yet
    # agreement backed only by computations over market-001, which every round-0 position cites
    assert not write_conf_round(debate_run, 1, turns("investor", "customer", "accountant")).rejected
    assert debate.run_conformity_flag(DEBATE_RUN)


def test_run_conformity_flag_off_once_new_evidence_entered_in_any_round(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=CONF_SEED)
    first = turns()
    first["operator"] = conf_rebuttal("operator", stance("operator", "disagree", {"new_claim_ids": ["pricing-001"]}))
    assert not write_conf_round(debate_run, 1, first).rejected
    second = {r: conf_rebuttal(r, *t.responses, round_no=2) for r, t in turns("investor", "customer", "accountant").items()}
    assert not write_conf_round(debate_run, 2, second).rejected
    assert not debate.run_conformity_flag(DEBATE_RUN)


def test_run_conformity_flag_ignores_rejected_agreement(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=CONF_SEED)
    t = turns("investor", "customer")
    t["accountant"] = conf_rebuttal("accountant", stance("accountant", "agree", {"evidence_gap": "None."}))
    result = write_conf_round(debate_run, 1, t)
    assert list(result.rejected) == ["accountant"]
    assert not debate.run_conformity_flag(DEBATE_RUN)


# ---------------------------------------------------------------- evidence subsets and mini-research (IF-407)

import shutil  # noqa: E402

import debate_validate  # noqa: E402
from conftest import DEBATE_CLAIMS, FIXTURES  # noqa: E402
from test_verify import FakeWeb, html  # noqa: E402

from ideaforge import agents, mini_research, verify  # noqa: E402
from ideaforge.schemas import RESEARCH_DIMENSIONS, Claim  # noqa: E402

MINI_SEED = 2026
MINI_MAP = debate.mapping_for(MINI_SEED)
MINI_URL = "https://example.invalid/synthetic/mini-market"
MINI_QUOTE = "Synthetic quote: 40 remote workers rented a lakeside cabin in 2025."
GAP = {"evidence_gap": "No verified claim on winter occupancy."}


def other_id(role):
    return next(pid for r, pid in MINI_MAP.items() if r != role)


def plain(role, round_no, **fields):
    response = {"target_position_id": other_id(role), "stance": "disagree", "basis": GAP}
    return {"role": role, "round": round_no, "responses": [response]} | fields


def request(role, dimension="market"):
    return {"question": "Synthetic question?", "dimension": dimension, "requested_by": role}


def rebuttal_round(run_dir, round_no, **overrides):
    for role in PERSONAS:
        write_role(run_dir, round_no, role, overrides.get(role) or plain(role, round_no))
    return debate.validate_round(DEBATE_RUN, round_no)


def mini_markdown(claim_id="market-101", dimension="market"):
    """A synthetic mini-research file (TICKETS.md plan note 14) that meets the research contract."""
    claim = {
        "claim_id": claim_id, "dimension": dimension, "statement": "Synthetic: 40 remote workers rented a cabin.",
        "value": 40, "unit": "persons", "source_url": MINI_URL, "source_title": "Synthetic source",
        "quote": MINI_QUOTE, "published_date": None, "source_type": "news", "confidence": 0.7, "flags": [],
    }  # fmt: skip
    return (
        f"# {dimension}\n\nA synthetic mini-research answer.\n\n## Findings\n\n"
        f"Synthetic: 40 remote workers rented a lakeside cabin in 2025 [src: {MINI_URL}].\n> {MINI_QUOTE}\n\n"
        f"## Candidate claims\n\n```json\n{json.dumps([claim], indent=2)}\n```\n\n## Gaps\n\n- None (synthetic).\n"
    )


def write_mini(run_dir, task, text=None):
    path = task.output(DEBATE_RUN)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else mini_markdown(f"{task.dimension}-{task.claim_start:03d}",
                                                               task.dimension), encoding="utf-8")
    with open(run_dir / ".seen_urls.txt", "a", encoding="utf-8") as f:
        f.write(f"{task.agent}\t{MINI_URL}\n")


@pytest.fixture
def debating(debate_run):
    debate.anonymize(DEBATE_RUN, 0, seed=MINI_SEED)
    shutil.copy(FIXTURES / "scores.json", debate_run / "04_scores.json")
    return debate_run


def test_persona_evidence_files_hold_only_their_subset(debate_run):
    debate.write_evidence(DEBATE_RUN, seed=MINI_SEED)
    verified = {cid for cid, state in DEBATE_CLAIMS.items() if state == "verified"}
    for role in PERSONAS:
        data = json.loads(debate.evidence_path(DEBATE_RUN, role).read_text(encoding="utf-8"))
        dims = agents.PERSONA_EVIDENCE[role] or RESEARCH_DIMENSIONS
        assert data["role"] == role and data["position_id"] == MINI_MAP[role]
        assert data["dimensions"] == list(dims)
        ids = {c["claim_id"] for c in data["claims"]}
        assert ids == {cid for cid in verified if cid.rsplit("-", 1)[0] in dims}, role
        assert all(c["verification"] == "verified" for c in data["claims"])
        assert data["mini_research_claims"] == []
    founder = json.loads(debate.evidence_path(DEBATE_RUN, "founder").read_text(encoding="utf-8"))
    assert {c["claim_id"] for c in founder["claims"]} == verified
    accountant = json.loads(debate.evidence_path(DEBATE_RUN, "accountant").read_text(encoding="utf-8"))
    assert {c["claim_id"] for c in accountant["claims"]} == {"regulation-001", "unit_economics-001"}


def test_evidence_creates_the_debate_seed_used_by_anonymize(debate_run):
    debate.write_evidence(DEBATE_RUN, seed=7)
    debate.anonymize(DEBATE_RUN, 0)
    assert debate.load_mapping(DEBATE_RUN) == debate.mapping_for(7)
    assert debate.main(["evidence", DEBATE_RUN, "--seed", "8"]) == 1


def test_evidence_is_stale_when_the_ledger_changes(debate_run):
    debate.write_evidence(DEBATE_RUN, seed=MINI_SEED)
    assert debate.stale_evidence(DEBATE_RUN) == []
    ledger = debate_run / "03_claims" / "verified.json"
    ledger.write_text(ledger.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert debate.stale_evidence(DEBATE_RUN) == list(PERSONAS)


def open_round(run_dir, round_no, role="investor", dimension="market"):
    result = rebuttal_round(run_dir, round_no, **{role: plain(role, round_no, mini_research=request(role, dimension))})
    assert result.rejected == {}, result.rejected
    return mini_research.open_task(DEBATE_RUN, round_no)


def test_open_turns_the_accepted_request_into_task_1(debating, capsys):
    task = open_round(debating, 1)
    assert (task.n, task.round, task.role, task.anon_id) == (1, 1, "investor", MINI_MAP["investor"])
    assert (task.dimension, task.status, task.claim_start) == ("market", "running", 101)
    assert task.output(DEBATE_RUN) == debating / "02_research" / "mini-1-market.md"
    assert mini_research.open_task(DEBATE_RUN, 1) == task  # idempotent
    assert mini_research.main(["open", DEBATE_RUN, "1"]) == 0
    out = capsys.readouterr().out
    assert "subagent_type: research-market" in out and "first claim id: market-101" in out
    assert f"output: runs/{DEBATE_RUN}/02_research/mini-1-market.md" in out


def test_a_round_without_a_request_opens_nothing(debating, capsys):
    rebuttal_round(debating, 1)
    assert mini_research.open_task(DEBATE_RUN, 1) is None
    assert mini_research.main(["open", DEBATE_RUN, "1"]) == 0
    assert "requested no mini-research" in capsys.readouterr().out


def finish_ok(run_dir, task):
    write_mini(run_dir, task)
    assert mini_research.finish_task(DEBATE_RUN, task.n).task.status == "done"
    web = FakeWeb({MINI_URL: html(MINI_QUOTE)})
    verify.verify_run(DEBATE_RUN, web, only=[task.stem])


def test_a_fourth_mini_research_request_is_refused(debating, capsys):
    for n in (1, 2, 3):
        task = open_round(debating, n)
        assert task.n == n
        finish_ok(debating, task)
    assert debate.debate_budget(DEBATE_RUN).max_mini_research_tasks == 3
    # Validation sends the fourth request back...
    result = rebuttal_round(debating, 4, investor=plain("investor", 4, mini_research=request("investor")))
    assert "max_mini_research_tasks: 3" in "\n".join(result.rejected["investor"])
    assert mini_research.open_task(DEBATE_RUN, 4) is None
    assert len(mini_research.tasks(DEBATE_RUN)) == 3


def test_open_refuses_a_request_past_the_limit(debating, monkeypatch, capsys):
    """The Python backstop: a request that passed validation is refused when the limit is used."""
    finish_ok(debating, open_round(debating, 1))
    open_round_2 = rebuttal_round(debating, 2, founder=plain("founder", 2, mini_research=request("founder")))
    assert open_round_2.rejected == {}
    budget = debate.debate_budget(DEBATE_RUN).model_copy(update={"max_mini_research_tasks": 1})
    monkeypatch.setattr(debate, "debate_budget", lambda run_id: budget)
    with pytest.raises(mini_research.Refused, match="max_mini_research_tasks: 1"):
        mini_research.open_task(DEBATE_RUN, 2)
    assert mini_research.main(["open", DEBATE_RUN, "2"]) == 3
    assert "refused:" in capsys.readouterr().err
    assert len(mini_research.tasks(DEBATE_RUN)) == 1


def test_economy_preset_allows_one_task(debating):
    with db.session() as conn:
        conn.execute("UPDATE runs SET budget_preset='economy' WHERE run_id=?", (DEBATE_RUN,))
    finish_ok(debating, open_round(debating, 1))
    result = rebuttal_round(debating, 2, customer=plain("customer", 2, mini_research=request("customer")))
    assert "max_mini_research_tasks: 1" in "\n".join(result.rejected["customer"])


def test_round_1_mini_research_claims_are_usable_in_round_2(debating):
    before = json.loads((debating / "03_claims" / "verified.json").read_text(encoding="utf-8"))
    task = open_round(debating, 1, role="customer")
    finish_ok(debating, task)
    ledger = json.loads((debating / "03_claims" / "verified.json").read_text(encoding="utf-8"))
    # earlier claims keep their state and retrieved_at
    assert [Claim.model_validate(c) for c in ledger[: len(before)]] == [Claim.model_validate(c) for c in before]
    new = ledger[len(before):]
    assert [(c["claim_id"], c["verification"]) for c in new] == [("market-101", "verified")]

    debate.write_evidence(DEBATE_RUN)
    for role in PERSONAS:  # every persona gets the new claim, whatever its subset
        data = json.loads(debate.evidence_path(DEBATE_RUN, role).read_text(encoding="utf-8"))
        assert [c["claim_id"] for c in data["mini_research_claims"]] == ["market-101"]
        assert "market-101" not in {c["claim_id"] for c in data["claims"]}

    agree = {"target_position_id": other_id("accountant"), "stance": "agree", "basis": {"new_claim_ids": ["market-101"]}}
    result = rebuttal_round(debating, 2, accountant={"role": "accountant", "round": 2, "responses": [agree]})
    assert "accountant" in result.accepted
    assert debate_validate.main([DEBATE_RUN, "2"]) == 0


def test_a_mini_research_claim_is_unknown_before_it_is_verified(debating):
    task = open_round(debating, 1)
    write_mini(debating, task)
    agree = {"target_position_id": other_id("accountant"), "stance": "agree", "basis": {"new_claim_ids": ["market-101"]}}
    result = rebuttal_round(debating, 2, accountant={"role": "accountant", "round": 2, "responses": [agree]})
    assert "market-101" in "\n".join(result.rejected["accountant"])


def test_finish_relaunches_once_then_sets_the_file_aside(debating, capsys):
    task = open_round(debating, 1)
    write_mini(debating, task, "# market\n\nNo claims.\n")
    assert mini_research.main(["finish", DEBATE_RUN, "1"]) == 2
    assert "Candidate claims" in capsys.readouterr().out
    assert mini_research.get(DEBATE_RUN, 1).status == "running"
    assert mini_research.main(["finish", DEBATE_RUN, "1"]) == 3
    failed = mini_research.get(DEBATE_RUN, 1)
    assert (failed.status, failed.attempts) == ("failed", 2)
    assert not task.output(DEBATE_RUN).exists()
    assert task.output(DEBATE_RUN).with_name("mini-1-market.md.failed").exists()
    # the failed task still counts, and a later round can open the next one
    nxt = open_round(debating, 2)
    assert nxt.n == 2


def test_finish_rejects_claim_ids_the_ledger_already_has(debating):
    task = open_round(debating, 1)
    write_mini(debating, task, mini_markdown("market-001"))
    result = mini_research.finish_task(DEBATE_RUN, 1)
    assert result.task.status == "running"
    assert "already in the run's ledger: market-001" in result.problems


def test_only_one_task_runs_at_a_time(debating):
    open_round(debating, 1)
    rebuttal_round(debating, 2, founder=plain("founder", 2, mini_research=request("founder")))
    with pytest.raises(debate.DebateError, match="still running"):
        mini_research.open_task(DEBATE_RUN, 2)


def test_claim_numbers_start_past_the_runs_ids(debating):
    finish_ok(debating, open_round(debating, 1))  # market-101
    second = open_round(debating, 2)
    assert second.claim_start == 201
    assert mini_research.claim_start(debating, "gtm") == 101


def test_verify_only_replaces_the_files_own_claims(debating):
    task = open_round(debating, 1)
    finish_ok(debating, task)
    web = FakeWeb({MINI_URL: html(MINI_QUOTE)})
    verify.verify_run(DEBATE_RUN, web, only=[task.stem])  # again: no duplicate, same ledger size
    ledger = json.loads((debating / "03_claims" / "verified.json").read_text(encoding="utf-8"))
    assert [c["claim_id"] for c in ledger].count("market-101") == 1
    assert len(ledger) == len(DEBATE_CLAIMS) + 1
    with pytest.raises(FileNotFoundError):
        verify.verify_run(DEBATE_RUN, web, only=["mini-9-market"])


# ---------------------------------------------------------------- re-prompts and resume (IF-407)


def test_reprompt_sends_each_rejected_persona_back_once(debating, capsys):
    bad = {"target_position_id": other_id("founder"), "stance": "agree", "basis": GAP}
    rebuttal_round(debating, 1, founder={"role": "founder", "round": 1, "responses": [bad]})
    assert debate.reprompt(DEBATE_RUN, 1) == (["founder"], [])
    assert debate.reprompt(DEBATE_RUN, 1) == ([], ["founder"])
    assert debate.main(["reprompt", DEBATE_RUN, "1"]) == 0
    assert "final: founder" in capsys.readouterr().out


def status():
    return debate.progress(DEBATE_RUN)


def test_status_walks_the_debate_step_by_step(debate_run, capsys):
    shutil.copy(FIXTURES / "scores.json", debate_run / "04_scores.json")
    assert status().step == "report"
    (debate_run / "05_report.md").write_text("# Synthetic report\n", encoding="utf-8")
    assert (status().step, status().roles) == ("evidence", list(PERSONAS))
    debate.write_evidence(DEBATE_RUN, seed=MINI_SEED)
    (debate_run / "debate" / "round0" / "operator.json").unlink()
    assert (status().step, status().round, status().roles) == ("positions", 0, ["operator"])
    write_role(debate_run, 0, "operator", debate_position("operator"))
    assert (status().step, status().round) == ("anonymize", 0)
    debate.anonymize(DEBATE_RUN, 0)
    assert (status().step, status().round, status().roles) == ("rebuttals", 1, list(PERSONAS))

    for role in PERSONAS[:4]:
        write_role(debate_run, 1, role, plain(role, 1))
    assert (status().step, status().roles) == ("rebuttals", ["operator"])
    bad = {"target_position_id": other_id("operator"), "stance": "agree", "basis": GAP}
    write_role(debate_run, 1, "operator", {"role": "operator", "round": 1, "responses": [bad]})
    assert status().step == "validate"
    debate.validate_round(DEBATE_RUN, 1)
    assert (status().step, status().roles) == ("reprompt", ["operator"])
    debate.reprompt(DEBATE_RUN, 1)
    write_role(debate_run, 1, "operator", plain("operator", 1, mini_research=request("operator")))
    assert status().step == "validate"
    debate.validate_round(DEBATE_RUN, 1)
    assert (status().step, status().round) == ("mini-research", 1)
    task = mini_research.open_task(DEBATE_RUN, 1)
    assert status().notes == ["task 1 is running"]
    write_mini(debate_run, task)
    mini_research.finish_task(DEBATE_RUN, 1)
    assert (status().step, status().notes) == ("verify", ["mini-1-market"])
    verify.verify_run(DEBATE_RUN, FakeWeb({MINI_URL: html(MINI_QUOTE)}), only=[task.stem])
    assert status().step == "evidence"
    debate.write_evidence(DEBATE_RUN)
    assert (status().step, status().round) == ("anonymize", 1)
    debate.anonymize(DEBATE_RUN, 1)
    assert (status().step, status().round) == ("interim", 1)
    scores = json.loads((debate_run / "04_scores.json").read_text(encoding="utf-8"))
    projected = {s["dimension"]: s["final_score"] for s in scores["scores"] if s["final_score"] is not None}
    moved = projected | {"market": min(5.0, projected["market"] + 1)}
    (debate_run / "debate" / "round1" / debate.INTERIM_NAME).write_text(
        json.dumps({"round": 1, "projected_scores": moved}), encoding="utf-8"
    )
    # round 1 brought a mini-research request and moved a projection, so the debate goes on
    assert (status().step, status().round) == ("rebuttals", 2)
    for role in PERSONAS:
        write_role(debate_run, 2, role, plain(role, 2))
    debate.validate_round(DEBATE_RUN, 2)
    debate.anonymize(DEBATE_RUN, 2)
    (debate_run / "debate" / "round2" / debate.INTERIM_NAME).write_text(
        json.dumps({"round": 2, "projected_scores": moved}), encoding="utf-8"
    )
    assert status().step == "judge"
    shutil.copy(FIXTURES / "debate" / "verdict.synthetic.json", debate_run / "debate" / "verdict.json")
    assert status().step == "render"
    (debate_run / "debate" / "revised_plan.md").write_text("# plan\n", encoding="utf-8")
    assert status().step == "done"
    assert debate.main(["status", DEBATE_RUN]) == 0
    assert capsys.readouterr().out.strip().endswith("next: done")
