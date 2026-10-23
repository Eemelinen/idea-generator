import json

from pydantic import TypeAdapter

from conftest import FIXTURES
from ideaforge import db, runs
from ideaforge.schemas import Claim

RUN = "20261023-120000-test-idea"


def setup_run():
    db.init()
    db.create_run(RUN, "test idea", idea_id="test-idea", stages=runs.STAGES)


def fixture_claims():
    return TypeAdapter(list[Claim]).validate_json((FIXTURES / "claims.json").read_text(encoding="utf-8"))


def test_init_is_idempotent_and_uses_wal(project):
    db.init()
    db.init()
    with db.session() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"runs", "idea_versions", "stages", "claims", "sources", "scores", "reports", "debates",
            "debate_turns", "assumptions", "experiments", "usage", "reviews", "claims_fts"} <= tables


def test_create_run_registers_all_stages(project):
    setup_run()
    assert [r["stage"] for r in db.stages(RUN)] == runs.STAGES
    assert all(r["status"] == "pending" for r in db.stages(RUN))


def test_upsert_claims_inserts_then_updates(project):
    setup_run()
    claims = fixture_claims()
    assert db.upsert_claims(RUN, claims) == 2
    claims[1].verification = "verified"
    db.upsert_claims(RUN, claims)
    with db.session() as conn:
        rows = conn.execute("SELECT claim_id, verification, flags FROM claims ORDER BY claim_id").fetchall()
    assert [(r["claim_id"], r["verification"]) for r in rows] == [
        ("competition-001", "verified"), ("market-001", "verified")
    ]
    assert json.loads(rows[0]["flags"]) == ["free_good_enough_substitute"]


def test_fts_tracks_inserts_and_updates(project):
    setup_run()
    claims = fixture_claims()
    db.upsert_claims(RUN, claims)
    with db.session() as conn:
        hit = conn.execute("SELECT rowid FROM claims_fts WHERE claims_fts MATCH 'etätyöpiste'").fetchall()
        assert len(hit) == 1
    claims[1].quote = "Kirjasto on suljettu."
    db.upsert_claims(RUN, claims)
    with db.session() as conn:
        assert conn.execute("SELECT * FROM claims_fts WHERE claims_fts MATCH 'etätyöpiste'").fetchall() == []
        assert len(conn.execute("SELECT * FROM claims_fts WHERE claims_fts MATCH 'suljettu'").fetchall()) == 1


def test_stage_lifecycle(project):
    setup_run()
    assert not db.stage_done(RUN, "intake")
    db.stage_set(RUN, "intake", "running")
    db.stage_set(RUN, "intake", "failed")
    db.stage_set(RUN, "intake", "running")
    db.stage_set(RUN, "intake", "done")
    assert db.stage_done(RUN, "intake")
    row = next(r for r in db.stages(RUN) if r["stage"] == "intake")
    assert row["attempts"] == 2
    assert row["started_at"] and row["finished_at"]

    db.stage_set(RUN, "research:gtm", "insufficient_data")
    assert db.stage_done(RUN, "research:gtm")
    assert not db.stage_done(RUN, "no-such-stage")
