#!/bin/sh
. ./test.env
# setup: uv sync --locked      (installs exactly what uv.lock records)
#uv run python scripts/dev_db.py drop
#uv run python scripts/dev_db.py create          # once; creates dev_ledgehog and migrates it
./sandbox/run.sh backend-serve -- .venv/bin/uvicorn app.main:app --port 8000
