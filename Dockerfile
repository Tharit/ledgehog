# syntax=docker/dockerfile:1
# Household ledger image (spec/architecture.md §10, spec/deployment.md §4).
# Three stages: the Node stage builds the frontend, the Python stage installs the locked
# dependencies, the final stage carries the virtual environment and the bundle only.
#
# Base images are meant to be pinned by digest: replace each `image:tag` below by
# `image:tag@sha256:<digest>` (`docker buildx imagetools inspect <image>:<tag>`), see README.md.

# ---------------------------------------------------------------- frontend bundle
# pin: node:22-slim@sha256:…
FROM node:22-slim AS frontend
WORKDIR /build/frontend
# .npmrc comes with it: install scripts stay off (ignore-scripts=true)
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
# `prepare` (svelte-kit sync) does not run with scripts off; the build needs its generated files
RUN npx svelte-kit sync && npm run build

# ---------------------------------------------------------------- python dependencies
# pin: python:3.12-slim@sha256:…
FROM python:3.12-slim AS python
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON_PREFERENCE=only-system
# /app is also the final stage's path: the project is installed editable, so the virtual
# environment points at its source directory
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app/ ./app/
# honours [tool.uv]: no-build (the project's own editable build, with its pinned build constraints,
# is the only build), hash-checked wheels from the lock
RUN uv sync --locked --no-dev

# ---------------------------------------------------------------- final image
# pin: python:3.12-slim@sha256:…
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/tmp
RUN groupadd --system --gid 10001 ledgehog \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin ledgehog
WORKDIR /app
COPY --from=python /app/.venv /app/.venv
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini pyproject.toml ./
# where app/main.py looks for it: <repo root>/frontend/build
COPY --from=frontend /build/frontend/build ./frontend/build
USER 10001:10001
EXPOSE 8000
# no health endpoint: the bundle's index.html answers without a session once the start sequence
# (migrations included) has finished and the app is bound
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/', timeout=4)"]
# exactly one worker, never --workers (architecture §3)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
