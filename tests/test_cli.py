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


def test_run_missing_spec_file_is_a_clean_usage_error() -> None:
    """A typo'd path must be a one-line usage error, not a raw
    FileNotFoundError traceback."""
    result = runner.invoke(app, ["run", "/no/such/spec.yaml"])
    assert result.exit_code == 2
    assert "does not exist" in result.output
    assert "Traceback" not in result.output


def test_run_invalid_spec_prints_the_line_numbered_error(tmp_path: Path) -> None:
    """A spec that fails pydantic validation must surface the loader's own
    line-numbered message, not a raw ValidationError traceback: this is
    exactly the message chaosllm/spec/loader.py was written to produce."""
    spec_path = tmp_path / "bad-spec.yaml"
    spec_path.write_text(
        """\
name: bad-spec-test
target:
  base_url: http://localhost:8100
  endpoint: POST /ask
  payload_file: payloads/questions.jsonl
load:
  concurrency: not-a-number
  duration_s: 30
  warmup_s: 10
"""
    )
    result = runner.invoke(app, ["run", str(spec_path)])
    assert result.exit_code == 1
    assert f"{spec_path}:7" in result.output
    assert "Traceback" not in result.output


def test_demo_rejects_unknown_action() -> None:
    result = runner.invoke(app, ["demo", "sideways"])
    assert result.exit_code == 1
    assert "up|down" in result.output


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("proxy", "run", "report", "demo"):
        assert command in result.output
