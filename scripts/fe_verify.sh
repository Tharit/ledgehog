#!/usr/bin/env bash
# Run the frontend checks and write a report that an agent can read.
#
# Why: the agents' sandbox cannot read frontend/node_modules, so they cannot run vite,
# svelte-check, vitest or eslint themselves. You run this in a spare terminal; they read
# frontend/.verify/summary.txt (one line per step) and report.txt (the full output).
#
#   scripts/fe_verify.sh               run check, lint and test once
#   scripts/fe_verify.sh --build       ... and also `npm run build`
#   scripts/fe_verify.sh --watch       re-run whenever a source or config file changes
#   scripts/fe_verify.sh --watch --build
#
# Needs only bash, npm and find. The report holds tool output (type errors, test failures)
# and no secrets; frontend/.verify/ is git-ignored.
set -u

cd "$(dirname "$0")/../frontend" || { echo "frontend/ does not exist yet" >&2; exit 2; }

steps=(check lint test)
watch=0
for arg in "$@"; do
  case "$arg" in
    --build) steps+=(build) ;;
    --watch) watch=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

out=.verify
mkdir -p "$out"

run_all() {
  local started failed=0
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  : > "$out/summary.tmp"
  : > "$out/report.tmp"
  echo "== frontend verify, started $started" >> "$out/report.tmp"
  for step in "${steps[@]}"; do
    echo "" >> "$out/report.tmp"
    echo "== npm run $step" >> "$out/report.tmp"
    npm run "$step" >> "$out/report.tmp" 2>&1
    local code=$?
    echo "== exit: $code" >> "$out/report.tmp"
    if [ "$code" -eq 0 ]; then echo "$step: ok" >> "$out/summary.tmp"; else echo "$step: FAILED ($code)" >> "$out/summary.tmp"; failed=1; fi
  done
  {
    echo "finished: $(date -u +%Y-%m-%dT%H:%M:%SZ) (started $started)"
    cat "$out/summary.tmp"
    if [ "$failed" -eq 0 ]; then echo "result: ALL OK"; else echo "result: FAILURES (see report.txt)"; fi
  } > "$out/summary.txt"
  mv "$out/report.tmp" "$out/report.txt"
  rm -f "$out/summary.tmp"
  cat "$out/summary.txt"
  return "$failed"
}

if [ "$watch" -eq 0 ]; then
  run_all
  exit $?
fi

# Poll for changes: a file newer than the stamp written at the start of the last run.
# (Edits made while a run is in progress are caught by the next poll.)
watched=(src static package.json tsconfig.json svelte.config.js vite.config.ts eslint.config.js)
while true; do
  touch "$out/.stamp"
  run_all
  echo "-- watching for changes (Ctrl-C to stop)"
  while true; do
    sleep 2
    if [ -n "$(find "${watched[@]}" -type f -newer "$out/.stamp" 2>/dev/null | head -n 1)" ]; then
      break
    fi
  done
done
