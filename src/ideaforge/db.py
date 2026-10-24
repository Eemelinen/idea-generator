"""SQLite schema and helpers. WAL mode; FTS5 over claim statements and quotes."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ideaforge.config import ROOT
from ideaforge.schemas import Assumption, Claim, DimensionScore, Experiment

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    idea_text     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    budget_preset TEXT NOT NULL DEFAULT 'standard',
    as_of         TEXT,
    status        TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS idea_versions (
    run_id     TEXT PRIMARY KEY REFERENCES runs(run_id),
    idea_id    TEXT NOT NULL,
    version    INTEGER NOT NULL,
    parent     TEXT REFERENCES runs(run_id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stages (
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    stage       TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('pending','running','done','failed','insufficient_data')),
    started_at  TEXT,
    finished_at TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS sources (
    url          TEXT PRIMARY KEY,
    domain       TEXT NOT NULL,
    content_sha  TEXT,
    cache_path   TEXT,
    fetched_at   TEXT,
    http_status  INTEGER
);

CREATE TABLE IF NOT EXISTS claims (
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    claim_id       TEXT NOT NULL,
    dimension      TEXT NOT NULL,
    statement      TEXT NOT NULL,
    value          REAL,
    unit           TEXT,
    source_url     TEXT NOT NULL,
    source_title   TEXT NOT NULL,
    quote          TEXT NOT NULL,
    published_date TEXT,
    retrieved_at   TEXT NOT NULL,
    source_type    TEXT NOT NULL,
    confidence     REAL NOT NULL,
    flags          TEXT NOT NULL DEFAULT '[]',
    verification   TEXT NOT NULL,
    PRIMARY KEY (run_id, claim_id)
);
CREATE INDEX IF NOT EXISTS claims_dim ON claims(run_id, dimension);

CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    statement, quote, content='claims', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS claims_ai AFTER INSERT ON claims BEGIN
    INSERT INTO claims_fts(rowid, statement, quote) VALUES (new.rowid, new.statement, new.quote);
END;
CREATE TRIGGER IF NOT EXISTS claims_ad AFTER DELETE ON claims BEGIN
    INSERT INTO claims_fts(claims_fts, rowid, statement, quote) VALUES ('delete', old.rowid, old.statement, old.quote);
END;
CREATE TRIGGER IF NOT EXISTS claims_au AFTER UPDATE ON claims BEGIN
    INSERT INTO claims_fts(claims_fts, rowid, statement, quote) VALUES ('delete', old.rowid, old.statement, old.quote);
    INSERT INTO claims_fts(rowid, statement, quote) VALUES (new.rowid, new.statement, new.quote);
END;

CREATE TABLE IF NOT EXISTS scores (
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    dimension      TEXT NOT NULL,
    proposed_score REAL NOT NULL,
    final_score    REAL,
    cap_reason     TEXT,
    status         TEXT NOT NULL,
    justification  TEXT NOT NULL,
    claim_ids      TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, dimension)
);

CREATE TABLE IF NOT EXISTS reports (
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    kind           TEXT NOT NULL CHECK (kind IN ('report','revised_plan')),
    path           TEXT NOT NULL,
    weighted_total REAL,
    verdict        TEXT,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (run_id, kind)
);

CREATE TABLE IF NOT EXISTS debates (
    run_id          TEXT PRIMARY KEY REFERENCES runs(run_id),
    rounds          INTEGER NOT NULL DEFAULT 0,
    seed            INTEGER NOT NULL,
    conformity_flag INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running',
    started_at      TEXT NOT NULL,
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS debate_turns (
    run_id   TEXT NOT NULL REFERENCES runs(run_id),
    round    INTEGER NOT NULL,
    role     TEXT NOT NULL,
    anon_id  TEXT,
    attempt  INTEGER NOT NULL DEFAULT 1,
    accepted INTEGER NOT NULL,
    reject_reason TEXT,
    payload  TEXT NOT NULL,
    PRIMARY KEY (run_id, round, role, attempt)
);

CREATE TABLE IF NOT EXISTS assumptions (
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    idx            INTEGER NOT NULL,
    assumption     TEXT NOT NULL,
    evidence_state TEXT NOT NULL,
    risk_if_wrong  TEXT NOT NULL,
    PRIMARY KEY (run_id, idx)
);

CREATE TABLE IF NOT EXISTS experiments (
    run_id            TEXT NOT NULL REFERENCES runs(run_id),
    idx               INTEGER NOT NULL,
    name              TEXT NOT NULL,
    cost_eur          REAL NOT NULL,
    days              REAL NOT NULL,
    success_threshold TEXT NOT NULL,
    info_value        INTEGER NOT NULL,
    result            TEXT,
    PRIMARY KEY (run_id, idx)
);

CREATE TABLE IF NOT EXISTS usage (
    ts            TEXT NOT NULL,
    run_id        TEXT,
    stage         TEXT,
    agent         TEXT,
    tool          TEXT NOT NULL,
    model         TEXT,
    approx_tokens INTEGER
);
CREATE INDEX IF NOT EXISTS usage_run ON usage(run_id);

CREATE TABLE IF NOT EXISTS reviews (
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    section    TEXT NOT NULL,
    score      INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    note       TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, section)
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def db_path() -> Path:
    return Path(os.environ.get("IDEAFORGE_DB") or ROOT / "ideaforge.db")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session(path: Path | None = None):
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init(path: Path | None = None) -> None:
    with session(path) as conn:
        conn.executescript(SCHEMA)


def create_run(
    run_id: str,
    idea_text: str,
    *,
    idea_id: str,
    version: int = 1,
    parent: str | None = None,
    budget_preset: str = "standard",
    as_of: str | None = None,
    stages: Iterable[str] = (),
) -> None:
    ts = now()
    with session() as conn:
        conn.execute(
            "INSERT INTO runs(run_id, idea_text, created_at, budget_preset, as_of) VALUES (?,?,?,?,?)",
            (run_id, idea_text, ts, budget_preset, as_of),
        )
        conn.execute(
            "INSERT INTO idea_versions(run_id, idea_id, version, parent, created_at) VALUES (?,?,?,?,?)",
            (run_id, idea_id, version, parent, ts),
        )
        conn.executemany(
            "INSERT INTO stages(run_id, stage, status) VALUES (?,?, 'pending')",
            [(run_id, s) for s in stages],
        )


def upsert_claims(run_id: str, claims: Iterable[Claim]) -> int:
    rows = [
        (
            run_id, c.claim_id, c.dimension, c.statement, c.value, c.unit, c.source_url,
            c.source_title, c.quote,
            c.published_date.isoformat() if c.published_date else None,
            c.retrieved_at.isoformat(), c.source_type, c.confidence, json.dumps(c.flags),
            c.verification,
        )
        for c in claims
    ]
    with session() as conn:
        conn.executemany(
            """
            INSERT INTO claims(run_id, claim_id, dimension, statement, value, unit, source_url,
                source_title, quote, published_date, retrieved_at, source_type, confidence,
                flags, verification)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id, claim_id) DO UPDATE SET
                dimension=excluded.dimension, statement=excluded.statement, value=excluded.value,
                unit=excluded.unit, source_url=excluded.source_url,
                source_title=excluded.source_title, quote=excluded.quote,
                published_date=excluded.published_date, retrieved_at=excluded.retrieved_at,
                source_type=excluded.source_type, confidence=excluded.confidence,
                flags=excluded.flags, verification=excluded.verification
            """,
            rows,
        )
    return len(rows)


def upsert_source(
    url: str,
    domain: str,
    *,
    content_sha: str | None,
    cache_path: str | None,
    fetched_at: str,
    http_status: int | None,
) -> None:
    with session() as conn:
        conn.execute(
            """
            INSERT INTO sources(url, domain, content_sha, cache_path, fetched_at, http_status)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
                domain=excluded.domain, content_sha=excluded.content_sha,
                cache_path=excluded.cache_path, fetched_at=excluded.fetched_at,
                http_status=excluded.http_status
            """,
            (url, domain, content_sha, cache_path, fetched_at, http_status),
        )


def replace_scores(run_id: str, scores: Iterable[DimensionScore]) -> int:
    """Replace a run's `scores` rows with the final score sheet's (one row per dimension)."""
    rows = [
        (
            run_id, s.dimension, s.proposed_score, s.final_score, s.cap_reason, s.status,
            s.justification, json.dumps(s.supporting_claim_ids),
        )
        for s in scores
    ]
    with session() as conn:
        conn.execute("DELETE FROM scores WHERE run_id=?", (run_id,))
        conn.executemany(
            "INSERT INTO scores(run_id, dimension, proposed_score, final_score, cap_reason, status,"
            " justification, claim_ids) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def get_report(run_id: str, kind: str = "report") -> sqlite3.Row | None:
    with session() as conn:
        return conn.execute("SELECT * FROM reports WHERE run_id=? AND kind=?", (run_id, kind)).fetchone()


def add_report(
    run_id: str,
    kind: str,
    path: str,
    *,
    weighted_total: float | None,
    verdict: str | None,
    created_at: str,
    then: Callable[[], None] = lambda: None,
) -> None:
    """Insert a run's `reports` row; raises sqlite3.IntegrityError if it already has one.

    `then` (writing the report file) runs inside the transaction, so if it fails no row is left.
    """
    with session() as conn:
        conn.execute(
            "INSERT INTO reports(run_id, kind, path, weighted_total, verdict, created_at) VALUES (?,?,?,?,?,?)",
            (run_id, kind, path, weighted_total, verdict, created_at),
        )
        then()


def add_revised_plan(
    run_id: str,
    path: str,
    *,
    assumptions: Iterable[Assumption],
    experiments: Iterable[Experiment],
    conformity_flag: bool,
    rounds: int,
    created_at: str,
    then: Callable[[], None] = lambda: None,
) -> None:
    """Store a debate's outcome in one transaction: the `reports` row (kind `revised_plan`; raises
    sqlite3.IntegrityError if it exists), the `assumptions` and `experiments` tables (experiments
    in the given order, idx 1…) and the finished `debates` row. `then` writes the file."""
    with session() as conn:
        conn.execute(
            "INSERT INTO reports(run_id, kind, path, weighted_total, verdict, created_at) VALUES (?,?,?,?,?,?)",
            (run_id, "revised_plan", path, None, None, created_at),
        )
        conn.execute("DELETE FROM assumptions WHERE run_id=?", (run_id,))
        conn.executemany(
            "INSERT INTO assumptions(run_id, idx, assumption, evidence_state, risk_if_wrong) VALUES (?,?,?,?,?)",
            [(run_id, i, a.assumption, a.evidence_state, a.risk_if_wrong) for i, a in enumerate(assumptions, start=1)],
        )
        conn.execute("DELETE FROM experiments WHERE run_id=?", (run_id,))
        conn.executemany(
            "INSERT INTO experiments(run_id, idx, name, cost_eur, days, success_threshold, info_value)"
            " VALUES (?,?,?,?,?,?,?)",
            [
                (run_id, i, e.name, e.cost_eur, e.days, e.success_threshold, e.info_value)
                for i, e in enumerate(experiments, start=1)
            ],
        )
        conn.execute(
            "UPDATE debates SET rounds=?, conformity_flag=?, status='done', finished_at=? WHERE run_id=?",
            (rounds, int(conformity_flag), created_at, run_id),
        )
        then()


def stage_set(run_id: str, stage: str, status: str) -> None:
    ts = now()
    with session() as conn:
        conn.execute(
            """
            INSERT INTO stages(run_id, stage, status, started_at, attempts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id, stage) DO UPDATE SET
                status = excluded.status,
                started_at = CASE WHEN excluded.status = 'running' THEN ? ELSE stages.started_at END,
                finished_at = CASE WHEN excluded.status IN ('done','failed','insufficient_data')
                                   THEN ? ELSE stages.finished_at END,
                attempts = stages.attempts + (excluded.status = 'running')
            """,
            (run_id, stage, status, ts if status == "running" else None,
             1 if status == "running" else 0, ts, ts),
        )


def stage_done(run_id: str, stage: str) -> bool:
    """The stored status only; runs.is_complete also requires the output file to validate."""
    with session() as conn:
        row = conn.execute(
            "SELECT status FROM stages WHERE run_id=? AND stage=?", (run_id, stage)
        ).fetchone()
    return row is not None and row["status"] in ("done", "insufficient_data")


def stages(run_id: str) -> list[sqlite3.Row]:
    with session() as conn:
        return conn.execute(
            "SELECT * FROM stages WHERE run_id=? ORDER BY rowid", (run_id,)
        ).fetchall()


def log_usage(row: dict) -> None:
    with session() as conn:
        conn.execute(
            "INSERT INTO usage(ts, run_id, stage, agent, tool, model, approx_tokens) "
            "VALUES (:ts, :run_id, :stage, :agent, :tool, :model, :approx_tokens)",
            {k: row.get(k) for k in ("ts", "run_id", "stage", "agent", "tool", "model", "approx_tokens")},
        )
