"""Record real Finnish/EU open-data API responses as test fixtures (IF-200).

    uv run python scripts/record_fixtures.py [--source statfin|luke|prh|eurostat]

Needs the network, so it is run by a person, never by an unattended session. Each recording is
saved as tests/fixtures/api/<source>/<name>.json (the parsed response, re-indented) next to
<name>.meta.json (url, method, request body, status, retrieved_at, and `trimmed` / `note` where
they apply). The fi clients (IF-201, IF-202) and API re-query (IF-209) are built and tested
offline against these files; tests/test_api_fixtures.py checks them.

Prints each request URL. Exit 0 when every recording is saved, 1 on the first failed request
(nothing of that recording is written).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from ideaforge import config

USER_AGENT = "ideaforge/0.1 (local business-idea validator; API fixture recording)"
TIMEOUT_S = 10
OUT_DIR = config.ROOT / "tests" / "fixtures" / "api"
STATFIN = "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin"
LUKE = "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE"
PRH = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
# PRH searches return full company records (~2.5 kB each); longer lists keep the first ones.
MAX_COMPANIES = 10


@dataclass(frozen=True)
class Recording:
    source: str
    name: str
    url: str
    params: dict[str, str] | None = None
    body: dict[str, Any] | None = None  # POST (PxWeb query) when set
    note: str | None = None


def _px_query(selections: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "query": [{"code": code, "selection": {"filter": "item", "values": values}} for code, values in selections.items()],
        "response": {"format": "json-stat2"},
    }


RECORDINGS: tuple[Recording, ...] = (
    Recording("statfin", "vaerak_listing", f"{STATFIN}/vaerak/", note="Table listing of the population structure database."),
    Recording("statfin", "11ra_metadata", f"{STATFIN}/vaerak/11ra.px", note="Key figures on population by region."),
    Recording(
        "statfin",
        "11ra_raakkyla_population",
        f"{STATFIN}/vaerak/11ra.px",
        body=_px_query(
            {
                "alue_23_20260101": ["KU707", "MK12"],  # Rääkkylä, Pohjois-Karjala (maakunta)
                "contentscode": ["vaerak-vaesto"],
                "timeperiod_y": ["2021", "2022", "2023", "2024", "2025"],
            }
        ),
        note="Population 31.12. of Rääkkylä and North Karelia, 2021–2025.",
    ),
    Recording(
        "statfin",
        "11re_metadata",
        f"{STATFIN}/vaerak/11re.px",
        note="Population by age, sex and region: 309 × 102 × 3 × 54 × 1 = 5 105 916 cells unfiltered (over the 100 000-cell limit).",
    ),
    Recording("luke", "0100_muuyri_metadata", f"{LUKE}/maa/muuyri/0100_muuyri.px", note="Diversified farms by ELY centre."),
    Recording(
        "luke",
        "0100_muuyri_query",
        f"{LUKE}/maa/muuyri/0100_muuyri.px",
        body=_px_query(
            {
                "INFO": ["TILA_KPL"],
                "A": ["2020", "2023"],
                "ELY": ["SSS", "ELY09"],  # whole country, Pohjois-Karjala
                "RAJ": ["SUUR_TOIM", "KAIK_YRI"],  # by main line / every line carried on
                "TOL": ["TOL_YHT", "MATK"],  # all lines, tourism / accommodation / leisure
            }
        ),
        note="Diversified farms, all lines and tourism/accommodation/leisure, Finland and North Karelia, 2020 and 2023. The all-lines total exists only by main line; the other cells are '..' (status).",
    ),
    Recording(
        "prh",
        "industry_55_raakkyla",
        PRH,
        params={"mainBusinessLine": "55", "location": "Rääkkylä"},
        note="Accommodation (TOL 55) in Rääkkylä. Industry codes are TOL 2025 (typeCodeSet TOIMI4) since 2026-01-01; the 5-digit 55201 of TOL 2008 finds nothing here, the 2-digit prefix matches.",
    ),
    Recording("prh", "name_raakkylan", PRH, params={"name": "Rääkkylän"}, note="Name search."),
    Recording(
        "eurostat",
        "tour_occ_ninat_fi",
        f"{EUROSTAT}/tour_occ_ninat",
        params={
            "geo": "FI",
            "unit": "NR",
            "c_resid": "TOTAL",
            "nace_r2": "I551-I553",
            "sinceTimePeriod": "2019",
            "lang": "EN",
        },
        note="Nights spent at tourist accommodation establishments in Finland, 2019 onwards (JSON-stat 2.0).",
    ),
)


def _trim(rec: Recording, data: Any) -> tuple[Any, str | None]:
    if rec.source == "prh" and len(data.get("companies", [])) > MAX_COMPANIES:
        total = len(data["companies"])
        data = {**data, "companies": data["companies"][:MAX_COMPANIES]}
        return data, f"companies: the first {MAX_COMPANIES} of {total} returned; totalResults is as returned"
    return data, None


def record(rec: Recording, session: requests.Session) -> int:
    if rec.body is None:
        r = session.get(rec.url, params=rec.params, timeout=TIMEOUT_S)
    else:
        r = session.post(rec.url, json=rec.body, timeout=TIMEOUT_S)
    print(f"{r.request.method} {r.url} → {r.status_code}")
    r.raise_for_status()
    data, trimmed = _trim(rec, r.json())
    meta: dict[str, Any] = {
        "url": r.url,
        "method": r.request.method,
        "request": rec.body,
        "status": r.status_code,
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if trimmed:
        meta["trimmed"] = trimmed
    if rec.note:
        meta["note"] = rec.note
    out = OUT_DIR / rec.source
    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    (out / f"{rec.name}.json").write_text(payload, encoding="utf-8")
    (out / f"{rec.name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(payload.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=sorted({r.source for r in RECORDINGS}), help="record only this source")
    args = parser.parse_args(argv)

    import truststore  # TLS interception on the dev machine (TICKETS.md plan note 9)

    truststore.inject_into_ssl()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    total = 0
    for rec in RECORDINGS:
        if args.source and rec.source != args.source:
            continue
        try:
            total += record(rec, session)
        except (requests.RequestException, ValueError) as e:
            print(f"error: {rec.source}/{rec.name}: {e}", file=sys.stderr)
            return 1
    print(f"saved {total / 1024:.0f} kB of responses under {OUT_DIR.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
