"""Unit economics (IF-303): claim mapping, VAT treatment, margin, break-even, payback, sensitivity.

Every claim here is synthetic (TICKETS.md plan note 14): invented URLs and values that exercise
the arithmetic and are never presented as real sources.
"""

from datetime import UTC, datetime

import pytest

from ideaforge import economics, scoring
from ideaforge.economics import Amount, Inputs
from ideaforge.schemas import Claim, UnitEconomics


def claim(cid, value, unit, statement="A synthetic statement.", *, verification="verified"):
    return Claim(
        claim_id=cid,
        dimension=cid.rsplit("-", 1)[0],
        statement=statement,
        value=value,
        unit=unit,
        source_url="https://example.com/synthetic",
        source_title="Synthetic source",
        quote="synthetic quote",
        retrieved_at=datetime(2026, 10, 23, tzinfo=UTC),
        source_type="news",
        confidence=0.8,
        verification=verification,
    )


def base_inputs(**changes):
    """Net-of-VAT inputs: price 25, cost 5, fixed 400/month, 100 units/month, CAC 30, 2 purchases/month."""
    values = {
        "price": Amount(25, ("pricing-001",), "excl"),
        "variable_cost": (Amount(5, ("unit_economics-001",), "excl"),),
        "fixed_costs": (Amount(400, ("unit_economics-002",), "excl"),),
        "cac": Amount(30, ("gtm-001",), "excl"),
        "volume": Amount(100, ("unit_economics-003",)),
        "purchases_per_customer": Amount(2, ("customer-001",)),
    }
    return Inputs(**(values | changes))


# ---------------------------------------------------------------- arithmetic on known inputs


def test_known_inputs():
    ue = economics.compute(base_inputs())
    assert ue.price_eur == 25
    assert ue.variable_cost_eur == 5
    assert ue.contribution_margin_eur == 20
    assert ue.contribution_margin_pct == pytest.approx(80)
    assert ue.fixed_costs_month_eur == 400
    assert ue.break_even_units_month == pytest.approx(20)
    assert ue.monthly_profit_eur == pytest.approx(1600)  # 20 × 100 − 400
    assert ue.payback_months == pytest.approx(0.75)  # 30 / (20 × 2)
    assert ue.purchases_per_customer_month == 2
    assert ue.missing_inputs == []
    assert ue.vat_registered is True
    assert ue.input_claim_ids == ["pricing-001", "unit_economics-001", "unit_economics-002", "gtm-001",
                                  "unit_economics-003", "customer-001"]  # fmt: skip
    assert economics.computed_triggers(ue) == []


def test_sensitivity_table():
    ue = economics.compute(base_inputs())
    table = {(r.price_change_pct, r.volume_change_pct): r.monthly_profit_eur for r in ue.sensitivity}
    assert len(table) == 9
    assert table[(0.0, 0.0)] == pytest.approx(ue.monthly_profit_eur)
    assert table[(-30.0, -30.0)] == pytest.approx((17.5 - 5) * 70 - 400)  # 475
    assert table[(-30.0, 30.0)] == pytest.approx((17.5 - 5) * 130 - 400)
    assert table[(30.0, -30.0)] == pytest.approx((32.5 - 5) * 70 - 400)
    assert table[(30.0, 30.0)] == pytest.approx((32.5 - 5) * 130 - 400)  # 3175


def test_negative_margin_sets_the_kill_trigger():
    ue = economics.compute(base_inputs(price=Amount(20, ("pricing-001",), "excl"),
                                       variable_cost=(Amount(25, ("unit_economics-001",), "excl"),)))  # fmt: skip
    assert ue.contribution_margin_eur == -5
    assert ue.contribution_margin_pct == pytest.approx(-25)
    assert ue.break_even_units_month is None
    assert ue.payback_months is None
    assert ue.monthly_profit_eur == pytest.approx(-900)  # −5 × 100 − 400
    assert "contribution margin is not positive: no break-even volume" in ue.notes
    assert economics.computed_triggers(ue) == ["negative_contribution_margin"]
    sheet = scoring.score([], [], unit_economics=ue, computed_triggers=economics.computed_triggers(ue))
    assert sheet.kill_triggers_fired == ["negative_contribution_margin"]
    assert sheet.verdict == "NO_GO"
    assert sheet.unit_economics == ue


def test_zero_margin_is_no_trigger_but_no_break_even():
    ue = economics.compute(base_inputs(variable_cost=(Amount(25, (), "excl"),)))
    assert ue.contribution_margin_eur == 0
    assert ue.break_even_units_month is None
    assert economics.computed_triggers(ue) == []


def test_zero_fixed_costs_break_even_at_zero():
    ue = economics.compute(base_inputs(fixed_costs=(Amount(0, (), "excl"),)))
    assert ue.break_even_units_month == 0


def test_additive_costs_and_commission():
    ue = economics.compute(
        base_inputs(
            price=Amount(100, (), "excl"),
            variable_cost=(Amount(6, (), "excl"), Amount(4, (), "excl")),
            variable_cost_pct=(Amount(15, ()),),
            fixed_costs=(Amount(300, (), "excl"), Amount(150, (), "excl")),
        )
    )
    assert ue.variable_cost_eur == pytest.approx(25)  # 6 + 4 + 15 % of 100
    assert ue.fixed_costs_month_eur == 450
    table = {(r.price_change_pct, r.volume_change_pct): r.monthly_profit_eur for r in ue.sensitivity}
    # The commission scales with the price: at +30 % it is 19.5, not 15.
    assert table[(30.0, 0.0)] == pytest.approx((130 - 10 - 19.5) * 100 - 450)


def test_commission_alone_is_a_variable_cost():
    ue = economics.compute(base_inputs(variable_cost=(), variable_cost_pct=(Amount(20, ()),)))
    assert ue.variable_cost_eur == pytest.approx(5)
    assert "variable_cost" not in ue.missing_inputs


def test_missing_inputs_are_listed_not_guessed():
    ue = economics.compute(Inputs(price=Amount(25, ("pricing-001",), "excl")))
    assert ue.missing_inputs == ["variable_cost", "fixed_costs", "cac", "volume", "purchases_per_customer"]
    assert ue.price_eur == 25
    for name in ("variable_cost_eur", "contribution_margin_eur", "break_even_units_month", "payback_months",
                 "monthly_profit_eur", "fixed_costs_month_eur", "volume_month"):  # fmt: skip
        assert getattr(ue, name) is None, name
    assert ue.sensitivity == []


def test_empty_inputs():
    ue = economics.compute(Inputs())
    assert ue.missing_inputs == ["price", "variable_cost", "fixed_costs", "cac", "volume", "purchases_per_customer"]
    assert ue.input_claim_ids == []


def test_break_even_without_volume():
    ue = economics.compute(base_inputs(volume=None))
    assert ue.break_even_units_month == pytest.approx(20)
    assert ue.monthly_profit_eur is None
    assert ue.sensitivity == []
    assert ue.missing_inputs == ["volume"]


def test_subscription_price_implies_one_purchase_per_month():
    ue = economics.compute(base_inputs(purchases_per_customer=None, subscription=True))
    assert ue.purchases_per_customer_month == 1
    assert ue.payback_months == pytest.approx(1.5)  # 30 / 20
    assert "purchases_per_customer" not in ue.missing_inputs


# ---------------------------------------------------------------- VAT


def test_vat_registered_works_net_of_vat():
    rate = Amount(25.5, ("regulation-001",))
    ue = economics.compute(
        base_inputs(
            price=Amount(31.375, ("pricing-001",), "incl"),
            variable_cost=(Amount(6.275, (), "incl"),),
            vat_rate=rate,
        )
    )
    assert ue.price_eur == pytest.approx(25)
    assert ue.variable_cost_eur == pytest.approx(5)
    assert ue.contribution_margin_eur == pytest.approx(20)
    assert ue.vat_rate_pct == 25.5
    assert "regulation-001" in ue.input_claim_ids


def test_unregistered_keeps_the_price_and_pays_vat_on_costs():
    ue = economics.compute(
        base_inputs(
            price=Amount(31.375, (), "incl"),
            variable_cost=(Amount(5, (), "excl"),),
            fixed_costs=(Amount(400, (), "incl"),),
            vat_rate=Amount(25.5, ()),
        ),
        vat_registered=False,
    )
    assert ue.vat_registered is False
    assert ue.price_eur == pytest.approx(31.375)  # no VAT is charged, so the whole price is revenue
    assert ue.variable_cost_eur == pytest.approx(6.275)  # 5 + non-deductible 25.5 %
    assert ue.fixed_costs_month_eur == 400
    assert ue.contribution_margin_eur == pytest.approx(25.1)


def test_unregistered_price_needs_no_rate():
    ue = economics.compute(base_inputs(price=Amount(30, (), "excl"), variable_cost=(Amount(5, (), "incl"),),
                                       fixed_costs=(Amount(400, (), "incl"),), cac=Amount(30, (), "incl")),
                           vat_registered=False)  # fmt: skip
    assert ue.price_eur == 30
    assert "vat_rate" not in ue.missing_inputs


def test_conversion_without_a_rate_is_missing_not_guessed():
    ue = economics.compute(base_inputs(price=Amount(31.375, ("pricing-001",), "incl")))
    assert ue.price_eur is None
    assert ue.contribution_margin_eur is None
    assert ue.missing_inputs == ["vat_rate"]
    ue = economics.compute(base_inputs(fixed_costs=(Amount(400, (), "excl"), Amount(50, (), "incl"))))
    assert ue.fixed_costs_month_eur is None
    assert ue.break_even_units_month is None
    assert ue.missing_inputs == ["vat_rate"]
    ue = economics.compute(base_inputs(variable_cost=(Amount(5, (), "incl"),), variable_cost_pct=(Amount(10, ()),)))
    assert ue.variable_cost_eur is None
    assert ue.contribution_margin_eur is None
    assert ue.missing_inputs == ["vat_rate"]


def test_unstated_vat_basis_takes_the_pessimistic_reading():
    # Registered: an unstated price is read as gross (lower net), an unstated cost as net (kept).
    ue = economics.compute(base_inputs(price=Amount(31.375, ("pricing-001",)), variable_cost=(Amount(5, ("unit_economics-001",)),),
                                       vat_rate=Amount(25.5, ())))  # fmt: skip
    assert ue.price_eur == pytest.approx(25)
    assert ue.variable_cost_eur == 5
    assert "price: pricing-001 states no VAT basis; read as incl. VAT (the pessimistic reading)" in ue.notes
    assert "variable_cost: unit_economics-001 states no VAT basis; read as excl. VAT (the pessimistic reading)" in ue.notes
    # Not registered: an unstated cost is grossed up; the price is used as quoted.
    ue = economics.compute(base_inputs(price=Amount(25, ()), variable_cost=(Amount(5, ()),), vat_rate=Amount(25.5, ())),
                           vat_registered=False)  # fmt: skip
    assert ue.price_eur == 25
    assert ue.variable_cost_eur == pytest.approx(6.275)
    # Without a rate the unstated price cannot be read pessimistically: missing, not guessed.
    ue = economics.compute(base_inputs(price=Amount(25, ("pricing-001",))))
    assert ue.price_eur is None
    assert ue.missing_inputs == ["vat_rate"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("EUR excl. VAT", "excl"),
        ("EUR excluding VAT", "excl"),
        ("EUR + VAT", "excl"),
        ("EUR + alv", "excl"),
        ("EUR alv 0 %", "excl"),
        ("Hinta on 20 € (veroton).", "excl"),
        ("20 € ilman alv", "excl"),
        ("EUR incl. VAT", "incl"),
        ("EUR including VAT", "incl"),
        ("EUR sis. alv", "incl"),
        ("Hinta 25 € sis. alv 25,5 %", "incl"),
        ("verollinen hinta", "incl"),
        ("EUR", None),
        ("The price is 25 EUR.", None),
        ("25,10 € sis. alv (20 € + alv)", None),
    ],
)
def test_vat_basis(text, expected):
    assert economics.vat_basis(text) == expected


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("EUR/month", "month"),
        ("EUR/kk", "kk"),
        ("EUR per year", "year"),
        ("visitors/year", "year"),
        ("visits/customer/month", "month"),
        ("units/weeks", "week"),
        ("EUR/person", None),
        ("EUR/night", None),
        ("EUR per a night", None),
        ("EUR/a", "a"),
        ("nights/season", None),
        ("EUR/quarter", "quarter"),
        ("EUR", None),
    ],
)
def test_period(unit, expected):
    assert economics.period(unit) == expected


# ---------------------------------------------------------------- automatic claim mapping


def sauna_claims():
    return [
        claim("pricing-001", 25, "EUR", "A sauna evening price is 25 EUR incl. VAT."),
        claim("competition-001", 22, "EUR/person", "The competitor's price is 22 EUR per person incl. VAT."),
        claim("unit_economics-001", 3, "EUR", "Firewood per sauna evening costs 3 EUR excl. VAT."),
        claim("unit_economics-002", 4, "EUR", "Cleaning per evening costs 4 EUR excl. VAT."),
        claim("location-001", 4800, "EUR/year", "Site rent costs 4800 EUR per year excl. VAT."),
        claim("unit_economics-003", 600, "visitors/year", "A comparable rural sauna has 600 visitors per year."),
        claim("market-001", 50000, "visitors/year", "North Karelia has 50000 visitors per year."),
        claim("gtm-001", 12, "EUR", "Customer acquisition cost via ads is 12 EUR."),
        claim("regulation-001", 25.5, "%", "The general VAT rate is 25.5 %."),
        claim("regulation-002", 150, "EUR", "The permit fee costs 150 EUR."),
        claim("pricing-002", 15, "%", "The booking platform commission is 15 %."),
        claim("pricing-003", 10, "EUR", "A cheap price of 10 EUR.", verification="unverified"),
    ]


@pytest.mark.parametrize(
    ("index", "role"),
    [(0, "price"), (1, "price"), (2, "variable_cost"), (4, "fixed_costs"), (5, "volume"), (6, None),
     (7, "cac"), (8, "vat_rate"), (9, None), (10, "variable_cost_pct")],
)  # fmt: skip
def test_auto_role(index, role):
    assert economics.auto_role(sauna_claims()[index]) == role


@pytest.mark.parametrize(
    ("value", "unit", "statement"),
    [
        (None, "EUR", "The price is unknown."),
        (40, "%", "40 % of visitors are tourists."),
        (1900, "persons", "Rääkkylä has 1900 residents."),
        (12, "km", "The site is 12 km from the centre."),
    ],
)
def test_auto_role_ignores(value, unit, statement):
    assert economics.auto_role(claim("unit_economics-009", value, unit, statement)) is None


def test_auto_mapping_picks_the_pessimistic_verified_claim():
    inputs = economics.inputs_from_claims(sauna_claims())
    assert inputs.price == Amount(22, ("competition-001",), "incl")  # lowest; pricing-003 is unverified
    assert inputs.variable_cost == (Amount(4, ("unit_economics-002",), "excl"),)  # highest, not summed
    assert inputs.variable_cost_pct == (Amount(15, ("pricing-002",)),)
    assert inputs.fixed_costs == (Amount(400, ("location-001",), "excl"),)  # 4800 / 12
    assert inputs.volume == Amount(50, ("unit_economics-003",))  # 600 / 12; market-001 is market size
    assert inputs.cac == Amount(12, ("gtm-001",))
    assert inputs.vat_rate == Amount(25.5, ("regulation-001",))
    assert "price: chose competition-001 (the lowest value) over pricing-001" in inputs.notes
    assert "fixed_costs: location-001 converted from per year to per month" in inputs.notes


def test_unit_economics_end_to_end():
    ue = economics.unit_economics(sauna_claims())
    net_price = 22 / 1.255
    assert ue.price_eur == pytest.approx(net_price)
    assert ue.variable_cost_eur == pytest.approx(4 + 0.15 * net_price)
    assert ue.contribution_margin_eur == pytest.approx(net_price * 0.85 - 4)
    assert ue.break_even_units_month == pytest.approx(400 / (net_price * 0.85 - 4))
    assert ue.missing_inputs == ["purchases_per_customer"]
    assert ue.payback_months is None
    assert "cac: gtm-001 states no VAT basis; read as excl. VAT (the pessimistic reading)" in ue.notes
    assert "pricing-003" not in ue.input_claim_ids
    UnitEconomics.model_validate_json(ue.model_dump_json())


def test_auto_mapping_with_no_claims():
    ue = economics.unit_economics([])
    assert ue.missing_inputs[:3] == ["price", "variable_cost", "fixed_costs"]


# ---------------------------------------------------------------- assigned claim mapping


def test_assignments_sum_cost_items_and_use_only_named_claims():
    assignments = {
        "price": ["pricing-001"],
        "variable_cost": ["unit_economics-001", "unit_economics-002", "unit_economics-001"],
        "fixed_costs": ["location-001"],
        "volume": ["unit_economics-003"],
        "vat_rate": ["regulation-001"],
    }
    inputs = economics.inputs_from_claims(sauna_claims(), assignments)
    assert inputs.price == Amount(25, ("pricing-001",), "incl")
    assert [a.value for a in inputs.variable_cost] == [3, 4]
    assert inputs.variable_cost_pct == ()
    assert inputs.cac is None
    ue = economics.compute(inputs)
    assert ue.variable_cost_eur == 7
    assert ue.contribution_margin_eur == pytest.approx(25 / 1.255 - 7)
    assert ue.missing_inputs == ["cac", "purchases_per_customer"]


def test_assignments_drop_unverified_unknown_and_mistyped_claims():
    claims = [*sauna_claims(), claim("customer-001", None, None, "No value.")]
    inputs = economics.inputs_from_claims(
        claims,
        {"price": ["pricing-003"], "cac": ["gtm-999"], "vat_rate": ["pricing-001"], "volume": ["customer-001"]},
    )
    assert inputs.price is None and inputs.cac is None and inputs.vat_rate is None and inputs.volume is None
    assert "price: pricing-003 is unverified, not verified; dropped" in inputs.notes
    assert "cac: gtm-999 is unknown, not verified; dropped" in inputs.notes
    assert "vat_rate: pricing-001 has unit 'EUR', expected '%'; dropped" in inputs.notes
    assert "volume: customer-001 has no value; dropped" in inputs.notes


def test_assigned_subscription_and_frequency():
    claims = [
        claim("pricing-001", 120, "EUR/year", "The membership price is 120 EUR per year excl. VAT."),
        claim("customer-001", 3, "visits/customer/month", "Members visit 3 times a month."),
        claim("unit_economics-001", 200, "customers", "200 customers."),
    ]
    inputs = economics.inputs_from_claims(
        claims, {"price": ["pricing-001"], "purchases_per_customer": ["customer-001"], "volume": ["unit_economics-001"]}
    )
    assert inputs.subscription is True
    assert inputs.price == Amount(10, ("pricing-001",), "excl")
    assert inputs.purchases_per_customer == Amount(3, ("customer-001",))
    assert inputs.volume == Amount(200, ("unit_economics-001",))
    assert "volume: unit_economics-001 unit 'customers' names no period; used as per month" in inputs.notes
    assert economics.compute(inputs).purchases_per_customer_month == 1  # a subscription month is the unit


@pytest.mark.parametrize(
    ("assignments", "message"),
    [
        ({"revenue": ["pricing-001"]}, "unknown unit-economics role"),
        ({"price": ["pricing-001", "competition-001"]}, "takes one claim"),
    ],
)
def test_bad_assignments_raise(assignments, message):
    with pytest.raises(ValueError, match=message):
        economics.inputs_from_claims(sauna_claims(), assignments)


# ---------------------------------------------------------------- evaluator regressions


def test_auto_pick_compares_converted_values():
    claims = [
        claim("location-001", 4800, "EUR/year", "Rent costs 4800 EUR per year excl. VAT."),  # 400 / month
        claim("location-002", 500, "EUR/month", "Rent costs 500 EUR per month excl. VAT."),
        claim("unit_economics-001", 100, "visitors/week", "A peer has 100 visitors per week."),  # ≈ 433 / month
        claim("unit_economics-002", 300, "visitors/month", "A peer has 300 visitors per month."),
        claim("pricing-001", 21, "EUR", "The price is 21 EUR excl. VAT."),
        claim("pricing-002", 25, "EUR", "The price is 25 EUR incl. VAT."),  # 19.92 net
        claim("regulation-001", 25.5, "%", "The general VAT rate is 25.5 %."),
    ]
    inputs = economics.inputs_from_claims(claims)
    assert inputs.fixed_costs == (Amount(500, ("location-002",), "excl"),)
    assert inputs.volume == Amount(300, ("unit_economics-002",))
    assert inputs.price == Amount(25, ("pricing-002",), "incl")
    # Unregistered, the price is used as quoted, so 21 is the lower one.
    assert economics.inputs_from_claims(claims, vat_registered=False).price.claim_ids == ("pricing-001",)
    assert "unit_economics-001 converted from per week" not in " ".join(inputs.notes)


def test_auto_pick_prefers_lower_subscription_month():
    claims = [
        claim("pricing-001", 15, "EUR/month", "The membership price is 15 EUR per month excl. VAT."),
        claim("pricing-002", 120, "EUR/year", "The membership price is 120 EUR per year excl. VAT."),
    ]
    inputs = economics.inputs_from_claims(claims)
    assert inputs.price == Amount(10, ("pricing-002",), "excl")
    assert inputs.subscription is True


def test_week_and_day_conversions():
    claims = [
        claim("unit_economics-001", 12, "visitors/week", "12 visitors per week."),
        claim("unit_economics-002", 3, "EUR/day", "Electricity costs 3 EUR per day excl. VAT."),
    ]
    inputs = economics.inputs_from_claims(claims, {"volume": ["unit_economics-001"], "fixed_costs": ["unit_economics-002"]})
    assert inputs.volume.value == pytest.approx(52)
    assert inputs.fixed_costs[0].value == pytest.approx(91.25)


def test_a_dropped_cost_item_makes_the_role_missing():
    claims = [*sauna_claims(), claim("location-002", 50, "EUR/month", "Insurance costs 50 EUR.", verification="unverified")]
    ue = economics.unit_economics(claims, {"price": ["pricing-001"], "fixed_costs": ["location-001", "location-002"],
                                           "variable_cost": ["unit_economics-001"], "vat_rate": ["regulation-001"]})  # fmt: skip
    assert ue.fixed_costs_month_eur is None
    assert ue.break_even_units_month is None
    assert "fixed_costs" in ue.missing_inputs
    assert ue.contribution_margin_eur is not None
    ue = economics.unit_economics(sauna_claims(), {"price": ["pricing-001"], "variable_cost_pct": ["pricing-003"],
                                                   "variable_cost": ["unit_economics-001"]})  # fmt: skip
    assert ue.variable_cost_eur is None
    assert ue.missing_inputs[:2] == ["variable_cost_pct", "fixed_costs"]


def test_unknown_period_is_dropped_not_read_as_monthly():
    claims = [claim("unit_economics-001", 900, "nights/season", "A peer sells 900 nights per season."),
              claim("location-001", 2000, "EUR/season", "Seasonal rent costs 2000 EUR excl. VAT.")]  # fmt: skip
    inputs = economics.inputs_from_claims(claims, {"volume": ["unit_economics-001"], "fixed_costs": ["location-001"]})
    assert inputs.volume is None
    assert inputs.fixed_costs == ()
    assert "volume: unit_economics-001 unit 'nights/season' has no monthly conversion; dropped" in inputs.notes
    ue = economics.compute(inputs)
    assert {"volume", "fixed_costs"} <= set(ue.missing_inputs)
    site = [claim("unit_economics-002", 40, "visitors/site", "40 visitors per site.")]
    inputs = economics.inputs_from_claims(site, {"volume": ["unit_economics-002"]})
    assert inputs.volume is None
    assert "volume: unit_economics-002 unit 'visitors/site' has no monthly conversion; dropped" in inputs.notes


def test_subscription_ignores_an_assigned_frequency():
    claims = [
        claim("pricing-001", 20, "EUR/month", "The membership price is 20 EUR per month excl. VAT."),
        claim("customer-001", 3, "visits/customer/month", "Members visit 3 times a month."),
    ]
    ue = economics.unit_economics(claims, {"price": ["pricing-001"], "purchases_per_customer": ["customer-001"]})
    assert ue.purchases_per_customer_month == 1
    assert "customer-001" not in ue.input_claim_ids
    assert "purchases_per_customer: customer-001 ignored; a subscription month is the unit sold" in ue.notes


def test_unregistered_grosses_up_cac():
    ue = economics.compute(base_inputs(cac=Amount(40, (), "excl"), vat_rate=Amount(25.5, ())), vat_registered=False)
    assert ue.cac_eur == pytest.approx(50.2)


def test_negative_margin_sensitivity_and_payback():
    ue = economics.compute(base_inputs(variable_cost=(Amount(30, (), "excl"),)))
    table = {(r.price_change_pct, r.volume_change_pct): r.monthly_profit_eur for r in ue.sensitivity}
    assert table[(0.0, 0.0)] == pytest.approx(-5 * 100 - 400)
    assert table[(30.0, 30.0)] == pytest.approx((32.5 - 30) * 130 - 400)
    assert table[(-30.0, 30.0)] == pytest.approx((17.5 - 30) * 130 - 400)
    assert ue.payback_months is None
    assert "contribution margin is not positive: the acquisition cost is never paid back" in ue.notes


def test_seasonal_costs_are_never_per_unit():
    claims = [
        claim("pricing-001", 25, "EUR", "The price is 25 EUR excl. VAT."),
        claim("unit_economics-001", 3, "EUR", "Firewood per evening costs 3 EUR excl. VAT."),
        claim("unit_economics-002", 600, "EUR/season", "Insurance costs 600 EUR per season excl. VAT."),
        claim("unit_economics-003", 900, "nights/kausi", "A peer sells 900 nights per season."),
    ]
    assert economics.auto_role(claims[2]) is None
    assert economics.auto_role(claims[3]) is None
    ue = economics.unit_economics(claims)
    assert ue.variable_cost_eur == 3
    assert economics.computed_triggers(ue) == []
    assert "unit_economics-002: unit 'EUR/season' has no monthly conversion; not used" in ue.notes
    assert {"fixed_costs", "volume"} <= set(ue.missing_inputs)
    inputs = economics.inputs_from_claims(claims, {"variable_cost": ["unit_economics-001", "unit_economics-002"]})
    assert inputs.variable_cost == (Amount(3, ("unit_economics-001",), "excl"),)
    assert inputs.incomplete == {"variable_cost"}
    assert "variable_cost: unit_economics-002 unit 'EUR/season' has no monthly conversion; dropped" in inputs.notes


@pytest.mark.parametrize(
    "unit",
    ["EUR/kesäkausi", "EUR/talvikausi", "EUR/seasons", "EUR/sesonkiaika", "EUR/off-season", "EUR per summers",
     "EUR/kesällä", "nights/kaudet", "EUR/high season", "EUR per the season", "EUR/koko kesä"],
)  # fmt: skip
def test_seasonal_matches_compounds_plurals_and_inflections(unit):
    assert economics.seasonal(unit)


@pytest.mark.parametrize(
    "unit",
    ["EUR/month", "EUR/kuukausi", "EUR/kuukauden", "EUR/kk", "EUR/year", "EUR/night", "EUR", "EUR/vuorokausi",
     "EUR/vuorokaudelta", "EUR/kesäkuussa"],
)  # fmt: skip
def test_seasonal_ignores_periods_and_units(unit):
    assert not economics.seasonal(unit)


@pytest.mark.parametrize("unit", ["EUR/kesäkausi", "EUR/seasons", "EUR/high season", "EUR per the season"])
def test_compound_and_plural_seasonal_costs_set_no_trigger(unit):
    claims = [
        claim("pricing-001", 25, "EUR", "The price is 25 EUR excl. VAT."),
        claim("unit_economics-001", 5, "EUR", "Firewood per evening costs 5 EUR excl. VAT."),
        claim("unit_economics-002", 1200, unit, "Insurance costs 1200 EUR per summer season excl. VAT."),
    ]
    assert economics.auto_role(claims[2]) is None
    ue = economics.unit_economics(claims)
    assert ue.variable_cost_eur == 5
    assert "unit_economics-002" not in ue.input_claim_ids
    assert economics.computed_triggers(ue) == []
    assert f"unit_economics-002: unit {unit!r} has no monthly conversion; not used" in ue.notes
    for role in ("variable_cost", "fixed_costs"):
        ue = economics.unit_economics(claims, {"price": ["pricing-001"], role: ["unit_economics-002"]})
        assert role in ue.missing_inputs
        assert "unit_economics-002" not in ue.input_claim_ids
        assert economics.computed_triggers(ue) == []
        assert f"{role}: unit_economics-002 unit {unit!r} has no monthly conversion; dropped" in ue.notes
    ue = economics.unit_economics(claims, {"price": ["pricing-001"],
                                           "variable_cost": ["unit_economics-001", "unit_economics-002"]})  # fmt: skip
    assert ue.variable_cost_eur is None
    assert ue.contribution_margin_eur is None
    assert economics.computed_triggers(ue) == []


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("EUR", True), ("EUR/person", True), ("EUR/persons", True), ("EUR/hlö", True), ("EUR per night", True),
     ("EUR/h", False), ("EUR/event", False), ("EUR/2 weeks", False), ("EUR/month", False)],
)  # fmt: skip
def test_per_unit(unit, expected):
    assert economics.per_unit(unit) is expected


@pytest.mark.parametrize("unit", ["EUR/h", "EUR/event", "EUR/2 weeks"])
def test_auto_cost_with_unclear_unit_is_not_a_per_unit_cost(unit):
    claims = [
        claim("pricing-001", 25, "EUR", "The price is 25 EUR excl. VAT."),
        claim("unit_economics-001", 300, unit, "Staff costs 300 EUR excl. VAT."),
    ]
    assert economics.auto_role(claims[1]) is None
    ue = economics.unit_economics(claims)
    assert ue.variable_cost_eur is None
    assert "variable_cost" in ue.missing_inputs
    assert economics.computed_triggers(ue) == []
    assert f"unit_economics-001: unit {unit!r} is neither per unit sold nor per period; not used" in ue.notes


def test_counted_period_is_dropped_not_read_as_monthly():
    assert economics.period("EUR/2 weeks") is None
    claims = [claim("unit_economics-001", 300, "EUR/2 weeks", "Cleaning costs 300 EUR every two weeks excl. VAT.")]
    inputs = economics.inputs_from_claims(claims, {"fixed_costs": ["unit_economics-001"]})
    assert inputs.fixed_costs == ()
    assert inputs.incomplete == {"fixed_costs"}
    assert "fixed_costs: unit_economics-001 unit 'EUR/2 weeks' has no monthly conversion; dropped" in inputs.notes


def test_vuorokausi_is_a_day():
    assert economics.period("EUR/vuorokausi") == "vuorokausi"
    claims = [claim("unit_economics-001", 2, "EUR/vuorokausi", "Electricity costs 2 EUR per day excl. VAT.")]
    inputs = economics.inputs_from_claims(claims, {"fixed_costs": ["unit_economics-001"]})
    assert inputs.fixed_costs[0].value == pytest.approx(2 * 365 / 12)


def test_auto_cost_stated_per_season_is_not_used():
    claims = [
        claim("pricing-001", 25, "EUR", "The price is 25 EUR excl. VAT."),
        claim("unit_economics-001", 5, "EUR", "Cleaning costs 5 EUR per evening in summer excl. VAT."),
        claim("unit_economics-002", 1200, "EUR", "Insurance costs 1200 EUR per summer season excl. VAT."),
    ]
    assert economics.auto_role(claims[2]) is None
    ue = economics.unit_economics(claims)
    assert ue.variable_cost_eur == 5
    assert economics.computed_triggers(ue) == []
    assert "unit_economics-002: statement names a per-season amount; not used" in ue.notes


def test_per_unit_roles_need_a_unit_sold_not_only_a_period():
    claims = [
        claim("pricing-001", 25, "EUR", "The price is 25 EUR excl. VAT."),
        claim("unit_economics-001", 1200, "EUR/month", "Rent costs 1200 EUR per month excl. VAT."),
        claim("unit_economics-002", 2, "EUR/guest/month", "Supplies cost 2 EUR per guest per month excl. VAT."),
        claim("gtm-001", 500, "EUR/month", "The customer acquisition cost is 500 EUR per month."),
    ]
    ue = economics.unit_economics(claims, {"price": ["pricing-001"], "variable_cost": ["unit_economics-001"]})
    assert ue.variable_cost_eur is None
    assert economics.computed_triggers(ue) == []
    assert "variable_cost: unit_economics-001 unit 'EUR/month' is per month, not per unit sold; dropped" in ue.notes
    ue = economics.unit_economics(claims, {"price": ["pricing-001"], "variable_cost": ["unit_economics-002"]})
    assert ue.variable_cost_eur == 2
    ue = economics.unit_economics(claims)
    assert ue.cac_eur is None
    assert "cac: gtm-001 unit 'EUR/month' is per month, not per unit sold; dropped" in ue.notes
