"""Statistics Finland (StatFin) and Luke PxWeb client (IF-201).

    python -m ideaforge.fi.pxweb search "<keyword>" [--db statfin|luke] [--path vaerak/] [--json]
    python -m ideaforge.fi.pxweb meta <table_path> [--json]
    python -m ideaforge.fi.pxweb get <table_path> --filter Alue=Rääkkylä,MK12 [--filter …] [--json]

A table path is `<database>/<path in the database>`, e.g. `statfin/vaerak/11ra.px` or
`luke/maa/muuyri/0100_muuyri.px` (the database name is case-insensitive, `.px` may be left out).
A filter is `<variable>=<value>,<value>…`; variable and values match by code or by text
(case-insensitive; a value text also matches without its code prefix, so `Pohjois-Karjala`
finds `MK12 Pohjois-Karjala`; when several values match, the first in table order is used and the
others are named on stderr). `*` selects every value. A variable without a filter selects every
value, so its whole size counts towards the cell limit.

`get` prints CSV (one row per cell: a label and a `_code` column per variable, `value`, `status`)
on stdout and the exact request (method, URL, query body, retrieval time) on stderr; `--json`
prints all of it as one object. Cite the URL as `source_url` with `source_type: api`.

Base URLs (one `Api` per API version, so the newer PxWeb API can be swapped in):
    StatFin: https://pxdata.stat.fi/PXWeb/api/v1/{lang}/StatFin/
    Luke:    https://statdb.luke.fi/PXWeb/api/v1/{lang}/LUKE/

Queries over 100 000 cells are refused before any data is requested, with the size of every
variable and a hint which to filter. Responses are cached in cache/pxweb/ for 24 h. The HTTP
layer is a plain callable (`Transport`) so tests replay the IF-200 recordings and never touch the
network. Search without `--path` uses the API's own search (`?query=`); with `--path` it filters
that folder's listing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd

from ideaforge import config

USER_AGENT = "ideaforge/0.1 (local business-idea validator; PxWeb statistics client)"
TIMEOUT_S = 10
CELL_LIMIT = 100_000
CACHE_TTL = timedelta(hours=24)
LANGS = ("fi", "en", "sv")

# method, url, JSON body (None for GET) → parsed JSON response
Transport = Callable[[str, str, dict[str, Any] | None], Any]


class PxWebError(Exception):
    """A request, lookup or filter that cannot be answered; the message is meant for the user."""


class CellLimitError(PxWebError):
    """The query would return more cells than the API allows."""


# ---------------------------------------------------------------- API versions


@dataclass(frozen=True)
class Api:
    """URLs and query bodies of the PxWeb API v1. A v2 client is another instance of this shape."""

    base: str  # with {lang}, ending in "/"

    def root(self, lang: str) -> str:
        return self.base.format(lang=lang)

    def node_url(self, lang: str, path: str) -> str:
        return self.root(lang) + quote(path.strip("/"), safe="/")

    def folder_url(self, lang: str, path: str) -> str:
        url = self.node_url(lang, path)
        return url if url.endswith("/") else url + "/"

    def search_url(self, lang: str, keyword: str) -> str:
        return f"{self.root(lang)}?query={quote(keyword, safe='')}"

    def query_body(self, selections: dict[str, list[str] | None]) -> dict[str, Any]:
        """None selects every value of the variable."""
        query = [
            {
                "code": code,
                "selection": {"filter": "all", "values": ["*"]}
                if values is None
                else {"filter": "item", "values": values},
            }
            for code, values in selections.items()
        ]
        return {"query": query, "response": {"format": "json-stat2"}}


DATABASES: dict[str, Api] = {
    "statfin": Api("https://pxdata.stat.fi/PXWeb/api/v1/{lang}/StatFin/"),
    "luke": Api("https://statdb.luke.fi/PXWeb/api/v1/{lang}/LUKE/"),
}


def split_table_path(table_path: str) -> tuple[str, str]:
    """`statfin/vaerak/11ra` → ("statfin", "vaerak/11ra.px")."""
    db, _, path = table_path.strip().strip("/").partition("/")
    if db.lower() not in DATABASES or not path:
        known = ", ".join(DATABASES)
        raise PxWebError(f"table path {table_path!r} must be <database>/<path>, database one of: {known}")
    if not path.lower().endswith(".px"):
        path += ".px"
    return db.lower(), path


# ---------------------------------------------------------------- transport and cache


def requests_transport(method: str, url: str, body: dict[str, Any] | None) -> Any:
    import requests
    import truststore

    truststore.inject_into_ssl()
    headers = {"User-Agent": USER_AGENT}
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=TIMEOUT_S)
        else:
            r = requests.post(url, json=body, headers=headers, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise PxWebError(f"{method} {url} failed: {type(e).__name__}: {e}") from e
    if r.status_code >= 400:
        raise PxWebError(f"{method} {url} → HTTP {r.status_code}: {r.text.strip()[:300]}")
    try:
        return r.json()
    except ValueError as e:
        raise PxWebError(f"{method} {url} did not return JSON") from e


@dataclass(frozen=True)
class Response:
    method: str
    url: str
    body: dict[str, Any] | None
    data: Any
    retrieved_at: datetime
    from_cache: bool


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class Client:
    """Requests through the 24 h cache in cache/pxweb/ (keyed by method, URL and body)."""

    def __init__(
        self,
        transport: Transport | None = None,
        lang: str = "fi",
        now: Callable[[], datetime] = _now,
    ) -> None:
        if lang not in LANGS:
            raise PxWebError(f"language must be one of {', '.join(LANGS)}")
        self.transport = transport or requests_transport
        self.lang = lang
        self.now = now

    def request(self, method: str, url: str, body: dict[str, Any] | None = None) -> Response:
        key = json.dumps([method, url, body], ensure_ascii=False, sort_keys=True)
        path = config.CACHE_DIR / "pxweb" / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"
        now = self.now()
        if path.is_file():
            cached = _read_cache_entry(path)  # None if unreadable: fetch again and overwrite it
            if cached is not None and now - cached[1] < CACHE_TTL:
                return Response(method, url, body, cached[0], cached[1], from_cache=True)
        data = self.transport(method, url, body)
        entry = {"method": method, "url": url, "body": body, "retrieved_at": now.isoformat(), "data": data}
        # Write then rename, so a killed process never leaves a truncated entry that counts as cached.
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        return Response(method, url, body, data, now, from_cache=False)


def _read_cache_entry(path: Path) -> tuple[Any, datetime] | None:
    """(data, retrieved_at) of a cache file, or None if it is not a JSON object with `data` and an
    aware ISO `retrieved_at` (the shape `Client.request` writes)."""
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entry, dict) or "data" not in entry:
            return None
        retrieved_at = datetime.fromisoformat(entry["retrieved_at"])
    except (ValueError, KeyError, TypeError):
        return None
    return (entry["data"], retrieved_at) if retrieved_at.tzinfo is not None else None


# ---------------------------------------------------------------- listing and search


@dataclass(frozen=True)
class TableRef:
    path: str  # <database>/<path>, as `get` takes it; folders end in "/"
    text: str
    updated: str | None = None
    is_folder: bool = False


def list_tables(path: str, client: Client | None = None) -> tuple[list[TableRef], Response]:
    """The entries of one folder, e.g. `statfin/vaerak/`."""
    client = client or Client()
    db, _, rel = path.strip().strip("/").partition("/")
    if db.lower() not in DATABASES:
        raise PxWebError(f"path {path!r} must start with a database: {', '.join(DATABASES)}")
    db = db.lower()
    resp = client.request("GET", DATABASES[db].folder_url(client.lang, rel))
    if not isinstance(resp.data, list):
        raise PxWebError(f"{resp.url} is not a folder listing")
    prefix = f"{db}/{rel.strip('/')}/" if rel.strip("/") else f"{db}/"
    refs = [
        TableRef(
            path=prefix + e["id"] + ("/" if e.get("type") == "l" else ""),
            text=e.get("text", ""),
            updated=e.get("updated"),
            is_folder=e.get("type") == "l",
        )
        for e in resp.data
    ]
    return refs, resp


def _matches(keyword: str, *texts: str) -> bool:
    haystack = " ".join(texts).casefold()
    return all(word in haystack for word in keyword.casefold().split())


def search(
    keyword: str, dbs: Iterable[str] = tuple(DATABASES), path: str | None = None, client: Client | None = None
) -> tuple[list[TableRef], list[Response]]:
    """Candidate tables for a keyword: the API search of each database, or one folder's listing."""
    client = client or Client()
    if path is not None:
        refs, resp = list_tables(path, client)
        return [r for r in refs if _matches(keyword, r.path, r.text)], [resp]
    found: list[TableRef] = []
    responses = []
    for db in dbs:
        resp = client.request("GET", DATABASES[db].search_url(client.lang, keyword))
        responses.append(resp)
        found.extend(_search_hits(db, resp))
    return found, responses


def _search_hits(db: str, resp: Response) -> list[TableRef]:
    """The hits of a PxWeb v1 search (`[{"id", "path", "title", "published", …}]`) as table paths.

    No live search response is recorded yet (IF-204), so an unexpected shape fails with the URL
    instead of a traceback.
    """
    hits = [] if resp.data is None else resp.data
    if not isinstance(hits, list):
        raise PxWebError(f"{resp.url} did not return a list of search hits; try --path <db>/<folder>/")
    refs = []
    for hit in hits:
        if not isinstance(hit, dict) or not isinstance(hit.get("id"), str) or not hit["id"].strip("/"):
            raise PxWebError(
                f"{resp.url} returned a search hit without a table id: {json.dumps(hit, ensure_ascii=False)[:200]}; "
                "try --path <db>/<folder>/"
            )
        folder = str(hit.get("path") or "").strip("/")
        table = hit["id"].strip("/")
        published = hit.get("published")
        refs.append(
            TableRef(
                path=f"{db}/{folder}/{table}" if folder else f"{db}/{table}",
                text=str(hit.get("title") or ""),
                updated=str(published) if published else None,
            )
        )
    return refs


# ---------------------------------------------------------------- metadata and query


@dataclass(frozen=True)
class Variable:
    code: str
    text: str
    values: list[str]
    value_texts: list[str]
    elimination: bool = False
    time: bool = False


@dataclass(frozen=True)
class Metadata:
    table_path: str
    title: str
    variables: list[Variable]
    response: Response


def metadata(table_path: str, client: Client | None = None) -> Metadata:
    client = client or Client()
    db, path = split_table_path(table_path)
    resp = client.request("GET", DATABASES[db].node_url(client.lang, path))
    if not isinstance(resp.data, dict) or "variables" not in resp.data:
        raise PxWebError(f"{resp.url} is not a table (no variables in its metadata)")
    variables = [
        Variable(
            code=v["code"],
            text=v.get("text", v["code"]),
            values=list(v["values"]),
            value_texts=list(v.get("valueTexts", v["values"])),
            elimination=bool(v.get("elimination", False)),
            time=bool(v.get("time", False)),
        )
        for v in resp.data["variables"]
    ]
    return Metadata(f"{db}/{path}", resp.data.get("title", ""), variables, resp)


def parse_filters(specs: Iterable[str]) -> dict[str, list[str]]:
    """`["Alue=Rääkkylä,MK12", "Vuosi=2025"]` → {"Alue": ["Rääkkylä", "MK12"], "Vuosi": ["2025"]}."""
    out: dict[str, list[str]] = {}
    for spec in specs:
        name, sep, values = spec.partition("=")
        items = [v.strip() for v in values.split(",") if v.strip()]
        if not sep or not name.strip() or not items:
            raise PxWebError(f"filter {spec!r} must look like <variable>=<value>[,<value>…]")
        out.setdefault(name.strip(), []).extend(items)
    return out


def _find_variable(meta: Metadata, name: str) -> Variable:
    key = name.casefold()
    for v in meta.variables:
        if key in (v.code.casefold(), v.text.casefold()):
            return v
    names = ", ".join(f"{v.text} ({v.code})" for v in meta.variables)
    raise PxWebError(f"{meta.table_path} has no variable {name!r}; its variables: {names}")


def _strip_code_prefix(text: str, code: str) -> str:
    head, _, rest = text.partition(" ")
    return rest if rest and head.casefold() == code.casefold() else text


def _resolve_value(var: Variable, wanted: str, warn: Callable[[str], None]) -> str:
    key = wanted.casefold()
    pairs = list(zip(var.values, var.value_texts, strict=False))
    for matcher in (
        lambda c, t: c.casefold() == key,
        lambda c, t: t.casefold() == key,
        lambda c, t: _strip_code_prefix(t, c).casefold() == key,
    ):
        hits = [(c, t) for c, t in pairs if matcher(c, t)]
        if hits:
            if len(hits) > 1:
                others = "; ".join(f"{c} {t!r}" for c, t in hits[1:])
                warn(f"{var.text}={wanted} matched {len(hits)} values; using {hits[0][0]} {hits[0][1]!r} (also: {others})")
            return hits[0][0]
    close = [f"{c} {t!r}" for c, t in pairs if key in t.casefold() or key in c.casefold()][:10]
    hint = f"; close: {', '.join(close)}" if close else f"; run `meta` to list its {len(pairs)} values"
    raise PxWebError(f"{var.text} ({var.code}) has no value {wanted!r}{hint}")


def selections(
    meta: Metadata, filters: dict[str, list[str]], warn: Callable[[str], None] = lambda _: None
) -> dict[str, list[str] | None]:
    """Variable code → selected value codes (None = every value), in table order."""
    chosen: dict[str, list[str]] = {}
    for name, wanted in filters.items():
        var = _find_variable(meta, name)
        if var.code in chosen:
            raise PxWebError(f"{var.text} ({var.code}) is filtered twice")
        if wanted == ["*"]:
            continue
        codes = [_resolve_value(var, w, warn) for w in wanted]
        chosen[var.code] = list(dict.fromkeys(codes))
    return {v.code: chosen.get(v.code) for v in meta.variables}


def cell_count(meta: Metadata, sel: dict[str, list[str] | None]) -> int:
    return math.prod(len(sel[v.code]) if sel[v.code] is not None else len(v.values) for v in meta.variables)


def _thousands(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def check_cell_limit(meta: Metadata, sel: dict[str, list[str] | None]) -> None:
    cells = cell_count(meta, sel)
    if cells <= CELL_LIMIT:
        return
    sizes = [(len(sel[v.code]) if sel[v.code] is not None else len(v.values), v) for v in meta.variables]
    factors = " × ".join(f"{v.text} {n}" for n, v in sizes)
    unfiltered = sorted(((n, v) for n, v in sizes if sel[v.code] is None and n > 1), key=lambda p: -p[0])
    if unfiltered:
        n, v = unfiltered[0]
        hint = (
            "Filter the largest unfiltered variables, e.g. "
            f"--filter {v.text}={v.values[min(1, n - 1)]} (codes or texts; `meta {meta.table_path}` lists them). "
            f"Unfiltered: {', '.join(f'{v.text} ({n} values)' for n, v in unfiltered)}."
        )
    else:
        hint = "Select fewer values, or split the query into several smaller ones."
    raise CellLimitError(
        f"Refused: {meta.table_path} with these filters is {_thousands(cells)} cells ({factors}); "
        f"the PxWeb API returns at most {_thousands(CELL_LIMIT)} cells per query. {hint}"
    )


@dataclass(frozen=True)
class QueryResult:
    table_path: str
    frame: pd.DataFrame
    response: Response
    label: str
    source: str
    updated: str | None


def _category_codes(dim: dict[str, Any]) -> list[str]:
    index = dim["category"].get("index")
    if index is None:
        return list(dim["category"]["label"])
    if isinstance(index, list):
        return list(index)
    return sorted(index, key=index.get)


def jsonstat_frame(data: dict[str, Any]) -> pd.DataFrame:
    """A JSON-stat 2.0 dataset as one row per cell: label + `_code` per dimension, value, status."""
    ids: list[str] = data["id"]
    dims = data["dimension"]
    labels = [dims[d].get("label", d) for d in ids]
    names = [lab if labels.count(lab) == 1 else d for d, lab in zip(ids, labels, strict=True)]
    codes = [_category_codes(dims[d]) for d in ids]
    values = data["value"]
    if isinstance(values, dict):  # sparse form: {"index": value}
        values = [values.get(str(i)) for i in range(math.prod(len(c) for c in codes))]
    status = data.get("status") or {}
    if isinstance(status, list):
        status = {str(i): s for i, s in enumerate(status) if s}
    elif isinstance(status, str):
        status = {str(i): status for i in range(len(values))}
    rows: list[dict[str, Any]] = []
    for i, combo in enumerate(_product(codes)):
        row: dict[str, Any] = {}
        for d, name, code in zip(ids, names, combo, strict=True):
            row[name] = dims[d]["category"].get("label", {}).get(code, code)
            row[f"{name}_code"] = code
        row["value"] = values[i]
        row["status"] = status.get(str(i), "")
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["value"] = pd.Series([r["value"] for r in rows], dtype=object)  # keep ints as ints
    return frame


def _product(lists: list[list[str]]) -> Iterable[tuple[str, ...]]:
    """Row-major (last dimension fastest), the JSON-stat value order."""
    if not lists:
        yield ()
        return
    for head in lists[0]:
        for tail in _product(lists[1:]):
            yield (head, *tail)


def query(
    table_path: str,
    filters: dict[str, list[str]],
    client: Client | None = None,
    warn: Callable[[str], None] = lambda _: None,
) -> QueryResult:
    """Fetch the table's metadata, refuse over CELL_LIMIT cells, then POST the query."""
    client = client or Client()
    meta = metadata(table_path, client)
    sel = selections(meta, filters, warn)
    check_cell_limit(meta, sel)
    db, path = split_table_path(meta.table_path)
    api = DATABASES[db]
    resp = client.request("POST", api.node_url(client.lang, path), api.query_body(sel))
    data = resp.data
    if not isinstance(data, dict) or "id" not in data:
        raise PxWebError(f"{resp.url} did not return a JSON-stat dataset")
    return QueryResult(
        meta.table_path,
        jsonstat_frame(data),
        resp,
        data.get("label", meta.title),
        data.get("source", ""),
        data.get("updated"),
    )


# ---------------------------------------------------------------- CLI


def _request_lines(resp: Response) -> list[str]:
    lines = [f"request: {resp.method} {resp.url}"]
    if resp.body is not None:
        lines.append("query: " + json.dumps(resp.body, ensure_ascii=False, separators=(",", ":")))
    cached = " (from cache)" if resp.from_cache else ""
    lines.append(f"retrieved_at: {resp.retrieved_at.isoformat()}{cached}")
    return lines


def _request_json(resp: Response) -> dict[str, Any]:
    return {
        "method": resp.method,
        "url": resp.url,
        "query": resp.body,
        "retrieved_at": resp.retrieved_at.isoformat(),
        "from_cache": resp.from_cache,
    }


def _cmd_search(args: argparse.Namespace, client: Client) -> int:
    dbs = [args.db] if args.db else list(DATABASES)
    path = args.path
    if path is not None and path.strip("/").split("/", 1)[0].lower() not in DATABASES:
        path = f"{dbs[0]}/{path}"  # a folder of --db (default statfin)
    refs, responses = search(args.keyword, dbs, path, client)
    if args.json:
        out = {
            "keyword": args.keyword,
            "requests": [_request_json(r) for r in responses],
            "tables": [asdict(r) for r in refs],
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    for resp in responses:
        for line in _request_lines(resp):
            print(line, file=sys.stderr)
    if not refs:
        print(f"no tables match {args.keyword!r}")
    for r in refs:
        updated = f"  (updated {r.updated})" if r.updated else ""
        print(f"{r.path}\t{r.text}{updated}")
    return 0


def _cmd_meta(args: argparse.Namespace, client: Client) -> int:
    meta = metadata(args.table_path, client)
    if args.json:
        out = {
            "table": meta.table_path,
            "title": meta.title,
            "request": _request_json(meta.response),
            "variables": [asdict(v) for v in meta.variables],
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    for line in _request_lines(meta.response):
        print(line, file=sys.stderr)
    print(f"{meta.table_path}: {meta.title}")
    for v in meta.variables:
        flags = ", ".join(f for f, on in (("time", v.time), ("can be left out", v.elimination)) if on)
        print(f"\n{v.text} ({v.code}), {len(v.values)} values{f' [{flags}]' if flags else ''}")
        shown = list(zip(v.values, v.value_texts, strict=False))
        for code, text in shown[:20]:
            print(f"  {code}\t{text}")
        if len(shown) > 20:
            print(f"  … {len(shown) - 20} more (--json lists all)")
    return 0


def _cmd_get(args: argparse.Namespace, client: Client) -> int:
    result = query(
        args.table_path,
        parse_filters(args.filter or []),
        client,
        warn=lambda m: print(f"note: {m}", file=sys.stderr),
    )
    if args.json:
        out = {
            "table": result.table_path,
            "label": result.label,
            "source": result.source,
            "updated": result.updated,
            "request": _request_json(result.response),
            "rows": json.loads(result.frame.to_json(orient="records", force_ascii=False)),
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    for line in _request_lines(result.response):
        print(line, file=sys.stderr)
    print(f"source: {result.source}; updated {result.updated}", file=sys.stderr)
    sys.stdout.write(result.frame.to_csv(index=False, lineterminator="\n"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m ideaforge.fi.pxweb", description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--lang", choices=LANGS, default="fi", help="API language (default fi)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="list candidate tables for a keyword")
    s.add_argument("keyword")
    s.add_argument("--db", choices=list(DATABASES), help="one database only (default: all)")
    s.add_argument("--path", help="filter this folder's listing instead, e.g. statfin/vaerak/")
    s.add_argument("--json", action="store_true")
    m = sub.add_parser("meta", help="variables and values of a table")
    m.add_argument("table_path")
    m.add_argument("--json", action="store_true")
    g = sub.add_parser("get", help="query a table; CSV on stdout, the request on stderr")
    g.add_argument("table_path")
    g.add_argument("--filter", action="append", metavar="VAR=VALUE[,VALUE…]")
    g.add_argument("--json", action="store_true")
    return p


def main(
    argv: list[str] | None = None,
    transport: Transport | None = None,
    now: Callable[[], datetime] = _now,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = Client(transport, args.lang, now)
        return {"search": _cmd_search, "meta": _cmd_meta, "get": _cmd_get}[args.cmd](args, client)
    except PxWebError as e:
        print(str(e), file=sys.stderr)
        return 2 if isinstance(e, CellLimitError) else 1


if __name__ == "__main__":
    sys.exit(main())
