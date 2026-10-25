"""Pipeline control from the UI (IF-607): the new-idea and new-version forms, run actions by run
state, the eval action, the jobs page with cancel and retry, the log tail, the dev-marker banner
and the server's background worker. `claude` is the fake binary of tests/test_jobs.py
(IDEAFORGE_CLAUDE_BIN); the runs are the synthetic runs of tests/test_web_run.py and the idea
texts and answers are synthetic (TICKETS.md plan note 14). Nothing touches the network."""

import json
import shutil
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from test_jobs import fake_claude, modes, wait_for  # noqa: F401 — fake_claude is a fixture
from test_web_run import FINISHED, STOPPED, finished, stopped  # noqa: F401 — fixtures

from ideaforge import config, db, jobs, runs
from ideaforge.schemas import KILL_TRIGGERS, Intake
from ideaforge.web import control, create_app, foreign_request

LOCAL = "http://127.0.0.1:8765"
FRESH = "20261024-120000-lake-tours"
IDEA = "Guided lake tours by electric boat (synthetic)"


def form(**overrides) -> dict:
    """A valid new-idea form, as the browser posts it."""
    fields = {
        "idea": IDEA,
        "goal": "side_income",
        "capital_eur": "3 000,50",
        "hours_per_week": "15",
        "skills": "\n".join(config.founder().skills),
        "geography": "Rääkkylä\nNorth Karelia",
        "business_mode": "local",
        "municipality": "Rääkkylä",
        "municipality_code": "KU707",
        "region": "North Karelia",
        "region_code": "MK12",
        "nearby": "Joensuu\nKitee",
        "official_domains": "raakkyla.fi",
        "leader_name": "Jetina",
        "leader_domain": "jetina.fi",
        "preset": "economy",
        "as_of": "",
        "question_1": "Who pays?",
        "answer_1": "Summer visitors from Joensuu (synthetic)",
        "run_to": "validate",
    }
    return fields | overrides


@pytest.fixture
def client(fake_claude, project):  # noqa: F811
    return TestClient(create_app(project), base_url=LOCAL)


def queue() -> list[tuple]:
    return [(r["job_id"], r["kind"], r["run_id"], r["status"], r["next_job_id"]) for r in jobs.all_jobs()]


def run_ids(project) -> list[str]:
    return sorted(p.name for p in (project / "runs").iterdir() if runs.RUN_ID_RE.match(p.name))


def fresh_run() -> None:
    """A run created but not started: a directory, its rows, every stage pending."""
    db.create_run(FRESH, IDEA, idea_id="lake-tours", stages=runs.STAGES)
    runs.create_run_dir(FRESH, IDEA)


# ---------------------------------------------------------------- new idea


def test_new_idea_form_starts_from_the_founder_defaults(client):
    html = client.get("/new").text
    founder = config.founder()
    assert f'name="capital_eur" value="{founder.capital_eur:g}"' in html
    assert f'name="hours_per_week" value="{founder.hours_per_week:g}"' in html
    assert founder.skills[0] in html and "\n".join(founder.geography) + "</textarea>" in html
    assert f'<option value="{config.budget().default_preset}" selected>' in html
    for preset in config.budget().presets:
        assert f'<option value="{preset}"' in html
    for trigger in KILL_TRIGGERS:
        assert f'value="{trigger}"' in html
    for key, _, _ in control.RUN_TO:
        assert f'name="run_to" value="{key}"' in html
    assert html.count('name="question_') == Intake.model_fields["answers"].metadata[0].max_length
    assert 'href="/new"' in client.get("/").text


def test_new_idea_form_prefills_the_scope_from_founder_yaml(client, project, monkeypatch):
    """The scope fields come from config/founder.yaml (editable on the Settings page)."""
    cfg = project / "config"
    shutil.copytree(config.CONFIG_DIR, cfg)
    monkeypatch.setattr(config, "CONFIG_DIR", cfg)
    text = (cfg / "founder.yaml").read_text(encoding="utf-8")
    text = text.replace("business_mode: local", "business_mode: hybrid").replace("municipality: Rääkkylä", "municipality: Kitee")
    (cfg / "founder.yaml").write_text(text, encoding="utf-8")
    config.reload()
    try:
        html = client.get("/new").text
    finally:
        config.reload()
    assert "Target markets, nearest first" in html
    for mode, help in control.BUSINESS_MODES:
        assert f'name="business_mode" value="{mode}"{" checked" if mode == "hybrid" else ""}>' in html
        assert help in html
    assert 'name="municipality" value="Kitee"' in html
    assert 'name="municipality_code" value="KU707"' in html and 'name="region_code" value="MK12"' in html
    assert "Joensuu\nKitee</textarea>" in html and "raakkyla.fi\nluotsipohjoiskarjala.fi</textarea>" in html
    assert 'name="leader_name" value="Jetina"' in html and 'name="leader_domain" value="jetina.fi"' in html
@pytest.mark.parametrize(
    "run_to, chain",
    [("validate", ["validate"]), ("synthesize", ["validate", "synthesize"]),
     ("debate", ["validate", "synthesize", "debate"])],
)
def test_new_idea_creates_the_run_and_queues_its_chain(client, project, run_to, chain):
    resp = client.post("/new", data=form(run_to=run_to), follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/jobs/1"
    (run_id,) = run_ids(project)
    ids = list(range(1, len(chain) + 1))
    assert queue() == [
        (i, kind, run_id, "queued", i + 1 if i < len(chain) else None) for i, kind in zip(ids, chain, strict=True)
    ]
    intake = Intake.model_validate_json((project / "runs" / run_id / "intake.json").read_text(encoding="utf-8"))
    assert intake.goal == "side_income" and intake.capital_eur == 3000.5 and intake.hours_per_week == 15
    assert intake.skills is None  # unchanged founder skills → config/founder.yaml's
    assert intake.geography == ["Rääkkylä", "North Karelia"]
    assert intake.business_mode == "local" and intake.base_location.model_dump() == {
        "municipality": "Rääkkylä", "municipality_code": "KU707", "region": "North Karelia", "region_code": "MK12",
        "nearby": ["Joensuu", "Kitee"], "official_domains": ["raakkyla.fi"],
        "leader_group": {"name": "Jetina", "domain": "jetina.fi"},
    }
    assert [(a.question, a.answer) for a in intake.answers] == [("Who pays?", "Summer visitors from Joensuu (synthetic)")]
    meta = json.loads((project / "runs" / run_id / "meta.json").read_text(encoding="utf-8"))
    assert meta["budget_preset"] == "economy"


def test_new_idea_with_skills_overrides_and_an_as_of_date(client, project):
    as_of = (date.today() - timedelta(days=400)).isoformat()
    data = form(skills="boat licence\n\n  guiding  ", as_of=as_of,
                kill_trigger_overrides=["permit_impossible", "free_good_enough_substitute"])
    assert client.post("/new", data=data, follow_redirects=False).status_code == 303
    (run_id,) = run_ids(project)
    intake = Intake.model_validate_json((project / "runs" / run_id / "intake.json").read_text(encoding="utf-8"))
    assert intake.skills == ["boat licence", "guiding"]
    assert intake.kill_trigger_overrides == ["free_good_enough_substitute", "permit_impossible"]
    with db.session() as conn:
        assert conn.execute("SELECT as_of FROM runs WHERE run_id=?", (run_id,)).fetchone()["as_of"] == as_of


def test_new_online_idea_based_elsewhere_without_codes_or_a_leader_group(client, project):
    data = form(business_mode="online", geography="Finland\nEU", municipality=" Kitee ", municipality_code="",
                region="North Karelia", region_code="", nearby="", official_domains="Kitee.fi\n",
                leader_name="", leader_domain="")
    assert client.post("/new", data=data, follow_redirects=False).status_code == 303
    (run_id,) = run_ids(project)
    intake = Intake.model_validate_json((project / "runs" / run_id / "intake.json").read_text(encoding="utf-8"))
    assert intake.business_mode == "online" and intake.geography == ["Finland", "EU"]
    base = intake.base_location
    assert (base.municipality, base.municipality_code, base.region_code, base.nearby) == ("Kitee", None, None, [])
    assert base.official_domains == ["kitee.fi"] and base.leader_group is None


def test_an_idea_text_starting_with_a_dash_is_not_an_option(client, project):
    assert client.post("/new", data=form(idea="-sauna cabins (synthetic)"), follow_redirects=False).status_code == 303
    (run_id,) = run_ids(project)
    assert (project / "runs" / run_id / "idea.md").read_text(encoding="utf-8").endswith("\n-sauna cabins (synthetic)\n")


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"idea": "   "}, "the idea text must not be empty"),
        ({"goal": "rich"}, "goal must be one of side_income, full_time, starttiraha"),
        ({"capital_eur": "lots"}, "capital (EUR) must be a number, not &#39;lots&#39;"),
        ({"capital_eur": ""}, "capital (EUR) is required"),
        ({"capital_eur": "-5"}, "capital_eur: Input should be greater than or equal to 0"),
        ({"hours_per_week": "120"}, "hours_per_week: Input should be less than or equal to 100"),
        ({"hours_per_week": "nan"}, "hours per week must be a finite number"),
        ({"geography": "\n  \n"}, "target markets need at least one place"),
        ({"business_mode": "mail_order"}, "business mode must be one of local, online, hybrid"),
        ({"business_mode": ""}, "business mode must be one of local, online, hybrid"),
        ({"municipality": "  "}, "base_location.municipality: String should have at least 1 character"),
        ({"municipality_code": "707"}, "base_location.municipality_code: String should match pattern"),
        ({"official_domains": "https://raakkyla.fi/"}, "base_location.official_domains.0: String should match"),
        ({"leader_domain": ""}, "base_location.leader_group.domain: String should match pattern"),
        ({"answer_1": ""}, "question 1 has no answer"),
        ({"question_2": "", "answer_2": "nobody asked (synthetic)"}, "answer 2 has no question"),
        ({"preset": "huge"}, "preset must be one of deep, economy, standard"),
        ({"as_of": "1.6.2025"}, "as-of date must be YYYY-MM-DD"),
        ({"as_of": (date.today() + timedelta(days=2)).isoformat()}, "as-of date must not be in the future"),
        ({"run_to": "report"}, "how far to run must be one of validate, synthesize, debate"),
        ({"kill_trigger_overrides": ["bad_luck"]}, "unknown kill trigger(s): bad_luck"),
    ],
)
def test_invalid_input_is_rejected_with_a_message_and_queues_nothing(client, project, overrides, message):
    resp = client.post("/new", data=form(**overrides))
    assert resp.status_code == 400
    assert 'id="form-errors"' in resp.text and message in resp.text
    assert run_ids(project) == [] and queue() == []
    if "idea" not in overrides:  # the form comes back as typed
        assert IDEA in resp.text


def test_new_run_refusal_is_shown(client, project, monkeypatch):
    def refuse(*args, **kwargs):
        raise jobs.JobError("new_run.py refused the idea (exit 2): run directory runs/x already exists")

    monkeypatch.setattr(jobs, "enqueue_idea", refuse)
    resp = client.post("/new", data=form())
    assert resp.status_code == 400 and "run directory runs/x already exists" in resp.text and queue() == []


# ---------------------------------------------------------------- run actions


def offered(client, run_id: str) -> list[str]:
    html = client.get(f"/runs/{run_id}").text
    actions = html.split('id="run-actions"', 1)[1].split("</div>", 1)[0]
    found = [key for key in ("validate", "synthesize", "debate") if f'/actions/{key}"' in actions]
    return found + (["version"] if f'/runs/{run_id}/version"' in actions else [])


@pytest.fixture
def states(client, finished, stopped):  # noqa: F811
    """A fresh run, one stopped after stage 3 and a finished one. The fixture's research files are
    placeholders that do not pass the research contract, so their dimensions count as complete
    the one way that needs no output: insufficient_data."""
    with db.session() as conn:
        conn.execute("UPDATE stages SET status='insufficient_data' WHERE stage LIKE 'research:%'")
    fresh_run()
    return {FRESH: ["validate", "version"], STOPPED: ["synthesize", "version"], FINISHED: ["debate", "version"]}


def test_run_page_offers_the_actions_its_state_allows(client, states):
    for run_id, expected in states.items():
        assert offered(client, run_id) == expected, run_id
    (runs.run_dir(FINISHED) / "debate").mkdir(exist_ok=True)
    (runs.run_dir(FINISHED) / "debate" / "revised_plan.md").write_text("# Revised plan (synthetic)\n", encoding="utf-8")
    assert offered(client, FINISHED) == ["version"]


def test_each_run_action_queues_its_job(client, states):
    for run_id, expected in states.items():
        action = expected[0]
        resp = client.post(f"/runs/{run_id}/actions/{action}", follow_redirects=False)
        assert resp.status_code == 303
        job_id = int(resp.headers["location"].rsplit("/", 1)[1])
        row = jobs.get(job_id)
        assert (row["kind"], row["run_id"], row["status"], row["next_job_id"]) == (action, run_id, "queued", None)
        assert jobs.command(row["kind"], row["run_id"], {}) == f"/{action} {run_id}"


@pytest.mark.parametrize(
    "run_id, action, reason",
    [
        (FINISHED, "validate", "stages 0–3 are complete"),
        (FRESH, "synthesize", "stages 0–3 are not complete; resume validate first"),
        (FINISHED, "synthesize", "synthesis, scoring and the report are complete"),
        (STOPPED, "debate", "the debate needs the report; synthesize first"),
        (FRESH, "debate", "the debate needs the report; synthesize first"),
    ],
)
def test_an_action_in_the_wrong_state_is_refused(client, states, run_id, action, reason):
    resp = client.post(f"/runs/{run_id}/actions/{action}", follow_redirects=False)
    assert resp.status_code == 409 and reason in resp.text and 'id="action-error"' in resp.text
    assert queue() == []


def test_a_finished_debate_and_a_busy_run_refuse_actions(client, states):
    (runs.run_dir(FINISHED) / "debate").mkdir(exist_ok=True)
    (runs.run_dir(FINISHED) / "debate" / "revised_plan.md").write_text("# Revised plan (synthetic)\n", encoding="utf-8")
    resp = client.post(f"/runs/{FINISHED}/actions/debate")
    assert resp.status_code == 409 and "the debate is finished" in resp.text
    (job_id,) = jobs.enqueue("validate", FRESH)
    resp = client.post(f"/runs/{FRESH}/actions/validate")
    assert resp.status_code == 409 and f"job {job_id} (validate) is queued for this run" in resp.text
    assert offered(client, FRESH) == ["version"]
    assert f'href="/jobs/{job_id}"' in client.get(f"/runs/{FRESH}").text
    assert len(queue()) == 1


def test_unknown_actions_and_runs(client, states):
    assert client.post(f"/runs/{FINISHED}/actions/report").status_code == 404
    assert client.post("/runs/20261024-000000-nothing/actions/validate").status_code == 404
    assert queue() == []


def test_a_run_without_its_row_offers_nothing(client, project):
    runs.create_run_dir(FRESH, IDEA)  # a directory with no database row
    assert offered(client, FRESH) == []
    resp = client.post(f"/runs/{FRESH}/actions/validate")
    assert resp.status_code == 409 and "needs both its directory and its database row" in resp.text
    assert client.get(f"/runs/{FRESH}/version").status_code == 409


# ---------------------------------------------------------------- new version


def test_new_version_form_starts_from_the_parent_spec(client, finished):  # noqa: F811
    html = client.get(f"/runs/{FINISHED}/version").text
    assert "Sauna-and-lake cabins for remote workers" in html  # the parent's idea text
    assert 'name="capital_eur" value="15000"' in html and "carpentry\nhospitality" in html
    assert "Rääkkylä\nNorth Karelia\nFinland\nonline" in html
    assert 'value="Do you already own the cabins?"' in html
    # the fixture spec predates the scope fields: Rääkkylä / local
    assert 'name="business_mode" value="local" checked>' in html and 'name="municipality" value="Rääkkylä"' in html


def test_new_version_form_takes_the_scope_from_the_parent_spec(client, finished):  # noqa: F811
    path = runs.run_dir(FINISHED) / "00_spec.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec |= {
        "business_mode": "online",
        "geography": ["Finland", "EU"],
        "base_location": {"municipality": "Kitee", "region": "North Karelia", "official_domains": ["kitee.fi"]},
    }
    path.write_text(json.dumps(spec), encoding="utf-8")
    html = client.get(f"/runs/{FINISHED}/version").text
    assert 'name="business_mode" value="online" checked>' in html and "Finland\nEU</textarea>" in html
    assert 'name="municipality" value="Kitee"' in html and 'name="municipality_code" value=""' in html
    assert 'name="leader_name" value=""' in html and "kitee.fi</textarea>" in html


def test_new_version_creates_the_next_version_and_queues_it(client, project, finished):  # noqa: F811
    before = sorted(p.relative_to(finished).as_posix() for p in finished.rglob("*"))
    data = form(idea="Sauna-and-lake cabins, winter stays only (synthetic)", run_to="synthesize")
    resp = client.post(f"/runs/{FINISHED}/version", data=data, follow_redirects=False)
    assert resp.status_code == 303
    child = f"{FINISHED}-v2"
    assert queue() == [(1, "validate", child, "queued", 2), (2, "synthesize", child, "queued", None)]
    with db.session() as conn:
        row = conn.execute("SELECT version, parent FROM idea_versions WHERE run_id=?", (child,)).fetchone()
    assert (row["version"], row["parent"]) == (2, FINISHED)
    assert (project / "runs" / child / "idea.md").read_text(encoding="utf-8").endswith("\nSauna-and-lake cabins, winter stays only (synthetic)\n")
    assert (project / "runs" / child / "intake.json").is_file()
    assert sorted(p.relative_to(finished).as_posix() for p in finished.rglob("*")) == before  # parent untouched


def test_an_invalid_version_form_creates_nothing(client, project, finished):  # noqa: F811
    resp = client.post(f"/runs/{FINISHED}/version", data=form(goal="rich"))
    assert resp.status_code == 400 and "goal must be one of" in resp.text
    assert run_ids(project) == [FINISHED] and queue() == []


# ---------------------------------------------------------------- eval


def test_eval_action_queues_the_golden_set(client):
    resp = client.post("/eval", data={"limit": "2", "fresh": "1"}, follow_redirects=False)
    assert resp.status_code == 303
    (row,) = jobs.all_jobs()
    assert (row["kind"], row["run_id"], json.loads(row["args"])) == ("eval", None, {"limit": 2, "fresh": True})
    assert jobs.command("eval", None, json.loads(row["args"])) == "/eval --limit 2 --fresh"
    html = client.get("/").text
    assert 'id="eval-form"' not in html and "eval job 1 is queued" in html
    resp = client.post("/eval", data={})
    assert resp.status_code == 409 and "Eval refused: eval job 1 is queued" in resp.text
    assert len(queue()) == 1


@pytest.mark.parametrize("limit", ["0", "two", "1.5"])
def test_eval_with_a_bad_limit_queues_nothing(client, limit):
    resp = client.post("/eval", data={"limit": limit})
    assert resp.status_code == 400 and "limit must be a whole number ≥ 1" in resp.text and queue() == []


def test_eval_without_a_limit(client):
    assert client.post("/eval", data={"limit": ""}, follow_redirects=False).status_code == 303
    assert json.loads(jobs.all_jobs()[0]["args"]) == {}


# ---------------------------------------------------------------- jobs page, cancel and retry


def test_jobs_page_lists_jobs_with_their_actions(client, states):
    jobs.enqueue("synthesize", STOPPED, then=["debate"])
    html = client.get("/jobs").text
    assert html.index('data-job="2"') < html.index('data-job="1"')  # newest first
    assert "after job 1" in html and f'href="/runs/{STOPPED}"' in html
    assert 'action="/jobs/1/cancel"' in html and 'action="/jobs/2/cancel"' in html
    job = client.get("/jobs/2").text
    assert f"/debate {STOPPED}" in job and 'href="/jobs/1"' in job  # its chain
    assert client.get("/jobs/99").status_code == 404


def test_cancel_and_retry_from_the_ui(client, states):
    jobs.enqueue("synthesize", STOPPED, then=["debate"])
    resp = client.post("/jobs/1/cancel", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/jobs/1"
    assert [r[3] for r in queue()] == ["cancelled", "cancelled"]
    resp = client.post("/jobs/1/cancel")
    assert resp.status_code == 409 and "Cancel refused: job 1 is already cancelled" in resp.text
    assert 'action="/jobs/1/retry"' in client.get("/jobs/1").text
    resp = client.post("/jobs/1/retry", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/jobs/3"
    assert queue()[2:] == [(3, "synthesize", STOPPED, "queued", 4), (4, "debate", STOPPED, "queued", None)]
    resp = client.post("/jobs/3/retry")
    assert resp.status_code == 409 and "Retry refused: job 3 is still queued" in resp.text
    assert client.post("/jobs/99/retry").status_code == 404


# ---------------------------------------------------------------- log tail


def test_log_tail_returns_only_new_bytes(client, states):
    (job_id,) = jobs.enqueue("validate", FRESH)
    log = jobs.log_file(job_id)
    log.parent.mkdir(parents=True, exist_ok=True)
    assert client.get(f"/jobs/{job_id}/log?offset=0").json() == {
        "text": "", "offset": 0, "size": 0, "done": False, "status": "queued"
    }
    log.write_bytes('{"type": "system"}\nsecond line, ä\npartial'.encode())
    first = client.get(f"/jobs/{job_id}/log?offset=0").json()
    assert first["text"] == '{"type": "system"}\nsecond line, ä\n'  # the unfinished line waits
    assert first["offset"] == len(first["text"].encode()) and not first["done"]
    again = client.get(f"/jobs/{job_id}/log", params={"offset": first["offset"]}).json()
    assert again["text"] == "" and again["offset"] == first["offset"]
    with open(log, "ab") as f:
        f.write(b" ends\nthird\n")
    nxt = client.get(f"/jobs/{job_id}/log", params={"offset": first["offset"]}).json()
    assert nxt["text"] == "partial ends\nthird\n" and nxt["offset"] == log.stat().st_size
    with db.session() as conn:
        conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job_id,))
    with open(log, "ab") as f:
        f.write(b"no newline at the end")
    last = client.get(f"/jobs/{job_id}/log", params={"offset": nxt["offset"]}).json()
    assert last == {"text": "no newline at the end", "offset": log.stat().st_size, "size": log.stat().st_size,
                    "done": True, "status": "done"}
    beyond = client.get(f"/jobs/{job_id}/log", params={"offset": 10**9}).json()
    assert beyond["text"] == "" and beyond["offset"] == log.stat().st_size
    assert client.get("/jobs/99/log?offset=0").status_code == 404


def test_job_page_shows_the_tail_from_a_line_start(client, states, monkeypatch):
    monkeypatch.setattr(control, "TAIL_BYTES", 20)
    (job_id,) = jobs.enqueue("validate", FRESH)
    log = jobs.log_file(job_id)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("line one is long enough\nline two\nline three\n", encoding="utf-8")
    chunk = control.log_chunk(job_id)
    assert chunk.text == "line three\n" and chunk.offset == log.stat().st_size
    html = client.get(f"/jobs/{job_id}").text
    assert f'data-offset="{chunk.offset}"' in html and "line three" in html and "line one" not in html
    assert '/static/logtail.js"' in html and client.get("/static/logtail.js").status_code == 200


# ---------------------------------------------------------------- dev marker and the worker


def test_dev_marker_banner(client, project):
    assert 'id="dev-marker"' not in client.get("/").text
    (project / ".ideaforge-dev").write_text("", encoding="utf-8")
    for path in ("/", "/new", "/jobs"):
        html = client.get(path).text
        assert 'id="dev-marker"' in html and ".ideaforge-dev exists" in html, path
    with TestClient(create_app(project, worker_poll=0.02), base_url=LOCAL) as c:
        assert "The worker cannot start" in c.get("/jobs").text
        assert c.post("/new", data=form(), follow_redirects=False).status_code == 303  # queued, waits
        assert [r[3] for r in queue()] == ["queued"]
    (project / ".ideaforge-dev").unlink()


def test_the_server_worker_runs_queued_jobs_with_the_fake_claude(fake_claude, project, monkeypatch):  # noqa: F811
    with TestClient(create_app(project, worker_poll=0.02), base_url=LOCAL) as c:
        assert "The worker is running" in c.get("/jobs").text
        resp = c.post("/new", data=form(run_to="synthesize"), follow_redirects=False)
        (run_id,) = run_ids(project)
        wait_for(lambda: [r[3] for r in queue()] == ["done", "done"])
        assert [s["prompt"] for s in fake_claude("start")] == [f"/validate {run_id}", f"/synthesize {run_id}"]
        assert all(s["harness_loop"] is None and s["run_id"] == run_id for s in fake_claude("start"))
        tail = c.get(f"{resp.headers['location']}/log?offset=0").json()
        assert tail["done"] and '"synthetic done"' in tail["text"]
    assert not (project / "runs" / ".jobs" / "worker.pid").exists()


def test_shutdown_stops_the_running_job_as_interrupted(fake_claude, project, monkeypatch, states):  # noqa: F811
    modes(monkeypatch, **{f"/validate_{FRESH}": "sleep"})
    with TestClient(create_app(project, worker_poll=0.02), base_url=LOCAL) as c:
        assert c.post(f"/runs/{FRESH}/actions/validate", follow_redirects=False).status_code == 303
        wait_for(lambda: jobs.get(1)["pid"] and fake_claude("start"))
    row = jobs.get(1)
    assert (row["status"], row["reason"]) == ("failed", "interrupted")
    assert fake_claude("end") == []  # stopped, not finished


def test_a_job_queued_while_the_worker_is_stopped_starts_it_again(fake_claude, project):  # noqa: F811
    (project / ".ideaforge-dev").write_text("", encoding="utf-8")
    app = create_app(project, worker_poll=0.02)
    with TestClient(app, base_url=LOCAL) as c:
        assert not app.state.worker.alive
        (project / ".ideaforge-dev").unlink()
        assert c.post("/eval", data={}, follow_redirects=False).status_code == 303
        assert app.state.worker.alive
        wait_for(lambda: jobs.get(1)["status"] == "done")
    assert fake_claude("start")[0]["prompt"] == "/eval"


# ---------------------------------------------------------------- requests from elsewhere


@pytest.mark.parametrize(
    "headers, refused",
    [
        ({"host": "127.0.0.1:8765"}, None),
        ({"host": "localhost:8765", "origin": "http://localhost:8765"}, None),
        ({"host": "[::1]:8765", "sec-fetch-site": "same-origin"}, None),
        ({"host": "evil.example:8765", "origin": "http://evil.example:8765"}, "is not this machine"),
        ({"host": "127.0.0.1:8765", "origin": "http://evil.example"}, "is not this UI"),
        ({"host": "127.0.0.1:8765", "origin": "null"}, "is not this UI"),
        ({"host": "127.0.0.1:8765", "sec-fetch-site": "cross-site"}, "a cross-site request"),
    ],
)
def test_foreign_request(headers, refused):
    why = foreign_request(headers)
    assert why is None if refused is None else refused in why


def test_a_post_from_another_site_starts_nothing(client, project):
    resp = client.post("/new", data=form(), headers={"origin": "http://evil.example"})
    assert resp.status_code == 403 and run_ids(project) == [] and queue() == []
    other = TestClient(create_app(project))  # Host: testserver
    assert other.post("/eval", data={}).status_code == 403 and queue() == []
    assert other.get("/jobs").status_code == 200  # reading is not refused

