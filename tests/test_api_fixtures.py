"""IF-200: the recorded API fixtures parse, carry their meta file and cite an allow-listed URL."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from ideaforge import config, verify
from ideaforge.fi import API_URL_PREFIXES

FIXTURES = config.ROOT / "tests" / "fixtures" / "api"
RESPONSES = sorted(p for p in FIXTURES.glob("*/*.json") if not p.name.endswith(".meta.json"))
META_KEYS = {"url", "method", "request", "status", "retrieved_at"}


def _meta(path: Path) -> dict:
    return json.loads(path.with_name(path.stem + ".meta.json").read_text(encoding="utf-8"))


def test_every_source_is_recorded():
    assert {p.parent.name for p in RESPONSES} == {"statfin", "luke", "prh", "eurostat"}


def test_every_meta_file_has_its_response():
    for meta in FIXTURES.glob("*/*.meta.json"):
        assert meta.with_name(meta.name.removesuffix(".meta.json") + ".json").exists(), meta


@pytest.mark.parametrize("path", RESPONSES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_fixture_parses_and_names_its_request(path):
    json.loads(path.read_text(encoding="utf-8"))
    meta = _meta(path)
    assert META_KEYS <= meta.keys()
    assert meta["status"] == 200
    assert meta["method"] == ("GET" if meta["request"] is None else "POST")
    datetime.fromisoformat(meta["retrieved_at"])
    assert verify.is_official(meta["url"]), meta["url"]
    assert meta["url"].startswith(API_URL_PREFIXES), meta["url"]


def test_trimmed_listings_say_so():
    for path in FIXTURES.glob("prh/*.json"):
        if path.name.endswith(".meta.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if len(data["companies"]) < data["totalResults"]:
            assert "trimmed" in _meta(path), path


def test_fixtures_stay_under_one_megabyte():
    assert sum(p.stat().st_size for p in FIXTURES.rglob("*.json")) < 1024 * 1024
