#!/bin/sh
. ./test.env
# uv run python scripts/dev_db.py drop
uv run python scripts/dev_db.py create          # once; creates dev_ledgehog and migrates it
export POSTGRES_DB=$(uv run python scripts/dev_db.py name)
export BASE_CURRENCY=EUR TIMEZONE=Europe/Berlin
export USER_1_LOGIN=martin USER_1_NAME=Martin USER_1_PASSWORD='martin'
export EXPOSE_OPENAPI=true                       # optional; development only
uv run uvicorn app.main:app --port 8000          # exactly one worker
