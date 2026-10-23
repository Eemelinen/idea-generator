import json
import sys
from pathlib import Path

import pytest

from ideaforge import config

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"

sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(autouse=True)
def no_claude_cli(monkeypatch):
    """Keep tests hermetic: meta.json never spawns the real `claude --version` (IF-308)."""
    monkeypatch.setenv("IDEAFORGE_CLAUDE_CODE_VERSION", "0.0.0-test")


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An isolated project root: runs/, cache/, a temp DB and no dev marker.

    config/, prompts/ and agent_templates/ still point at the real repo.
    """
    root = tmp_path / "proj"
    (root / "runs").mkdir(parents=True)
    (root / "cache").mkdir()
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(config, "RUNS_DIR", root / "runs")
    monkeypatch.setattr(config, "CACHE_DIR", root / "cache")
    monkeypatch.setattr(config, "DEV_MARKER", root / ".ideaforge-dev")
    monkeypatch.setenv("IDEAFORGE_DB", str(root / "test.db"))
    monkeypatch.delenv("IDEAFORGE_RUN_ID", raising=False)
    monkeypatch.delenv("HARNESS_LOOP", raising=False)  # set when pytest runs inside a driver session
    return root


@pytest.fixture
def active_run(project):
    """A run directory registered as the active run."""
    from ideaforge import runs

    run_id = "20261023-120000-test-idea"
    runs.create_run_dir(run_id, "test idea")
    runs.set_active(run_id)
    return project / "runs" / run_id


SYNTHETIC_RUN = "20261023-100000-sauna-cabins"


@pytest.fixture
def synthetic_run(project):
    """A synthetic run for the usage report and /status: fixed-time stage rows, claims in every
    verification state, kill-trigger flags, markers and tests/fixtures/status/usage.synthetic.jsonl.
    Values are invented for logic tests only (TICKETS.md plan note 14)."""
    import shutil

    from ideaforge import db, runs

    db.init()
    run_dir = runs.create_run_dir(SYNTHETIC_RUN, "Sauna-and-lake cabin rentals for remote workers")
    shutil.copy(FIXTURES / "status" / "usage.synthetic.jsonl", run_dir / "usage.jsonl")
    (run_dir / "BUDGET_EXCEEDED_research-pricing").write_text("WebSearch: 9 > 8\n", encoding="utf-8")
    (run_dir / "VALIDATION_FAILED_research-gtm").write_text(
        "figure without a following > quote: 'about 40 cabins'\n", encoding="utf-8"
    )
    (run_dir / "VALIDATION_WARNINGS_research-market").write_text(
        "no [src: …] on: 'Demand peaks in July.'\nno [src: …] on: 'Most guests drive.'\n", encoding="utf-8"
    )
    (run_dir / "00_spec.json").write_text('{"kill_trigger_overrides": ["permit_impossible"]}', encoding="utf-8")

    stage_times = {
        "intake": ("done", 1, "2026-10-23T10:00:00+00:00", "2026-10-23T10:02:00+00:00"),
        "plan": ("done", 1, "2026-10-23T10:02:00+00:00", "2026-10-23T10:05:00+00:00"),
        "research:market": ("done", 1, "2026-10-23T10:05:00+00:00", "2026-10-23T10:20:00+00:00"),
        "research:pricing": ("done", 2, "2026-10-23T10:05:05+00:00", "2026-10-23T10:25:00+00:00"),
        "research:gtm": ("failed", 2, "2026-10-23T10:05:07+00:00", "2026-10-23T10:12:00+00:00"),
        # restarted after it had finished once: the old finished_at stays, the window is open
        "research:killcause": ("running", 2, "2026-10-23T10:05:10+00:00", "2026-10-23T10:04:00+00:00"),
    }
    with db.session() as conn:
        conn.execute(
            "INSERT INTO runs(run_id, idea_text, created_at, budget_preset) VALUES (?,?,?,?)",
            (SYNTHETIC_RUN, "Sauna-and-lake cabin rentals for remote workers\nsecond line",
             "2026-10-23T10:00:00+00:00", "standard"),
        )
        conn.execute(
            "INSERT INTO runs(run_id, idea_text, created_at, budget_preset, status) VALUES (?,?,?,?,?)",
            ("20261020-090000-berry-drying", "Berry drying service", "2026-10-20T09:00:00+00:00",
             "economy", "abandoned"),
        )
        for rid in (SYNTHETIC_RUN, "20261020-090000-berry-drying"):
            for stage in runs.STAGES:
                status, attempts, started, finished = (
                    stage_times.get(stage, ("pending", 0, None, None)) if rid == SYNTHETIC_RUN
                    else ("pending", 0, None, None)
                )
                conn.execute(
                    "INSERT INTO stages(run_id, stage, status, started_at, finished_at, attempts)"
                    " VALUES (?,?,?,?,?,?)",
                    (rid, stage, status, started, finished, attempts),
                )
        claims = [
            ("market-001", "market", "verified", []),
            ("market-002", "market", "unverified", ["unfetchable"]),
            ("competition-001", "competition", "verified", ["free_good_enough_substitute"]),
            ("competition-002", "competition", "conflict", []),
            ("regulation-001", "regulation", "verified", ["permit_impossible"]),
            ("pricing-001", "pricing", "pending", []),
            ("killcause-001", "killcause", "unverified", ["permit_impossible", "robots_disallowed"]),
            ("killcause-002", "killcause", "verified", ["free_good_enough_substitute"]),
            ("killcause-003", "killcause", "conflict", ["no_evidence_anyone_pays"]),
        ]
        conn.executemany(
            "INSERT INTO claims(run_id, claim_id, dimension, statement, source_url, source_title, quote,"
            " retrieved_at, source_type, confidence, flags, verification)"
            " VALUES (?,?,?,'synthetic statement','https://example.invalid/synthetic','synthetic',"
            " 'synthetic quote','2026-10-23T10:35:00+00:00','news',0.5,?,?)",
            [(SYNTHETIC_RUN, cid, dim, json.dumps(flags), state) for cid, dim, state, flags in claims],
        )
    return run_dir
