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
#   scripts/fe_verify.sh --gen         first run `npm run gen:api` (when openapi.json exists)
#   scripts/fe_verify.sh --format      first rewrite files with `prettier --write`
#
# When lint fails, the report also lists what prettier would change (a diff per file).
#
# Needs only bash, npm and find. The report holds tool output (type errors, test failures)
# and no secrets; frontend/.verify/ is git-ignored.
set -u

cd "$(dirname "$0")/../frontend" || { echo "frontend/ does not exist yet" >&2; exit 2; }

steps=(check lint test)
watch=0
gen=0
format=0
for arg in "$@"; do
  case "$arg" in
    --build) steps+=(build) ;;
    --watch) watch=1 ;;
    --gen) gen=1 ;;
    --format) format=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

out=.verify
mkdir -p "$out"

prettier_diffs() {
  echo ""
  echo "== prettier: what --write would change (diff: file vs formatted)"
  npx prettier --list-different . 2>/dev/null | while read -r file; do
    echo "--- $file"
    npx prettier "$file" 2>/dev/null | diff "$file" - || true
  done
}

run_all() {
  local started failed=0
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  : > "$out/summary.tmp"
  : > "$out/report.tmp"
  echo "== frontend verify, started $started" >> "$out/report.tmp"
  if [ "$format" -eq 1 ]; then
    npx prettier --write . > /dev/null 2>&1
  fi
  local run_steps=("${steps[@]}")
  if [ "$gen" -eq 1 ] && [ -f openapi.json ]; then run_steps=(gen:api "${steps[@]}"); fi
  for step in "${run_steps[@]}"; do
    echo "" >> "$out/report.tmp"
    echo "== npm run $step" >> "$out/report.tmp"
    npm run "$step" >> "$out/report.tmp" 2>&1
    local code=$?
    echo "== exit: $code" >> "$out/report.tmp"
    if [ "$step" = lint ] && [ "$code" -ne 0 ]; then prettier_diffs >> "$out/report.tmp"; fi
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
watched=(src static openapi.json package.json tsconfig.json svelte.config.js vite.config.ts eslint.config.js)
while true; do
  touch "$out/.stamp"
  run_all
  echo "-- watching for changes (Ctrl-C to stop)"
  while true; do
    sleep 2
    # api.d.ts is OUTPUT of a run (`--gen` rewrites it every time): counting it as a change would
    # make every run trigger the next, and Vite's dev server would reload on each rewrite.
    if [ -n "$(find "${watched[@]}" -type f ! -path 'src/lib/types/api.d.ts' -newer "$out/.stamp" 2>/dev/null | head -n 1)" ]; then
      break
    fi
  done
done
