"""JSONL metrics tap: one line per proxied request.

JSONL is the Phase 1 sink because it needs no schema and is trivially
diffable in a PR. SQLite (`runs`, `requests`, `assertions`) lands in Phase 3
once the runner needs queryable per-phase aggregates; see DESIGN.md 4.4.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    """Current UTC time as an ISO 8601 string, for record timestamps."""
    return datetime.now(UTC).isoformat()


@dataclass
class RequestRecord:
    """One proxied request, as logged to the metrics tap.

    Three separate timing fields rather than one merged `latency_ms`
    (DESIGN.md 4.1: "latency (proxy-added and upstream)"): `total_ms` is what
    the caller actually waited, `upstream_ms` is the real provider call alone
    (None when short-circuited, no upstream call happened), and
    `injected_delay_ms` is the `latency` fault's own sleep. A latency fault
    sleeping before forwarding was previously invisible in the logged number
    entirely (only the post-sleep upstream call was timed), so a request that
    took 2.8s end to end could show ~0.8s in the log.
    """

    request_id: str
    timestamp: str
    method: str
    route: str
    upstream: str
    status: int
    total_ms: float
    upstream_ms: float | None
    injected_delay_ms: float
    faults_fired: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "method": self.method,
            "route": self.route,
            "upstream": self.upstream,
            "status": self.status,
            "total_ms": self.total_ms,
            "upstream_ms": self.upstream_ms,
            "injected_delay_ms": self.injected_delay_ms,
            "faults_fired": self.faults_fired,
        }


class MetricsTap:
    """Appends one JSON object per line to a metrics file.

    Guarded by an asyncio.Lock rather than opening the file once and holding
    it, since the proxy is a single process but handles requests concurrently;
    the lock keeps interleaved writes from producing a corrupt line.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def record(self, record: RequestRecord) -> None:
        line = json.dumps(record.to_json()) + "\n"
        async with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)


def fault_fire_counts_since(path: Path, *, since: str, until: str) -> dict[str, int]:
    """Count fault fires logged in `path` within [since, until] (inclusive).

    Backs the control API's GET /control/metrics/summary, which exists so a
    caller queries the proxy's own live metrics over HTTP instead of reading
    metrics.jsonl by file path. That assumption breaks the moment the proxy
    runs in a different process or container than the caller: the runner did
    exactly that, silently reading a stale or nonexistent file and always
    seeing zero fault fires.
    """
    if not path.exists():
        return {}
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        timestamp = record.get("timestamp", "")
        if not (since <= timestamp <= until):
            continue
        for fault_id in record.get("faults_fired", []):
            counts[fault_id] = counts.get(fault_id, 0) + 1
    return counts
