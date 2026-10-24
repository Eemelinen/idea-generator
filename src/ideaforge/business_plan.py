"""The starttiraha business-plan draft (IF-307): a section of 05_report.md.

    context(spec, sheet, claims, risks, funding, language) → the data `business_plan.md.j2` renders

Two parts, in `config/report.yaml: business_plan_language` (en | fi):

- a liiketoimintasuunnitelma skeleton in the order of the usual TE-palvelut / Uusyrityskeskus
  template, prefilled from the spec and the verified claims of each section's dimensions, with
  `TÄYDENNÄ` (fill in) placeholders for what research cannot know;
- a kannattavuuslaskelma table from the score sheet's unit economics (`economics.py`).

Every figure traces to claim ids (`UnitEconomics.input_claims`, the claims each input role used)
or is marked as an assumption: the founder's own figures from the spec, and the per-year column,
which is 12 × the month. A missing input stays blank with the role to fill in, never guessed.
Like the rest of the report, nothing here decides anything and `config/finland.yaml` is never read.
Rules chosen unattended are TICKETS.md plan note 34.
"""

from __future__ import annotations

from typing import Any

from ideaforge.schemas import Claim, IdeaSpec, RiskItem, ScoreSheet, UnitEconomics

# Plan sections that research fills: key → the dimensions whose verified claims back it.
SECTIONS = (
    ("founder", ("founder_risk",)),
    ("product", ()),
    ("market", ("customer", "market")),
    ("competition", ("competition",)),
    ("pricing", ("pricing",)),
    ("marketing", ("gtm",)),
    ("location", ("location",)),
    ("regulation", ("regulation",)),
)
MAX_RISKS = 5

TEXT: dict[str, dict[str, Any]] = {
    "fi": {
        "title": "Liiketoimintasuunnitelma (luonnos starttirahahakemusta varten)",
        "intro": (
            "Luonnos on koottu tämän raportin tiedoista. Luvut ovat vahvistettuja väitteitä (tunnus "
            "`claim_id`) tai niistä laskettuja; perustajan omat luvut ja muut oletukset on merkitty "
            "**oletukseksi**. Täydennä kohdat, joissa lukee TÄYDENNÄ, ja tarkista luvut ennen hakemusta."
        ),
        "fill": "TÄYDENNÄ",
        "sections": {
            "summary": "1. Yhteenveto ja liikeidea",
            "founder": "2. Yrittäjä ja osaaminen",
            "product": "3. Tuote tai palvelu",
            "market": "4. Asiakkaat ja markkinat",
            "competition": "5. Kilpailutilanne",
            "pricing": "6. Hinnoittelu ja ansaintamalli",
            "marketing": "7. Markkinointi ja myynti",
            "location": "8. Sijainti ja toimintaympäristö",
            "regulation": "9. Luvat, vakuutukset ja verotus",
            "risks": "10. Riskit",
            "financing": "11. Rahoitussuunnitelma",
            "calculation": "12. Kannattavuuslaskelma",
            "todo": "13. Täydennettävät kohdat",
        },
        "idea": "Liikeidea",
        "customer": "Asiakas",
        "problem": "Asiakkaan ongelma",
        "solution": "Ratkaisu",
        "revenue_model": "Ansaintamalli",
        "geography": "Markkina-alue",
        "verdict": "Ideaforge-arvio",
        "weighted": "painotettu kokonaispistemäärä",
        "score": "Ideaforge-pisteet",
        "of5": "/ 5",
        "verified": "Vahvistetut väitteet",
        "no_claims": "ei vahvistettuja väitteitä; katso raportin puutteet (Gaps)",
        "skills": "Osaaminen (perustajan ilmoitus)",
        "hours": "Työaika yritykselle",
        "hours_unit": "h / viikko",
        "goal": "Tavoite (perustajan ilmoitus)",
        "summary_fill": "yrityksen nimi, yritysmuoto, aloituspäivä",
        "founder_fill": "koulutus, työkokemus, aiempi yrittäjyys, verkostot",
        "product_fill": "palvelun sisältö, toimitustapa, aloitusaikataulu",
        "market_fill": "kohderyhmän koko ja tavoitettavuus omin sanoin",
        "competition_fill": "tärkeimmät kilpailijat ja oma erottautuminen",
        "pricing_fill": "hinnaston perusteet, alennukset ja lisäpalvelut",
        "marketing_fill": "kanavat, budjetti ja ensimmäiset asiakkaat",
        "location_fill": "toimitilat ja niiden kustannukset",
        "regulation_fill": "yritysmuoto, vakuutukset, YEL-työtulo",
        "risks_none": "Riskirekisteri on tyhjä.",
        "risk_cols": ("Riski", "Todennäköisyys", "Vaikutus", "Varautuminen", "Väitteet"),
        "risks_more": "Loput riskit: raportin riskirekisteri.",
        "own_capital": "Oma pääoma",
        "funding": "Julkiset rahoitusmuodot (vain vahvistettu, virallisen lähteen väite kelpaa)",
        "unverified": "vahvistamaton – katso puutteet",
        "financing_fill": "investoinnit, lainat, starttirahan määrä ja kesto viralliselta sivulta",
        "assumption": "oletus",
        "founder_stated": "perustajan ilmoitus, 00_spec.json",
        "calc_cols": ("Erä", "€ tai kpl / kk", "/ vuosi (oletus: 12 × kk)", "Lähde"),
        "rows": {
            "price": "Myyntihinta, € / myyty yksikkö",
            "volume": "Myyntimäärä, kpl",
            "revenue": "Liikevaihto, €",
            "unit_cost": "Muuttuvat kulut, € / yksikkö",
            "variable_total": "Muuttuvat kulut yhteensä, €",
            "margin": "Myyntikate, €",
            "margin_pct": "Myyntikate, % liikevaihdosta",
            "fixed": "Kiinteät kulut, €",
            "profit": "Liiketulos ennen yrittäjän palkkaa, YEL-maksuja ja veroja, €",
            "break_even": "Kannattavuusraja, kpl",
            "break_even_revenue": "Kannattavuusraja, liikevaihto €",
            "cac": "Asiakashankintakustannus, € / asiakas",
            "frequency": "Ostokertoja / asiakas",
            "payback": "Asiakashankinnan takaisinmaksuaika, kk",
        },
        "amounts": "Rahamäärät",
        "unknown": "tuntematon",
        "vat_net": "alv 0 %",
        "vat_gross": "ei alv-velvollinen: hinnat ja kulut verollisina",
        "claims": "väitteet",
        "computed": "laskettu",
        "missing": "puuttuu",
        "missing_fill": "täydennä oma arvio ja merkitse se oletukseksi",
        "formulas": {
            "revenue": "hinta × määrä",
            "variable_total": "muuttuvat kulut / yksikkö × määrä",
            "margin": "liikevaihto − muuttuvat kulut",
            "margin_pct": "myyntikate ÷ liikevaihto",
            "profit": "myyntikate − kiinteät kulut",
            "break_even": "kiinteät kulut ÷ myyntikate / yksikkö",
            "break_even_revenue": "kannattavuusraja × hinta",
            "payback": "hankintakustannus ÷ (myyntikate / yksikkö × ostokerrat)",
            "subscription": "tilaus: yksi kuukausi on myyty yksikkö",
        },
        "assumptions": "Oletukset",
        "assume_year": "Vuosiluvut ovat 12 × kuukausiluku: kausivaihtelua ei ole mallinnettu.",
        "assume_vat": "Arvonlisäverovelvollisuus: {state} (perustajan valinta, 00_spec.json).",
        "vat_yes": "rekisteröity",
        "vat_no": "ei rekisteröity",
        "assume_salary": (
            "Yrittäjän oma palkka, YEL-maksut, verot ja lainojen lyhennykset eivät ole laskelmassa: TÄYDENNÄ."
        ),
        "not_computed": "ei laskettavissa: katso laskennan huomiot",
        "calc_notes": "Laskennan huomiot (economics.py, englanniksi)",
        "todo_missing": "Puuttuvat laskelman syötteet",
        "todo_none": "Laskelman syötteet ovat kaikki vahvistettuja; täydennä TÄYDENNÄ-kohdat yllä.",
        "roles": {
            "price": "myyntihinta",
            "variable_cost": "muuttuvat kulut / yksikkö",
            "variable_cost_pct": "provisiot ja maksut, % hinnasta",
            "fixed_costs": "kiinteät kulut / kk",
            "cac": "asiakashankintakustannus",
            "volume": "myyntimäärä / kk",
            "purchases_per_customer": "ostokerrat / asiakas / kk",
            "vat_rate": "alv-kanta",
        },
        "goals": {"side_income": "sivutulo", "full_time": "päätoiminen yrittäjyys", "starttiraha": "starttiraha"},
        "decimal": ",",
    },
    "en": {
        "title": "Business plan (draft for a starttiraha application)",
        "intro": (
            "This draft is compiled from this report. Figures are verified claims (`claim_id`) or "
            "computed from them; the founder's own figures and other assumptions are marked as an "
            "**assumption**. Fill in every FILL IN item and check the figures before applying."
        ),
        "fill": "FILL IN",
        "sections": {
            "summary": "1. Summary and business idea",
            "founder": "2. Founder and skills",
            "product": "3. Product or service",
            "market": "4. Customers and market",
            "competition": "5. Competition",
            "pricing": "6. Pricing and revenue model",
            "marketing": "7. Marketing and sales",
            "location": "8. Location and operating environment",
            "regulation": "9. Permits, insurance and taxation",
            "risks": "10. Risks",
            "financing": "11. Financing plan",
            "calculation": "12. Profitability calculation",
            "todo": "13. Items to complete",
        },
        "idea": "Business idea",
        "customer": "Customer",
        "problem": "Customer problem",
        "solution": "Solution",
        "revenue_model": "Revenue model",
        "geography": "Market area",
        "verdict": "Ideaforge verdict",
        "weighted": "weighted total",
        "score": "Ideaforge score",
        "of5": "of 5",
        "verified": "Verified claims",
        "no_claims": "no verified claims; see the report's gaps",
        "skills": "Skills (stated by the founder)",
        "hours": "Time for the business",
        "hours_unit": "h / week",
        "goal": "Goal (stated by the founder)",
        "summary_fill": "company name, legal form, start date",
        "founder_fill": "education, work experience, earlier entrepreneurship, networks",
        "product_fill": "what the service contains, how it is delivered, start schedule",
        "market_fill": "the size and reachability of the target group in your own words",
        "competition_fill": "the main competitors and how you differ",
        "pricing_fill": "how the prices are set, discounts and add-ons",
        "marketing_fill": "channels, budget and the first customers",
        "location_fill": "premises and their costs",
        "regulation_fill": "company form, insurance, YEL income",
        "risks_none": "The risk register is empty.",
        "risk_cols": ("Risk", "Likelihood", "Impact", "Mitigation", "Claims"),
        "risks_more": "The other risks: the report's risk register.",
        "own_capital": "Own capital",
        "funding": "Public funding (only a verified claim on an official source counts)",
        "unverified": "unverified – see gaps",
        "financing_fill": "investments, loans, the starttiraha amount and duration from the official page",
        "assumption": "assumption",
        "founder_stated": "stated by the founder, 00_spec.json",
        "calc_cols": ("Item", "EUR or units / month", "/ year (assumption: 12 × month)", "Source"),
        "rows": {
            "price": "Price, EUR / unit sold",
            "volume": "Units sold",
            "revenue": "Revenue, EUR",
            "unit_cost": "Variable costs, EUR / unit",
            "variable_total": "Variable costs in total, EUR",
            "margin": "Contribution margin, EUR",
            "margin_pct": "Contribution margin, % of revenue",
            "fixed": "Fixed costs, EUR",
            "profit": "Operating profit before the founder's salary, YEL and taxes, EUR",
            "break_even": "Break-even, units",
            "break_even_revenue": "Break-even, revenue EUR",
            "cac": "Customer acquisition cost, EUR / customer",
            "frequency": "Purchases / customer",
            "payback": "Acquisition payback, months",
        },
        "amounts": "Amounts",
        "unknown": "unknown",
        "vat_net": "excl. VAT",
        "vat_gross": "not VAT-registered: prices and costs incl. VAT",
        "claims": "claims",
        "computed": "computed",
        "missing": "missing",
        "missing_fill": "fill in your own estimate and mark it as an assumption",
        "formulas": {
            "revenue": "price × units",
            "variable_total": "variable cost / unit × units",
            "margin": "revenue − variable costs",
            "margin_pct": "contribution margin ÷ revenue",
            "profit": "contribution margin − fixed costs",
            "break_even": "fixed costs ÷ contribution margin / unit",
            "break_even_revenue": "break-even units × price",
            "payback": "acquisition cost ÷ (margin / unit × purchases)",
            "subscription": "subscription: one month is the unit sold",
        },
        "assumptions": "Assumptions",
        "assume_year": "Yearly figures are 12 × the month: seasonality is not modelled.",
        "assume_vat": "VAT: {state} (the founder's choice, 00_spec.json).",
        "vat_yes": "registered",
        "vat_no": "not registered",
        "assume_salary": "The founder's salary, YEL, taxes and loan repayments are not in the calculation: FILL IN.",
        "not_computed": "not computable: see the calculation notes",
        "calc_notes": "Calculation notes (economics.py)",
        "todo_missing": "Missing calculation inputs",
        "todo_none": "Every calculation input is verified; complete the FILL IN items above.",
        "roles": {
            "price": "price",
            "variable_cost": "variable cost / unit",
            "variable_cost_pct": "commissions and fees, % of price",
            "fixed_costs": "fixed costs / month",
            "cac": "customer acquisition cost",
            "volume": "units sold / month",
            "purchases_per_customer": "purchases / customer / month",
            "vat_rate": "VAT rate",
        },
        "goals": {"side_income": "side income", "full_time": "full-time business", "starttiraha": "starttiraha"},
        "decimal": ".",
    },
}


def number(x: float | None, digits: int, language: str) -> str:
    """A figure with a space as the thousands separator and the language's decimal mark."""
    if x is None:
        return "–"
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", TEXT[language]["decimal"])


def code(ids: list[str]) -> str:
    return ", ".join(f"`{cid}`" for cid in ids)


class Calculation:
    """The kannattavuuslaskelma rows: every figure with its claim ids, formula or missing role."""

    def __init__(self, ue: UnitEconomics, language: str) -> None:
        self.ue, self.t, self.language = ue, TEXT[language], language
        self.rows: list[dict[str, str]] = []

    def ids(self, *roles: str) -> list[str]:
        """The claim ids the roles used; a sheet from before `input_claims` falls back to every input id."""
        if not self.ue.input_claims:
            return list(self.ue.input_claim_ids)
        found = [cid for role in roles for cid in self.ue.input_claims.get(role, [])]
        return list(dict.fromkeys(found))

    def source(self, value: float | None, roles: tuple[str, ...], formula: str | None, missing: list[str]) -> str:
        t = self.t
        if value is None:
            names = [r for r in roles if r in missing]
            if not names:  # every input is there, but the figure has no value (a margin ≤ 0)
                return t["not_computed"]
            return f"{t['missing']} ({', '.join(f'`{r}`' for r in names)}): {t['missing_fill']}"
        ids = self.ids(*roles)
        if formula:
            return f"{t['computed']}: {formula}" + (f" ({t['claims']} {code(ids)})" if ids else "")
        return f"{t['claims']} {code(ids)}"

    def add(
        self, key: str, value: float | None, roles: tuple[str, ...], *, digits: int = 2,
        formula: str | None = None, yearly: bool = False,
    ) -> None:  # fmt: skip
        missing = self.ue.missing_inputs
        self.rows.append(
            {
                "label": self.t["rows"][key],
                "month": number(value, digits, self.language),
                "year": number(value * 12, digits, self.language) if yearly and value is not None else "",
                "source": self.source(value, roles, formula and self.t["formulas"][formula], missing),
            }
        )


def calculation(ue: UnitEconomics, language: str) -> list[dict[str, str]]:
    """The kannattavuuslaskelma, per month (and per year where it is a flow)."""
    calc = Calculation(ue, language)
    vat = ("vat_rate",)
    price, volume, vc = ue.price_eur, ue.volume_month, ue.variable_cost_eur
    price_roles, volume_roles = ("price", *vat), ("volume",)
    cost_roles = ("variable_cost", "variable_cost_pct", "price", *vat) if "variable_cost_pct" in ue.input_claims else (
        "variable_cost", "variable_cost_pct", *vat)  # fmt: skip
    margin_roles = tuple(dict.fromkeys((*price_roles, *cost_roles)))

    def times(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else a * b

    calc.add("price", price, price_roles)
    calc.add("volume", volume, volume_roles, digits=1, yearly=True)
    calc.add("revenue", times(price, volume), (*price_roles, *volume_roles), formula="revenue", yearly=True)
    calc.add("unit_cost", vc, cost_roles)
    calc.add("variable_total", times(vc, volume), (*cost_roles, *volume_roles), formula="variable_total", yearly=True)
    margin_roles_volume = (*margin_roles, *volume_roles)
    calc.add("margin", times(ue.contribution_margin_eur, volume), margin_roles_volume, formula="margin", yearly=True)
    calc.add("margin_pct", ue.contribution_margin_pct, margin_roles, digits=1, formula="margin_pct")
    calc.add("fixed", ue.fixed_costs_month_eur, ("fixed_costs", *vat), yearly=True)
    profit_roles = (*margin_roles_volume, "fixed_costs")
    calc.add("profit", ue.monthly_profit_eur, profit_roles, formula="profit", yearly=True)
    be_roles = (*margin_roles, "fixed_costs")
    calc.add("break_even", ue.break_even_units_month, be_roles, digits=1, formula="break_even")
    calc.add("break_even_revenue", times(ue.break_even_units_month, price), be_roles, formula="break_even_revenue")
    calc.add("cac", ue.cac_eur, ("cac", *vat))
    subscription = ue.purchases_per_customer_month is not None and "purchases_per_customer" not in ue.input_claims
    if subscription and ue.input_claims:
        calc.add("frequency", ue.purchases_per_customer_month, ("price",), formula="subscription")
    else:
        calc.add("frequency", ue.purchases_per_customer_month, ("purchases_per_customer",))
    pay_roles = (*margin_roles, "cac", "purchases_per_customer")
    calc.add("payback", ue.payback_months, pay_roles, digits=1, formula="payback")
    return calc.rows


def section_claims(claims: list[Claim], dimensions: tuple[str, ...]) -> list[Claim]:
    return [c for c in claims if c.dimension in dimensions and c.verification == "verified"]


def context(
    spec: IdeaSpec,
    sheet: ScoreSheet,
    claims: list[Claim],
    risks: list[RiskItem],
    funding: list[dict[str, Any]],
    language: str,
) -> dict[str, Any]:
    """What `business_plan.md.j2` renders; `funding` is `report.funding_fit`'s output."""
    t = TEXT[language]
    ue = sheet.unit_economics
    scores = {s.dimension: s for s in sheet.scores}
    fc = spec.founder_constraints
    known = {c.claim_id for c in claims}
    return {
        "t": t,
        "language": language,
        "sections": {
            key: {
                "claims": section_claims(claims, dims),
                "scores": [
                    (d, number(scores[d].final_score, 0 if scores[d].final_score % 1 == 0 else 1, language))
                    for d in dims
                    if d in scores and scores[d].final_score is not None
                ],
            }
            for key, dims in SECTIONS
        },
        "weighted_total": number(sheet.weighted_total, 2, language),
        "skills": ", ".join(fc.skills) or t["fill"],
        "hours": number(fc.hours_per_week, 0 if fc.hours_per_week % 1 == 0 else 1, language),
        "goal": t["goals"].get(fc.goal, fc.goal),
        "capital": number(fc.capital_eur, 0, language),
        "risks": [
            (r, ", ".join(cid if cid in known else f"{cid} ({t['unknown']})" for cid in r.claim_ids))
            for r in sorted(risks, key=lambda r: -r.likelihood * r.impact)[:MAX_RISKS]
        ],
        "more_risks": len(risks) > MAX_RISKS,
        "funding": funding,
        "vat_basis": t["vat_net"] if (spec.vat_registered if ue.vat_registered is None else ue.vat_registered) else t["vat_gross"],
        "vat_state": t["vat_yes"] if spec.vat_registered else t["vat_no"],
        "rows": calculation(ue, language),
        "missing": [(role, t["roles"].get(role, role)) for role in ue.missing_inputs],
        "notes": ue.notes,
    }
