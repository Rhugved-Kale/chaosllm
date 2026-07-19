FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY chaosllm ./chaosllm

RUN pip install --no-cache-dir .

ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands; Railway assigns this at runtime, docker-compose
# leaves it at the ENV default above.
CMD chaosllm proxy --host 0.0.0.0 --port $PORT
