"""The scope lines of the research and debate briefs (IF-702).

The specs are tests/fixtures/spec.json (written before D-009, so it loads the schema's default
scope) with the scope fields changed. The changed values are synthetic: "Testikylä" and
"Testimaakunta" are invented places without Statistics Finland codes (TICKETS.md plan note 14).
"""

import json
from pathlib import Path

import pytest

from ideaforge import brief, runs
from ideaforge.schemas import IdeaSpec

FIXTURES = Path(__file__).parent / "fixtures"
SPEC = json.loads((FIXTURES / "spec.json").read_text(encoding="utf-8"))
SYNTHETIC_BASE = {"municipality": "Testikylä", "region": "Testimaakunta"}


def write_spec(run_dir: Path, **changes) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    spec = IdeaSpec.model_validate(SPEC | changes)
    (run_dir / "00_spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    return run_dir


def test_online_scope_names_the_base_with_codes_and_the_markets(tmp_path):
    lines = brief.scope_lines(write_spec(tmp_path, business_mode="online", geography=["Finland", "EU"]))
    assert lines == [
        "Scope: online business. Base: Rääkkylä (KU707), North Karelia (MK12); nearby: Joensuu, Kitee."
        " Target markets, nearest first: Finland → EU.",
        "The base's official sites raakkyla.fi, luotsipohjoiskarjala.fi; Leader group Jetina (jetina.fi).",
        brief.MODE_GUIDANCE["online"],
    ]
    assert 'follow the "Online or hybrid:" steps, skip the "Local or hybrid:" ones' in lines[-1]
    assert "logistics, costs, registration and funding" in lines[-1]


def test_local_scope_is_the_default_for_a_spec_written_before_the_scope_fields(tmp_path):
    lines = brief.scope_lines(write_spec(tmp_path))
    assert lines[0] == (
        "Scope: local business. Base: Rääkkylä (KU707), North Karelia (MK12); nearby: Joensuu, Kitee."
        " Target markets, nearest first: Rääkkylä → North Karelia → Finland → online."
    )
    assert lines[-1] == brief.MODE_GUIDANCE["local"]
    assert 'follow the "Local or hybrid:" steps and skip the "Online or hybrid:" ones' in lines[-1]


def test_hybrid_scope_without_codes_or_sources_says_how_to_find_the_codes(tmp_path):
    run_dir = write_spec(
        tmp_path, business_mode="hybrid", base_location=SYNTHETIC_BASE, geography=["Testikylä", "Finland"]
    )
    assert brief.scope_lines(run_dir) == [
        "Scope: hybrid business. Base: Testikylä, Testimaakunta. Target markets, nearest first: Testikylä → Finland.",
        "The spec gives no Statistics Finland municipality or region code: find it with `pxweb meta`"
        " before filtering `Alue=`; never guess a code.",
        brief.MODE_GUIDANCE["hybrid"],
    ]
    assert '"Local or hybrid:" and the "Online or hybrid:" steps' in brief.MODE_GUIDANCE["hybrid"]


def test_one_missing_code_and_a_leader_group_alone(tmp_path):
    base = SYNTHETIC_BASE | {"region_code": "MK12", "leader_group": {"name": "Testi-Leader", "domain": "testi.example"}}
    lines = brief.scope_lines(write_spec(tmp_path, base_location=base))
    assert lines[0].startswith("Scope: local business. Base: Testikylä, Testimaakunta (MK12). ")
    assert lines[1] == "The base's Leader group Testi-Leader (testi.example)."
    assert lines[2].startswith("The spec gives no Statistics Finland municipality code:")


def test_every_mode_has_guidance():
    assert set(brief.MODE_GUIDANCE) == {"online", "local", "hybrid"}


def test_missing_or_invalid_spec_is_an_error(tmp_path):
    with pytest.raises(brief.BriefError, match="finish stage 0"):
        brief.scope_lines(tmp_path)
    (tmp_path / "00_spec.json").write_text('{"title": "half a spec"}', encoding="utf-8")
    with pytest.raises(brief.BriefError, match="not a valid IdeaSpec"):
        brief.scope_lines(tmp_path)


def new_run(project, **changes) -> str:
    import new_run as script

    assert script.main(["sauna cabins by the lake"]) == 0
    run_id = runs.active_run_id()
    write_spec(project / "runs" / run_id, **changes)
    return run_id


def test_research_brief_puts_the_scope_lines_before_the_budget_line(project, capsys):
    import research_brief

    run_id = new_run(project, business_mode="online", geography=["Finland", "EU"])
    capsys.readouterr()
    assert research_brief.main([run_id, "market"]) == 0
    lines = capsys.readouterr().out.splitlines()
    scope = brief.scope_lines(runs.run_dir(run_id))
    assert lines[: len(scope)] == scope and len(lines) == len(scope) + 1
    assert lines[-1].startswith("Budget (preset ")
    assert brief.brief_lines(run_id, "killcause")[: len(scope)] == scope


def test_research_brief_scope_prints_the_scope_lines_alone(project, capsys):
    import research_brief

    run_id = new_run(project, business_mode="hybrid")
    capsys.readouterr()
    assert research_brief.main([run_id, "--scope"]) == 0
    assert capsys.readouterr().out.splitlines() == brief.scope_lines(runs.run_dir(run_id))
    for argv in ([run_id], [run_id, "market", "--scope"]):
        with pytest.raises(SystemExit) as e:
            research_brief.main(argv)
        assert e.value.code == 2


def test_research_brief_without_a_spec_exits_1(project, capsys):
    import new_run as script
    import research_brief

    assert script.main(["sauna cabins by the lake"]) == 0
    run_id = runs.active_run_id()
    capsys.readouterr()
    assert research_brief.main([run_id, "market"]) == 1
    assert research_brief.main([run_id, "--scope"]) == 1
    assert "finish stage 0" in capsys.readouterr().err
