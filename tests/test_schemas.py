import json

import pytest
from pydantic import TypeAdapter, ValidationError

from conftest import FIXTURES
from ideaforge.schemas import (
    SCHEMAS,
    Basis,
    Claim,
    IdeaSpec,
    ResearchPlan,
    Verdict,
)

OBJECT_FIXTURES = {
    "spec.json": "spec",
    "plan.json": "plan",
    "scores_proposed.json": "scores_proposed",
    "risks.json": "risks",
    "scores.json": "scores",
    "position.json": "position",
    "rebuttal.json": "rebuttal",
    "verdict.json": "verdict",
    "meta.json": "meta",
}


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,kind", OBJECT_FIXTURES.items())
def test_fixture_validates(name, kind):
    SCHEMAS[kind].model_validate(load(name))


def test_every_fixture_is_covered():
    on_disk = {p.name for p in FIXTURES.glob("*.json")}
    assert on_disk == set(OBJECT_FIXTURES) | {"claims.json"}


def test_claims_fixture_validates():
    claims = TypeAdapter(list[Claim]).validate_python(load("claims.json"))
    assert [c.claim_id for c in claims] == ["market-001", "competition-001"]


@pytest.mark.parametrize("name,kind", OBJECT_FIXTURES.items())
def test_extra_fields_rejected(name, kind):
    data = load(name) | {"unexpected": 1}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SCHEMAS[kind].model_validate(data)


def claim(**overrides):
    return load("claims.json")[0] | overrides


def test_claim_id_must_match_dimension():
    with pytest.raises(ValidationError, match="prefix"):
        Claim.model_validate(claim(claim_id="pricing-001"))


def test_claim_id_format():
    with pytest.raises(ValidationError, match="claim_id"):
        Claim.model_validate(claim(claim_id="market-1"))


def test_quote_max_60_words():
    Claim.model_validate(claim(quote=" ".join(["sana"] * 60)))
    with pytest.raises(ValidationError, match="60 words"):
        Claim.model_validate(claim(quote=" ".join(["sana"] * 61)))


def test_claim_rejects_unknown_flag_and_source_type():
    with pytest.raises(ValidationError):
        Claim.model_validate(claim(flags=["looks_bad"]))
    with pytest.raises(ValidationError):
        Claim.model_validate(claim(source_type="blog"))


def test_claim_url_must_be_http():
    with pytest.raises(ValidationError, match="http"):
        Claim.model_validate(claim(source_url="ftp://example.fi/x"))


def test_spec_allows_at_most_5_clarifications():
    data = load("spec.json")
    data["clarifications"] = [{"question": f"q{i}", "answer": "a"} for i in range(6)]
    with pytest.raises(ValidationError):
        IdeaSpec.model_validate(data)


def test_plan_requires_killcause_and_unique_dimensions():
    data = load("plan.json")
    no_kill = data | {"dimensions": [d for d in data["dimensions"] if d["dimension"] != "killcause"]}
    with pytest.raises(ValidationError, match="killcause"):
        ResearchPlan.model_validate(no_kill)
    dupes = data | {"dimensions": data["dimensions"] + [data["dimensions"][0]]}
    with pytest.raises(ValidationError, match="only once"):
        ResearchPlan.model_validate(dupes)


def test_basis_must_not_be_empty():
    with pytest.raises(ValidationError, match="basis needs"):
        Basis.model_validate({})


def test_verdict_accepted_change_needs_claim_id():
    data = load("verdict.json")
    data["accepted_changes"][0]["claim_ids"] = []
    with pytest.raises(ValidationError, match="must cite"):
        Verdict.model_validate(data)


def test_verdict_needs_five_experiments_with_a_threshold():
    data = load("verdict.json")
    Verdict.model_validate(data)
    with pytest.raises(ValidationError, match="at least 5"):
        Verdict.model_validate(data | {"experiments": data["experiments"][:4]})
    for blank in ("", "  "):
        data["experiments"][0]["success_threshold"] = blank
        with pytest.raises(ValidationError, match="success_threshold"):
            Verdict.model_validate(data)
