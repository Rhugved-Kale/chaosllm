"""CLI stub commands exit non-zero with a message until their phase lands."""

from __future__ import annotations

from typer.testing import CliRunner

from chaosllm.cli import app

runner = CliRunner()


def test_run_stub_exits_nonzero() -> None:
    result = runner.invoke(app, ["run", "experiments/does-not-matter.yaml"])
    assert result.exit_code == 1
    assert "Phase 3" in result.output


def test_report_stub_exits_nonzero() -> None:
    result = runner.invoke(app, ["report", "some-run-id"])
    assert result.exit_code == 1


def test_demo_stub_exits_nonzero() -> None:
    result = runner.invoke(app, ["demo", "up"])
    assert result.exit_code == 1


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("proxy", "run", "report", "demo"):
        assert command in result.output
