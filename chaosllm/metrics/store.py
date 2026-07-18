"""SQLite summary store: one row per run, one per (run, phase), one per assertion.

The per-request firehose stays JSONL (`tap.py` for the proxy, the runner's
own event log for target-app requests); this store holds the aggregated
summary a report renders from. Stdlib sqlite3, no ORM, per CLAUDE.md.

Writes here happen a handful of times per run (once per phase, once at
finish), not per request, so blocking the event loop briefly on each sqlite3
call is an acceptable v0.1 simplification over a thread offload.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@dataclass
class PhaseSummary:
    phase: str
    total_count: int
    success_count: int
    error_count: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_p99_ms: float | None
    error_taxonomy: dict[str, int]


@dataclass
class AssertionResult:
    idx: int
    type: str
    passed: bool
    detail: str


@dataclass
class RunRecord:
    run_id: str
    name: str
    description: str
    spec_path: str
    started_at: str
    finished_at: str | None
    status: str
    fault_fire_counts: dict[str, int]


class MetricsStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_run(
        self, *, run_id: str, name: str, description: str, spec_path: str, started_at: str
    ) -> None:
        self._conn.execute(
            "INSERT INTO runs (run_id, name, description, spec_path, started_at, status) "
            "VALUES (?, ?, ?, ?, ?, 'running')",
            (run_id, name, description, spec_path, started_at),
        )
        self._conn.commit()

    def finish_run(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        fault_fire_counts: dict[str, int],
    ) -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, fault_fire_counts = ? WHERE run_id = ?",
            (finished_at, status, json.dumps(fault_fire_counts), run_id),
        )
        self._conn.commit()

    def record_phase_summary(self, run_id: str, summary: PhaseSummary) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO requests "
            "(run_id, phase, total_count, success_count, error_count, "
            " latency_p50_ms, latency_p95_ms, latency_p99_ms, error_taxonomy) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                summary.phase,
                summary.total_count,
                summary.success_count,
                summary.error_count,
                summary.latency_p50_ms,
                summary.latency_p95_ms,
                summary.latency_p99_ms,
                json.dumps(summary.error_taxonomy),
            ),
        )
        self._conn.commit()

    def record_assertion(self, run_id: str, result: AssertionResult) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO assertions (run_id, idx, type, passed, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, result.idx, result.type, int(result.passed), result.detail),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return RunRecord(
            run_id=row["run_id"],
            name=row["name"],
            description=row["description"],
            spec_path=row["spec_path"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            fault_fire_counts=json.loads(row["fault_fire_counts"]),
        )

    def get_phase_summaries(self, run_id: str) -> list[PhaseSummary]:
        rows = self._conn.execute(
            "SELECT * FROM requests WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        return [
            PhaseSummary(
                phase=row["phase"],
                total_count=row["total_count"],
                success_count=row["success_count"],
                error_count=row["error_count"],
                latency_p50_ms=row["latency_p50_ms"],
                latency_p95_ms=row["latency_p95_ms"],
                latency_p99_ms=row["latency_p99_ms"],
                error_taxonomy=json.loads(row["error_taxonomy"]),
            )
            for row in rows
        ]

    def get_assertions(self, run_id: str) -> list[AssertionResult]:
        rows = self._conn.execute(
            "SELECT * FROM assertions WHERE run_id = ? ORDER BY idx", (run_id,)
        ).fetchall()
        return [
            AssertionResult(
                idx=row["idx"], type=row["type"], passed=bool(row["passed"]), detail=row["detail"]
            )
            for row in rows
        ]
