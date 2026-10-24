# Sauna-and-lake cabins for remote workers: Ideaforge report

- Run: `20261023-130000-sauna-cabins` (idea `sauna-cabins-remote-work`, version 1)
- Generated: 2026-10-23T14:00:00+00:00
- Idea: Week-long cabin rentals with sauna, fibre and a desk on Lake Orivesi for remote workers.
- Customer: Remote-working professionals in Helsinki and abroad who want a quiet working retreat.
- Revenue model: Weekly rental fee; optional add-ons (meals, guided nature trips).
- Geography: Rääkkylä → North Karelia → Finland → online
- Founder: 20 h/week, 15 000 EUR capital, goal `side_income`; VAT registered

This report is immutable. Scores, caps, kill triggers, the verdict and the unit economics are computed in Python (`config/rubric.yaml`, `score_run.py`); the synthesizer only proposed. Only verified claims count.

## Verdict: GO

No kill trigger fired and the weighted total is 3.80 of 5 (GO ≥ 3.5, PIVOT ≥ 2.5). That reaches GO. Capped at 2 for missing evidence: founder_risk. Strongest dimension: customer (4); weakest: founder_risk (0). Contribution margin: 11.92 EUR per unit sold.

## Score table

| Dimension | Weight | Proposed | Final | Status |
| --- | ---: | ---: | ---: | --- |
| `customer` | 0.15 | 4 | 4 | scored |
| `market` | 0.10 | 4 | 4 | scored |
| `competition` | 0.15 | 4 | 4 | scored |
| `pricing` | 0.10 | 4 | 4 | scored |
| `unit_economics` | 0.15 | 4 | 4 | scored |
| `gtm` | 0.10 | 4 | 4 | scored |
| `regulation` | 0.10 | 4 | 4 | scored |
| `financing` | 0.05 | 4 | 4 | scored |
| `location` | 0.05 | 4 | 4 | scored |
| `founder_risk` | 0.05 | 0 | 0 | **capped at 2**: insufficient data (min_sources: 0 of 2 independent source domains) |
| **Weighted total** | | | **3.80** | 1 dimension(s) with insufficient data |

## Kill triggers

| Trigger | State | Verified evidence | Flagged, not counted |
| --- | --- | --- | --- |
| `free_good_enough_substitute` | not fired |  |  |
| `permit_impossible` | not fired |  | killcause-002 (unverified) |
| `negative_contribution_margin` | not fired |  |  |
| `beachhead_below_founder_income` | not fired |  |  |
| `no_evidence_anyone_pays` | not fired |  |  |

No kill trigger is overridden in the spec.

## Unit economics

| Item | Value |
| --- | ---: |
| Price per unit sold (EUR) | 19.92 |
| Variable cost per unit sold (EUR) | 8.00 |
| Contribution margin per unit (EUR) | 11.92 (59.8 %) |
| Fixed costs per month (EUR) | 400.00 |
| Customer acquisition cost (EUR) | – |
| Units sold per month | 60.0 |
| Purchases per customer per month | – |
| Monthly profit (EUR) | 315.22 |
| Break-even units per month | 33.6 |
| Payback (months) | – |
| VAT | registered, rate 25.5 % |

- Input claims: pricing-001, unit_economics-004, unit_economics-002, unit_economics-005, regulation-004
- Missing inputs: cac, purchases_per_customer
- Note: price: pricing-001 states no VAT basis; read as incl. VAT (the pessimistic reading)
- Note: fixed_costs: unit_economics-002 states no VAT basis; read as excl. VAT (the pessimistic reading)

### Sensitivity (monthly profit, EUR)

| Price change ↓, volume change → | -30 % | 0 % | +30 % |
| --- | ---: | ---: | ---: |
| -30 % | -150.34 | -43.35 | 63.65 |
| 0 % | 100.65 | 315.22 | 529.78 |
| +30 % | 351.65 | 673.78 | 995.92 |

## Dimensions

### Customer & problem (JTBD) (`customer`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing customer-001, customer-002, customer-003, customer-004, customer-999.

Cited verified claims:

- `customer-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/customer>)
- `customer-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/customer>)
- `customer-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/customer>)

Not counted (not verified): `customer-004` (unverified)

Gaps:
- No research file for this dimension.

### Market size (bottom-up beachhead) (`market`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing market-001, market-002, market-003, market-004.

Cited verified claims:

- `market-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/market>)
- `market-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/market>)
- `market-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/market>)

Not counted (not verified): `market-004` (conflict)

Gaps:
- No research file for this dimension.

### Competition & substitutes (`competition`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing competition-001, competition-002, competition-003.

Cited verified claims:

- `competition-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/competition>)
- `competition-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/competition>)
- `competition-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/competition>)

Not counted (not verified): `competition-004` (pending)

Gaps:
- No research file for this dimension.

### Pricing & willingness to pay (`pricing`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing pricing-001, pricing-002, pricing-003.

Cited verified claims:

- `pricing-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/pricing>)
- `pricing-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/pricing>)
- `pricing-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/pricing>)

Gaps:
- No research file for this dimension.

### Unit economics & costs (`unit_economics`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing unit_economics-001, unit_economics-002, unit_economics-003.

Cited verified claims:

- `unit_economics-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/unit-economics>)
- `unit_economics-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/unit-economics>)
- `unit_economics-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/unit-economics>)

Other verified claims (not cited by the score): unit_economics-004, unit_economics-005

Gaps:
- No research file for this dimension.

### Go-to-market & channels (`gtm`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing gtm-001, gtm-002, gtm-003.

Cited verified claims:

- `gtm-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/gtm>)
- `gtm-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/gtm>)
- `gtm-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/gtm>)

Not counted (not verified): `gtm-004` (conflict)

Gaps:
- No research file for this dimension.

### Regulation, permits, tax (`regulation`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing regulation-001, regulation-002, regulation-003.

Cited verified claims:

- `regulation-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/regulation>)
- `regulation-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/regulation>)
- `regulation-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/regulation>)

Other verified claims (not cited by the score): regulation-004

Gaps:
- No research file for this dimension.

### Financing & funding fit (`financing`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing financing-001, financing-002, financing-003.

Cited verified claims:

- `financing-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/financing>)
- `financing-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/financing>)
- `financing-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/financing>)

Other verified claims (not cited by the score): financing-004, financing-006

Not counted (not verified): `financing-005` (unverified)

Gaps:
- No official page found on Leader (Jetina) funding for this kind of business.
- Elinvoimakeskus grant conditions for side businesses not found.

### Location fit (Rääkkylä / North Karelia) (`location`)

Score: 4 of 5 (proposed 4).

Findings (synthesizer's justification): Synthetic justification citing location-001, location-002, location-003.

Cited verified claims:

- `location-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/location>)
- `location-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/location>)
- `location-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/location>)

Other verified claims (not cited by the score): location-004

Gaps:
- No data on broadband coverage by village in Rääkkylä.

### Founder fit & risk register (`founder_risk`)

Score: 0 of 5 (proposed 0), **capped at 2**: insufficient data (min_sources: 0 of 2 independent source domains).

Findings (synthesizer's justification): no verified evidence (proposed 2; dropped citations: founder_risk-404). Synthetic: cites only an unknown id (founder_risk-404).

Cited verified claims: none.

Other verified claims (not cited by the score): founder_risk-001, founder_risk-002, founder_risk-003

Gaps:
- No research file for this dimension.

### Kill causes (not scored) (`killcause`)

Not scored: kill-cause research feeds the kill triggers above.

Other verified claims (not cited by the score): killcause-001

Not counted (not verified): `killcause-002` (unverified)

Gaps:
- No research file for this dimension.

## Finland funding fit

Each item counts only when a verified financing claim on an allow-listed official domain (`config/domains.yaml`) backs it. Eligibility, amounts and conditions change: check the cited page before applying.

### Starttiraha (start-up grant)

- `financing-004`: Starttiraha can be granted to a person who starts full-time business activity.

  > synthetic starttiraha quote

  Source: [Synthetic starttiraha page](<https://tyomarkkinatori.fi/synthetic/starttiraha>), retrieved 2026-10-23T10:31:00+00:00

### Leader (Jetina)

- **unverified – see gaps**: no verified financing claim on an official domain covers this.
- Not counted: `financing-006` (not on an allow-listed official domain): A blog says the Leader group funds | rural projects.

### Elinvoimakeskus business development grants

- **unverified – see gaps**: no verified financing claim on an official domain covers this.

### Finnvera loans and guarantees

- **unverified – see gaps**: no verified financing claim on an official domain covers this.
- Not counted: `financing-005` (unverified): Finnvera offers small loans to new entrepreneurs.

### Funding gaps (financing research)

- No official page found on Leader (Jetina) funding for this kind of business.
- Elinvoimakeskus grant conditions for side businesses not found.

## Rääkkylä location notes

Location score: 4 of 5.

- `location-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/location>)
- `location-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/location>)
- `location-003`: 1900 residents live in the area (1900 persons). Source: [Synthetic source](<https://example.org/synthetic/location>)
- `location-004`: Rääkkylä has a synthetic number of summer residents (3000 persons). Source: [Synthetic Rääkkylä page](<https://www.raakkyla.fi/synthetic/residents>)
- Not counted (not verified): `gtm-004` (conflict)

Location gaps:
- No data on broadband coverage by village in Rääkkylä.

## Risk register

| # | Risk | Dimension | Likelihood | Impact | L×I | Mitigation | Claims |
| ---: | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | Synthetic: a similar business closed nearby. | `killcause` | 3 | 4 | 12 | Synthetic mitigation. | killcause-001 |
| 2 | Synthetic: cites an id that does not exist. | `market` | 2 | 2 | 4 | Synthetic mitigation. | market-404 (unknown) |

## Starttiraha business-plan draft

### Liiketoimintasuunnitelma (luonnos starttirahahakemusta varten)

Luonnos on koottu tämän raportin tiedoista. Luvut ovat vahvistettuja väitteitä (tunnus `claim_id`) tai niistä laskettuja; perustajan omat luvut ja muut oletukset on merkitty **oletukseksi**. Täydennä kohdat, joissa lukee TÄYDENNÄ, ja tarkista luvut ennen hakemusta.

#### 1. Yhteenveto ja liikeidea

- Liikeidea: Sauna-and-lake cabins for remote workers: Week-long cabin rentals with sauna, fibre and a desk on Lake Orivesi for remote workers.
- Asiakas: Remote-working professionals in Helsinki and abroad who want a quiet working retreat.
- Markkina-alue: Rääkkylä → North Karelia → Finland → online
- Ideaforge-arvio: GO (painotettu kokonaispistemäärä 3,80 / 5)
- **TÄYDENNÄ**: yrityksen nimi, yritysmuoto, aloituspäivä

#### 2. Yrittäjä ja osaaminen

- Osaaminen (perustajan ilmoitus): carpentry, hospitality
- Työaika yritykselle: 20 h / viikko (**oletus**: perustajan ilmoitus, 00_spec.json)
- Tavoite (perustajan ilmoitus): sivutulo
- Ideaforge-pisteet (`founder_risk`): 0 / 5
- Vahvistetut väitteet:
  - `founder_risk-001`: The price of one sauna evening is 25 EUR (25 EUR).
  - `founder_risk-002`: Rent costs 400 EUR per month (400 EUR/month).
  - `founder_risk-003`: 1900 residents live in the area (1900 persons).
- **TÄYDENNÄ**: koulutus, työkokemus, aiempi yrittäjyys, verkostot

#### 3. Tuote tai palvelu

- Asiakkaan ongelma: Holiday cottages rarely have reliable internet, a proper desk or availability outside summer.
- Ratkaisu: Two renovated lakeside cabins with fibre, ergonomic desks, wood-fired sauna and weekly rates.
- **TÄYDENNÄ**: palvelun sisältö, toimitustapa, aloitusaikataulu

#### 4. Asiakkaat ja markkinat

- Asiakas: Remote-working professionals in Helsinki and abroad who want a quiet working retreat.
- Ideaforge-pisteet (`customer`): 4 / 5
- Ideaforge-pisteet (`market`): 4 / 5
- Vahvistetut väitteet:
  - `customer-001`: The price of one sauna evening is 25 EUR (25 EUR).
  - `customer-002`: Rent costs 400 EUR per month (400 EUR/month).
  - `customer-003`: 1900 residents live in the area (1900 persons).
  - `market-001`: The price of one sauna evening is 25 EUR (25 EUR).
  - `market-002`: Rent costs 400 EUR per month (400 EUR/month).
  - `market-003`: 1900 residents live in the area (1900 persons).
- **TÄYDENNÄ**: kohderyhmän koko ja tavoitettavuus omin sanoin

#### 5. Kilpailutilanne

- Ideaforge-pisteet (`competition`): 4 / 5
- Vahvistetut väitteet:
  - `competition-001`: The price of one sauna evening is 25 EUR (25 EUR).
  - `competition-002`: Rent costs 400 EUR per month (400 EUR/month).
  - `competition-003`: 1900 residents live in the area (1900 persons).
- **TÄYDENNÄ**: tärkeimmät kilpailijat ja oma erottautuminen

#### 6. Hinnoittelu ja ansaintamalli

- Ansaintamalli: Weekly rental fee; optional add-ons (meals, guided nature trips).
- Ideaforge-pisteet (`pricing`): 4 / 5
- Vahvistetut väitteet:
  - `pricing-001`: The price of one sauna evening is 25 EUR (25 EUR).
  - `pricing-002`: Rent costs 400 EUR per month (400 EUR/month).
  - `pricing-003`: 1900 residents live in the area (1900 persons).
- **TÄYDENNÄ**: hinnaston perusteet, alennukset ja lisäpalvelut

#### 7. Markkinointi ja myynti

- Ideaforge-pisteet (`gtm`): 4 / 5
- Vahvistetut väitteet:
  - `gtm-001`: The price of one sauna evening is 25 EUR (25 EUR).
  - `gtm-002`: Rent costs 400 EUR per month (400 EUR/month).
  - `gtm-003`: 1900 residents live in the area (1900 persons).
- **TÄYDENNÄ**: kanavat, budjetti ja ensimmäiset asiakkaat

#### 8. Sijainti ja toimintaympäristö

- Markkina-alue: Rääkkylä → North Karelia → Finland → online
- Ideaforge-pisteet (`location`): 4 / 5
- Vahvistetut väitteet:
  - `location-001`: The price of one sauna evening is 25 EUR (25 EUR).
  - `location-002`: Rent costs 400 EUR per month (400 EUR/month).
  - `location-003`: 1900 residents live in the area (1900 persons).
  - `location-004`: Rääkkylä has a synthetic number of summer residents (3000 persons).
- **TÄYDENNÄ**: toimitilat ja niiden kustannukset

#### 9. Luvat, vakuutukset ja verotus

- Ideaforge-pisteet (`regulation`): 4 / 5
- Vahvistetut väitteet:
  - `regulation-001`: The price of one sauna evening is 25 EUR (25 EUR).
  - `regulation-002`: Rent costs 400 EUR per month (400 EUR/month).
  - `regulation-003`: 1900 residents live in the area (1900 persons).
  - `regulation-004`: The general VAT rate is 25.5 % (25.5 %).
- **TÄYDENNÄ**: yritysmuoto, vakuutukset, YEL-työtulo

#### 10. Riskit

| Riski | Todennäköisyys | Vaikutus | Varautuminen | Väitteet |
| --- | ---: | ---: | --- | --- |
| Synthetic: a similar business closed nearby. | 3 | 4 | Synthetic mitigation. | killcause-001 |
| Synthetic: cites an id that does not exist. | 2 | 2 | Synthetic mitigation. | market-404 (tuntematon) |

#### 11. Rahoitussuunnitelma

- Oma pääoma: 15 000 € (**oletus**: perustajan ilmoitus, 00_spec.json)
- Julkiset rahoitusmuodot (vain vahvistettu, virallisen lähteen väite kelpaa):
  - Starttiraha (start-up grant): `financing-004`
  - Leader (Jetina): **vahvistamaton – katso puutteet**
  - Elinvoimakeskus business development grants: **vahvistamaton – katso puutteet**
  - Finnvera loans and guarantees: **vahvistamaton – katso puutteet**
- **TÄYDENNÄ**: investoinnit, lainat, starttirahan määrä ja kesto viralliselta sivulta

#### 12. Kannattavuuslaskelma

Rahamäärät: alv 0 %.

| Erä | € tai kpl / kk | / vuosi (oletus: 12 × kk) | Lähde |
| --- | ---: | ---: | --- |
| Myyntihinta, € / myyty yksikkö | 19,92 |  | väitteet `pricing-001`, `regulation-004` |
| Myyntimäärä, kpl | 60,0 | 720,0 | väitteet `unit_economics-005` |
| Liikevaihto, € | 1 195,22 | 14 342,63 | laskettu: hinta × määrä (väitteet `pricing-001`, `regulation-004`, `unit_economics-005`) |
| Muuttuvat kulut, € / yksikkö | 8,00 |  | väitteet `unit_economics-004`, `regulation-004` |
| Muuttuvat kulut yhteensä, € | 480,00 | 5 760,00 | laskettu: muuttuvat kulut / yksikkö × määrä (väitteet `unit_economics-004`, `regulation-004`, `unit_economics-005`) |
| Myyntikate, € | 715,22 | 8 582,63 | laskettu: liikevaihto − muuttuvat kulut (väitteet `pricing-001`, `regulation-004`, `unit_economics-004`, `unit_economics-005`) |
| Myyntikate, % liikevaihdosta | 59,8 |  | laskettu: myyntikate ÷ liikevaihto (väitteet `pricing-001`, `regulation-004`, `unit_economics-004`) |
| Kiinteät kulut, € | 400,00 | 4 800,00 | väitteet `unit_economics-002`, `regulation-004` |
| Liiketulos ennen yrittäjän palkkaa, YEL-maksuja ja veroja, € | 315,22 | 3 782,63 | laskettu: myyntikate − kiinteät kulut (väitteet `pricing-001`, `regulation-004`, `unit_economics-004`, `unit_economics-005`, `unit_economics-002`) |
| Kannattavuusraja, kpl | 33,6 |  | laskettu: kiinteät kulut ÷ myyntikate / yksikkö (väitteet `pricing-001`, `regulation-004`, `unit_economics-004`, `unit_economics-002`) |
| Kannattavuusraja, liikevaihto € | 668,45 |  | laskettu: kannattavuusraja × hinta (väitteet `pricing-001`, `regulation-004`, `unit_economics-004`, `unit_economics-002`) |
| Asiakashankintakustannus, € / asiakas | – |  | puuttuu (`cac`): täydennä oma arvio ja merkitse se oletukseksi |
| Ostokertoja / asiakas | – |  | puuttuu (`purchases_per_customer`): täydennä oma arvio ja merkitse se oletukseksi |
| Asiakashankinnan takaisinmaksuaika, kk | – |  | puuttuu (`cac`, `purchases_per_customer`): täydennä oma arvio ja merkitse se oletukseksi |

Oletukset:

- **oletus**: Vuosiluvut ovat 12 × kuukausiluku: kausivaihtelua ei ole mallinnettu.
- **oletus**: Arvonlisäverovelvollisuus: rekisteröity (perustajan valinta, 00_spec.json).
- Yrittäjän oma palkka, YEL-maksut, verot ja lainojen lyhennykset eivät ole laskelmassa: TÄYDENNÄ.

Laskennan huomiot (economics.py, englanniksi):

- price: pricing-001 states no VAT basis; read as incl. VAT (the pessimistic reading)
- fixed_costs: unit_economics-002 states no VAT basis; read as excl. VAT (the pessimistic reading)

#### 13. Täydennettävät kohdat

Puuttuvat laskelman syötteet:

- `cac` (asiakashankintakustannus): täydennä oma arvio ja merkitse se oletukseksi
- `purchases_per_customer` (ostokerrat / asiakas / kk): täydennä oma arvio ja merkitse se oletukseksi

## Sources

| Source | Retrieved | Verification | Official | Claims |
| --- | --- | --- | --- | --- |
| [Synthetic source](<https://example.net/synthetic/conflict>) | 2026-10-23T10:30:00+00:00 | conflict ×1 |  | market-004 |
| [Synthetic source](<https://example.net/synthetic/killcause>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | killcause-001 |
| [Synthetic source](<https://example.net/synthetic/killcause-unverified>) | 2026-10-23T10:30:00+00:00 | unverified ×1 |  | killcause-002 |
| [Synthetic (blog) about Leader](<https://example.net/synthetic/leader-blog>) | 2026-10-23T10:33:00+00:00 | verified ×1 |  | financing-006 |
| [Synthetic newsletter](<https://example.net/synthetic/newsletter>) | 2026-10-23T10:35:00+00:00 | conflict ×1 |  | gtm-004 |
| [Synthetic source](<https://example.net/synthetic/pending>) | 2026-10-23T10:30:00+00:00 | pending ×1 |  | competition-004 |
| [Synthetic source](<https://example.net/synthetic/unverified>) | 2026-10-23T10:30:00+00:00 | unverified ×1; unfetchable |  | customer-004 |
| [Synthetic source](<https://example.net/synthetic/variable-cost>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | unit_economics-004 |
| [Synthetic source](<https://example.net/synthetic/volume>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | unit_economics-005 |
| [Synthetic source](<https://example.org/synthetic/competition>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | competition-003 |
| [Synthetic source](<https://example.org/synthetic/customer>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | customer-003 |
| [Synthetic source](<https://example.org/synthetic/financing>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | financing-003 |
| [Synthetic source](<https://example.org/synthetic/founder-risk>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | founder_risk-003 |
| [Synthetic source](<https://example.org/synthetic/gtm>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | gtm-003 |
| [Synthetic source](<https://example.org/synthetic/location>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | location-003 |
| [Synthetic source](<https://example.org/synthetic/market>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | market-003 |
| [Synthetic source](<https://example.org/synthetic/pricing>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | pricing-003 |
| [Synthetic source](<https://example.org/synthetic/regulation>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | regulation-003 |
| [Synthetic source](<https://example.org/synthetic/unit-economics>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | unit_economics-003 |
| [Synthetic starttiraha page](<https://tyomarkkinatori.fi/synthetic/starttiraha>) | 2026-10-23T10:31:00+00:00 | verified ×1 | yes | financing-004 |
| [Synthetic source](<https://www.example.com/synthetic/competition>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | competition-002 |
| [Synthetic source](<https://www.example.com/synthetic/customer>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | customer-002 |
| [Synthetic source](<https://www.example.com/synthetic/financing>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | financing-002 |
| [Synthetic source](<https://www.example.com/synthetic/founder-risk>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | founder_risk-002 |
| [Synthetic source](<https://www.example.com/synthetic/gtm>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | gtm-002 |
| [Synthetic source](<https://www.example.com/synthetic/location>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | location-002 |
| [Synthetic source](<https://www.example.com/synthetic/market>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | market-002 |
| [Synthetic source](<https://www.example.com/synthetic/pricing>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | pricing-002 |
| [Synthetic source](<https://www.example.com/synthetic/regulation>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | regulation-002 |
| [Synthetic source](<https://www.example.com/synthetic/unit-economics>) | 2026-10-23T10:30:00+00:00 | verified ×1 |  | unit_economics-002 |
| [Synthetic Finnvera page](<https://www.finnvera.fi/synthetic/microloan>) | 2026-10-23T10:32:00+00:00 | unverified ×1; unfetchable | yes | financing-005 |
| [Synthetic Rääkkylä page](<https://www.raakkyla.fi/synthetic/residents>) | 2026-10-23T10:34:00+00:00 | verified ×1 | yes | location-004 |
| [Synthetic source](<https://www.vero.fi/synthetic/competition>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | competition-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/customer>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | customer-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/financing>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | financing-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/founder-risk>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | founder_risk-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/gtm>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | gtm-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/location>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | location-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/market>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | market-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/pricing>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | pricing-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/regulation>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | regulation-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/unit-economics>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | unit_economics-001 |
| [Synthetic source](<https://www.vero.fi/synthetic/vat>) | 2026-10-23T10:30:00+00:00 | verified ×1 | yes | regulation-004 |

## Usage summary

```text
usage for 20261023-130000-sauna-cabins: 12 tool calls, 4 searches, 2 fetches, ~20290 tokens
warning: skipped 1 malformed line(s) in usage.jsonl

per stage
stage               calls  searches  fetches  ~tokens
research:market         3         1        1     8300
research:pricing        3         2        1     7700
research:killcause      1         1        0     1800
verify                  1         0        0      600
(no stage)              4         0        0     1890
total                  12         4        2    20290

per agent
agent               calls  searches  fetches  ~tokens
main                    5         0        0     2490
research-killcause      1         1        0     1800
research-market         3         1        1     8300
research-pricing        3         2        1     7700
total                  12         4        2    20290

budget markers
none
```
