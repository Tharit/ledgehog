#!/bin/sh
# Frontend verify watcher: re-runs gen:api, prettier --write, check/lint/test and build on every change.
# Sandboxed (no network; writes limited to frontend/src and the build/cache dirs); agents read frontend/.verify/summary.txt.
cd "$(dirname "$0")"
./sandbox/run.sh frontend-verify --allow "$PWD/frontend/src" -- scripts/fe_verify.sh --watch --gen --build --format
