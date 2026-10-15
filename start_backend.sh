#!/bin/sh
. ./test.env
#uv run python scripts/dev_db.py drop
#uv run python scripts/dev_db.py create          # once; creates dev_ledgehog and migrates it
uv run uvicorn app.main:app --port 8000          # exactly one worker
