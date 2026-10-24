# Sauna-and-lake cabins for remote workers: revised plan after the debate

- Run: `20261023-130000-sauna-cabins` (idea `sauna-cabins-remote-work`, version 1)
- Generated: 2026-10-24T09:00:00+00:00
- Compared with: `05_report.md` (verdict GO, weighted total 3.80)
- Debate: 1 rebuttal round(s); judged author-blind against the verified claim ledger

Conformity flag: not raised (no change was backed by 4 or more personas without new claim ids).

This plan is immutable. The projected scores are the judge's proposals; the projected total is computed in Python from them and is not a new score. The verdict changes only when the revised idea is run again as a new version (`/validate --from 20261023-130000-sauna-cabins`).

## Changes against the report

```diff
@@ dimension scores: 05_report.md → judge's projection @@
  customer        4  (not projected)
- market          4
+ market          3.5
  competition     4  (not projected)
- pricing         4
+ pricing         3
  unit_economics  4  (not projected)
  gtm             4  (not projected)
  regulation      4  (not projected)
  financing       4  (not projected)
  location        4  (not projected)
  founder_risk    0  (not projected)
@@ weighted total: report → projection @@
- 3.80
+ 3.65
@@ plan changes accepted by the judge @@
+ Size the beachhead from remote-worker stays, not total nights. [market-001, market-002]
+ Sell week-long winter packages at the verified price point. [pricing-001]
```

### Accepted changes

1. **Size the beachhead from remote-worker stays, not total nights.** Synthetic reason: the segment is a fraction of all nights.
   - `market-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/market>), retrieved 2026-10-23T10:30:00+00:00.
   - `market-002`: Rent costs 400 EUR per month (400 EUR/month). Source: [Synthetic source](<https://www.example.com/synthetic/market>), retrieved 2026-10-23T10:30:00+00:00.
2. **Sell week-long winter packages at the verified price point.** Synthetic reason: the price claim supports it.
   - `pricing-001`: The price of one sauna evening is 25 EUR (25 EUR). Source: [Synthetic source](<https://www.vero.fi/synthetic/pricing>), retrieved 2026-10-23T10:30:00+00:00.

### Rejected changes

1. Add a third cabin in year one. Reason: Synthetic reason: no verified demand beyond two cabins.
2. Undercut the nearest competitor by half. Reason: Synthetic reason: the margin claim does not allow it. Claims: competition-001, market-999. Not in the ledger: market-999.

## Assumption register

| # | Assumption | Evidence state | Risk if wrong |
| ---: | --- | --- | --- |
| 1 | Remote workers book week-long winter stays. | untested | Fixed costs are uncovered for five months. |
| 2 | Guests accept a \| in the price list. | contested | Synthetic risk with a pipe. |
| 3 | Cleaning can be bought locally. | supported | The founder cleans every stay. |

## Experiments

Ordered by information value per euro (info value 1–5 ÷ cost); a free experiment comes first.

| # | Experiment | Cost (EUR) | Days | Success threshold | Info value | Per 100 EUR |
| ---: | --- | ---: | ---: | --- | ---: | ---: |
| 1 | Remote-work forum post | 0.00 | 7 | 10 booking enquiries | 3 | free |
| 2 | Cleaning quote from two providers | 0.00 | 5 | Quote under the assumed cost per stay | 2 | free |
| 3 | Price test at two nightly rates | 40.00 | 21 | Higher rate converts at least half as often | 4 | 10.00 |
| 4 | Winter landing page with deposit | 60.00 | 14 | 5 paid deposits | 5 | 8.33 |
| 5 | Sauna-equipment rental quote | 60.00 | 10 | Rental under 40 EUR per week | 2 | 3.33 |
| 6 | Weekend pilot stay | 150.00 | 30 | Guest rates the stay 4/5 or better | 4 | 2.67 |
