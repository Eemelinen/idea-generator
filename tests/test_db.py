import json
import sqlite3

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


# ---------------------------------------------------------------- schema versions and backup (IF-601)


def table_names(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_fresh_database_reaches_the_latest_version(project):
    db.init()
    with db.session() as conn:
        assert db.schema_version(conn) == len(db.MIGRATIONS)
        assert [r["version"] for r in conn.execute("SELECT version FROM schema_version")] == list(
            range(1, len(db.MIGRATIONS) + 1)
        )


def test_database_from_before_versioning_is_migrated_and_keeps_its_rows(project):
    # A database as IF-601's predecessors created it: the plain schema, no schema_version table.
    with db.session() as conn:
        conn.executescript(db.SCHEMA)
        assert db.schema_version(conn) == 0
    db.create_run(RUN, "test idea", idea_id="test-idea", stages=runs.STAGES)
    db.upsert_claims(RUN, fixture_claims())

    db.init()
    with db.session() as conn:
        assert db.schema_version(conn) == len(db.MIGRATIONS)
        assert conn.execute("SELECT idea_text FROM runs").fetchone()[0] == "test idea"
        assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM stages").fetchone()[0] == len(runs.STAGES)
        # the FTS triggers still work on the migrated database
        assert len(conn.execute("SELECT * FROM claims_fts WHERE claims_fts MATCH 'etätyöpiste'").fetchall()) == 1


def test_new_migrations_apply_in_order_once_and_keep_rows(project, monkeypatch):
    setup_run()
    migrations = [
        *db.MIGRATIONS,
        "CREATE TABLE IF NOT EXISTS synthetic_a (x INTEGER);",
        "CREATE TABLE IF NOT EXISTS synthetic_b (y INTEGER REFERENCES runs(run_id));"
        " INSERT INTO synthetic_a(x) SELECT COUNT(*) FROM synthetic_a;",
    ]
    monkeypatch.setattr(db, "MIGRATIONS", migrations)
    db.init()
    db.init()  # idempotent: nothing is applied twice
    with db.session() as conn:
        assert db.schema_version(conn) == len(migrations)
        assert {"synthetic_a", "synthetic_b"} <= table_names(conn)
        # the version-3 insert ran exactly once
        assert conn.execute("SELECT COUNT(*) FROM synthetic_a").fetchone()[0] == 1
        assert conn.execute("SELECT run_id FROM runs").fetchone()[0] == RUN
        versions = conn.execute("SELECT version, applied_at FROM schema_version ORDER BY version").fetchall()
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert all(v["applied_at"] for v in versions)


def test_backup_copy_opens_and_matches(project):
    setup_run()
    db.upsert_claims(RUN, fixture_claims())
    dest = db.backup()
    assert dest.parent == project / "backups"
    assert dest.name.startswith("ideaforge-") and dest.suffix == ".db"
    second = db.backup()
    assert second != dest and second.exists()

    copy = sqlite3.connect(dest)
    try:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for table in ("runs", "idea_versions", "stages", "claims", "schema_version"):
            with db.session() as conn:
                original = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            assert [tuple(r) for r in copy.execute(f"SELECT * FROM {table} ORDER BY rowid")] == original
    finally:
        copy.close()


def test_backup_includes_uncheckpointed_wal_writes(project, tmp_path):
    setup_run()
    holder = db.connect()  # keeps the WAL from being checkpointed into the main file
    try:
        holder.execute("UPDATE runs SET status='abandoned' WHERE run_id=?", (RUN,))
        holder.commit()
        dest = db.backup(tmp_path / "elsewhere")
    finally:
        holder.close()
    assert dest.parent == tmp_path / "elsewhere"
    copy = sqlite3.connect(dest)
    try:
        assert copy.execute("SELECT status FROM runs").fetchone()[0] == "abandoned"
    finally:
        copy.close()


def test_backup_cli(project, capsys, tmp_path):
    assert db.main(["backup"]) == 1
    assert "no database at" in capsys.readouterr().err
    assert not (project / "backups").exists()

    setup_run()
    assert db.main(["backup", "--to", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("wrote ") and str(tmp_path / "out") in out
    assert len(list((tmp_path / "out").glob("ideaforge-*.db"))) == 1

    assert db.main(["init"]) == 0
    assert f"schema version {len(db.MIGRATIONS)}" in capsys.readouterr().out
