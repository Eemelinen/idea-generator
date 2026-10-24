"""The settings editor (IF-608): form and raw-YAML saves of a copy of `config/*.yaml` keep the
files' comments, invalid values are rejected with the file unchanged, a models save runs
gen_agents (into a temporary `.claude/agents`) and leaves the `harness_*` roles alone, every save
has a history row with a diff and a revert, and saving is refused while a job runs. The jobs are
synthetic rows; nothing runs `claude` or touches the network."""

import shutil
from markupsafe import escape

import pytest
from fastapi.testclient import TestClient

from ideaforge import config, db
from ideaforge.web import create_app, settings

LOCAL = "http://127.0.0.1:8765"


@pytest.fixture
def conf(project, monkeypatch):
    """The project's config/ as a copy of the real one, and an empty `.claude/agents` for
    gen_agents; the config cache is cleared before and after."""
    cfg = project / "config"
    shutil.copytree(config.CONFIG_DIR, cfg)
    monkeypatch.setattr(config, "CONFIG_DIR", cfg)
    monkeypatch.setattr(config, "AGENTS_DIR", project / ".claude" / "agents")
    config.reload()
    yield cfg
    config.reload()


@pytest.fixture
def client(conf, project):
    return TestClient(create_app(project), base_url=LOCAL)


def text(conf, key: str) -> str:
    return (conf / f"{key}.yaml").read_text(encoding="utf-8")


def form_of(key: str, **changes: str) -> dict[str, str]:
    """The settings form as the browser posts it (read-only fields are not posted), with
    `changes` keyed by field path (`roles/research_subagent`)."""
    fields = {f.name: f.value for f in settings.fields(key) if f.kind != "readonly"}
    for path, value in changes.items():
        assert f"f:{path}" in fields, path
        fields[f"f:{path}"] = value
    return fields


def history_rows() -> list:
    with db.session() as conn:
        return conn.execute("SELECT * FROM settings_history ORDER BY id").fetchall()


def changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    a, b = before.splitlines(), after.splitlines()
    assert len(a) == len(b)
    return [(x, y) for x, y in zip(a, b, strict=True) if x != y]


def running_job() -> int:
    with db.session() as conn:
        return conn.execute(
            "INSERT INTO jobs(kind, run_id, status, created_at, started_at)"
            " VALUES ('validate', '20261024-120000-lake-tours', 'running', ?, ?)",
            (db.now(), db.now()),
        ).lastrowid


# ---------------------------------------------------------------- pages


def test_index_lists_every_pipeline_config_file(client):
    html = client.get("/settings").text
    assert 'href="/settings" class="active"' in html
    for key in ("models", "budget", "founder", "report", "rubric", "domains", "finland"):
        assert f'href="/settings/{key}"' in html and f"config/{key}.yaml" in html
    assert "harness.config.json" in html and 'href="/settings/harness' not in html
    assert client.get("/settings/harness").status_code == 404


def test_each_page_has_the_form_the_raw_yaml_and_the_file_comments(client, conf):
    for key in settings.FILES:
        html = client.get(f"/settings/{key}").text
        assert f'action="/settings/{key}"' in html and f'action="/settings/{key}/raw"' in html
        assert 'name="raw"' in html and "No saves from this page yet." in html
    models = client.get("/settings/models").text
    assert '<option value="sonnet">sonnet</option>' in models and '<option value="opus" selected>' in models
    assert "downgrade candidate #1 (haiku) when limits bite" in models  # the file's comment as help
    assert "Downgrade order if usage limits are hit" in models  # notes
    assert "Single source of truth" in models  # the header comment
    budget = client.get("/settings/budget").text
    assert '<select id="f:default_preset" name="f:default_preset">' in budget
    for preset in config.budget().presets:
        assert f'<option value="{preset}"' in budget
    assert '<select id="f:goal" name="f:goal">' in client.get("/settings/founder").text
    assert '<option value="fi" selected>' in client.get("/settings/report").text
    rubric = client.get("/settings/rubric").text
    assert "The dimension weights sum to 1 (they must sum to 1.0)." in rubric
    assert "dimensions › pricing › weight" in rubric
    assert 'id="hints-not-facts"' in client.get("/settings/finland").text
    assert "Hints to verify, not facts" in client.get("/settings/finland").text


# ---------------------------------------------------------------- round trip


def test_an_unchanged_form_saves_nothing_and_the_round_trip_is_exact(client, conf):
    for key in settings.FILES:
        before = text(conf, key)
        assert settings.form_text(key, form_of(key)) == before, key
        resp = client.post(f"/settings/{key}", data=form_of(key))
        assert resp.status_code == 200 and "No changes: nothing was saved." in resp.text
        assert text(conf, key) == before
    assert history_rows() == []


def test_a_form_save_keeps_comments_order_and_flow_style(client, conf):
    before = text(conf, "rubric")
    resp = client.post(
        "/settings/rubric",
        data=form_of(
            "rubric",
            **{"dimensions/0/weight": "0.10", "dimensions/1/weight": "0.15", "dimensions/2/kill_triggers": "free_good_enough_substitute\npermit_impossible"},
        ),
    )
    assert resp.status_code == 200 and "Saved config/rubric.yaml." in resp.text
    after = text(conf, "rubric")
    assert changed_lines(before, after) == [
        ("    weight: 0.15", "    weight: 0.1"),  # a changed number is written as Python spells it
        ("    weight: 0.10", "    weight: 0.15"),
        ("    kill_triggers: [free_good_enough_substitute]", "    kill_triggers: [free_good_enough_substitute, permit_impossible]"),
    ]
    assert "# Scoring rubric. Weights must sum to 1.0" in after
    assert "      - {rule: min_sources, n: 3, independent: true}" in after
    assert config.rubric().dimension("customer").weight == 0.10  # the cache was cleared

    before = text(conf, "finland")
    client.post("/settings/finland", data=form_of("finland", **{"hints/yel_minimum_income/value_eur": "30000"}))
    after = text(conf, "finland")
    assert changed_lines(before, after) == [("    value_eur: null", "    value_eur: 30000")]
    assert after.startswith("# HINTS, NOT FACTS.") and "daily_amount_eur: null" in after

    before = text(conf, "founder")
    client.post("/settings/founder", data=form_of("founder", goal="starttiraha", hours_per_week="25"))
    assert changed_lines(before, text(conf, "founder")) == [
        ("hours_per_week: 20", "hours_per_week: 25"),
        ("goal: side_income        # side_income | full_time | starttiraha", "goal: starttiraha        # side_income | full_time | starttiraha"),
    ]


def test_a_raw_save_writes_the_text_as_typed(client, conf):
    raw = text(conf, "report").replace("language: en", "language: fi  # switched in the raw editor")
    resp = client.post("/settings/report/raw", data={"raw": raw.replace("\n", "\r\n")})
    assert resp.status_code == 200 and "Saved config/report.yaml." in resp.text
    assert text(conf, "report") == raw and config.report().language == "fi"


# ---------------------------------------------------------------- invalid saves


@pytest.mark.parametrize(
    "key, changes, message",
    [
        ("rubric", {"dimensions/0/weight": "0.20"}, "rubric weights must sum to 1.0"),
        ("rubric", {"dimensions/0/weight": "lots"}, "'lots' is not a number"),
        ("budget", {"presets/economy/debate/max_rounds": "5"}, "presets.economy.debate.max_rounds: Input should be less than or equal to 3"),
        ("budget", {"default_preset": "turbo"}, "default_preset 'turbo' is not defined"),
        ("founder", {"goal": "get_rich"}, "goal: Input should be"),
        ("report", {"language": "sv"}, "language: Input should be 'en' or 'fi'"),
        ("finland", {"hints/vat_general_rate/verify_at_runtime": "false"}, "hints.vat_general_rate.verify_at_runtime: Input should be True"),
        ("finland", {"hints/vat_general_rate/verify_url": "http://www.vero.fi/"}, "hints.vat_general_rate.verify_url: String should match pattern"),
    ],
)
def test_an_invalid_form_is_rejected_and_the_file_is_unchanged(client, conf, key, changes, message):
    before = text(conf, key)
    resp = client.post(f"/settings/{key}", data=form_of(key, **changes))
    assert resp.status_code == 400, resp.text
    assert "is unchanged" in resp.text and escape(message) in resp.text
    assert text(conf, key) == before and history_rows() == []
    path, value = next(iter(changes.items()))
    if next(f for f in settings.fields(key) if f.name == f"f:{path}").kind != "select":
        assert f'value="{escape(value)}"' in resp.text  # the refused value is shown again, for correcting


@pytest.mark.parametrize(
    "raw, message",
    [
        ("language: [en\n", "not valid YAML"),
        ("language: en\nbusiness_plan_language: fi\ncolour: blue\n", "colour: Extra inputs are not permitted"),
        ("- en\n- fi\n", "Input should be a valid dictionary"),
    ],
)
def test_invalid_raw_yaml_is_rejected_and_the_file_is_unchanged(client, conf, raw, message):
    before = text(conf, "report")
    resp = client.post("/settings/report/raw", data={"raw": raw})
    assert resp.status_code == 400 and escape(message) in resp.text and "is unchanged" in resp.text
    assert text(conf, "report") == before and history_rows() == []


# ---------------------------------------------------------------- models and gen_agents


def test_a_models_save_regenerates_the_agents(client, conf, project):
    agents = project / ".claude" / "agents"
    resp = client.post("/settings/models", data=form_of("models", **{"roles/research_subagent": "sonnet"}))
    assert resp.status_code == 200 and 'id="gen-agents-output"' in resp.text and "wrote " in resp.text
    assert "model: sonnet" in (agents / "research-market.md").read_text(encoding="utf-8")
    assert "model: opus" in (agents / "synthesizer.md").read_text(encoding="utf-8")
    assert "  research_subagent: sonnet" in text(conf, "models")
    assert "  claim_extractor: opus       # downgrade candidate #1 (haiku) when limits bite" in text(conf, "models")
    assert config.models().roles["research_subagent"] == "sonnet"


def test_the_harness_roles_are_read_only(client, conf):
    html = client.get("/settings/models").text
    assert '<code id="f:roles/harness_generator">opus</code>' in html
    assert 'name="f:roles/harness_generator"' not in html and 'name="f:roles/harness_evaluator"' not in html
    before = text(conf, "models")
    # posted anyway (a hand-made request): the field is not taken from the form
    form = form_of("models") | {"f:roles/harness_generator": "haiku"}
    resp = client.post("/settings/models", data=form)
    assert resp.status_code == 200 and text(conf, "models") == before
    # and the raw YAML may not change them
    resp = client.post("/settings/models/raw", data={"raw": before.replace("harness_evaluator: opus", "harness_evaluator: sonnet")})
    assert resp.status_code == 400 and "roles.harness_evaluator is a development setting" in resp.text
    resp = client.post("/settings/models/raw", data={"raw": before.replace("  harness_generator: opus\n", "")})
    assert resp.status_code == 400 and "roles.harness_generator is a development setting" in resp.text
    assert text(conf, "models") == before and history_rows() == []


def test_a_failed_generation_restores_the_file(client, conf, project, monkeypatch):
    monkeypatch.setattr(config, "AGENT_TEMPLATES_DIR", project / "no-templates")
    before = text(conf, "models")
    resp = client.post("/settings/models", data=form_of("models", **{"roles/synthesizer": "sonnet"}))
    assert resp.status_code == 400
    assert "scripts/gen_agents.py failed, so config/models.yaml was restored." in resp.text
    assert "template set mismatch" in resp.text  # its output
    assert text(conf, "models") == before and history_rows() == []
    assert config.models().roles["synthesizer"] == "opus"


def test_files_without_agents_do_not_run_gen_agents(client, project):
    resp = client.post("/settings/founder", data=form_of("founder", hours_per_week="30"))
    assert resp.status_code == 200 and 'id="gen-agents-output"' not in resp.text
    assert not (project / ".claude" / "agents").exists()


# ---------------------------------------------------------------- history


def test_history_diff_and_revert(client, conf, project):
    original = text(conf, "models")
    client.post("/settings/models", data=form_of("models", **{"roles/research_subagent": "sonnet"}))
    resp = client.post("/settings/models", data=form_of("models", **{"roles/debate_persona": "haiku"}))
    first, second = history_rows()
    assert (first["file"], first["content_before"], first["sha_before"]) == ("models.yaml", original, settings.sha(original))
    assert first["content_after"] == second["content_before"] and second["sha_after"] == settings.sha(text(conf, "models"))
    assert f'href="/settings/models/history/{second["id"]}">See the diff</a>' in resp.text

    html = client.get("/settings/models").text
    assert html.index(f'data-entry="{second["id"]}"') < html.index(f'data-entry="{first["id"]}"')  # newest first
    entry = client.get(f"/settings/models/history/{first['id']}").text
    assert '<span class="del">-  research_subagent: opus</span>' in entry
    assert '<span class="add">+  research_subagent: sonnet</span>' in entry
    assert "debate_persona: haiku" not in entry

    # revert the first save: research_subagent goes back, the second save's change stays
    resp = client.post(f"/settings/models/history/{first['id']}/revert")
    assert resp.status_code == 200 and "Saved config/models.yaml." in resp.text
    assert text(conf, "models") == original  # first's content_before
    rows = history_rows()
    assert len(rows) == 3 and rows[2]["content_after"] == original
    assert "model: opus" in (project / ".claude" / "agents" / "research-market.md").read_text(encoding="utf-8")
    # reverting to what the file already is saves nothing
    resp = client.post(f"/settings/models/history/{first['id']}/revert")
    assert resp.status_code == 200 and "No changes" in resp.text and len(history_rows()) == 3

    assert client.get("/settings/models/history/999").status_code == 404
    assert client.get(f"/settings/budget/history/{first['id']}").status_code == 404  # another file's save
    assert client.post("/settings/models/history/999/revert").status_code == 404


def test_a_revert_is_validated(client, conf):
    """A revert that would undo a hand change of the harness roles is refused like any save."""
    client.post("/settings/models", data=form_of("models", **{"roles/research_subagent": "sonnet"}))
    (entry,) = history_rows()
    edited = text(conf, "models").replace("harness_generator: opus", "harness_generator: sonnet")
    (conf / "models.yaml").write_text(edited, encoding="utf-8")
    resp = client.post(f"/settings/models/history/{entry['id']}/revert")
    assert resp.status_code == 400 and "Not reverted" in resp.text and "roles.harness_generator" in resp.text
    assert text(conf, "models") == edited and len(history_rows()) == 1


# ---------------------------------------------------------------- refusal while a job runs


def test_saving_is_refused_while_a_job_runs(client, conf):
    client.post("/settings/report", data=form_of("report", language="fi"))
    (entry,) = history_rows()
    job_id = running_job()
    before = {key: text(conf, key) for key in settings.FILES}

    for path in ("/settings", "/settings/report", f"/settings/report/history/{entry['id']}"):
        html = client.get(path).text
        assert 'id="settings-refused"' in html and f"job {job_id} (/validate 20261024-120000-lake-tours) is running" in html
    assert "<button type=\"submit\" disabled>Save</button>" in client.get("/settings/report").text

    resp = client.post("/settings/report", data=form_of("report", language="en"))
    assert resp.status_code == 409 and "Saving is refused" in resp.text
    resp = client.post("/settings/models/raw", data={"raw": before["models"].replace("synthesizer: opus", "synthesizer: sonnet")})
    assert resp.status_code == 409
    resp = client.post(f"/settings/report/history/{entry['id']}/revert")
    assert resp.status_code == 409 and "Saving is refused" in resp.text
    assert {key: text(conf, key) for key in settings.FILES} == before and len(history_rows()) == 1

    with db.session() as conn:
        conn.execute("UPDATE jobs SET status='done', finished_at=? WHERE job_id=?", (db.now(), job_id))
    assert client.post("/settings/report", data=form_of("report", language="en")).status_code == 200
    assert len(history_rows()) == 2


def test_a_save_from_another_site_is_refused(client, conf):
    before = text(conf, "report")
    resp = client.post("/settings/report", data=form_of("report", language="fi"), headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403 and text(conf, "report") == before
