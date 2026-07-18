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
    """One proxied request, as logged to the metrics tap."""

    request_id: str
    timestamp: str
    method: str
    route: str
    upstream: str
    status: int
    latency_ms: float
    faults_fired: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "method": self.method,
            "route": self.route,
            "upstream": self.upstream,
            "status": self.status,
            "latency_ms": self.latency_ms,
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
