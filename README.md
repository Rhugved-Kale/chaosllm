# chaosllm

Chaos engineering for LLM-powered applications. Point your app at the proxy
instead of the provider, inject realistic failures (latency, rate limits,
truncated output, malformed JSON), and see how it degrades.

Status: Phase 1 (skeleton + passthrough proxy). Full pitch, architecture
diagram, and quickstart land in Phase 4 per PLAN.md; see DESIGN.md for the
full v0.1 scope in the meantime.

## Phase 1: what works today

```bash
pip install -e ".[dev]"
chaosllm proxy
```

This starts the fault-injection proxy (no faults yet, just a metrics-logged
passthrough). Point an OpenAI or Anthropic SDK at it by overriding
`base_url`:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/openai/v1", api_key="sk-...")
```

Every request is logged to `metrics.jsonl`. A generic
`/passthrough/{id}/*` route forwards to any HTTP upstream named in
`proxy.yaml`.

## Development

```bash
ruff check .
ruff format --check .
mypy chaosllm
pytest -q
```
