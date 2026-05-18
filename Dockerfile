FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# UV_COMPILE_BYTECODE=1: Compile .py files to .pyc bytecode files
# UV_LINK_MODE=copy: Copy files instead of symlinking to avoid issues in final
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./

# --mount=type=cache: Mounts a cache directory for uv to speed up builds and avoid including cache in layers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

FROM python:3.12-slim

# PYTHONUNBUFFERED=1: Force stdout/stderr to be unbuffered
# PYTHONDONTWRITEBYTECODE=1: Prevent Python from writing .pyc files (we compiled them in builder)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

WORKDIR /app

RUN useradd -m appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

COPY --chown=appuser:appuser src/ src/
COPY --chown=appuser:appuser configs/ configs/

USER appuser

CMD ["python", "src/annotate.py", "--max-concurrency", "10", "--rate-limit", "5"]
