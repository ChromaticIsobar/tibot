FROM ghcr.io/astral-sh/uv:0.11.7-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm

RUN groupadd --system tibot && useradd --system --gid tibot --home-dir /app tibot
WORKDIR /app
COPY --from=builder --chown=tibot:tibot /app/.venv /app/.venv
COPY --chown=tibot:tibot src ./src
COPY --chown=tibot:tibot modules/ti4 ./modules/ti4
RUN mkdir /data && chown tibot:tibot /data

ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE_PATH=/data/tibot.db \
    PYTHONUNBUFFERED=1
USER tibot
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-m", "tibot.healthcheck"]
CMD ["tibot"]

