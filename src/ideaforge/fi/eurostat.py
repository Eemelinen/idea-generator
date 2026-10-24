"""Eurostat JSON-stat client (IF-202, absorbs IF-203).

    python -m ideaforge.fi.eurostat get <dataset> --geo FI [--filter unit=NR] [--since 2019] [--json]

Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/<dataset>
`get(dataset, filters)` returns the JSON-stat 2.0 dataset as a DataFrame (one row per cell: a
label and a `_code` column per dimension, `value`, `status`; a cell without data has an empty
value). A filter is `<dimension>=<code>,<code>…` with Eurostat's dimension and category codes
(`unit=NR`, `nace_r2=I551-I553`); `--geo FI` is the same as `--filter geo=FI`. `--since` /
`--until` restrict the time period.

`get` prints CSV on stdout and the exact request (method, URL, retrieval time) on stderr; `--json`
prints all of it as one object. Cite the URL as `source_url` with `source_type: api`. Responses are
cached in cache/eurostat/ for 24 h (`ideaforge.fi.http`); tests replay the IF-200 recording through a
fake transport.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

import pandas as pd

from ideaforge.fi import http
from ideaforge.fi.http import FiDataError, Response, Transport, now_utc
from ideaforge.fi.pxweb import jsonstat_frame, parse_filters

USER_AGENT = "ideaforge/0.1 (local business-idea validator; Eurostat statistics client)"
BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
LANGS = ("EN", "FR", "DE")
_DATASET = re.compile(r"^[A-Za-z0-9_$-]+$")

requests_transport = http.requests_transport(USER_AGENT)


class Client(http.CachedClient):
    """Requests through the 24 h cache in cache/eurostat/; `lang` picks the label language."""

    def __init__(
        self, transport: Transport | None = None, lang: str = "EN", now: Callable[[], datetime] = now_utc
    ) -> None:
        if lang.upper() not in LANGS:
            raise FiDataError(f"language must be one of {', '.join(LANGS)}")
        super().__init__(transport or requests_transport, "eurostat", now)
        self.lang = lang.upper()


def data_url(
    dataset: str,
    filters: dict[str, list[str]],
    lang: str = "EN",
    since: str | None = None,
    until: str | None = None,
) -> str:
    """The data URL: filters in the given order (a dimension repeated per code), then the time
    period and the language."""
    dataset = dataset.strip()
    if not _DATASET.match(dataset):
        raise FiDataError(f"dataset {dataset!r} must be a Eurostat dataset code, e.g. tour_occ_ninat")
    params: list[tuple[str, str]] = [(dim, code) for dim, codes in filters.items() for code in codes]
    if since:
        params.append(("sinceTimePeriod", since.strip()))
    if until:
        params.append(("untilTimePeriod", until.strip()))
    params.append(("lang", lang))
    return f"{BASE_URL}{dataset}?{urlencode(params, quote_via=quote)}"


@dataclass(frozen=True)
class Dataset:
    dataset: str
    frame: pd.DataFrame
    response: Response
    label: str
    source: str
    updated: str | None


def _error_text(data: Any) -> str:
    if isinstance(data, dict) and isinstance(data.get("error"), dict | list):
        errors = data["error"] if isinstance(data["error"], list) else [data["error"]]
        return "; ".join(str(e.get("label") or e) for e in errors if e)
    return ""


def get(
    dataset: str,
    filters: dict[str, list[str]],
    client: Client | None = None,
    since: str | None = None,
    until: str | None = None,
) -> Dataset:
    client = client or Client()
    resp = client.request("GET", data_url(dataset, filters, client.lang, since, until))
    data = resp.data
    if not isinstance(data, dict) or "id" not in data or "dimension" not in data:
        detail = _error_text(data)
        raise FiDataError(f"{resp.url} did not return a JSON-stat dataset{f': {detail}' if detail else ''}")
    return Dataset(
        dataset.strip(),
        jsonstat_frame(data),
        resp,
        data.get("label", ""),
        data.get("source", ""),
        data.get("updated"),
    )


# ---------------------------------------------------------------- CLI


def _filters(args: argparse.Namespace) -> dict[str, list[str]]:
    specs = ([f"geo={args.geo}"] if args.geo else []) + (args.filter or [])
    try:
        return parse_filters(specs)
    except FiDataError as e:
        raise FiDataError(str(e).replace("<variable>", "<dimension>")) from None


def _cmd_get(args: argparse.Namespace, client: Client) -> int:
    result = get(args.dataset, _filters(args), client, args.since, args.until)
    if args.json:
        out = {
            "dataset": result.dataset,
            "label": result.label,
            "source": result.source,
            "updated": result.updated,
            "request": http.request_json(result.response),
            "rows": json.loads(result.frame.to_json(orient="records", force_ascii=False)),
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    for line in http.request_lines(result.response):
        print(line, file=sys.stderr)
    print(f"source: {result.source}; updated {result.updated}", file=sys.stderr)
    sys.stdout.write(result.frame.to_csv(index=False, lineterminator="\n"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m ideaforge.fi.eurostat", description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--lang", type=str.upper, choices=LANGS, default="EN", help="label language (default EN)")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get", help="fetch a dataset; CSV on stdout, the request on stderr")
    g.add_argument("dataset", help="dataset code, e.g. tour_occ_ninat")
    g.add_argument("--geo", metavar="CODE[,CODE…]", help="geography, e.g. FI (same as --filter geo=FI)")
    g.add_argument("--filter", action="append", metavar="DIM=CODE[,CODE…]")
    g.add_argument("--since", metavar="PERIOD", help="first time period, e.g. 2019")
    g.add_argument("--until", metavar="PERIOD", help="last time period")
    g.add_argument("--json", action="store_true")
    return p


def main(
    argv: list[str] | None = None,
    transport: Transport | None = None,
    now: Callable[[], datetime] = now_utc,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = Client(transport, args.lang, now)
        return {"get": _cmd_get}[args.cmd](args, client)
    except FiDataError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
