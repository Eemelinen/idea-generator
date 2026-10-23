"""Scoring (IF-302): evidence rules, caps, kill triggers, weighted total and verdict.

Every claim here is synthetic (TICKETS.md plan note 14): invented URLs and values that exercise
the logic and are never presented as real sources.
"""

from datetime import UTC, datetime

import pytest

from ideaforge import config, scoring
from ideaforge.config import EvidenceRule, VerdictThresholds
from ideaforge.schemas import RUBRIC_DIMENSIONS, Claim, DimensionScore, ScoreSheet, UnitEconomics

RUBRIC = config.rubric()


def claim(cid, url="https://example.com/synthetic", *, verification="verified", value=None, unit=None,
          statement="A synthetic statement.", flags=(), source_type="news"):  # fmt: skip
    return Claim(
        claim_id=cid,
        dimension=cid.rsplit("-", 1)[0],
        statement=statement,
        value=value,
        unit=unit,
        source_url=url,
        source_title="Synthetic source",
        quote="synthetic quote",
        retrieved_at=datetime(2026, 10, 23, tzinfo=UTC),
        source_type=source_type,
        confidence=0.8,
        flags=list(flags),
        verification=verification,
    )


def proposal(dim, score, ids=()):
    return DimensionScore(dimension=dim, proposed_score=score, justification="synthetic", supporting_claim_ids=list(ids))


def full_evidence(dim):
    """Three verified claims that pass every rubric rule: an official price, a cost and a count."""
    return [
        claim(f"{dim}-001", "https://www.vero.fi/synthetic", value=25, unit="EUR/unit", statement="The price is 25 EUR."),
        claim(f"{dim}-002", "https://www.example.com/a", value=400, unit="EUR/month", statement="Rent costs 400 EUR."),
        claim(f"{dim}-003", "https://example.org/b", value=1900, unit="persons", statement="1900 residents."),
    ]


def full_run(score=4.0):
    claims = [c for d in RUBRIC_DIMENSIONS for c in full_evidence(d)]
    proposed = [proposal(d, score, [f"{d}-001", f"{d}-002", f"{d}-003"]) for d in RUBRIC_DIMENSIONS]
    return proposed, claims


# ---------------------------------------------------------------- claim helpers


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://pxdata.stat.fi/PxWeb/api", "stat.fi"),
        ("https://www.vero.fi/yritykset", "vero.fi"),
        ("https://VERO.FI./x", "vero.fi"),
        ("https://www.bbc.co.uk/news", "bbc.co.uk"),
        ("https://ec.europa.eu/eurostat/data", "europa.eu"),
        ("https://localhost/x", "localhost"),
    ],
)
def test_domain(url, expected):
    assert scoring.domain(url) == expected


@pytest.mark.parametrize(
    ("cid", "value", "unit", "statement", "expected"),
    [
        ("market-001", None, "EUR", "No value.", None),
        ("market-001", 10, None, "No unit.", None),
        ("gtm-001", 25, "EUR", "The price of a sauna evening is 25 EUR.", "price"),
        ("gtm-001", 25, "€/unit", "Hinta on 25 euroa.", "price"),
        ("pricing-001", 25, "EUR", "A sauna evening costs 25 EUR.", "price"),
        ("gtm-001", 400, "EUR/month", "Rent is 400 EUR a month.", "cost"),
        ("gtm-001", 15, "EUR", "The platform fee is 15 EUR.", "cost"),
        ("regulation-001", 300, "EUR", "Vuokra on 300 euroa.", "cost"),
        ("unit_economics-001", 3, "EUR/unit", "Firewood for one evening.", "cost"),
        ("unit_economics-001", 30, "EUR", "The price per night is 30 EUR.", "price"),
        ("market-001", 20000, "EUR", "Turnover of the sector.", None),
        ("market-001", 1900, "persons", "1900 residents.", "unit_count"),
        ("competition-001", 12, "companies", "12 companies.", "unit_count"),
        ("market-001", 5000, "visitors/year", "5000 visitors a year.", "unit_count"),
        ("market-001", 40, "kpl", "40 mökkiä.", "unit_count"),
        ("market-001", 300, "households", "300 households.", "unit_count"),
        ("market-001", 1900, "asukasta", "Väkiluku 1 900 asukasta.", "unit_count"),
        ("market-001", 12, "henkilöä/km²", "Density.", None),
        ("market-001", 800, "nights/season", "800 nights a season.", "unit_count"),
        ("pricing-001", 25, "euroa", "25 euroa illalta.", "price"),
        ("market-001", 3, "species", "3 species.", None),
        ("market-001", 12, "%", "12 % growth.", None),
        ("location-001", 60, "km", "60 km to Joensuu.", None),
    ],
)
def test_numeric_field(cid, value, unit, statement, expected):
    assert scoring.numeric_field(claim(cid, value=value, unit=unit, statement=statement)) == expected


# ---------------------------------------------------------------- evidence rules


SAME_DOMAIN = [claim("customer-001", "https://a.example.com/1"), claim("customer-002", "https://b.example.com/2")]
THREE_DOMAINS = [
    claim("customer-001", "https://example.com/1"),
    claim("customer-002", "https://example.org/2"),
    claim("customer-003", "https://www.vero.fi/3"),
]


@pytest.mark.parametrize(
    ("evidence", "n", "independent", "expected"),
    [
        ([], 1, True, "min_sources: 0 of 1 independent source domains"),
        (SAME_DOMAIN, 2, True, "min_sources: 1 of 2 independent source domains"),
        (SAME_DOMAIN, 2, False, None),
        (SAME_DOMAIN, 3, False, "min_sources: 2 of 3 verified claims"),
        (THREE_DOMAINS, 3, True, None),
        (THREE_DOMAINS, 4, True, "min_sources: 3 of 4 independent source domains"),
    ],
)
def test_min_sources(evidence, n, independent, expected):
    assert scoring.min_sources(evidence, n, independent) == expected


@pytest.mark.parametrize(
    ("url", "source_type", "passes"),
    [
        ("https://www.vero.fi/x", "news", True),
        ("https://pxdata.stat.fi/api/x", "api", True),
        ("https://ec.europa.eu/eurostat/x", "official", True),
        ("https://ec.europa.eu/other/x", "official", False),
        # a model-declared `official` on a non-listed domain does not count (plan note 16)
        ("https://example.com/x", "official", False),
    ],
)
def test_has_official_source(url, source_type, passes):
    result = scoring.has_official_source([claim("regulation-001", url, source_type=source_type)])
    assert (result is None) is passes


def test_has_numeric():
    evidence = full_evidence("unit_economics")
    assert scoring.has_numeric(evidence, "price") is None
    assert scoring.has_numeric(evidence, "cost") is None
    assert scoring.has_numeric(evidence[:1], "cost") == "has_numeric(cost): no verified claim with a cost value"
    with pytest.raises(ValueError, match="unknown field 'revenue'"):
        scoring.has_numeric(evidence, "revenue")


@pytest.mark.parametrize(
    ("rule", "error"),
    [
        ({"rule": "min_sources"}, "integer n >= 1"),
        ({"rule": "min_sources", "n": 0}, "integer n >= 1"),
        ({"rule": "min_sources", "n": True}, "integer n >= 1"),
        ({"rule": "min_sources", "n": 2, "independent": "yes"}, "independent must be true or false"),
        ({"rule": "min_sources", "n": 2, "domains": 3}, "unknown parameters"),
        ({"rule": "has_official_source", "n": 1}, "unknown parameters"),
        ({"rule": "has_numeric"}, "unknown field None"),
        ({"rule": "has_numeric", "field": "revenue"}, "unknown field 'revenue'"),
    ],
)
def test_malformed_rules_raise(rule, error):
    with pytest.raises(ValueError, match=error):
        scoring.check_rule(EvidenceRule.model_validate(rule), [])


def test_rubric_rules_all_apply():
    scoring.check_rubric(RUBRIC)


def test_broken_rubric_names_the_dimension():
    broken = RUBRIC.model_copy(deep=True)
    broken.dimension("gtm").evidence_rule.append(EvidenceRule.model_validate({"rule": "has_numeric", "field": "x"}))
    with pytest.raises(ValueError, match="rubric dimension gtm: has_numeric: unknown field 'x'"):
        scoring.check_rubric(broken)


# ---------------------------------------------------------------- caps


@pytest.mark.parametrize(
    ("dim", "proposed", "evidence_ids", "final", "status", "reason"),
    [
        # every rule passes: the proposed score stands
        ("customer", 4.5, ["customer-001", "customer-002", "customer-003"], 4.5, "scored", None),
        ("regulation", 5.0, ["regulation-001", "regulation-002"], 5.0, "scored", None),
        # fewer than 3 independent domains → capped at 2 with the reason
        ("customer", 4.5, ["customer-001", "customer-002"], 2.0, "insufficient_data", "min_sources: 2 of 3"),
        # a failed rule labels the dimension even when the proposal is already ≤ 2
        ("customer", 1.0, ["customer-001"], 1.0, "insufficient_data", "min_sources: 1 of 3"),
        # official source missing
        ("regulation", 4.0, ["regulation-002", "regulation-003"], 2.0, "insufficient_data", "has_official_source"),
        # numeric field missing; failures are joined
        ("pricing", 4.0, ["pricing-003"], 2.0, "insufficient_data", "has_numeric(price)"),
        ("market", 4.0, ["market-001"], 2.0, "insufficient_data", "min_sources: 1 of 3 independent source domains; has_numeric(unit_count)"),
        # unverified, conflicting and unknown citations are dropped before the rules run
        ("customer", 4.0, ["customer-001", "customer-002", "customer-009", "customer-010", "nope-001"], 2.0, "insufficient_data", "min_sources: 2 of 3"),
        ("financing", 3.0, [], 2.0, "insufficient_data", "min_sources: 0 of 2"),
    ],
)  # fmt: skip
def test_caps(dim, proposed, evidence_ids, final, status, reason):
    claims = {c.claim_id: c for c in full_evidence(dim)}
    claims[f"{dim}-009"] = claim(f"{dim}-009", "https://example.net/9", verification="unverified")
    claims[f"{dim}-010"] = claim(f"{dim}-010", "https://example.net/10", verification="conflict")
    result = scoring.score_dimension(proposal(dim, proposed, evidence_ids), claims, RUBRIC)
    assert result.final_score == final
    assert result.status == status
    if reason is None:
        assert result.cap_reason is None
    else:
        assert reason in result.cap_reason
    assert all(claims[cid].verification == "verified" for cid in result.supporting_claim_ids)


def test_citation_from_another_dimension_counts():
    # unit_economics cites the price found by the pricing agent (plan note 20)
    claims = {c.claim_id: c for c in [*full_evidence("pricing"), *full_evidence("unit_economics")]}
    ids = ["pricing-001", "unit_economics-002", "unit_economics-003"]
    assert scoring.score_dimension(proposal("unit_economics", 4, ids), claims, RUBRIC).status == "scored"
    claims["gtm-001"] = claim("gtm-001", "https://example.net/channel")
    no_price = ["unit_economics-002", "unit_economics-003", "gtm-001"]
    capped = scoring.score_dimension(proposal("unit_economics", 4, no_price), claims, RUBRIC)
    assert capped.cap_reason == "has_numeric(price): no verified claim with a price value"


def test_citations_deduplicated_and_dropped():
    claims = {c.claim_id: c for c in [claim("gtm-001"), claim("gtm-002", verification="pending")]}
    kept, dropped = scoring.verified_citations(proposal("gtm", 3, ["gtm-001", "gtm-001", "gtm-002", "x-001"]), claims)
    assert kept == ["gtm-001"]
    assert dropped == ["gtm-002", "x-001"]


def test_dropped_citations_per_dimension():
    proposed, claims = full_run()
    proposed[0] = proposal("customer", 4, ["customer-001", "customer-404"])
    assert scoring.dropped_citations(proposed, claims) == {"customer": ["customer-404"]}


# ---------------------------------------------------------------- kill triggers


@pytest.mark.parametrize(
    ("claims", "overrides", "computed", "expected"),
    [
        ([claim("regulation-001", flags=["permit_impossible"])], [], [], ["permit_impossible"]),
        ([claim("killcause-001", flags=["permit_impossible", "free_good_enough_substitute"])], [], [],
         ["free_good_enough_substitute", "permit_impossible"]),
        # only verified claims fire
        ([claim("regulation-001", flags=["permit_impossible"], verification="unverified")], [], [], []),
        ([claim("regulation-001", flags=["permit_impossible"], verification="conflict")], [], [], []),
        # verification flags are not kill triggers
        ([claim("market-001", flags=["unfetchable"])], [], [], []),
        # spec overrides remove a trigger, also a computed one
        ([claim("regulation-001", flags=["permit_impossible"])], ["permit_impossible"], [], []),
        ([], [], ["negative_contribution_margin"], ["negative_contribution_margin"]),
        ([], ["negative_contribution_margin"], ["negative_contribution_margin"], []),
    ],
)  # fmt: skip
def test_kill_triggers(claims, overrides, computed, expected):
    assert scoring.fired_kill_triggers(claims, overrides, computed) == expected


def test_unknown_computed_trigger_raises():
    with pytest.raises(ValueError, match="unknown kill trigger 'bad_vibes'"):
        scoring.fired_kill_triggers([], computed=["bad_vibes"])


# ---------------------------------------------------------------- total and verdict


@pytest.mark.parametrize(
    ("total", "insufficient", "triggers", "expected"),
    [
        (5.0, 0, [], "GO"),
        (3.5, 0, [], "GO"),
        (3.49, 0, [], "PIVOT"),
        (2.5, 2, [], "PIVOT"),
        (2.49, 0, [], "NO_GO"),
        (0.0, 0, [], "NO_GO"),
        (4.0, 3, [], "INSUFFICIENT_DATA"),
        (4.0, 0, ["permit_impossible"], "NO_GO"),
        # verified kill evidence outranks missing data
        (4.0, 5, ["permit_impossible"], "NO_GO"),
    ],
)
def test_verdict(total, insufficient, triggers, expected):
    assert scoring.verdict(total, insufficient, triggers, RUBRIC) == expected


def test_verdict_thresholds_come_from_the_rubric():
    strict = RUBRIC.model_copy(
        update={"verdict_thresholds": VerdictThresholds(go=4.5, pivot=4.0, max_insufficient_dimensions=0)}
    )
    assert scoring.verdict(4.2, 0, [], strict) == "PIVOT"
    assert scoring.verdict(3.9, 0, [], strict) == "NO_GO"
    assert scoring.verdict(5.0, 1, [], strict) == "INSUFFICIENT_DATA"
    proposed, claims = full_run(3.9)
    assert scoring.score(proposed, claims, rubric=strict).verdict == "NO_GO"


def test_weighted_total_uses_rubric_weights():
    scores = [proposal(d, 0).model_copy(update={"final_score": 0.0}) for d in RUBRIC_DIMENSIONS]
    scores[0] = scores[0].model_copy(update={"final_score": 5.0})  # customer, weight 0.15
    assert scoring.weighted_total(scores, RUBRIC) == 0.75


def test_weighted_total_needs_final_scores():
    with pytest.raises(ValueError, match="customer has no final_score"):
        scoring.weighted_total([proposal("customer", 3)], RUBRIC)


# ---------------------------------------------------------------- whole run


def test_well_supported_run_is_go():
    proposed, claims = full_run(4.0)
    sheet = scoring.score(proposed, claims)
    assert [s.dimension for s in sheet.scores] == list(RUBRIC_DIMENSIONS)
    assert all(s.status == "scored" and s.final_score == 4.0 for s in sheet.scores)
    assert sheet.weighted_total == 4.0
    assert sheet.kill_triggers_fired == []
    assert sheet.verdict == "GO"
    assert sheet.unit_economics == UnitEconomics()
    assert ScoreSheet.model_validate_json(sheet.model_dump_json()) == sheet


def test_permit_impossible_claim_flips_to_no_go():
    proposed, claims = full_run(4.5)
    claims.append(claim("killcause-001", "https://www.raakkyla.fi/synthetic", flags=["permit_impossible"]))
    sheet = scoring.score(proposed, claims)
    assert sheet.weighted_total == 4.5
    assert sheet.kill_triggers_fired == ["permit_impossible"]
    assert sheet.verdict == "NO_GO"
    # the spec's override restores the threshold verdict
    assert scoring.score(proposed, claims, ["permit_impossible"]).verdict == "GO"


def test_computed_trigger_and_unit_economics_pass_through():
    proposed, claims = full_run(4.0)
    economics = UnitEconomics(price_eur=25, variable_cost_eur=30, contribution_margin_eur=-5)
    sheet = scoring.score(
        proposed, claims, unit_economics=economics, computed_triggers=["negative_contribution_margin"]
    )
    assert sheet.unit_economics == economics
    assert sheet.kill_triggers_fired == ["negative_contribution_margin"]
    assert sheet.verdict == "NO_GO"


def test_missing_dimensions_are_scored_zero_and_capped():
    proposed, claims = full_run(4.0)
    sheet = scoring.score(proposed[:7], claims)  # financing, location, founder_risk not proposed
    missing = [s for s in sheet.scores if s.dimension in ("financing", "location", "founder_risk")]
    assert all(s.final_score == 0 and s.status == "insufficient_data" and s.cap_reason for s in missing)
    assert all(s.justification == "no proposed score" for s in missing)
    assert sheet.weighted_total == pytest.approx(4.0 * 0.85)
    assert sheet.verdict == "INSUFFICIENT_DATA"


def test_two_insufficient_dimensions_still_get_a_threshold_verdict():
    proposed, claims = full_run(4.0)
    proposed[0] = proposal("customer", 4.0, ["customer-001"])
    proposed[1] = proposal("market", 4.0, [])
    sheet = scoring.score(proposed, claims)
    assert [s.status for s in sheet.scores].count("insufficient_data") == 2
    assert sheet.weighted_total == pytest.approx(4.0 - 0.15 * 2 - 0.10 * 2)
    assert sheet.verdict == "GO"


def test_duplicate_dimension_raises():
    proposed, claims = full_run()
    with pytest.raises(ValueError, match="customer is scored more than once"):
        scoring.score([*proposed, proposal("customer", 1)], claims)
