"""IF-202: the PRH (YTJ v3) company search on the recorded responses (IF-200), never the network.

The fake transport answers only the exact requests that were recorded (method and URL from each
.meta.json), so a test passes only if the client builds those URLs itself.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from ideaforge import config
from ideaforge.fi import API_URL_PREFIXES, prh

FIXTURES = config.ROOT / "tests" / "fixtures" / "api" / "prh"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
INDUSTRY_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?mainBusinessLine=55&location=R%C3%A4%C3%A4kkyl%C3%A4"
NAME_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?name=R%C3%A4%C3%A4kkyl%C3%A4n"


class Recorded:
    """Replays tests/fixtures/api/prh; counts calls; fails on anything not recorded."""

    def __init__(self, extra=None):
        self.calls: list[str] = []
        self.responses = dict(extra or {})
        for meta_path in FIXTURES.glob("*.meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            data_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + ".json")
            self.responses[(meta["method"], meta["url"])] = json.loads(data_path.read_text(encoding="utf-8"))

    def __call__(self, method, url, body):
        self.calls.append(url)
        assert body is None
        if (method, url) not in self.responses:
            raise AssertionError(f"not recorded: {method} {url}")
        return self.responses[(method, url)]


@pytest.fixture
def recorded(project):
    return Recorded()


def run(capsys, transport, *argv, now=T0):
    code = prh.main(list(argv), transport=transport, now=lambda: now)
    out, err = capsys.readouterr()
    return code, out, err


def test_industry_and_municipality_search_prints_count_rows_and_url(capsys, recorded):
    code, out, err = run(capsys, recorded, "search", "--industry", "55", "--municipality", "Rääkkylä")
    assert code == 0, err
    assert recorded.calls == [INDUSTRY_URL]
    assert f"request: GET {INDUSTRY_URL}" in err
    assert f"retrieved_at: {T0.isoformat()}" in err
    lines = out.splitlines()
    assert lines[0] == "count: 1"
    assert lines[1] == ",".join(prh.COLUMNS)
    assert lines[2] == (
        "Joen Kukkatalo Oy,2597220-1,2014-02-14,Rekisterissä,,55100,Hotellit ja vastaava majoitustoiminta,Osakeyhtiö"
    )
    assert len(lines) == 3


def test_name_search_reports_the_total_and_that_only_a_page_is_shown(capsys, recorded):
    code, out, err = run(capsys, recorded, "search", "--name", "Rääkkylän")
    assert code == 0, err
    assert recorded.calls == [NAME_URL]
    lines = out.splitlines()
    assert lines[0] == "count: 54"  # totalResults as returned; the recording keeps 10 rows
    assert len(lines) == 2 + 10
    assert "note: 10 of 54 companies shown (page 1); --page 2 for more" in err


def test_rows_carry_current_name_status_and_end_date(recorded):
    result = prh.search(prh.Criteria(name="Rääkkylän"), prh.Client(recorded, now=lambda: T0))
    by_id = {c.business_id: c for c in result.companies}
    ceased = by_id["0429211-9"]
    assert ceased.name == "Rääkkylän Kiinteistötoimisto Ky"
    assert (ceased.status, ceased.end_date, ceased.registration_date) == ("Lakannut", "2018-11-26", "1989-03-08")
    assert ceased.company_form == "Kommandiittiyhtiö"
    renamed = next(c for c in result.companies if "Vuokratalot" in c.name)
    assert renamed.name == "Kiinteistö Oy Rääkkylän Vuokratalot"  # not the earlier name that has an end date
    assert {c.status for c in result.companies} == {"Rekisterissä", "Lakannut"}


def test_lang_picks_the_description_language(capsys, recorded):
    code, out, _ = run(capsys, recorded, "--lang", "en", "search", "--industry", "55", "--municipality", "Rääkkylä")
    assert code == 0
    assert out.splitlines()[2].endswith(",Registered,,55100,Hotels and similar accommodation,Limited company")


def test_json_has_count_request_and_companies(capsys, recorded):
    code, out, _ = run(capsys, recorded, "search", "--industry", "55", "--municipality", "Rääkkylä", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["count"] == 1
    assert data["request"] == {
        "method": "GET",
        "url": INDUSTRY_URL,
        "query": None,
        "retrieved_at": T0.isoformat(),
        "from_cache": False,
    }
    assert data["criteria"]["industry"] == "55"
    assert data["companies"][0]["business_id"] == "2597220-1"
    assert data["notes"] == []


def test_a_tol_2008_code_that_finds_nothing_gets_a_prefix_hint(capsys, project):
    # Synthetic empty answer (not a recording): IF-200 found that 55201 matches nothing since TOL 2025.
    url = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?mainBusinessLine=55201&location=R%C3%A4%C3%A4kkyl%C3%A4"
    transport = Recorded({("GET", url): {"totalResults": 0, "companies": []}})
    code, out, err = run(capsys, transport, "search", "--industry", "55201", "--municipality", "Rääkkylä")
    assert code == 0
    assert out == "count: 0\n"
    assert f"request: GET {url}" in err
    assert "TOL 2025" in err and "--industry 55" in err


def test_registration_dates_and_page_build_the_url():
    url = prh.search_url(
        prh.Criteria(industry="56.1", registered_from="2020-01-01", registered_to="2024-12-31", page=2)
    )
    assert url == (
        "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?mainBusinessLine=561"
        "&registrationDateStart=2020-01-01&registrationDateEnd=2024-12-31&page=2"
    )
    assert url.startswith(API_URL_PREFIXES)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ([], "give at least one of"),
        (["--industry", "hotels"], "must be a TOL code"),
        (["--registered-from", "2020-13-01"], "must be a date YYYY-MM-DD"),
        (["--name", "x", "--page", "0"], "--page must be 1 or more"),
    ],
)
def test_bad_criteria_exit_1_without_a_request(capsys, recorded, argv, message):
    code, out, err = run(capsys, recorded, "search", *argv)
    assert (code, out) == (1, "")
    assert message in err
    assert recorded.calls == []


def test_an_unexpected_response_is_an_error_naming_the_url(capsys, project):
    transport = Recorded()
    transport.responses[("GET", NAME_URL)] = {"message": "synthetic error body"}
    code, _, err = run(capsys, transport, "search", "--name", "Rääkkylän")
    assert code == 1
    assert f"{NAME_URL} did not return a company list" in err


def test_second_search_within_24_hours_is_a_cache_hit(capsys, recorded, project):
    argv = ("search", "--industry", "55", "--municipality", "Rääkkylä")
    _, first, _ = run(capsys, recorded, *argv)
    assert len(list((project / "cache" / "prh").glob("*.json"))) == 1
    code, second, err = run(capsys, recorded, *argv, now=T0 + timedelta(hours=23))
    assert (code, second) == (0, first)
    assert len(recorded.calls) == 1
    assert f"retrieved_at: {T0.isoformat()} (from cache)" in err
    run(capsys, recorded, *argv, now=T0 + timedelta(hours=24))
    assert len(recorded.calls) == 2
