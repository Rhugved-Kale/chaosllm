"""chaosllm CLI: proxy | run | report | demo.

`run`, `report`, and `demo` are stubs until their phases land (runner and
demo app in Phase 3, report generator in Phase 3). They exist now so the
command surface is stable across phases.
"""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from chaosllm.proxy.app import create_app
from chaosllm.proxy.config import ProxyConfig

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
def run(spec: Path = typer.Argument(..., help="Path to an experiment YAML spec.")) -> None:
    """Run an experiment against a target app."""
    typer.echo("chaosllm run: not implemented until Phase 3", err=True)
    raise typer.Exit(code=1)


@app.command()
def report(run_id: str = typer.Argument(..., help="Run id to report on.")) -> None:
    """Render a resilience report for a completed run."""
    typer.echo("chaosllm report: not implemented until Phase 3", err=True)
    raise typer.Exit(code=1)


@app.command()
def demo(action: str = typer.Argument(..., help="up | down")) -> None:
    """Start or stop the demo RAG stack."""
    typer.echo("chaosllm demo: not implemented until Phase 3", err=True)
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
