"""IF-201: the PxWeb client on the recorded StatFin and Luke responses (IF-200), never the network.

The fake transport answers only the exact requests that were recorded (method, URL and body from
each .meta.json), so a test passes only if the client builds those requests itself.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from ideaforge import config
from ideaforge.fi import API_URL_PREFIXES, pxweb, requery

FIXTURES = config.ROOT / "tests" / "fixtures" / "api"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
STATFIN_11RA = "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/11ra.px"
RAAKKYLA_FILTERS = [
    "Alue=Rääkkylä,MK12",
    "Tiedot=vaerak-vaesto",
    "Vuosi=2021,2022,2023,2024,2025",
]


def _key(method, url, body):
    return json.dumps([method, url, body], ensure_ascii=False, sort_keys=True)


class Recorded:
    """Replays tests/fixtures/api/{statfin,luke}; counts calls; fails on anything not recorded."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.responses = {}
        for source in ("statfin", "luke"):
            for meta_path in (FIXTURES / source).glob("*.meta.json"):
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                data_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + ".json")
                data = json.loads(data_path.read_text(encoding="utf-8"))
                self.responses[_key(meta["method"], meta["url"], meta["request"])] = data

    def __call__(self, method, url, body):
        self.calls.append((method, url))
        key = _key(method, url, body)
        if key not in self.responses:
            raise AssertionError(f"not recorded: {method} {url} {json.dumps(body, ensure_ascii=False)}")
        return self.responses[key]


@pytest.fixture
def recorded(project):
    return Recorded()


def run(capsys, recorded, *argv, now=T0):
    code = pxweb.main(list(argv), transport=recorded, now=lambda: now)
    out, err = capsys.readouterr()
    return code, out, err


# ---------------------------------------------------------------- search


def test_search_lists_matching_tables_of_a_folder(capsys, recorded):
    code, out, err = run(capsys, recorded, "search", "alueittain", "--path", "statfin/vaerak/")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("statfin/vaerak/11ra.px\t11ra -- Tunnuslukuja väestöstä alueittain")
    assert any(line.startswith("statfin/vaerak/11re.px\t") for line in lines)
    assert all("alueittain" in line.casefold() for line in lines)
    assert "request: GET https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/" in err


def test_search_needs_every_word_and_says_when_nothing_matches(capsys, recorded):
    code, out, _ = run(capsys, recorded, "search", "väestö sukupuolen alueittain", "--db", "statfin", "--path", "vaerak")
    assert code == 0
    assert {line.split("\t")[0] for line in out.splitlines()} >= {"statfin/vaerak/11re.px"}
    assert "statfin/vaerak/11ra.px" not in out
    code, out, _ = run(capsys, recorded, "search", "porokanta", "--path", "statfin/vaerak/")
    assert (code, out) == (0, "no tables match 'porokanta'\n")


def test_search_json_carries_the_request(capsys, recorded):
    code, out, _ = run(capsys, recorded, "search", "11ra", "--path", "statfin/vaerak/", "--json")
    assert code == 0
    data = json.loads(out)
    assert [t["path"] for t in data["tables"]] == ["statfin/vaerak/11ra.px"]
    assert data["requests"][0]["url"] == "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/"


def test_search_without_path_uses_the_api_search_of_each_database(project):
    # No search response was recorded (IF-200), so this only checks the requests; an empty
    # result list is the one response that needs no invented data.
    seen = []

    def transport(method, url, body):
        seen.append((method, url, body))
        return []

    refs, responses = pxweb.search("väkiluku", client=pxweb.Client(transport))
    assert refs == []
    assert seen == [
        ("GET", "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/?query=v%C3%A4kiluku", None),
        ("GET", "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/?query=v%C3%A4kiluku", None),
    ]
    assert all(r.url.startswith(API_URL_PREFIXES) for r in responses)


# Synthetic (TICKETS.md plan note 14): no live `?query=` response is recorded yet (IF-204). These
# hits only follow the documented PxWeb v1 search shape (`id`, `path`, `title`, `published`); the
# titles and dates are invented and never cited.
SYNTHETIC_SEARCH_HITS = {
    "statfin": [
        {"id": "11ra.px", "path": "/vaerak", "title": "Synthetic title A", "score": 2.5,
         "published": "2026-01-01T08:00:00"},
        {"id": "top.px", "path": "", "title": "Synthetic title B", "score": 1.0, "published": None},
    ],
    "luke": [{"id": "0100_muuyri.px", "path": "/maa/muuyri/", "title": "Synthetic title C", "score": 1.0}],
}  # fmt: skip


def synthetic_search(method, url, body):
    assert (method, body) == ("GET", None) and "?query=" in url
    return SYNTHETIC_SEARCH_HITS["luke" if "/LUKE/" in url else "statfin"]


def test_search_hits_become_table_paths(capsys, project):
    code, out, err = run(capsys, synthetic_search, "search", "väkiluku")
    assert code == 0
    assert out.splitlines() == [
        "statfin/vaerak/11ra.px\tSynthetic title A  (updated 2026-01-01T08:00:00)",
        "statfin/top.px\tSynthetic title B",
        "luke/maa/muuyri/0100_muuyri.px\tSynthetic title C",
    ]
    assert "request: GET https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/?query=v%C3%A4kiluku" in err
    assert "request: GET https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/?query=v%C3%A4kiluku" in err

    code, out, _ = run(capsys, synthetic_search, "search", "väkiluku", "--db", "luke", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["tables"] == [
        {"path": "luke/maa/muuyri/0100_muuyri.px", "text": "Synthetic title C", "updated": None, "is_folder": False}
    ]
    assert [r["url"] for r in data["requests"]] == ["https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/?query=v%C3%A4kiluku"]


@pytest.mark.parametrize(
    "response",
    [{"error": "unexpected"}, "text", [{"path": "/vaerak", "title": "no id"}], ["11ra.px"], [{"id": 7}]],
)
def test_a_malformed_search_response_is_an_error_naming_the_url(capsys, project, response):
    code, out, err = run(capsys, lambda method, url, body: response, "search", "väkiluku", "--db", "statfin")
    assert (code, out) == (1, "")
    assert "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/?query=v%C3%A4kiluku" in err
    assert "Traceback" not in err


# ---------------------------------------------------------------- get


def test_get_prints_csv_plus_the_exact_request(capsys, recorded):
    filters = [a for f in RAAKKYLA_FILTERS for a in ("--filter", f)]
    code, out, err = run(capsys, recorded, "get", "statfin/vaerak/11ra.px", *filters)
    assert code == 0
    assert out.splitlines() == [
        "Alue,Alue_code,Tiedot,Tiedot_code,Vuosi,Vuosi_code,value,status",
        "Rääkkylä,KU707,Väestö 31.12.,vaerak-vaesto,2021,2021,2032,",
        "Rääkkylä,KU707,Väestö 31.12.,vaerak-vaesto,2022,2022,1960,",
        "Rääkkylä,KU707,Väestö 31.12.,vaerak-vaesto,2023,2023,1902,",
        "Rääkkylä,KU707,Väestö 31.12.,vaerak-vaesto,2024,2024,1881,",
        "Rääkkylä,KU707,Väestö 31.12.,vaerak-vaesto,2025,2025,1830,",
        "MK12 Pohjois-Karjala,MK12,Väestö 31.12.,vaerak-vaesto,2021,2021,163281,",
        "MK12 Pohjois-Karjala,MK12,Väestö 31.12.,vaerak-vaesto,2022,2022,162540,",
        "MK12 Pohjois-Karjala,MK12,Väestö 31.12.,vaerak-vaesto,2023,2023,162321,",
        "MK12 Pohjois-Karjala,MK12,Väestö 31.12.,vaerak-vaesto,2024,2024,162091,",
        "MK12 Pohjois-Karjala,MK12,Väestö 31.12.,vaerak-vaesto,2025,2025,161418,",
    ]
    assert f"request: POST {STATFIN_11RA}\n" in err
    body = json.loads(err.split("query: ", 1)[1].splitlines()[0])
    assert body == json.loads((FIXTURES / "statfin" / "11ra_raakkyla_population.meta.json").read_text("utf-8"))["request"]
    assert f"retrieved_at: {T0.isoformat()}\n" in err
    assert recorded.calls == [("GET", STATFIN_11RA), ("POST", STATFIN_11RA)]
    # the URL to cite carries the selection, so verification can re-run this query (IF-209)
    cite = f"{STATFIN_11RA}?alue_23_20260101=KU707,MK12&contentscode=vaerak-vaesto&timeperiod_y=2021,2022,2023,2024,2025"
    assert err.endswith(f"cite: {cite}\n")
    call = requery.parse(cite)
    assert (call.table_path, call.lang) == ("statfin/vaerak/11ra.px", "fi")
    assert [v for _, v in call.filters.items()] == [["KU707", "MK12"], ["vaerak-vaesto"], ["2021", "2022", "2023", "2024", "2025"]]


def test_get_matches_variables_and_values_by_code_or_text(capsys, recorded):
    # codes for the variables, a value text without its code prefix, and the table path without
    # .px in another case: still the recorded request
    code, out, err = run(
        capsys, recorded, "get", "StatFin/vaerak/11ra",
        "--filter", "alue_23_20260101=KU707", "--filter", "alue_23_20260101=pohjois-karjala",
        "--filter", "contentscode=Väestö 31.12.", "--filter", "timeperiod_y=2021,2022,2023,2024,2025",
    )  # fmt: skip
    assert code == 0, err
    assert "MK12,Väestö 31.12.,vaerak-vaesto,2025,2025,161418," in out
    # Pohjois-Karjala also names a hospital district, an employment area and a NUTS region
    assert "note: Alue=pohjois-karjala matched 3 values; using MK12" in err
    assert "TA29" in err and "FI1DC" in err


def test_get_json_has_rows_url_and_missing_cells(capsys, recorded):
    code, out, _ = run(
        capsys, recorded, "get", "luke/maa/muuyri/0100_muuyri.px", "--json",
        "--filter", "Tieto=TILA_KPL", "--filter", "Vuosi=2020,2023", "--filter", "ELY=KOKO MAA,Pohjois-Karjala",
        "--filter", "RAJ=SUUR_TOIM,KAIK_YRI", "--filter", "Toimiala=TOL_YHT,MATK",
    )  # fmt: skip
    assert code == 0
    data = json.loads(out)
    assert data["request"]["method"] == "POST"
    assert data["request"]["url"] == "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/maa/muuyri/0100_muuyri.px"
    assert data["request"]["from_cache"] is False
    assert data["source"].startswith("SVT: Luonnonvarakeskus")
    assert data["cite_url"] == (
        "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/maa/muuyri/0100_muuyri.px"
        "?INFO=TILA_KPL&A=2020,2023&ELY=SSS,ELY09&RAJ=SUUR_TOIM,KAIK_YRI&TOL=TOL_YHT,MATK"
    )
    rows = data["rows"]
    assert len(rows) == 16
    assert rows[0] == {
        "Tieto": "Tiloja (kpl)", "Tieto_code": "TILA_KPL", "Vuosi": "2020", "Vuosi_code": "2020",
        "ELY-keskus": "KOKO MAA", "ELY-keskus_code": "SSS",
        "Rajaus": "Liikevaihdoltaan suurimman toimialan mukaan", "Rajaus_code": "SUUR_TOIM",
        "Toimiala": "YHTEENSÄ (toimialat)", "Toimiala_code": "TOL_YHT", "value": 14542, "status": "",
    }  # fmt: skip
    # the all-lines total exists only by main line: '..' cells have no value
    assert (rows[2]["Rajaus_code"], rows[2]["Toimiala_code"], rows[2]["value"], rows[2]["status"]) == (
        "KAIK_YRI", "TOL_YHT", None, "..",
    )  # fmt: skip


def test_get_refuses_an_unknown_variable_or_value(capsys, recorded):
    code, _, err = run(capsys, recorded, "get", "statfin/vaerak/11ra.px", "--filter", "Kunta=Rääkkylä")
    assert code == 1
    assert "has no variable 'Kunta'" in err and "Alue (alue_23_20260101)" in err
    code, _, err = run(capsys, recorded, "get", "statfin/vaerak/11ra.px", "--filter", "Alue=Rääkkylää")
    assert code == 1
    assert "has no value 'Rääkkylää'" in err
    code, _, err = run(capsys, recorded, "get", "statfin/vaerak/11ra.px", "--filter", "Alue")
    assert code == 1 and "must look like" in err
    code, _, err = run(capsys, recorded, "get", "stat/vaerak/11ra.px")
    assert code == 1 and "database one of: statfin, luke" in err
    assert all(method == "GET" for method, _ in recorded.calls)


# ---------------------------------------------------------------- cell limit


def test_query_over_the_cell_limit_is_refused_before_any_data_request(capsys, recorded):
    code, out, err = run(capsys, recorded, "get", "statfin/vaerak/11re.px")
    assert (code, out) == (2, "")
    assert "5 105 916 cells (Alue 309 × Ikä 102 × Sukupuoli 3 × Vuosi 54 × Tiedot 1)" in err
    assert "at most 100 000 cells" in err
    assert "--filter Alue=KU020" in err  # the largest unfiltered variable first
    assert recorded.calls == [("GET", "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/11re.px")]


def test_cell_count_follows_the_filters(recorded):
    client = pxweb.Client(recorded, now=lambda: T0)
    meta = pxweb.metadata("statfin/vaerak/11re.px", client)
    sel = pxweb.selections(meta, pxweb.parse_filters(["Alue=Rääkkylä", "Vuosi=2025"]))
    assert pxweb.cell_count(meta, sel) == 1 * 102 * 3 * 1 * 1
    pxweb.check_cell_limit(meta, sel)  # under the limit: no error
    sel = pxweb.selections(meta, pxweb.parse_filters(["Ikä=*", "Vuosi=2024,2025"]))
    assert pxweb.cell_count(meta, sel) == 309 * 102 * 3 * 2
    with pytest.raises(pxweb.CellLimitError, match="189 108 cells"):
        pxweb.check_cell_limit(meta, sel)


# ---------------------------------------------------------------- cache


def test_second_get_within_24_hours_is_a_cache_hit(capsys, recorded, project):
    filters = [a for f in RAAKKYLA_FILTERS for a in ("--filter", f)]
    _, first, _ = run(capsys, recorded, "get", "statfin/vaerak/11ra.px", *filters)
    assert len(recorded.calls) == 2
    assert len(list((project / "cache" / "pxweb").glob("*.json"))) == 2

    later = T0 + timedelta(hours=23, minutes=59)
    code, second, err = run(capsys, recorded, "get", "statfin/vaerak/11ra.px", *filters, now=later)
    assert (code, second) == (0, first)
    assert len(recorded.calls) == 2  # nothing new was requested
    # the cited retrieval time is the original fetch, not the cache read
    assert f"retrieved_at: {T0.isoformat()} (from cache)" in err

    code, _, err = run(capsys, recorded, "get", "statfin/vaerak/11ra.px", *filters, now=T0 + timedelta(hours=24))
    assert code == 0
    assert len(recorded.calls) == 4  # expired: metadata and data fetched again
    assert "(from cache)" not in err


@pytest.mark.parametrize(
    "broken",
    [
        "{not json",
        "[]",
        '"text"',
        json.dumps({"retrieved_at": T0.isoformat()}),  # no data
        json.dumps({"data": {}}),  # no retrieval time
        json.dumps({"data": {}, "retrieved_at": 1}),
        json.dumps({"data": {}, "retrieved_at": "2026-10-24T12:00:00"}),  # no time zone
    ],
)
def test_a_broken_cache_entry_is_fetched_again(recorded, project, broken):
    client = pxweb.Client(recorded, now=lambda: T0)
    pxweb.metadata("statfin/vaerak/11ra.px", client)
    (entry,) = (project / "cache" / "pxweb").glob("*.json")
    entry.write_text(broken, encoding="utf-8")
    meta = pxweb.metadata("statfin/vaerak/11ra.px", client)
    assert meta.response.from_cache is False
    assert len(recorded.calls) == 2
    assert json.loads(entry.read_text(encoding="utf-8"))["url"] == STATFIN_11RA
    assert pxweb.metadata("statfin/vaerak/11ra.px", client).response.from_cache is True


# ---------------------------------------------------------------- API wrapper


def test_every_database_url_is_a_citable_api_prefix():
    for api in pxweb.DATABASES.values():
        for lang in pxweb.LANGS:
            assert api.root(lang).startswith(API_URL_PREFIXES)


def test_swapping_the_api_changes_every_url(project, monkeypatch):
    seen = []

    def transport(method, url, body):
        seen.append(url)
        raise pxweb.PxWebError("offline")

    monkeypatch.setitem(pxweb.DATABASES, "statfin", pxweb.Api("https://pxdata.stat.fi/PxWeb/api/v2/{lang}/"))
    with pytest.raises(pxweb.PxWebError, match="offline"):
        pxweb.metadata("statfin/vaerak/11ra.px", pxweb.Client(transport, lang="en"))
    assert seen == ["https://pxdata.stat.fi/PxWeb/api/v2/en/vaerak/11ra.px"]


def test_meta_lists_variables_with_codes(capsys, recorded):
    code, out, err = run(capsys, recorded, "meta", "luke/maa/muuyri/0100_muuyri.px")
    assert code == 0
    assert "ELY-keskus (ELY), 17 values\n" in out
    assert "  ELY09\tPohjois-Karjala\n" in out
    assert "Vuosi (A), 5 values [time]" in out
    assert "request: GET https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/maa/muuyri/0100_muuyri.px" in err
    code, out, _ = run(capsys, recorded, "meta", "statfin/vaerak/11ra.px", "--json")
    variables = json.loads(out)["variables"]
    assert [v["code"] for v in variables] == ["alue_23_20260101", "contentscode", "timeperiod_y"]
    assert len(variables[0]["values"]) == 568
