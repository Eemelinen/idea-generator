"""Re-run the query behind an API claim's cited URL (IF-209).

    requery(url) → Answer(api, values, text, response)

A claim with `source_type: api` cites the URL one of the `fi` tools printed. `parse` turns that
URL back into the client call that produced it and `requery` runs it again through the client
(and so through its 24 h cache in cache/<api>/):

    pxweb     the `cite:` URL, https://pxdata.stat.fi/PXWeb/api/v1/<lang>/StatFin/<path>.px
              ?<code>=<value>,<value>&… (or statdb.luke.fi/…/LUKE/…) → pxweb.query; a variable
              left out of the query string selects every value
    prh       https://avoindata.prh.fi/opendata-ytj-api/v3/companies?<params> → prh.search
    eurostat  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/<dataset>
              ?<dim>=<code>&…&sinceTimePeriod=&untilTimePeriod=&lang= → eurostat.get

`Answer.values` are the numbers a claim may state: every non-empty cell of a statistics table,
the company count of a PRH search. `Answer.text` is the answer as the tool prints it (CSV; PRH
with a count line first), for matching the quote of a claim that has no value. A URL on one of
these APIs that is not such a call raises `NotAQuery`; a failed request raises `FiDataError`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import parse_qsl, unquote, urlsplit

import pandas as pd

from ideaforge.fi import eurostat, prh, pxweb
from ideaforge.fi.http import FiDataError, Response, Transport, now_utc

ApiName = Literal["pxweb", "prh", "eurostat"]
# PRH query parameter → prh.Criteria field (prh.search_url builds the URL from these).
PRH_PARAMS = {
    "name": "name",
    "mainBusinessLine": "industry",
    "location": "municipality",
    "registrationDateStart": "registered_from",
    "registrationDateEnd": "registered_to",
    "page": "page",
}
EUROSTAT_PERIODS = {"sinceTimePeriod": "since", "untilTimePeriod": "until"}


class NotAQuery(FiDataError):
    """The URL is on one of the APIs but is not a call a `fi` client makes."""


@dataclass(frozen=True)
class PxWebCall:
    table_path: str
    filters: dict[str, list[str]]
    lang: str


@dataclass(frozen=True)
class PrhCall:
    criteria: prh.Criteria


@dataclass(frozen=True)
class EurostatCall:
    dataset: str
    filters: dict[str, list[str]]
    lang: str
    since: str | None
    until: str | None


Call = PxWebCall | PrhCall | EurostatCall


@dataclass(frozen=True)
class Answer:
    api: ApiName
    values: list[int | float]
    text: str
    response: Response


def _split(url: str) -> tuple[str, list[tuple[str, str]]]:
    parts = urlsplit(url.strip())
    base = f"{parts.scheme}://{parts.netloc}{parts.path}"
    return base, parse_qsl(parts.query, keep_blank_values=True)


def api_of(url: str) -> ApiName | None:
    """Which `fi` client's API the URL is on, or None for any other URL."""
    base, _ = _split(url)
    if any(base.startswith(api.root(lang)) for api in pxweb.DATABASES.values() for lang in pxweb.LANGS):
        return "pxweb"
    if base.startswith(prh.BASE_URL):
        return "prh"
    if base.startswith(eurostat.BASE_URL):
        return "eurostat"
    return None


def _code_lists(params: list[tuple[str, str]], url: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, value in params:
        codes = [c.strip() for c in value.split(",") if c.strip()]
        if not key.strip() or not codes:
            raise NotAQuery(f"{url}: query parameter {key!r} selects no value")
        out.setdefault(key.strip(), []).extend(codes)
    return out


def _parse_pxweb(base: str, params: list[tuple[str, str]], url: str) -> PxWebCall:
    for db, api in pxweb.DATABASES.items():
        for lang in pxweb.LANGS:
            root = api.root(lang)
            if base.startswith(root):
                path = unquote(base[len(root) :]).strip("/")
                if not path.lower().endswith(".px"):
                    raise NotAQuery(f"{url} is not a table (a PxWeb table path ends in .px)")
                return PxWebCall(f"{db}/{path}", _code_lists(params, url), lang)
    raise NotAQuery(f"{url} is not a PxWeb table URL")


def _parse_prh(base: str, params: list[tuple[str, str]], url: str) -> PrhCall:
    if base.rstrip("/") != prh.BASE_URL:
        raise NotAQuery(f"{url} is not a PRH company search ({prh.BASE_URL}?…)")
    values: dict[str, Any] = {}
    for key, value in params:
        field = PRH_PARAMS.get(key)
        if field is None:
            raise NotAQuery(f"{url}: the PRH client never sends {key!r} (it sends {', '.join(PRH_PARAMS)})")
        if field in values:
            raise NotAQuery(f"{url}: {key!r} is given twice")
        if field == "page":
            if not value.isdigit():
                raise NotAQuery(f"{url}: page {value!r} is not a number")
            values[field] = int(value)
        else:
            values[field] = value
    criteria = prh.Criteria(**values)
    try:
        prh.search_url(criteria)  # the client's own checks: digits for the industry, ISO dates
    except FiDataError as e:
        raise NotAQuery(f"{url}: {e}") from None
    return PrhCall(criteria)


def _parse_eurostat(base: str, params: list[tuple[str, str]], url: str) -> EurostatCall:
    dataset = unquote(base[len(eurostat.BASE_URL) :]).strip("/")
    if not dataset or "/" in dataset:
        raise NotAQuery(f"{url} is not a Eurostat dataset URL ({eurostat.BASE_URL}<dataset>?…)")
    lang = "EN"
    periods: dict[str, str] = {}
    filters: list[tuple[str, str]] = []
    for key, value in params:
        if key == "lang":
            lang = value.upper()
        elif key in EUROSTAT_PERIODS:
            periods[EUROSTAT_PERIODS[key]] = value
        else:
            filters.append((key, value))
    if lang not in eurostat.LANGS:
        raise NotAQuery(f"{url}: lang {lang!r} is not one of {', '.join(eurostat.LANGS)}")
    call = EurostatCall(dataset, _code_lists(filters, url), lang, periods.get("since"), periods.get("until"))
    try:
        eurostat.data_url(call.dataset, call.filters, call.lang, call.since, call.until)
    except FiDataError as e:
        raise NotAQuery(f"{url}: {e}") from None
    return call


def parse(url: str) -> Call:
    """The client call behind a cited URL; `NotAQuery` if it is not one."""
    base, params = _split(url)
    api = api_of(url)
    if api == "pxweb":
        return _parse_pxweb(base, params, url)
    if api == "prh":
        return _parse_prh(base, params, url)
    if api == "eurostat":
        return _parse_eurostat(base, params, url)
    raise NotAQuery(f"{url} is not on an API of the fi tools")


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def cell_values(frame: pd.DataFrame) -> list[int | float]:
    """The non-empty cells of a statistics frame, ints kept as ints (counts compare exactly)."""
    if frame.empty or "value" not in frame:
        return []
    return [v for v in frame["value"].tolist() if _is_number(v)]


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n")


def requery(url: str, transport: Transport | None = None, now: Callable[[], datetime] = now_utc) -> Answer:
    """Parse the URL back into its client call and run it again (live transport if None)."""
    call = parse(url)
    if isinstance(call, PxWebCall):
        result = pxweb.query(call.table_path, call.filters, pxweb.Client(transport, call.lang, now))
        return Answer("pxweb", cell_values(result.frame), _csv(result.frame), result.response)
    if isinstance(call, PrhCall):
        found = prh.search(call.criteria, prh.Client(transport, now=now))
        return Answer("prh", [found.count], f"count: {found.count}\n{_csv(found.frame())}", found.response)
    data = eurostat.get(call.dataset, call.filters, eurostat.Client(transport, call.lang, now), call.since, call.until)
    return Answer("eurostat", cell_values(data.frame), _csv(data.frame), data.response)

