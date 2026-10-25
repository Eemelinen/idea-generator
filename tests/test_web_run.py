"""The run page (IF-605) on synthetic runs: every tab on a finished run and on a run stopped after
stage 3, the claim filters, the claims-table fallback, report escaping and the read-only file
browser's refusals. The run files are the score_run / report fixtures (synthetic, TICKETS.md plan
note 14) plus synthetic markers, conflicts and plan; nothing touches the network."""

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import PurePosixPath

import pytest
import score_run
from conftest import FIXTURES, SYNTHETIC_RUN
from fastapi.testclient import TestClient

from ideaforge import db, debate, report, runs, usage
from ideaforge.schemas import KILL_TRIGGERS
from ideaforge.synthesis import load_claims, load_scores
from ideaforge.web import create_app, run_detail
from ideaforge.web.run_detail import ClaimFilters, NotFound

FINISHED = "20261023-130000-sauna-cabins"
STOPPED = "20261023-150000-berry-drying"
NOW = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
TABS = ("", "/idea", "/claims", "/scores", "/economics", "/report", "/debate", "/review", "/usage", "/files")
CONFLICT = ["market-003", "market-004"]


def make_run(run_id, idea, done):
    """A run with spec, plan, research files, verified claims, conflicts, markers and usage;
    the stages in `done` are marked done, the rest stay pending."""
    db.init()
    run_dir = runs.create_run_dir(run_id, idea)
    db.create_run(run_id, idea, idea_id=run_id[16:], stages=runs.STAGES)
    with db.session() as conn:
        conn.executemany(
            "UPDATE stages SET status='done', attempts=1, started_at='2026-10-23T10:00:00+00:00',"
            " finished_at='2026-10-23T10:05:00+00:00' WHERE run_id=? AND stage=?",
            [(run_id, s) for s in done],
        )
    shutil.copy(FIXTURES / "spec.json", run_dir / "00_spec.json")
    plan = json.loads((FIXTURES / "plan.json").read_text(encoding="utf-8"))
    plan["run_id"] = run_id
    (run_dir / "01_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    for md in (FIXTURES / "report" / "02_research").iterdir():
        shutil.copy(md, run_dir / "02_research" / md.name)
    claims = json.loads((FIXTURES / "score_run" / "verified.synthetic.json").read_text(encoding="utf-8"))
    claims += json.loads((FIXTURES / "report" / "extra_claims.synthetic.json").read_text(encoding="utf-8"))
    (run_dir / "03_claims" / "verified.json").write_text(json.dumps(claims), encoding="utf-8")
    (run_dir / "03_claims" / "conflicts.json").write_text(
        json.dumps([{"dimension": "market", "claim_ids": CONFLICT}]), encoding="utf-8"
    )
    shutil.copy(FIXTURES / "status" / "usage.synthetic.jsonl", run_dir / "usage.jsonl")
    (run_dir / "VALIDATION_WARNINGS_research-market").write_text(
        "no [src: …] on: 'Demand peaks in July.'\nno [src: …] on: 'Most guests drive.'\n", encoding="utf-8"
    )
    (run_dir / "BUDGET_EXCEEDED_research-pricing").write_text("WebSearch: 9 > 8\n", encoding="utf-8")
    return run_dir


@pytest.fixture
def finished(project):
    run_dir = make_run(FINISHED, "Sauna-and-lake cabins for remote workers", runs.STAGES)
    shutil.copy(FIXTURES / "score_run" / "04_scores_proposed.synthetic.json", run_dir / "04_scores_proposed.json")
    shutil.copy(FIXTURES / "score_run" / "04_risks.synthetic.json", run_dir / "04_risks.json")
    assert score_run.main([FINISHED]) == 0
    report.render(FINISHED, now=NOW)
    return run_dir


@pytest.fixture
def stopped(project):
    done = [s for s in runs.STAGES if runs.STAGES.index(s) <= runs.STAGES.index("verify")]
    return make_run(STOPPED, "Berry drying service", done)


@pytest.fixture
def client(project):
    return TestClient(create_app(project))


def rows(html, attr):
    return re.findall(rf'{attr}="([^"]+)"', html)


# ---------------------------------------------------------------- every tab


def test_every_tab_answers_on_both_runs(finished, stopped, client):
    for run_id in (FINISHED, STOPPED):
        for suffix in TABS:
            resp = client.get(f"/runs/{run_id}{suffix}")
            assert resp.status_code == 200, (run_id, suffix)
            assert f"<code>{run_id}</code>" in resp.text
            assert "not in the database" not in resp.text


def test_stages_tab(finished, client):
    html = client.get(f"/runs/{FINISHED}").text
    assert rows(html, "data-stage") == runs.STAGES
    assert "2026-10-23 10:00:00" in html and "2026-10-23 10:05:00" in html
    # both markers with every line of their contents
    assert rows(html, "data-marker") == ["BUDGET_EXCEEDED_research-pricing", "VALIDATION_WARNINGS_research-market"]
    assert "WebSearch: 9 &gt; 8" in html
    assert "Demand peaks in July." in html and "Most guests drive." in html


def test_stages_tab_of_a_running_stage_and_a_failed_marker(synthetic_run, client):
    html = client.get(f"/runs/{SYNTHETIC_RUN}").text
    killcause = re.search(r'data-stage="research:killcause">(.*?)</tr>', html, re.S).group(1)
    assert "running" in killcause and "<td>-</td>" in killcause  # an old finished_at is hidden
    assert "VALIDATION_FAILED_research-gtm" in html and "about 40 cabins" in html


def test_idea_tab(finished, client):
    html = client.get(f"/runs/{FINISHED}/idea").text
    assert "Sauna-and-lake cabins for remote workers" in html
    assert "Do you already own the cabins?" in html and "One cabin is owned" in html
    # the fixture spec predates the scope fields (IF-701): it shows as Rääkkylä / local
    assert "<dt>Business mode</dt><dd>local</dd>" in html
    assert "Rääkkylä (KU707), North Karelia (MK12) · nearby: Joensuu, Kitee" in html and "Leader group: Jetina" in html
    assert "<dt>Target markets</dt><dd>Rääkkylä → North Karelia → Finland → online</dd>" in html
    plan = json.loads((FIXTURES / "plan.json").read_text(encoding="utf-8"))
    assert rows(html, "data-dimension") == [d["dimension"] for d in plan["dimensions"]]
    assert plan["dimensions"][0]["questions"][0] in html


def test_claims_tab_lists_the_ledger_and_conflict_groups(finished, client):
    html = client.get(f"/runs/{FINISHED}/claims").text
    ledger = load_claims(finished)
    assert rows(html, "data-claim") == [c.claim_id for c in ledger]
    assert "From <code>03_claims/verified.json</code>" in html
    first = ledger[0]
    assert f'href="{first.source_url}"' in html and first.quote in html
    conflict = html.split("Conflict groups", 1)[1]
    assert f'href="/runs/{FINISHED}/claims#claim-{CONFLICT[0]}"' in conflict
    assert conflict.index(CONFLICT[0]) < conflict.index('<span class="tag">preferred</span>') < conflict.index(CONFLICT[1])


def test_scores_tab(finished, client):
    sheet = load_scores(finished)
    html = client.get(f"/runs/{FINISHED}/scores").text
    assert f'id="verdict">{sheet.verdict}<' in html
    assert f'id="weighted-total">{sheet.weighted_total:.2f}<' in html
    assert rows(html, "data-dimension") == [s.dimension for s in sheet.scores]
    capped = [s for s in sheet.scores if s.cap_reason]
    assert capped and capped[0].cap_reason in html
    cited = next(s for s in sheet.scores if s.supporting_claim_ids)
    assert f'href="/runs/{FINISHED}/claims#claim-{cited.supporting_claim_ids[0]}"' in html
    assert rows(html, "data-trigger") == list(KILL_TRIGGERS)
    assert "killcause-002 (unverified)" in html  # flagged but not counted


def test_fired_and_overridden_kill_triggers(finished, client):
    data = json.loads((finished / "04_scores.json").read_text(encoding="utf-8"))
    data["kill_triggers_fired"] = ["no_evidence_anyone_pays"]
    (finished / "04_scores.json").write_text(json.dumps(data), encoding="utf-8")
    spec = json.loads((finished / "00_spec.json").read_text(encoding="utf-8"))
    spec["kill_trigger_overrides"] = ["permit_impossible"]
    (finished / "00_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    html = client.get(f"/runs/{FINISHED}/scores").text
    assert 'data-trigger="no_evidence_anyone_pays" class="fired"' in html
    assert "Overrides in <code>00_spec.json</code>: permit_impossible." in html
    assert "not fired (overridden in the spec)" in html


def test_economics_tab(finished, client):
    ue = load_scores(finished).unit_economics
    html = client.get(f"/runs/{FINISHED}/economics").text
    for label, value in report.economics_rows(load_scores(finished)):
        assert f"<th>{label}</th><td>{value}</td>" in html
    if ue.sensitivity:
        assert 'class="grid sensitivity"' in html
    else:
        assert "No sensitivity table" in html
    for m in ue.missing_inputs:
        assert m in html
    for role, ids in ue.input_claims.items():
        assert f'data-role="{role}"' in html
        for cid in ids:
            assert f"#claim-{cid}" in html


def test_report_tab_renders_markdown_with_a_download(finished, client):
    html = client.get(f"/runs/{FINISHED}/report").text
    assert f'href="/runs/{FINISHED}/raw/05_report.md"' in html
    assert "<h1>" in html and "<table>" in html
    raw = client.get(f"/runs/{FINISHED}/raw/05_report.md")
    assert raw.status_code == 200
    assert raw.content == (finished / "05_report.md").read_bytes()
    assert "attachment" in raw.headers["content-disposition"]


def test_report_html_is_escaped(finished, project):
    path = finished / "05_report.md"
    path.chmod(0o644)
    path.write_text("# R\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n", encoding="utf-8")
    html = TestClient(create_app(project)).get(f"/runs/{FINISHED}/report").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert 'href="javascript:' not in html


def test_usage_tab_matches_the_usage_report(finished, client):
    summary = usage.summarize(FINISHED, finished, db.stages(FINISHED))
    t = summary.total
    html = client.get(f"/runs/{FINISHED}/usage").text
    assert f"{t.calls} tool calls, {t.searches} searches, {t.fetches} fetches, ~{t.tokens} tokens" in html
    stage_table = html.split('data-by="stage"', 1)[1].split("</table>", 1)[0]
    agent_table = html.split('data-by="agent"', 1)[1].split("</table>", 1)[0]
    assert re.findall(r"<td><code>([^<]+)</code></td>", stage_table) == [n for n, _ in usage.ordered("stage", summary.by_stage)]
    assert re.findall(r"<td><code>([^<]+)</code></td>", agent_table) == [n for n, _ in usage.ordered("agent", summary.by_agent)]
    assert "BUDGET_EXCEEDED_research-pricing" in html


def test_files_tab_lists_every_file(finished, client):
    html = client.get(f"/runs/{FINISHED}/files").text
    expected = sorted(p.relative_to(finished).as_posix() for p in finished.rglob("*") if p.is_file())
    assert rows(html, "data-path") == expected
    assert "05_report.md" in expected and "03_claims/verified.json" in expected
    view = client.get(f"/runs/{FINISHED}/files/03_claims/conflicts.json")
    assert view.status_code == 200 and "market-003" in view.text


# ---------------------------------------------------------------- a run stopped after stage 3


def test_tabs_of_later_stages_say_they_have_not_run(stopped, client):
    for suffix, path in (("/scores", "04_scores.json"), ("/economics", "04_scores.json"), ("/report", "05_report.md")):
        html = client.get(f"/runs/{STOPPED}{suffix}").text
        assert "has not run yet (status: pending)" in html and f"<code>{path}</code> does not exist" in html
    html = client.get(f"/runs/{STOPPED}/claims").text
    assert len(rows(html, "data-claim")) == len(load_claims(stopped))
    stages = client.get(f"/runs/{STOPPED}").text
    assert re.search(r'data-stage="verify">.*?status-done', stages, re.S)
    assert re.search(r'data-stage="synthesize">.*?status-pending', stages, re.S)


def test_a_run_before_intake(project, client):
    db.init()
    run_id = "20261024-080000-empty-run"
    runs.create_run_dir(run_id, "Empty run")
    db.create_run(run_id, "Empty run", idea_id="empty-run", stages=runs.STAGES)
    html = client.get(f"/runs/{run_id}/idea").text
    assert "Stage <code>intake</code> has not run yet" in html and "Empty run" in html
    html = client.get(f"/runs/{run_id}/claims").text
    assert "Stage <code>verify</code> has not run yet" in html
    assert "No tool calls logged yet." in client.get(f"/runs/{run_id}/usage").text


def test_invalid_files_show_an_error_instead_of_failing(finished, client):
    (finished / "04_scores.json").write_text("{not json", encoding="utf-8")
    (finished / "01_plan.json").write_text('{"run_id": "x"}', encoding="utf-8")
    (finished / "03_claims" / "conflicts.json").write_text("[{}]", encoding="utf-8")
    for suffix in ("/scores", "/economics", "/idea", "/claims"):
        resp = client.get(f"/runs/{FINISHED}{suffix}")
        assert resp.status_code == 200 and "Invalid file." in resp.text, suffix


def test_claims_fall_back_to_the_claims_table(synthetic_run, client):
    html = client.get(f"/runs/{SYNTHETIC_RUN}/claims").text
    assert "From <code>the claims table</code>" in html
    assert len(rows(html, "data-claim")) == 9


# ---------------------------------------------------------------- claim filters


def test_claim_filters(finished):
    claims = load_claims(finished)
    by = lambda **kw: [c.claim_id for c in run_detail.filter_claims(claims, ClaimFilters(**kw))]  # noqa: E731
    assert by(dimension="market") == ["market-001", "market-002", "market-003", "market-004"]
    assert by(verification="conflict") == ["market-004", "gtm-004"]
    assert by(verification="unverified") == ["customer-004", "killcause-002", "financing-005"]
    assert by(source_type="official", dimension="regulation") == ["regulation-001", "regulation-004"]
    assert by(flag="unfetchable") == ["customer-004", "financing-005"]
    assert by(flag="permit_impossible", verification="verified") == []
    assert by() == [c.claim_id for c in claims]


def test_claim_filters_over_http(finished, client):
    url = f"/runs/{FINISHED}/claims"
    html = client.get(url, params={"dimension": "killcause"}).text
    assert rows(html, "data-claim") == ["killcause-001", "killcause-002"]
    assert '<option value="killcause" selected>' in html and f"2 of {len(load_claims(finished))} claim(s)" in html
    html = client.get(url, params={"verification": "pending", "source_type": "news"}).text
    assert rows(html, "data-claim") == ["competition-004"]
    html = client.get(url, params={"flag": "unfetchable", "source_type": "official"}).text
    assert rows(html, "data-claim") == ["financing-005"]
    html = client.get(url, params={"dimension": "location", "verification": "conflict"}).text
    assert rows(html, "data-claim") == [] and "No claim matches the filters." in html


def test_link_claims_escapes_and_links_only_known_ids():
    html = run_detail.link_claims("<b>see</b> market-001 and gtm-999", "R", {"market-001"})
    assert str(html) == '&lt;b&gt;see&lt;/b&gt; <a href="/runs/R/claims#claim-market-001">market-001</a> and gtm-999'


# ---------------------------------------------------------------- file browser refusals


@pytest.mark.parametrize("path", [
    "../" + FINISHED + "/idea.md",
    "03_claims/../../other/idea.md",
    "..",
    "/etc/passwd",
    "C:/Windows/win.ini",
    "03_claims\\verified.json",
    "./idea.md",
    "03_claims//verified.json",
    "03_claims",
    "missing.json",
])
def test_safe_file_refuses(finished, path):
    with pytest.raises(NotFound):
        run_detail.safe_file(finished, path)


def test_browser_refuses_traversal_and_absolute_paths_over_http(finished, project, client):
    (project / "secret.txt").write_text("outside", encoding="utf-8")
    for path in (
        f"/runs/{FINISHED}/files/%2e%2e/%2e%2e/secret.txt",
        f"/runs/{FINISHED}/files/..%2F..%2Fsecret.txt",
        f"/runs/{FINISHED}/files/%2Fetc%2Fpasswd",
        f"/runs/{FINISHED}/files//etc/passwd",
        f"/runs/{FINISHED}/raw/%2e%2e/%2e%2e/secret.txt",
        f"/runs/{FINISHED}/raw/%2Fetc%2Fpasswd",
    ):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert "outside" not in resp.text and "root:" not in resp.text


def test_browser_refuses_symlinks(finished, project, client):
    (project / "secret.txt").write_text("outside", encoding="utf-8")
    (finished / "link.txt").symlink_to(project / "secret.txt")
    (finished / "inner.txt").symlink_to(finished / "idea.md")  # even one that stays inside
    (finished / "linked_dir").symlink_to(project, target_is_directory=True)
    for path in ("link.txt", "inner.txt", "linked_dir/secret.txt"):
        for kind in ("files", "raw"):
            resp = client.get(f"/runs/{FINISHED}/{kind}/{path}")
            assert resp.status_code == 404, (kind, path)
            assert "outside" not in resp.text
    listed = rows(client.get(f"/runs/{FINISHED}/files").text, "data-path")
    assert not {"link.txt", "inner.txt"} & set(listed)
    assert not any(p.startswith("linked_dir/") for p in listed)


def test_debate_mapping_is_withheld_until_the_verdict(finished, client):
    d = finished / "debate"
    (d / debate.MAPPING_NAME).write_text('{"founder": "P1"}', encoding="utf-8")
    assert run_detail.withheld(finished, PurePosixPath("debate", debate.MAPPING_NAME))
    assert client.get(f"/runs/{FINISHED}/files/debate/{debate.MAPPING_NAME}").status_code == 404
    assert f"debate/{debate.MAPPING_NAME}" not in client.get(f"/runs/{FINISHED}/files").text
    (d / debate.VERDICT_NAME).write_text("{}", encoding="utf-8")
    assert client.get(f"/runs/{FINISHED}/files/debate/{debate.MAPPING_NAME}").status_code == 200


def test_viewer_does_not_show_binary_files(finished, client):
    (finished / "blob.bin").write_bytes(b"\xff\xfe\x00binary")
    html = client.get(f"/runs/{FINISHED}/files/blob.bin").text
    assert "not UTF-8 text" in html
    raw = client.get(f"/runs/{FINISHED}/raw/blob.bin")
    assert raw.content == b"\xff\xfe\x00binary" and raw.headers["content-type"] == "application/octet-stream"


# ---------------------------------------------------------------- unknown runs and navigation


def test_unknown_and_invalid_runs_are_404(project, client):
    assert client.get("/runs/20261024-000000-nothing-here").status_code == 404
    assert client.get("/runs/not-a-run-id").status_code == 404
    assert client.get("/runs/not-a-run-id/files/idea.md").status_code == 404


def test_run_without_a_directory(project, client):
    db.init()
    run_id = "20261024-070000-no-dir"
    db.create_run(run_id, "No directory", idea_id="no-dir", stages=runs.STAGES)
    for suffix in TABS:
        resp = client.get(f"/runs/{run_id}{suffix}")
        assert resp.status_code == 200 and "no run directory" in resp.text, suffix


def test_dashboard_links_to_the_run_page(finished, client):
    assert f'href="/runs/{FINISHED}"' in client.get("/").text
    html = client.get(f"/runs/{FINISHED}/claims").text
    assert f'href="/runs/{FINISHED}/claims" class="active"' in html


def test_run_pages_load_nothing_from_the_network(finished, client):
    for suffix in TABS:
        html = client.get(f"/runs/{FINISHED}{suffix}").text.replace("http://testserver/", "/")
        # source links are fine; nothing the browser loads by itself may be remote
        assert not re.search(r'<(script|img|link|iframe)[^>]+(src|href)="https?://', html), suffix
