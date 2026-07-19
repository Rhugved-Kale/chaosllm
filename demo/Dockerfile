FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY demo ./demo

RUN pip install --no-cache-dir .

ENV PORT=8100
EXPOSE 8100

# Shell form so $PORT expands; Railway assigns this at runtime, docker-compose
# leaves it at the ENV default above.
CMD uvicorn demo.main:app --host 0.0.0.0 --port $PORT
