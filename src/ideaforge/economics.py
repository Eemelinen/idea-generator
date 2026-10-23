"""Stage 5 unit economics: verified numeric claims → margin, break-even, payback and sensitivity.

Two steps, both deterministic:

- `inputs_from_claims` maps verified claims to the input roles (`ROLES`). Given `assignments`
  (role → claim ids, e.g. from the synthesizer) it uses exactly those; without, it picks one
  claim per role by unit and keywords and takes the most pessimistic candidate after period and
  VAT conversion. Values are converted to per month (fixed costs, volume, purchase frequency)
  from the unit's period; a period with no monthly conversion (`/season`) drops the claim.
- `compute` does the arithmetic. Every input that is absent, or an assigned cost role that lost
  a claim, is listed in `missing_inputs` and every output that needs it stays `None`.

VAT is explicit. A money claim states its basis in its unit or statement (`incl. VAT`,
`sis. alv`, `alv 0 %`, `+ VAT`, `veroton`, …). A VAT-registered business works net of VAT
(gross amounts are divided by 1 + rate). A business under the registration threshold charges no
VAT, so its price is used as quoted, and pays VAT it cannot deduct, so net costs are grossed up.
An amount with no stated basis is read the way that hurts the business (a price as incl. VAT, a
cost as excl. VAT) and noted. A conversion needs a verified VAT-rate claim, else `vat_rate` is
missing.

Rules chosen unattended are TICKETS.md plan note 21.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from ideaforge.schemas import Claim, SensitivityRow, UnitEconomics
from ideaforge.scoring import numeric_field

ROLES = (
    "price",
    "variable_cost",
    "variable_cost_pct",
    "fixed_costs",
    "cac",
    "volume",
    "purchases_per_customer",
    "vat_rate",
)
# Roles whose claims are summed (separate cost items); every other role takes one claim.
ADDITIVE_ROLES = ("variable_cost", "variable_cost_pct", "fixed_costs")
MONEY_ROLES = ("price", "variable_cost", "fixed_costs", "cac")
PERCENT_ROLES = ("variable_cost_pct", "vat_rate")
MONTHLY_ROLES = ("fixed_costs", "volume", "purchases_per_customer")
SENSITIVITY_STEPS = (-30.0, 0.0, 30.0)
NEGATIVE_MARGIN = "negative_contribution_margin"

VatBasis = Literal["incl", "excl"]

_MONTH = ("month", "mo", "kk", "kuukausi", "kuukaudessa", "kuussa")
_YEAR = ("year", "yr", "a", "annum", "vuosi", "v", "vuodessa")
# Months per unit of each period word, as written after `/` or `per` in a unit.
_PER_MONTH = {
    **dict.fromkeys(_MONTH, 1.0),
    **dict.fromkeys(_YEAR, 1 / 12),
    **dict.fromkeys(("quarter", "kvartaali", "neljännes"), 1 / 3),
    **dict.fromkeys(("week", "wk", "vko", "viikko", "viikossa"), 52 / 12),
    **dict.fromkeys(("day", "vrk", "päivä", "pv", "päivässä"), 365 / 12),
}
# A price per month or year is a subscription: one unit sold is one customer-month.
_SUBSCRIPTION_PERIODS = {*_MONTH, *_YEAR}
# Periods with no fixed length: a figure per season cannot be spread over months or units.
_SEASONS = {"season", "kausi", "kaudessa", "sesonki", "sesongissa", "summer", "winter", "kesä", "talvi"}
# `per a night` is per unit, not per annum.
_PER_RE = re.compile(r"(?:/|\bper\s+(?!an?\b))\s*([a-zäö]+)", re.IGNORECASE)
_EXCL_VAT_RE = re.compile(
    r"\b(excl(\.|uding|usive( of)?)?|ex\.?|without|net of|before)\s+vat\b|\bvat\s+excl|\+\s*(vat|alv)\b"
    r"|\b(alv|vat)\s*0\b(?![,.]\d)|\bverotons?|\bilman\s+alv",
    re.IGNORECASE,
)
_INCL_VAT_RE = re.compile(
    r"\b(incl(\.|uding|usive( of)?)?|with)\s+vat\b|\bvat\s+incl|\bsis(\.|ältäen|ältää)?\s*alv|\bverollinen",
    re.IGNORECASE,
)
_VAT_RATE_RE = re.compile(r"\bvat\b|\balv\b|arvonlisäv", re.IGNORECASE)
_CAC_RE = re.compile(
    r"\bcac\b|acquisition cost|cost of acquiring|cost[- ]per[- ](acquisition|lead|click|conversion)"
    r"|asiakashankin|hankintakustannu|asiakkaan hankin",
    re.IGNORECASE,
)
_COMMISSION_RE = re.compile(r"\bcommission|\bfees?\b|take rate|\bprovisio|\bpalkkio|\bmaksu", re.IGNORECASE)
# Without assignments, only these dimensions supply a role: market-size counts and one-off
# permit fees elsewhere are not the business's own volume or per-unit cost.
_AUTO_DIMENSIONS = {
    "variable_cost": {"unit_economics"},
    "variable_cost_pct": {"unit_economics", "pricing", "gtm"},
    "cac": {"unit_economics", "gtm"},
    "volume": {"unit_economics"},
}
# The pessimistic candidate per role when several claims qualify.
_PICK = {
    "price": min,
    "variable_cost": max,
    "variable_cost_pct": max,
    "fixed_costs": max,
    "cac": max,
    "volume": min,
    "purchases_per_customer": min,
    "vat_rate": max,
}


@dataclass(frozen=True)
class Amount:
    """One input value in its role's unit (EUR per unit, EUR or units per month, %)."""

    value: float
    claim_ids: tuple[str, ...] = ()
    vat: VatBasis | None = None


@dataclass
class Inputs:
    price: Amount | None = None
    variable_cost: tuple[Amount, ...] = ()
    variable_cost_pct: tuple[Amount, ...] = ()
    fixed_costs: tuple[Amount, ...] = ()
    cac: Amount | None = None
    volume: Amount | None = None
    purchases_per_customer: Amount | None = None
    vat_rate: Amount | None = None
    # The price is per customer-month (a subscription), so the purchase frequency is 1.
    subscription: bool = False
    # Additive roles that lost an assigned claim: their sum would understate the cost.
    incomplete: frozenset[str] = frozenset()
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Mapped:
    amount: Amount
    subscription: bool
    notes: tuple[str, ...]


# ---------------------------------------------------------------- units and VAT


def vat_basis(text: str) -> VatBasis | None:
    """`excl` or `incl` when the text states exactly one VAT basis, else None."""
    excl, incl = bool(_EXCL_VAT_RE.search(text)), bool(_INCL_VAT_RE.search(text))
    if excl == incl:
        return None
    return "excl" if excl else "incl"


def _per_words(unit: str) -> list[str]:
    """The words after `/` or `per` in a unit, plural `s` dropped from period words."""
    words = [w.lower() for w in _PER_RE.findall(unit)]
    return [w.removesuffix("s") if w not in _PER_MONTH and w.removesuffix("s") in _PER_MONTH else w for w in words]


def period(unit: str) -> str | None:
    """The last period word of a unit (`EUR/month` → `month`, `visits/customer/year` → `year`)."""
    found = [w for w in _per_words(unit) if w in _PER_MONTH]
    return found[-1] if found else None


def vat_treated(role: str, amount: Amount, *, vat_registered: bool, rate: float | None) -> tuple[float | None, str | None]:
    """The amount as the business books it (net if registered, else gross) and a note, or None without a rate.

    An unstated basis is read the way that hurts the business: a price as incl. VAT, a cost as
    excl. VAT. An unregistered business charges no VAT, so its price is used as quoted.
    """
    if not vat_registered and role == "price":
        return amount.value, None
    target = "excl" if vat_registered else "incl"
    basis, note = amount.vat, None
    if basis is None:
        basis = "incl" if role == "price" else "excl"
        ids = ", ".join(amount.claim_ids) or "input"
        note = f"{role}: {ids} states no VAT basis; read as {basis}. VAT (the pessimistic reading)"
    if basis == target:
        return amount.value, note
    if rate is None:
        return None, note
    factor = 1 + rate / 100
    return (amount.value / factor if vat_registered else amount.value * factor), note


# ---------------------------------------------------------------- claim mapping


def _percent(claim: Claim) -> bool:
    return (claim.unit or "").strip() == "%"


def seasonal(unit: str) -> bool:
    """Whether a unit is per season (`EUR/season`, `nights/kausi`): no monthly or per-unit reading."""
    return any(w in _SEASONS for w in _per_words(unit))


def auto_role(claim: Claim) -> str | None:
    """The role a verified claim fills without assignments, or None."""
    if claim.value is None or not claim.unit or seasonal(claim.unit):
        return None
    text = f"{claim.unit} {claim.statement}"
    role = None
    if _percent(claim):
        if _VAT_RATE_RE.search(claim.statement):
            return "vat_rate"
        if _COMMISSION_RE.search(claim.statement):
            role = "variable_cost_pct"
    else:
        kind = numeric_field(claim)
        if kind in ("price", "cost") and _CAC_RE.search(text):
            role = "cac"
        elif kind == "price":
            role = "price"
        elif kind == "cost":
            role = "fixed_costs" if period(claim.unit) else "variable_cost"
        elif kind == "unit_count" and period(claim.unit):
            role = "volume"
    if role is None or claim.dimension not in _AUTO_DIMENSIONS.get(role, {claim.dimension}):
        return None
    return role


def _map(role: str, claim: Claim) -> _Mapped | str:
    """A claim as an `Amount` of `role` with its notes, or the reason it is dropped."""
    cid = claim.claim_id
    if claim.value is None:
        return f"{role}: {cid} has no value; dropped"
    if (role in PERCENT_ROLES) != _percent(claim):
        expected = "'%'" if role in PERCENT_ROLES else "not '%'"
        return f"{role}: {cid} has unit {claim.unit!r}, expected {expected}; dropped"
    value, unit = claim.value, claim.unit or ""
    if seasonal(unit):
        return f"{role}: {cid} unit {unit!r} has no monthly conversion; dropped"
    per = period(unit)
    subscription, notes = False, []
    if role == "price" and per in _SUBSCRIPTION_PERIODS:
        value *= _PER_MONTH[per]
        subscription = True
        notes.append(f"price: {cid} is per {per}; one unit sold is one customer-month")
    elif role in MONTHLY_ROLES:
        if per is None and _per_words(unit):
            return f"{role}: {cid} unit {unit!r} has no monthly conversion; dropped"
        if per is None:
            notes.append(f"{role}: {cid} unit {unit!r} names no period; used as per month")
        elif _PER_MONTH[per] != 1.0:
            value *= _PER_MONTH[per]
            notes.append(f"{role}: {cid} converted from per {per} to per month")
    vat = vat_basis(f"{unit} {claim.statement}") if role in MONEY_ROLES else None
    return _Mapped(Amount(value, (cid,), vat), subscription, tuple(notes))


def _assigned(
    claims: Mapping[str, Claim], assignments: Mapping[str, Iterable[str]], notes: list[str]
) -> tuple[dict[str, list[_Mapped]], set[str]]:
    picked: dict[str, list[_Mapped]] = {}
    incomplete: set[str] = set()
    for role, ids in assignments.items():
        if role not in ROLES:
            raise ValueError(f"unknown unit-economics role {role!r}; expected one of {', '.join(ROLES)}")
        ids = list(dict.fromkeys(ids))
        if role not in ADDITIVE_ROLES and len(ids) > 1:
            raise ValueError(f"role {role!r} takes one claim, got {len(ids)}")
        for cid in ids:
            claim = claims.get(cid)
            if claim is None or claim.verification != "verified":
                mapped = f"{role}: {cid} is {'unknown' if claim is None else claim.verification}, not verified; dropped"
            else:
                mapped = _map(role, claim)
            if isinstance(mapped, str):
                notes.append(mapped)
                if role in ADDITIVE_ROLES:
                    incomplete.add(role)
            else:
                picked.setdefault(role, []).append(mapped)
    return picked, incomplete


def _automatic(claims: Iterable[Claim], notes: list[str], vat_registered: bool) -> dict[str, list[_Mapped]]:
    candidates: dict[str, list[_Mapped]] = {}
    for claim in claims:
        if claim.verification != "verified":
            continue
        if claim.value is not None and claim.unit and seasonal(claim.unit) and numeric_field(claim):
            notes.append(f"{claim.claim_id}: unit {claim.unit!r} has no monthly conversion; not used")
        if (role := auto_role(claim)) is not None:
            mapped = _map(role, claim)
            if isinstance(mapped, _Mapped):
                candidates.setdefault(role, []).append(mapped)
    rate = None
    if "vat_rate" in candidates:  # picked first: the other roles compare VAT-treated values
        rate = _PICK["vat_rate"](candidates["vat_rate"], key=lambda m: m.amount.value).amount.value
    picked = {}
    for role, found in candidates.items():
        def booked(m: _Mapped, role: str = role) -> float:
            value, _ = vat_treated(role, m.amount, vat_registered=vat_registered, rate=rate)
            return m.amount.value if value is None else value

        best = _PICK[role](found, key=booked if role in MONEY_ROLES else lambda m: m.amount.value)
        if len(found) > 1:
            extreme = "lowest" if _PICK[role] is min else "highest"
            others = ", ".join(m.amount.claim_ids[0] for m in found if m is not best)
            notes.append(f"{role}: chose {best.amount.claim_ids[0]} (the {extreme} value) over {others}")
        notes.extend(best.notes)
        picked[role] = [best]
    return picked


def inputs_from_claims(
    claims: Iterable[Claim],
    assignments: Mapping[str, Iterable[str]] | None = None,
    *,
    vat_registered: bool = True,
) -> Inputs:
    """Map verified claims to `Inputs`: the assigned claim ids per role, or one automatic pick per role.

    `vat_registered` only matters for the automatic pick, which compares VAT-treated values.
    """
    claims = list(claims)
    notes: list[str] = []
    incomplete: set[str] = set()
    if assignments is None:
        picked = _automatic(claims, notes, vat_registered)
    else:
        picked, incomplete = _assigned({c.claim_id: c for c in claims}, assignments, notes)
    inputs = Inputs(incomplete=frozenset(incomplete), notes=notes)
    for role, mapped in picked.items():
        if assignments is not None:
            notes.extend(n for m in mapped for n in m.notes)
        if role in ADDITIVE_ROLES:
            setattr(inputs, role, tuple(m.amount for m in mapped))
        else:
            [one] = mapped
            setattr(inputs, role, one.amount)
            inputs.subscription = inputs.subscription or (role == "price" and one.subscription)
    return inputs


# ---------------------------------------------------------------- arithmetic


def compute(inputs: Inputs, *, vat_registered: bool = True) -> UnitEconomics:
    """Contribution margin, break-even, payback and the ±30 % price × volume table from `inputs`.

    The commission (`variable_cost_pct`) is a share of the price as booked; VAT on the commission
    itself is not modelled.
    """
    notes = list(inputs.notes)
    rate = inputs.vat_rate.value if inputs.vat_rate else None
    needs_rate = False

    def treated(role: str, amount: Amount) -> float | None:
        nonlocal needs_rate
        value, note = vat_treated(role, amount, vat_registered=vat_registered, rate=rate)
        if note:
            notes.append(note)
        needs_rate = needs_rate or value is None
        return value

    def total(role: str) -> float | None:
        values = [treated(role, a) for a in getattr(inputs, role)]
        return None if not values or None in values or role in inputs.incomplete else sum(values)

    price = treated("price", inputs.price) if inputs.price else None
    unit_cost = total("variable_cost")
    cost_pct = sum(a.value for a in inputs.variable_cost_pct) if inputs.variable_cost_pct else None
    fixed = total("fixed_costs")
    cac = treated("cac", inputs.cac) if inputs.cac else None
    volume = inputs.volume.value if inputs.volume else None
    frequency = inputs.purchases_per_customer.value if inputs.purchases_per_customer else None
    used = [a for role in ROLES for a in _role_amounts(inputs, role)]
    if inputs.subscription:
        if inputs.purchases_per_customer:
            ids = ", ".join(inputs.purchases_per_customer.claim_ids) or "input"
            notes.append(f"purchases_per_customer: {ids} ignored; a subscription month is the unit sold")
            used.remove(inputs.purchases_per_customer)
        frequency = 1.0
    variable_missing = (not inputs.variable_cost and not inputs.variable_cost_pct) or bool(
        {"variable_cost", "variable_cost_pct"} & inputs.incomplete
    )

    def variable_cost(at_price: float) -> float | None:
        if variable_missing or (inputs.variable_cost and unit_cost is None):
            return None
        return (unit_cost or 0.0) + (cost_pct or 0.0) / 100 * at_price

    vc = variable_cost(price) if price is not None else None
    margin = price - vc if price is not None and vc is not None else None
    margin_pct = margin / price * 100 if margin is not None and price > 0 else None
    break_even = profit = payback = None
    if margin is not None and fixed is not None:
        if margin > 0:
            break_even = fixed / margin
        else:
            notes.append("contribution margin is not positive: no break-even volume")
    if margin is not None and fixed is not None and volume is not None:
        profit = margin * volume - fixed
    if margin is not None and cac is not None and frequency is not None:
        if margin * frequency > 0:
            payback = cac / (margin * frequency)
        else:
            notes.append("contribution margin is not positive: the acquisition cost is never paid back")
    sensitivity = []
    if price is not None and vc is not None and fixed is not None and volume is not None:
        for dp in SENSITIVITY_STEPS:
            p = price * (1 + dp / 100)
            for dv in SENSITIVITY_STEPS:
                monthly = (p - variable_cost(p)) * volume * (1 + dv / 100) - fixed
                sensitivity.append(SensitivityRow(price_change_pct=dp, volume_change_pct=dv, monthly_profit_eur=monthly))

    absent = {
        "price": inputs.price is None,
        "variable_cost": (not inputs.variable_cost and not inputs.variable_cost_pct)
        or "variable_cost" in inputs.incomplete,
        "variable_cost_pct": "variable_cost_pct" in inputs.incomplete,
        "fixed_costs": not inputs.fixed_costs or "fixed_costs" in inputs.incomplete,
        "cac": inputs.cac is None,
        "volume": inputs.volume is None,
        "purchases_per_customer": frequency is None,
        "vat_rate": needs_rate,
    }
    return UnitEconomics(
        price_eur=price,
        variable_cost_eur=vc,
        contribution_margin_eur=margin,
        contribution_margin_pct=margin_pct,
        fixed_costs_month_eur=fixed,
        cac_eur=cac,
        volume_month=volume,
        purchases_per_customer_month=frequency,
        monthly_profit_eur=profit,
        break_even_units_month=break_even,
        payback_months=payback,
        sensitivity=sensitivity,
        vat_registered=vat_registered,
        vat_rate_pct=rate,
        missing_inputs=[name for name, missing in absent.items() if missing],
        input_claim_ids=list(dict.fromkeys(cid for a in used for cid in a.claim_ids)),
        notes=list(dict.fromkeys(notes)),
    )


def _role_amounts(inputs: Inputs, role: str) -> list[Amount]:
    value = getattr(inputs, role)
    return list(value) if isinstance(value, tuple) else [value] if value is not None else []


def unit_economics(
    claims: Iterable[Claim],
    assignments: Mapping[str, Iterable[str]] | None = None,
    *,
    vat_registered: bool = True,
) -> UnitEconomics:
    """`compute(inputs_from_claims(claims, assignments))`: the stage 5 entry point."""
    inputs = inputs_from_claims(claims, assignments, vat_registered=vat_registered)
    return compute(inputs, vat_registered=vat_registered)


def computed_triggers(economics: UnitEconomics) -> list[str]:
    """Kill triggers the economics prove: a negative contribution margin (for `scoring.score`)."""
    margin = economics.contribution_margin_eur
    return [NEGATIVE_MARGIN] if margin is not None and margin < 0 else []
