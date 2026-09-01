FROM python:3.12.11-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
# --extra analysis: pybatfish is declared optional, but the image is what
# decides whether ANALYSIS_ENABLED can do anything. Leaving it out made the
# flag a no-op that failed as 503 at request time.
RUN uv sync --frozen --no-dev --no-install-project --extra analysis

FROM python:3.12.11-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
    && apt-get install --yes --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app app
WORKDIR /app
COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app app ./app
RUN mkdir -p /data/snapshots && chown app:app /data/snapshots
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
