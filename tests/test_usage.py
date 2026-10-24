import json

from ideaforge import usage


def hook(tool, agent=None, **tool_io):
    data = {"tool_name": tool, "tool_input": tool_io.get("tool_input", {}), "tool_response": tool_io.get("tool_response", "")}
    if agent:
        data |= {"agent_id": "id-" + agent, "agent_type": agent}
    return data


def test_noop_without_active_run(project):
    usage.log(hook("Read"))
    assert not list((project / "runs").rglob("usage.jsonl"))


def test_appends_usage_line(active_run):
    usage.log(hook("Read", tool_input={"file_path": "x"}))
    usage.log(hook("WebSearch", agent="research-market"))
    lines = [json.loads(line) for line in (active_run / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["agent"], r["tool"], r["model"]) for r in lines] == [
        ("main", "Read", "opus"), ("research-market", "WebSearch", "opus")
    ]
    assert all(r["approx_tokens"] >= 0 for r in lines)


def test_records_seen_urls(active_run):
    usage.log(hook("WebSearch", agent="research-market",
                   tool_response={"results": [{"url": "https://stat.fi/a"}, {"url": "https://vero.fi/b."}]}))
    usage.log(hook("WebFetch", agent="research-market", tool_input={"url": "https://luke.fi/c"}))
    seen = (active_run / ".seen_urls.txt").read_text(encoding="utf-8").splitlines()
    assert seen == [
        "research-market\thttps://stat.fi/a",
        "research-market\thttps://vero.fi/b",
        "research-market\thttps://luke.fi/c",
    ]


def test_budget_exceeded_marker(active_run):
    for _ in range(8):  # standard preset: 8 searches allowed
        usage.log(hook("WebSearch", agent="research-pricing"))
    marker = active_run / "BUDGET_EXCEEDED_research-pricing"
    assert not marker.exists()
    usage.log(hook("WebSearch", agent="research-pricing"))
    assert "WebSearch: 9 > 8" in marker.read_text(encoding="utf-8")
    counters = json.loads((active_run / ".counters.json").read_text(encoding="utf-8"))
    assert counters["research-pricing"]["WebSearch"] == 9


def test_killcause_has_its_own_budget(active_run):
    for _ in range(10):
        usage.log(hook("WebSearch", agent="research-killcause"))
    assert not (active_run / "BUDGET_EXCEEDED_research-killcause").exists()


def test_preset_from_meta(active_run):
    (active_run / "meta.json").write_text(json.dumps({"budget_preset": "economy"}), encoding="utf-8")
    for _ in range(7):
        usage.log(hook("WebSearch", agent="research-gtm"))
    assert (active_run / "BUDGET_EXCEEDED_research-gtm").exists()


def test_a_mini_research_task_has_its_own_budget(active_run):
    from test_guard import open_mini_task

    usage.log(hook("WebSearch", agent="research-pricing"))  # stage 2
    open_mini_task(active_run)
    for _ in range(9):
        usage.log(hook("WebSearch", agent="research-pricing"))
    counters = json.loads((active_run / ".counters.json").read_text(encoding="utf-8"))
    assert counters["research-pricing"]["WebSearch"] == 1
    assert counters["research-pricing.mini-1"]["WebSearch"] == 9
    assert not (active_run / "BUDGET_EXCEEDED_research-pricing").exists()
    assert "WebSearch: 9 > 8" in (active_run / "BUDGET_EXCEEDED_research-pricing.mini-1").read_text(encoding="utf-8")
