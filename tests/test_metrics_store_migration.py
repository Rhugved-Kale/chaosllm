"""MetricsStore upgrades a pre-v2 (schema_version=1) DB in place.

v2 added requests.fault_fire_counts and runs.warnings. A DB created by the
v1 store (no schema_version row at all, or version=1 with neither column)
must open cleanly, gain the new columns with their defaults, and end up at
schema_version=2, without losing any existing rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from chaosllm.metrics.store import SCHEMA_VERSION, MetricsStore


def _create_v1_database(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (1);

            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                spec_path TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                fault_fire_counts TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE requests (
                run_id TEXT NOT NULL REFERENCES runs (run_id),
                phase TEXT NOT NULL,
                total_count INTEGER NOT NULL,
                success_count INTEGER NOT NULL,
                error_count INTEGER NOT NULL,
                latency_p50_ms REAL,
                latency_p95_ms REAL,
                latency_p99_ms REAL,
                error_taxonomy TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (run_id, phase)
            );

            CREATE TABLE assertions (
                run_id TEXT NOT NULL REFERENCES runs (run_id),
                idx INTEGER NOT NULL,
                type TEXT NOT NULL,
                passed INTEGER NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (run_id, idx)
            );

            INSERT INTO runs (run_id, name, spec_path, started_at, status, fault_fire_counts)
            VALUES ('old-run-1', 'old-run', 'spec.yaml', '2026-01-01T00:00:00+00:00',
                    'completed', '{"error": 3}');

            INSERT INTO requests (run_id, phase, total_count, success_count, error_count)
            VALUES ('old-run-1', 'chaos', 10, 7, 3);
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_migrates_v1_database_and_preserves_existing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    _create_v1_database(db_path)

    store = MetricsStore(db_path)
    try:
        version_row = store._conn.execute("SELECT version FROM schema_version").fetchone()
        assert version_row["version"] == SCHEMA_VERSION

        run = store.get_run("old-run-1")
        assert run is not None
        assert run.name == "old-run"
        assert run.fault_fire_counts == {"error": 3}
        assert run.warnings == []  # new column, defaulted for pre-existing rows

        phases = store.get_phase_summaries("old-run-1")
        assert len(phases) == 1
        assert phases[0].total_count == 10
        assert phases[0].fault_fire_counts == {}  # new column, defaulted
    finally:
        store.close()


def test_migration_is_idempotent_across_repeated_opens(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    _create_v1_database(db_path)

    MetricsStore(db_path).close()
    store = MetricsStore(db_path)
    try:
        version_row = store._conn.execute("SELECT version FROM schema_version").fetchone()
        assert version_row["version"] == SCHEMA_VERSION
        assert store.get_run("old-run-1") is not None
    finally:
        store.close()


def test_fresh_database_starts_at_current_schema_version(tmp_path: Path) -> None:
    store = MetricsStore(tmp_path / "new.db")
    try:
        version_row = store._conn.execute("SELECT version FROM schema_version").fetchone()
        assert version_row["version"] == SCHEMA_VERSION
    finally:
        store.close()
