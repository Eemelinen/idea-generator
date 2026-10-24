"""IF-202 (absorbs IF-203): the Eurostat JSON-stat client on the recorded response (IF-200), never
the network. The fake transport answers only the recorded URL, so the client must build it itself.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from ideaforge import config
from ideaforge.fi import API_URL_PREFIXES, eurostat

FIXTURES = config.ROOT / "tests" / "fixtures" / "api" / "eurostat"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
META = json.loads((FIXTURES / "tour_occ_ninat_fi.meta.json").read_text(encoding="utf-8"))
DATA = json.loads((FIXTURES / "tour_occ_ninat_fi.json").read_text(encoding="utf-8"))
ARGV = (
    "get",
    "tour_occ_ninat",
    "--geo",
    "FI",
    "--filter",
    "unit=NR",
    "--filter",
    "c_resid=TOTAL",
    "--filter",
    "nace_r2=I551-I553",
    "--since",
    "2019",
)
# The recorded values, in time order (2019–2025).
NIGHTS = [23095660, 14323661, 17488715, 21971266, 22832061, 22678358, 23293003]


class Recorded:
    def __init__(self, responses=None):
        self.calls: list[str] = []
        self.responses = responses if responses is not None else {(META["method"], META["url"]): DATA}

    def __call__(self, method, url, body):
        self.calls.append(url)
        if (method, url) not in self.responses:
            raise AssertionError(f"not recorded: {method} {url}")
        return self.responses[(method, url)]


@pytest.fixture
def recorded(project):
    return Recorded()


def run(capsys, transport, *argv, now=T0):
    code = eurostat.main(list(argv), transport=transport, now=lambda: now)
    out, err = capsys.readouterr()
    return code, out, err


def test_get_returns_the_recorded_values_as_a_dataframe(recorded):
    filters = {"geo": ["FI"], "unit": ["NR"], "c_resid": ["TOTAL"], "nace_r2": ["I551-I553"]}
    result = eurostat.get("tour_occ_ninat", filters, eurostat.Client(recorded, now=lambda: T0), since="2019")
    assert recorded.calls == [META["url"]]
    assert result.response.url == META["url"]
    frame = result.frame
    assert list(frame["Time_code"]) == [str(y) for y in range(2019, 2026)]
    assert list(frame["value"]) == NIGHTS
    assert set(frame["Geopolitical entity (reporting)"]) == {"Finland"}
    assert set(frame["Geopolitical entity (reporting)_code"]) == {"FI"}
    assert set(frame["status"]) == {""}
    assert result.label == "Nights spent at tourist accommodation establishments"
    assert (result.source, result.updated) == ("ESTAT", "2026-10-12T23:00:00+0200")


def test_cli_prints_csv_and_the_exact_request(capsys, recorded):
    code, out, err = run(capsys, recorded, *ARGV)
    assert code == 0, err
    assert f"request: GET {META['url']}" in err
    assert f"retrieved_at: {T0.isoformat()}" in err
    assert "source: ESTAT; updated 2026-10-12T23:00:00+0200" in err
    lines = out.splitlines()
    assert lines[0].startswith("Time frequency,Time frequency_code,Country of residence,")
    assert lines[0].endswith(",Time,Time_code,value,status")
    assert len(lines) == 1 + len(NIGHTS)
    assert lines[1].endswith(",2019,2019,23095660,")


def test_json_has_rows_and_request(capsys, recorded):
    code, out, _ = run(capsys, recorded, *ARGV, "--json")
    assert code == 0
    data = json.loads(out)
    assert data["dataset"] == "tour_occ_ninat"
    assert data["request"]["url"] == META["url"]
    assert data["request"]["from_cache"] is False
    assert [r["value"] for r in data["rows"]] == NIGHTS
    assert data["rows"][0]["Time_code"] == "2019"


def test_missing_cells_and_status_flags(project):
    # Synthetic sparse dataset (not a recording) in the JSON-stat 2.0 shape Eurostat returns.
    synthetic = {
        "version": "2.0",
        "class": "dataset",
        "label": "synthetic",
        "id": ["geo", "time"],
        "size": [1, 3],
        "value": {"0": 1.5, "2": 2.5},
        "status": {"2": "p"},
        "dimension": {
            "geo": {"label": "geo", "category": {"index": {"FI": 0}, "label": {"FI": "Finland"}}},
            "time": {"label": "time", "category": {"index": {"2023": 0, "2024": 1, "2025": 2}}},
        },
    }
    url = eurostat.data_url("x_synthetic", {"geo": ["FI"]})
    result = eurostat.get("x_synthetic", {"geo": ["FI"]}, eurostat.Client(Recorded({("GET", url): synthetic})))
    assert list(result.frame["value"]) == [1.5, None, 2.5]
    assert list(result.frame["status"]) == ["", "", "p"]


def test_until_ends_the_series_on_the_recorded_live_answer(capsys, project):
    # IF-204: the live answer with untilTimePeriod, recorded next to the open-ended one.
    meta = json.loads((FIXTURES / "tour_occ_ninat_fi_2019_2022.meta.json").read_text(encoding="utf-8"))
    data = json.loads((FIXTURES / "tour_occ_ninat_fi_2019_2022.json").read_text(encoding="utf-8"))
    transport = Recorded({(meta["method"], meta["url"]): data})
    code, out, err = run(capsys, transport, *ARGV, "--until", "2022", "--json")
    assert code == 0, err
    assert transport.calls == [meta["url"]]
    assert [row["value"] for row in json.loads(out)["rows"]] == NIGHTS[:4]


def test_url_repeats_a_dimension_per_code_and_is_citable():
    url = eurostat.data_url("demo_r_pjangrp3", {"geo": ["FI", "FI1D"], "sex": ["T"]}, until="2024")
    assert url == (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/demo_r_pjangrp3"
        "?geo=FI&geo=FI1D&sex=T&untilTimePeriod=2024&lang=EN"
    )
    assert url.startswith(API_URL_PREFIXES)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["get", "tour occ", "--geo", "FI"], "must be a Eurostat dataset code"),
        (["get", "tour_occ_ninat", "--filter", "unit"], "<dimension>=<value>"),
    ],
)
def test_bad_input_exits_1_without_a_request(capsys, recorded, argv, message):
    code, out, err = run(capsys, recorded, *argv)
    assert (code, out) == (1, "")
    assert message in err
    assert recorded.calls == []


def test_an_error_body_is_reported_with_the_url(capsys, project):
    url = eurostat.data_url("nosuch", {"geo": ["FI"]})
    transport = Recorded({("GET", url): {"error": [{"status": 404, "label": "synthetic: dataset not found"}]}})
    code, _, err = run(capsys, transport, "get", "nosuch", "--geo", "FI")
    assert code == 1
    assert f"{url} did not return a JSON-stat dataset: synthetic: dataset not found" in err


def test_second_get_within_24_hours_is_a_cache_hit(capsys, recorded, project):
    _, first, _ = run(capsys, recorded, *ARGV)
    assert len(list((project / "cache" / "eurostat").glob("*.json"))) == 1
    code, second, err = run(capsys, recorded, *ARGV, now=T0 + timedelta(hours=23))
    assert (code, second) == (0, first)
    assert recorded.calls == [META["url"]]
    assert f"retrieved_at: {T0.isoformat()} (from cache)" in err
