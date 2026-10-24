"""The web app shell and runs dashboard (IF-601) on synthetic runs: rows, lineage, stage progress,
filters and the runs/ ↔ database mismatch banner. All values are invented for logic tests
(TICKETS.md plan note 14); nothing touches the network."""

import shutil
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from conftest import FIXTURES
from ideaforge import db, meta, runs
from ideaforge.schemas import RunMeta
from ideaforge.web import HOST, create_app, dashboard
from ideaforge.web.__main__ import main as web_main

STATUS_FIXTURES = FIXTURES / "status"
RUN_V1 = "20261023-110000-sauna-cabins"
RUN_V2 = "20261023-110000-sauna-cabins-v2"
RUN_BERRY = "20261024-090000-berry-drying"
RUN_DEBATING = "20261024-100000-lake-tours"
OPUS = {"orchestrator": "opus", "synthesizer": "opus"}


def make_run(run_id, idea, *, created, idea_id, version=1, parent=None, preset="standard", as_of=None,
             done=(), scores=None, report=False, usage=False):
    """A synthetic run: db rows (stages in `done` set to done), directory and meta.json."""
    db.init()
    db.create_run(run_id, idea, idea_id=idea_id, version=version, parent=parent, budget_preset=preset,
                  as_of=as_of, stages=runs.STAGES)
    with db.session() as conn:
        conn.execute("UPDATE runs SET created_at=? WHERE run_id=?", (created, run_id))
        conn.executemany("UPDATE stages SET status='done', attempts=1 WHERE run_id=? AND stage=?",
                         [(run_id, s) for s in done])
    run_dir = runs.create_run_dir(run_id, idea)
    meta.write(run_dir, RunMeta(
        run_id=run_id, idea_id=idea_id, version=version, parent_run_id=parent,
        created_at=datetime.fromisoformat(created), models=OPUS, budget_preset=preset,
    ))
    if scores:
        shutil.copy(STATUS_FIXTURES / scores, run_dir / "04_scores.json")
    if report:
        (run_dir / "05_report.md").write_text("# Synthetic report\n", encoding="utf-8")
    if usage:
        shutil.copy(STATUS_FIXTURES / "usage.synthetic.jsonl", run_dir / "usage.jsonl")
    return run_dir


@pytest.fixture
def runs_set(project):
    """Two versions of the sauna idea (v2 debated to the end), an unscored berry run stopped
    after intake, and a lake-tours run whose debate is under way."""
    make_run(RUN_V1, "Sauna-and-lake cabin rentals\nsecond line", created="2026-10-23T11:00:00+00:00",
             idea_id="sauna-cabins", done=runs.STAGES, scores="scores_v1.synthetic.json", report=True,
             usage=True)
    v2 = make_run(RUN_V2, "Sauna-and-lake cabin rentals, weekly stays", created="2026-10-24T11:00:00+00:00",
                  idea_id="sauna-cabins", version=2, parent=RUN_V1, preset="economy", as_of="2025-06-01",
                  done=runs.STAGES, scores="scores_v2.synthetic.json", report=True)
    (v2 / "debate" / "revised_plan.md").write_text("# Revised plan\n", encoding="utf-8")
    make_run(RUN_BERRY, "Berry drying service", created="2026-10-24T09:00:00+00:00", idea_id="berry-drying",
             done=["intake"])
    lake = make_run(RUN_DEBATING, "Guided lake tours", created="2026-10-24T10:00:00+00:00",
                    idea_id="lake-tours", done=runs.STAGES, report=True)
    (lake / "03_claims" / "verified.json").write_text("[]", encoding="utf-8")
    (lake / "debate" / "round0").mkdir()
    return project


@pytest.fixture
def client(runs_set):
    return TestClient(create_app(runs_set))


def by_id(rows):
    return {r.run_id: r for r in rows}


def test_rows_newest_first_with_every_field(runs_set):
    rows = dashboard.run_rows()
    assert [r.run_id for r in rows] == [RUN_V2, RUN_DEBATING, RUN_BERRY, RUN_V1]
    r = by_id(rows)
    v1, v2, berry, lake = r[RUN_V1], r[RUN_V2], r[RUN_BERRY], r[RUN_DEBATING]

    assert v1.title == "Sauna-and-lake cabin rentals"
    assert (v1.version, v1.parent, v1.idea_id) == (1, None, "sauna-cabins")
    assert (v2.version, v2.parent, v2.idea_id) == (2, RUN_V1, "sauna-cabins")
    assert (v1.verdict, v1.weighted_total) == ("NO_GO", 2.65)
    assert (v2.verdict, v2.weighted_total) == ("PIVOT", 2.95)
    assert (berry.verdict, berry.weighted_total) == (None, None)
    assert (v2.preset, v2.as_of) == ("economy", "2025-06-01")
    assert (v1.preset, v1.as_of) == ("standard", None)

    assert v1.debate == "not started"
    assert v2.debate == "done"
    assert berry.debate == "-"
    assert lake.debate == "next: evidence founder, investor, customer, accountant, operator"


def test_stage_progress_comes_from_the_stages_table(runs_set):
    r = by_id(dashboard.run_rows())
    total = len(runs.STAGES)
    assert (r[RUN_V1].stages_done, r[RUN_V1].stages_total) == (total, total)
    assert (r[RUN_BERRY].stages_done, r[RUN_BERRY].stages_total) == (1, total)
    assert r[RUN_BERRY].stage_line.startswith("intake done · plan pending · research: 11 pending")
    db.stage_set(RUN_BERRY, "plan", "running")
    db.stage_set(RUN_BERRY, "research:market", "insufficient_data")
    r = by_id(dashboard.run_rows())
    assert r[RUN_BERRY].stages_done == 2  # insufficient_data counts as complete, running does not
    assert "plan running" in r[RUN_BERRY].stage_line


def test_usage_totals_match_the_usage_report(runs_set):
    from ideaforge import usage

    v1 = by_id(dashboard.run_rows())[RUN_V1]
    expected = usage.summarize(RUN_V1, runs.run_dir(RUN_V1), db.stages(RUN_V1)).total
    assert v1.usage == expected and expected.calls > 0
    assert by_id(dashboard.run_rows())[RUN_BERRY].usage.calls == 0


def test_lineage_groups_versions_by_idea(runs_set):
    groups = dashboard.lineages(dashboard.run_rows())
    assert [g.idea_id for g in groups] == ["sauna-cabins", "lake-tours", "berry-drying"]
    assert [r.run_id for r in groups[0].runs] == [RUN_V2, RUN_V1]


def test_filters(runs_set):
    rows = dashboard.run_rows()
    assert [r.run_id for r in dashboard.filter_rows(rows, verdict="PIVOT")] == [RUN_V2]
    assert [r.run_id for r in dashboard.filter_rows(rows, verdict=dashboard.UNSCORED)] == [RUN_DEBATING, RUN_BERRY]
    assert [r.run_id for r in dashboard.filter_rows(rows, idea="sauna-cabins")] == [RUN_V2, RUN_V1]
    assert dashboard.filter_rows(rows, verdict="GO", idea="sauna-cabins") == []


def test_dashboard_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    for run_id in (RUN_V1, RUN_V2, RUN_BERRY, RUN_DEBATING):
        assert f'data-run="{run_id}"' in html
    assert 'data-idea="sauna-cabins"' in html and "2 version(s)" in html
    assert f"from <code>{RUN_V1}</code>" in html
    assert "NO_GO" in html and "2.65" in html and "PIVOT" in html and "2.95" in html
    assert "2025-06-01" in html and "economy" in html
    assert f"{len(runs.STAGES)}/{len(runs.STAGES)}" in html and f"1/{len(runs.STAGES)}" in html
    assert "4 of 4 run(s)" in html
    assert 'id="mismatch"' not in html
    # navigation for every section, the current one marked
    assert 'href="/" class="active"' in html and 'href="/jobs"' in html and 'href="/settings"' in html


def test_dashboard_filters_by_query(client):
    html = client.get("/", params={"verdict": "NO_GO"}).text
    assert f'data-run="{RUN_V1}"' in html and f'data-run="{RUN_V2}"' not in html
    assert "1 of 4 run(s)" in html
    html = client.get("/", params={"idea": "berry-drying"}).text
    assert f'data-run="{RUN_BERRY}"' in html and f'data-run="{RUN_V1}"' not in html
    html = client.get("/", params={"verdict": "GO"}).text
    assert "No run matches the filters." in html


def test_idea_text_is_escaped(project):
    make_run("20261024-120000-xss", "<script>alert(1)</script>", created="2026-10-24T12:00:00+00:00",
             idea_id="xss")
    html = TestClient(create_app(project)).get("/").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_mismatch_banner(runs_set):
    assert not dashboard.mismatch()
    runs.create_run_dir("20261025-080000-orphan-dir", "no row")
    (runs_set / "runs" / ".jobs").mkdir()  # not a run id: ignored
    shutil.rmtree(runs.run_dir(RUN_BERRY))
    m = dashboard.mismatch()
    assert m.dirs_without_row == ["20261025-080000-orphan-dir"]
    assert m.rows_without_dir == [RUN_BERRY]

    html = TestClient(create_app(runs_set)).get("/").text
    assert 'id="mismatch"' in html
    assert "<code>20261025-080000-orphan-dir</code>" in html
    assert f"<code>{RUN_BERRY}</code>" in html and "no directory" in html


def test_empty_project(project):
    html = TestClient(create_app(project)).get("/").text
    assert "No runs yet" in html and 'id="mismatch"' not in html


def test_broken_debate_files_show_an_error_instead_of_failing(runs_set):
    (runs.run_dir(RUN_DEBATING) / "03_claims" / "verified.json").unlink()
    lake = by_id(dashboard.run_rows())[RUN_DEBATING]
    assert lake.debate.startswith("error: ") and "verified.json does not exist" in lake.debate


def test_placeholders_and_static(client):
    for path, ticket in (("/jobs", "IF-607"), ("/settings", "IF-608")):
        resp = client.get(path)
        assert resp.status_code == 200 and ticket in resp.text
    css = client.get("/static/app.css")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]


def test_pages_load_nothing_from_the_network(client):
    for path in ("/", "/jobs", "/settings"):
        html = client.get(path).text
        assert "http://" not in html.replace("http://testserver", "") and "https://" not in html


def test_create_app_migrates_the_database(project):
    create_app(project)
    with db.session() as conn:
        assert db.schema_version(conn) == len(db.MIGRATIONS)


def test_create_app_refuses_another_root(project, tmp_path):
    with pytest.raises(ValueError, match="IDEAFORGE_ROOT"):
        create_app(tmp_path / "elsewhere")


def test_server_binds_to_localhost_only(project, monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append(kw))
    assert web_main([]) == 0
    assert web_main(["--port", "9001"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8765}, {"host": "127.0.0.1", "port": 9001}]
    assert HOST == "127.0.0.1"
