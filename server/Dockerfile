ARG PYTHON_BASE_IMAGE=python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
ARG UV_BASE_IMAGE=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a

FROM ${UV_BASE_IMAGE} AS uv

FROM ${PYTHON_BASE_IMAGE} AS builder

ARG UV_DEFAULT_INDEX=https://pypi.org/simple

COPY --from=uv /uv /uvx /bin/

ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX} \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/server

COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server/alembic.ini ./
COPY server/app ./app
COPY server/golden ./golden
COPY server/migrations ./migrations
COPY server/scripts ./scripts
COPY certs/ApsaraDB-CA-Chain.pem /app/certs/ApsaraDB-CA-Chain.pem

FROM ${PYTHON_BASE_IMAGE} AS runtime

ENV PATH="/app/server/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 pdos \
    && useradd --uid 10001 --gid pdos --no-create-home --shell /usr/sbin/nologin pdos

WORKDIR /app/server
COPY --from=builder --chown=pdos:pdos /app /app

USER pdos

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
