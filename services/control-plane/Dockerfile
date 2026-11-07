# syntax=docker/dockerfile:1
# SPDX-License-Identifier: Apache-2.0

# ── Build: resolve dependencies exactly as pinned in uv.lock ──────────────────
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.20 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first (cached layer), then the project itself, non-editable so
# the runtime image needs no source checkout beyond the installed package.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY raggie_control_plane ./raggie_control_plane
RUN uv sync --frozen --no-dev --no-editable

# ── Runtime: only the virtualenv + migrations, non-root ──────────────────────
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# The runtime never installs packages: drop the base image's pip, whose
# vendored urllib3 / msgpack / setuptools lag the venv's patched versions.
RUN python -m pip uninstall -y -q pip \
    && useradd -m -u 10001 raggie

COPY --from=build /app/.venv /app/.venv
COPY migrations ./migrations
# The package resolves migrations next to itself (../migrations) unless told
# otherwise; point it at the shipped copy explicitly.
ENV MIGRATIONS_DIR=/app/migrations

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"]
CMD ["uvicorn", "raggie_control_plane.main:app", "--host", "0.0.0.0", "--port", "8000"]
