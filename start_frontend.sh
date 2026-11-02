#!/bin/sh
cd "$(dirname "$0")"
./sandbox/run.sh frontend-serve -- sh -c 'cd frontend && npm run dev'
