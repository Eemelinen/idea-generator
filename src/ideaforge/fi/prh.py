"""PRH open data (YTJ) company search (IF-202).

    python -m ideaforge.fi.prh search --name "<text>" [--json]
    python -m ideaforge.fi.prh search --industry <TOL> --municipality Rääkkylä [--json]
    python -m ideaforge.fi.prh search --industry 55 --registered-from 2020-01-01 [--registered-to …] [--page 2]

Endpoint: https://avoindata.prh.fi/opendata-ytj-api/v3/companies
Prints the company count (`totalResults`) and one CSV row per returned company (name, business id,
registration date, trade-register status, end date, main business line, company form) on stdout,
and the exact request (method, URL, retrieval time) on stderr; `--json` prints all of it as one
object. Cite the URL as `source_url` with `source_type: api`.

Industry codes are TOL 2025 since 2026-01-01 (`typeCodeSet` TOIMI4): a 5-digit TOL 2008 code such
as 55201 may find nothing, while a shorter prefix (55) matches every code under it. The count is
the whole match; the rows are one page of it (`--page` for the next).

Limitations of the open data: no sole traders (toiminimi) and no contact details, so a count is a
lower bound on the businesses in an industry. Responses are cached in cache/prh/ for 24 h
(`ideaforge.fi.http`); tests replay the IF-200 recordings through a fake transport.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import quote, urlencode

import pandas as pd

from ideaforge.fi import http
from ideaforge.fi.http import FiDataError, Response, Transport, now_utc

USER_AGENT = "ideaforge/0.1 (local business-idea validator; PRH company search client)"
BASE_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"
LANG_CODES = {"fi": "1", "sv": "2", "en": "3"}  # `languageCode` of the descriptions
TRADE_REGISTER = "1"  # `register` of the trade-register entries in `registeredEntries`
COLUMNS = [
    "name",
    "business_id",
    "registration_date",
    "status",
    "end_date",
    "industry_code",
    "industry",
    "company_form",
]

requests_transport = http.requests_transport(USER_AGENT)


class Client(http.CachedClient):
    """Requests through the 24 h cache in cache/prh/; `lang` picks the language of descriptions."""

    def __init__(
        self, transport: Transport | None = None, lang: str = "fi", now: Callable[[], datetime] = now_utc
    ) -> None:
        if lang not in LANG_CODES:
            raise FiDataError(f"language must be one of {', '.join(LANG_CODES)}")
        super().__init__(transport or requests_transport, "prh", now)
        self.lang = lang


@dataclass(frozen=True)
class Criteria:
    name: str | None = None
    industry: str | None = None  # TOL code or prefix, digits only
    municipality: str | None = None
    registered_from: str | None = None  # YYYY-MM-DD
    registered_to: str | None = None
    page: int | None = None


def _iso_date(value: str, flag: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise FiDataError(f"{flag} {value!r} must be a date YYYY-MM-DD") from None


def search_url(criteria: Criteria) -> str:
    """The v3 `companies` URL for the criteria, in a fixed parameter order."""
    params: list[tuple[str, str]] = []
    if criteria.name and criteria.name.strip():
        params.append(("name", criteria.name.strip()))
    if criteria.industry and criteria.industry.strip():
        code = criteria.industry.strip().replace(".", "")
        if not code.isdigit():
            raise FiDataError(f"--industry {criteria.industry!r} must be a TOL code or prefix (digits, e.g. 55)")
        params.append(("mainBusinessLine", code))
    if criteria.municipality and criteria.municipality.strip():
        params.append(("location", criteria.municipality.strip()))
    if criteria.registered_from:
        params.append(("registrationDateStart", _iso_date(criteria.registered_from, "--registered-from")))
    if criteria.registered_to:
        params.append(("registrationDateEnd", _iso_date(criteria.registered_to, "--registered-to")))
    if not params:
        raise FiDataError(
            "give at least one of --name, --industry, --municipality, --registered-from, --registered-to"
        )
    if criteria.page is not None:
        if criteria.page < 1:
            raise FiDataError("--page must be 1 or more")
        params.append(("page", str(criteria.page)))
    return f"{BASE_URL}?{urlencode(params, quote_via=quote)}"


# ---------------------------------------------------------------- parsing


@dataclass(frozen=True)
class Company:
    name: str
    business_id: str
    registration_date: str | None
    status: str
    end_date: str | None
    industry_code: str | None
    industry: str
    company_form: str


def _description(item: dict[str, Any] | None, lang: str) -> str:
    if not item:
        return ""
    texts = {d.get("languageCode"): d.get("description", "") for d in item.get("descriptions") or []}
    return texts.get(LANG_CODES[lang]) or texts.get(LANG_CODES["fi"]) or next(iter(texts.values()), "")


def _current(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The first entry without an end date, else the first entry."""
    return next((i for i in items if not i.get("endDate")), items[0] if items else None)


def _name(company: dict[str, Any]) -> str:
    names = company.get("names") or []
    main = [n for n in names if n.get("type") == "1"] or names  # type 1 = the company name
    current = _current(main)
    return str(current.get("name", "")) if current else ""


def _status(company: dict[str, Any], lang: str) -> str:
    """The trade-register status in words, from the matching `registeredEntries` description
    (`1` Registered, `4` Ceased in the IF-200 recordings); the bare code if none matches."""
    code = company.get("tradeRegisterStatus")
    if code is None:
        return ""
    entries = [
        e
        for e in company.get("registeredEntries") or []
        if e.get("register") == TRADE_REGISTER and e.get("type") == str(code)
    ]
    return _description(_current(entries), lang) or f"code {code}"


def parse_company(company: dict[str, Any], lang: str = "fi") -> Company:
    business_id = company.get("businessId") or {}
    line = company.get("mainBusinessLine") or None
    return Company(
        name=_name(company),
        business_id=str(business_id.get("value", "")),
        registration_date=company.get("registrationDate") or business_id.get("registrationDate"),
        status=_status(company, lang),
        end_date=company.get("endDate"),
        industry_code=line.get("type") if line else None,
        industry=_description(line, lang),
        company_form=_description(_current(company.get("companyForms") or []), lang),
    )


@dataclass(frozen=True)
class SearchResult:
    criteria: Criteria
    count: int
    companies: list[Company]
    response: Response

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(c) for c in self.companies], columns=COLUMNS)


def search(criteria: Criteria, client: Client | None = None) -> SearchResult:
    client = client or Client()
    resp = client.request("GET", search_url(criteria))
    data = resp.data
    if not isinstance(data, dict) or not isinstance(data.get("companies"), list):
        raise FiDataError(f"{resp.url} did not return a company list")
    companies = [parse_company(c, client.lang) for c in data["companies"] if isinstance(c, dict)]
    total = data.get("totalResults")
    count = total if isinstance(total, int) else len(companies)
    return SearchResult(criteria, count, companies, resp)


def hints(result: SearchResult) -> list[str]:
    out = []
    code = (result.criteria.industry or "").strip().replace(".", "")
    if result.count == 0 and len(code) > 2:
        out.append(
            f"no match for industry {code}: PRH uses TOL 2025 codes since 2026-01-01, so a TOL 2008 code "
            f"may find nothing; try a prefix such as --industry {code[:2]}"
        )
    if result.count > len(result.companies):
        page = result.criteria.page or 1
        out.append(
            f"{len(result.companies)} of {result.count} companies shown (page {page}); --page {page + 1} for more"
        )
    return out


# ---------------------------------------------------------------- CLI


def _cmd_search(args: argparse.Namespace, client: Client) -> int:
    criteria = Criteria(
        name=args.name,
        industry=args.industry,
        municipality=args.municipality,
        registered_from=args.registered_from,
        registered_to=args.registered_to,
        page=args.page,
    )
    result = search(criteria, client)
    notes = hints(result)
    if args.json:
        out = {
            "criteria": asdict(criteria),
            "count": result.count,
            "request": http.request_json(result.response),
            "notes": notes,
            "companies": [asdict(c) for c in result.companies],
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    for line in http.request_lines(result.response):
        print(line, file=sys.stderr)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    print(f"count: {result.count}")
    if result.companies:
        sys.stdout.write(result.frame().to_csv(index=False, lineterminator="\n"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m ideaforge.fi.prh", description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--lang", choices=list(LANG_CODES), default="fi", help="language of descriptions (default fi)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="count and list companies; CSV on stdout, the request on stderr")
    s.add_argument("--name", help="company name or part of it")
    s.add_argument("--industry", metavar="TOL", help="main business line, a TOL 2025 code or prefix (e.g. 55)")
    s.add_argument("--municipality", help="municipality (town) name, e.g. Rääkkylä")
    s.add_argument("--registered-from", metavar="YYYY-MM-DD", help="registered on or after this date")
    s.add_argument("--registered-to", metavar="YYYY-MM-DD", help="registered on or before this date")
    s.add_argument("--page", type=int, help="result page (default 1)")
    s.add_argument("--json", action="store_true")
    return p


def main(
    argv: list[str] | None = None,
    transport: Transport | None = None,
    now: Callable[[], datetime] = now_utc,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = Client(transport, args.lang, now)
        return {"search": _cmd_search}[args.cmd](args, client)
    except FiDataError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
