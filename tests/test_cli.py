"""CLI surface: argument validation and error paths that don't need a live proxy.

`run` and `report`'s happy paths are covered by the end-to-end test
(test_runner_e2e.py), which drives a real proxy and target app; a CliRunner
invocation can't set that up cheaply, so this file sticks to what's testable
in isolation.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from chaosllm.cli import app

runner = CliRunner()


def test_report_missing_run_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["report", "no-such-run", "--db", str(tmp_path / "empty.db")])
    assert result.exit_code == 1
    assert "no such run" in result.output


def test_demo_rejects_unknown_action() -> None:
    result = runner.invoke(app, ["demo", "sideways"])
    assert result.exit_code == 1
    assert "up|down" in result.output


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("proxy", "run", "report", "demo"):
        assert command in result.output
