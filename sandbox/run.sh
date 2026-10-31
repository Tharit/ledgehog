#!/usr/bin/env bash
# Run a dev job under a nono sandbox profile (sandbox/<job>.json).
#
#   sandbox/run.sh <job> [extra nono flags...] -- <command...>
#
#   sandbox/run.sh frontend -- scripts/fe_verify.sh --build
#   sandbox/run.sh backend --allow-domain api.example.com -- .venv/bin/uvicorn app.main:app --port 8000
#
# Before starting it
#   - refuses to run while sandbox/ has uncommitted changes (SANDBOX_ALLOW_DIRTY=1 overrides);
#   - refuses to run if the profile would let a canary host through (an open network);
#   - creates the node_modules dirs the frontend jobs may write to (grants on missing dirs are skipped).
#   - proxy-mode jobs (backend, deps) are chained to tinyproxy (nono --upstream-proxy), which only lets
#     CONNECT to ports 443 and 993 through; run.sh starts it on a free localhost port and stops it at exit.
# While it runs (backend by default; SANDBOX_WATCH=1 / 0 forces it on / off) a watcher follows nono's proxy log
# and tinyproxy's log and, on the first denied connection, prints a banner, stops the session and makes run.sh exit 1.
# See sandbox/README.md.
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

job=${1:-}
if [ -z "$job" ] || [ "$job" = -h ] || [ "$job" = --help ] || [ ! -f "sandbox/$job.json" ]; then
  [ -n "$job" ] && [ "$job" != -h ] && [ "$job" != --help ] && echo "unknown job: $job" >&2
  echo "usage: sandbox/run.sh <job> [extra nono flags...] -- <command...>" >&2
  echo "jobs:" >&2
  for f in sandbox/*.json; do basename "$f" .json | sed 's/^/  /' >&2; done
  exit 2
fi
shift
profile="sandbox/$job.json"

if [ -n "$(git status --porcelain sandbox/)" ]; then
  if [ "${SANDBOX_ALLOW_DIRTY:-}" = 1 ]; then
    echo "WARNING: sandbox/ has uncommitted changes; running anyway (SANDBOX_ALLOW_DIRTY=1)" >&2
  else
    echo "refusing to run: sandbox/ has uncommitted changes (commit them, or set SANDBOX_ALLOW_DIRTY=1)" >&2
    exit 1
  fi
fi

# Egress canary: a static policy query (no network). An open network, i.e. no `block` and no non-empty
# allow_domain, would let the canary through. Only the caller's --allow-domain flags are taken into account
# (`nono why` accepts no other run flags), so --allow-domain '*' is caught as well.
canary=egress-canary.invalid
why=(nono why --profile "$profile" --workdir "$root" --host "$canary")
prev=
for a in "$@"; do
  [ "$a" = -- ] && break
  [ "$prev" = --allow-domain ] && why+=(--allow-domain "$a")
  prev=$a
done
if "${why[@]}" 2>&1 | grep -q '^ALLOWED'; then
  echo "refusing to run: $profile lets an arbitrary host through ($canary would be allowed)." >&2
  echo "  Give the profile network.block=true, or a non-empty network.allow_domain (an empty list means an open network)." >&2
  exit 1
fi

if { [ "$job" = frontend ] || [ "$job" = frontend-dev ]; } && [ -d frontend/node_modules ]; then
  mkdir -p frontend/node_modules/.vite frontend/node_modules/.vite-temp 'frontend/node_modules/$app'
fi

# --allow-cwd: without it nono starts the command in / ; the access level still comes from the profile (read)
nono=(nono run --profile "$profile" --workdir "$root" --allow-cwd)

# Proxy-mode jobs (network.allow_domain) are chained to tinyproxy as nono's upstream proxy: nono's proxy
# filters by HOST only and ignores ports, so a listed mail host would also be reachable on its SMTP ports.
# tinyproxy lets only CONNECT to ports 443 and 993 through (plain HTTP is refused outright).
tinyproxy=0
case "$job" in backend | deps) tinyproxy=1 ;; esac

watch=0
[ "$job" = backend ] && watch=1
[ -n "${SANDBOX_WATCH:-}" ] && watch=$SANDBOX_WATCH
if [ "$watch" != 1 ] && [ "$tinyproxy" != 1 ]; then
  exec "${nono[@]}" "$@"
fi

# From here on run.sh supervises nono (no exec): temp dir, tinyproxy and watcher are removed on every exit.
tmp=$(mktemp -d "${TMPDIR:-/tmp}/sandbox-run.XXXXXX")
tp_log=$tmp/tinyproxy.log
tpid= wpid=
cleanup() {
  if [ -n "$wpid" ]; then kill "$wpid" 2>/dev/null || true; wait "$wpid" 2>/dev/null || true; fi
  if [ -n "$tpid" ]; then kill "$tpid" 2>/dev/null || true; wait "$tpid" 2>/dev/null || true; fi
  rm -rf "$tmp"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

if [ "$tinyproxy" = 1 ]; then
  tp_bin=$(command -v tinyproxy || true)
  [ -z "$tp_bin" ] && [ -x /opt/homebrew/opt/tinyproxy/bin/tinyproxy ] && tp_bin=/opt/homebrew/opt/tinyproxy/bin/tinyproxy
  if [ -z "$tp_bin" ]; then
    echo "refusing to run: tinyproxy is not installed (it restricts the allowed hosts to ports 443/993): brew install tinyproxy" >&2
    exit 1
  fi
  tp_port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
  # The filter is a whitelist over "host:port" (CONNECT) and full URLs (plain HTTP): only the former matches.
  echo '^[^/]+:(443|993)$' >"$tmp/tinyproxy.filter"
  cat >"$tmp/tinyproxy.conf" <<EOF
Listen 127.0.0.1
Port $tp_port
Allow 127.0.0.1
ConnectPort 443
ConnectPort 993
Filter "$tmp/tinyproxy.filter"
FilterType ere
FilterURLs On
FilterDefaultDeny Yes
Timeout 600
MaxClients 50
DisableViaHeader Yes
LogFile "$tp_log"
LogLevel Info
EOF
  "$tp_bin" -d -c "$tmp/tinyproxy.conf" >"$tmp/tinyproxy.out" 2>&1 &
  tpid=$!
  up=0
  for _ in $(seq 1 50); do
    kill -0 "$tpid" 2>/dev/null || break
    if python3 -c 'import socket,sys; socket.create_connection(("127.0.0.1",int(sys.argv[1])),1).close()' "$tp_port" 2>/dev/null; then up=1; break; fi
    sleep 0.1
  done
  if [ "$up" != 1 ]; then
    echo "refusing to run: tinyproxy did not start on 127.0.0.1:$tp_port" >&2
    sed 's/^/  /' "$tmp/tinyproxy.out" "$tp_log" >&2 2>/dev/null || true
    exit 1
  fi
  nono+=(--upstream-proxy "127.0.0.1:$tp_port")
fi

name="ledgehog-$job-$$"
log=$tmp/nono.log
: > "$log"
flags=(--name "$name")

# Watcher: nono logs `proxy request denied ...` live (with -v) but records nothing live for the audit trail;
# the watcher polls that log, and tinyproxy's log for refused ports. It sees proxy-mode denials only: with
# network.block (no proxy) the kernel denies silently, and file denials are never reported.
# tinyproxy logs `Request (...): CONNECT host:port ...` and then `Refused CONNECT method on port N`;
# a non-CONNECT request is always refused (filter), and leaves only its `Request` line.
tp_awk='
/Request \(file descriptor/ {
  r = $0; sub(/.*\): /, "", r); split(r, a, " ")
  if (a[1] == "CONNECT") { last = a[2]; next }
  u = a[2]; sub(/^[A-Za-z]+:\/\//, "", u); sub(/\/.*/, "", u)
  if (u !~ /:[0-9]+$/) u = u ":80"
  print u "\tplain HTTP not allowed (only CONNECT to 443 and 993)"; exit
}
/Refused CONNECT method on port/ { t = last; sub(/:[0-9]+$/, "", t); print t ":" $NF "\tport not allowed (only 443 and 993)"; exit }'

watcher() {
  local line target host port reason hint sid
  while sleep 0.5; do
    hint="if the host is expected, add it to network.allow_domain in $profile"$'\n'"  (or pass --allow-domain HOST for one run)"
    if line=$(grep -m1 'proxy request denied' "$log" 2>/dev/null); then
      line=$(printf '%s' "$line" | sed $'s/\x1b\\[[0-9;]*m//g')
      host=$(printf '%s' "$line" | sed -n 's/.* host=\([^ ]*\).*/\1/p')
      port=$(printf '%s' "$line" | sed -n 's/.* port=\([^ ]*\).*/\1/p')
      reason=$(printf '%s' "$line" | sed -n 's/.* reason=\(.*\) denial_category=.*/\1/p')
      hint=${hint//HOST/$host}
      # nono reports tinyproxy's refusal (a port other than 443/993) as a denial of its own
      case "$reason" in
        *"enterprise proxy rejected CONNECT"*)
          reason="port not allowed (only 443 and 993)"
          hint="the allowed ports are fixed in run.sh (tinyproxy ConnectPort / filter)" ;;
      esac
    elif [ -s "$tp_log" ] && line=$(awk "$tp_awk" "$tp_log") && [ -n "$line" ]; then
      target=${line%%$'\t'*}
      reason=${line#*$'\t'}
      host=${target%:*}
      port=${target##*:}
      hint="the allowed ports are fixed in run.sh (tinyproxy ConnectPort / filter)"
    else
      continue
    fi
    {
      printf '\n\033[1;97;41m'
      printf '%s\n' "################################################################################" \
        "#  SANDBOX: BLOCKED OUTBOUND CONNECTION  -  stopping the job" \
        "################################################################################"
      printf '\033[0m'
      printf '  time:    %s\n  target:  %s:%s\n  reason:  %s\n  %s\n\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$host" "$port" "$reason" "$hint"
    } >&2
    touch "$tmp/denied"
    sid=$(nono ps --json 2>/dev/null | python3 -c 'import json,sys; print(next((s["session_id"] for s in json.load(sys.stdin) if s.get("name")==sys.argv[1]), ""))' "$name") || sid=
    [ -n "$sid" ] && nono stop "$sid" >/dev/null 2>&1
    return
  done
}

if [ "$watch" = 1 ]; then
  flags+=(-v --log-file "$log")
  watcher &
  wpid=$!
fi

rc=0
"${nono[@]}" "${flags[@]}" "$@" || rc=$?
# give the watcher one poll to notice a denial that came right before the exit
[ -n "$wpid" ] && sleep 0.7
if [ -e "$tmp/denied" ]; then exit 1; fi
exit "$rc"
