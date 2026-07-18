-- chaosllm metrics schema, version 1.
--
-- The per-request firehose stays JSONL (see tap.py, runner event logs);
-- these tables hold the summary a report is rendered from: one row per run,
-- one row per (run, phase) with aggregated stats, one row per assertion
-- result. Bump `schema_version` and add migration statements below when this
-- shape changes.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    spec_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    fault_fire_counts TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS requests (
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

CREATE TABLE IF NOT EXISTS assertions (
    run_id TEXT NOT NULL REFERENCES runs (run_id),
    idx INTEGER NOT NULL,
    type TEXT NOT NULL,
    passed INTEGER NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, idx)
);
