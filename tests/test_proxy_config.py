"""ProxyConfig.load: valid YAML, and a missing file falling back to empty."""

from __future__ import annotations

from pathlib import Path

from chaosllm.proxy.config import ProxyConfig


def test_load_missing_file_returns_empty_config(tmp_path: Path) -> None:
    config = ProxyConfig.load(tmp_path / "does-not-exist.yaml")
    assert config.passthrough == {}


def test_load_parses_passthrough_targets(tmp_path: Path) -> None:
    config_path = tmp_path / "proxy.yaml"
    config_path.write_text(
        "passthrough:\n  vectordb:\n    base_url: http://localhost:9000\n",
        encoding="utf-8",
    )

    config = ProxyConfig.load(config_path)

    assert config.passthrough["vectordb"].base_url == "http://localhost:9000"
