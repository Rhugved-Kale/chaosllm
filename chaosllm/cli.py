"""chaosllm CLI: proxy | run | report | demo."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import typer
import uvicorn

from chaosllm.metrics.store import MetricsStore
from chaosllm.proxy.app import create_app
from chaosllm.proxy.config import ProxyConfig
from chaosllm.report.render import RunNotFoundError, render_json, render_markdown
from chaosllm.runner.runner import run_experiment

app = typer.Typer(help="Chaos engineering for LLM-powered applications.")


@app.command()
def proxy(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
    config_path: Path = typer.Option(
        Path("proxy.yaml"), "--config", help="Path to the proxy.yaml passthrough config."
    ),
    metrics_path: Path = typer.Option(
        Path("metrics.jsonl"), "--metrics", help="Path to the JSONL metrics log."
    ),
) -> None:
    """Run the fault-injection proxy."""
    proxy_config = ProxyConfig.load(config_path)
    asgi_app = create_app(config=proxy_config, metrics_path=metrics_path)
    uvicorn.run(asgi_app, host=host, port=port)


@app.command()
def run(
    spec: Path = typer.Argument(..., help="Path to an experiment YAML spec."),
    proxy_url: str = typer.Option(
        "http://127.0.0.1:8000", help="Base URL of the running proxy's control API."
    ),
    proxy_metrics: Path = typer.Option(
        Path("metrics.jsonl"), help="Path to the proxy's JSONL metrics log."
    ),
    db: Path = typer.Option(Path("chaosllm.db"), help="Path to the SQLite summary store."),
    runs_dir: Path = typer.Option(Path("runs"), help="Directory for per-run JSONL event logs."),
) -> None:
    """Run an experiment against a target app and print its report."""
    summary = asyncio.run(
        run_experiment(
            spec,
            proxy_url=proxy_url,
            proxy_metrics_path=proxy_metrics,
            db_path=db,
            runs_dir=runs_dir,
        )
    )
    store = MetricsStore(db)
    try:
        typer.echo(render_markdown(store, summary.run_id))
    finally:
        store.close()

    for warning in summary.warnings:
        typer.echo(f"warning: {warning}", err=True)


@app.command()
def report(
    run_id: str = typer.Argument(..., help="Run id to report on."),
    db: Path = typer.Option(Path("chaosllm.db"), help="Path to the SQLite summary store."),
    as_json: bool = typer.Option(False, "--json", help="Render as JSON instead of Markdown."),
) -> None:
    """Render a resilience report for a completed run."""
    store = MetricsStore(db)
    try:
        if as_json:
            typer.echo(json.dumps(render_json(store, run_id), indent=2))
        else:
            typer.echo(render_markdown(store, run_id))
    except RunNotFoundError:
        typer.echo(f"no such run: {run_id}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        store.close()


@app.command()
def demo(action: str = typer.Argument(..., help="up | down")) -> None:
    """Start or stop the demo stack via docker compose."""
    if action not in ("up", "down"):
        typer.echo("usage: chaosllm demo [up|down]", err=True)
        raise typer.Exit(code=1)
    args = (
        ["docker", "compose", "up", "-d", "--build"]
        if action == "up"
        else ["docker", "compose", "down"]
    )
    result = subprocess.run(args, check=False)
    raise typer.Exit(code=result.returncode)


if __name__ == "__main__":
    app()
