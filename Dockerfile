FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY chaosllm ./chaosllm

RUN pip install --no-cache-dir .

# Not part of the Python package: bundled so the "Run a live experiment"
# trigger endpoint (chaosllm/proxy/demo_trigger.py) can load its spec and
# payload file straight off disk at runtime, the same way any other
# chaosllm run invocation resolves paths relative to the cwd.
COPY experiments ./experiments
COPY payloads ./payloads

ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands; Railway assigns this at runtime, docker-compose
# leaves it at the ENV default above.
CMD chaosllm proxy --host 0.0.0.0 --port $PORT
