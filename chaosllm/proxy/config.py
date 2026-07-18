"""proxy.yaml: passthrough targets for the generic /passthrough/{id}/* route.

DESIGN.md 4.1: `/openai/*` and `/anthropic/*` are hardcoded since those
providers are the primary target; anything else (vector DBs, other HTTP
upstreams) is named in this config and reached through /passthrough/{id}/*.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class PassthroughTarget(BaseModel):
    base_url: str


class ProxyConfig(BaseModel):
    passthrough: dict[str, PassthroughTarget] = {}

    @classmethod
    def load(cls, path: Path) -> ProxyConfig:
        """Load from a YAML file.

        A missing file yields an empty config (no passthrough targets,
        /openai and /anthropic still work), so running the proxy without a
        proxy.yaml is a valid starting point.
        """
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)
