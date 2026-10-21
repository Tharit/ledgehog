#!/usr/bin/env bash
# Real-server smoke run of the importer endpoints (account, instance, link, upload, runs, revert).
#
#   . ./test.env && UV_CACHE_DIR="$PWD/.uv-cache" scripts/smoke_http.sh
#
# Creates the dev database, starts ONE uvicorn worker under a 180 s timeout (it ends by itself),
# drives it with curl (multipart through a real client, which exercises the hand-rolled parser
# in app/api/routers/importers.py) and drops the database at the end. Every request and response
# is printed (cookie and password redacted, bodies cut at 600 chars). All data is synthetic; the
# marker PRIVATE-NAME sits in the file's preamble and must appear in no response and no log line.
set -u
cd "$(dirname "$0")/.."
: "${POSTGRES_PASSWORD:?source test.env first}"
T="${TMPDIR:-/tmp}/smoke_http.$$"
mkdir -p "$T"
UV="uv run --no-sync"
DB=$($UV python scripts/dev_db.py name)
PW="smoke-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
URL="http://127.0.0.1:$PORT"
JAR="$T/jar"
LOG="$T/server.log"
LEAKS=0
# the server must end by itself: `timeout 180` where there is one, else a SIGALRM after 180 s
if command -v timeout >/dev/null; then TIMEOUT=(timeout 180); else TIMEOUT=(perl -e 'alarm 180; exec @ARGV' --); fi

$UV python scripts/dev_db.py create || exit 1

cleanup() {
  [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null
  for p in $(lsof -ti "tcp:$PORT" 2>/dev/null); do kill "$p" 2>/dev/null; done
  sleep 1
  $UV python scripts/dev_db.py drop
  if curl -s -m 2 -o /dev/null "$URL/api/me"; then echo "WARNING: port $PORT still answers"; else echo "port $PORT no longer answers"; fi
}
trap cleanup EXIT

POSTGRES_DB="$DB" BASE_CURRENCY=EUR TIMEZONE=Europe/Berlin USER_1_LOGIN=smoke USER_1_NAME=Smoke \
  USER_1_PASSWORD="$PW" "${TIMEOUT[@]}" .venv/bin/uvicorn app.main:app --port "$PORT" --workers 1 >"$LOG" 2>&1 &
SRV=$!
for _ in $(seq 1 60); do
  curl -s -m 1 -o /dev/null "$URL/api/me" && break
  sleep 0.5
done

N=0
# req LABEL CURL-ARGS...: prints the request line and the response (status, headers, body cut at 600)
req() {
  local label="$1"; shift
  N=$((N + 1))
  local h="$T/h$N" b="$T/b$N"
  echo; echo "### [$N] $label"
  if [ -n "${NOAUTH:-}" ]; then curl -s -D "$h" -o "$b" "$@"; else curl -s -D "$h" -o "$b" -c "$JAR" -b "$JAR" "$@"; fi
  sed -e 's/^\(Set-Cookie: [^=]*=\)[^;]*/\1[redacted]/' -e 's/\r$//' "$h" | grep -iv '^\(date\|server\):' | sed '/^$/d'
  head -c 600 "$b"; echo
  [ "$(wc -c <"$b")" -gt 600 ] && echo "...[body truncated, $(wc -c <"$b") bytes]"
  grep -q PRIVATE-NAME "$b" "$h" && { echo "!!! LEAK: PRIVATE-NAME in response $N"; LEAKS=$((LEAKS + 1)); }
  LAST_BODY="$b"
  LAST_STATUS=$(head -1 "$h" | awk '{print $2}')
}
jqb() { jq -r "$1" "$LAST_BODY"; }

echo "server: $URL (db $DB, pid $SRV)"
echo "login: smoke / [redacted]"
N=$((N + 1)); echo; echo "### [$N] POST /api/login"
curl -s -i -c "$JAR" -b "$JAR" -H 'content-type: application/json' \
  -d "{\"login\":\"smoke\",\"password\":\"$PW\"}" "$URL/api/login" |
  sed -e 's/^\(Set-Cookie: [^=]*=\)[^;]*/\1[redacted]/' -e 's/\r$//' | grep -iv '^\(date\|server\):' | head -c 700; echo

req "POST /api/ledger/accounts" -H 'content-type: application/json' \
  -d '{"name":"Smoke Giro","kind":"checking","currency":"EUR"}' "$URL/api/ledger/accounts"
ACCT=$(jqb .account.id)

PRESET=$($UV python -c 'import json; from app.plugins.importers.csv import load_presets; print(json.dumps(load_presets()["consorsbank_giro"]))')
BODY=$(jq -c -n --argjson s "$PRESET" '{importer:"csv",label:"Smoke giro",settings:$s}')
req "POST /api/importers/instances (consorsbank_giro)" -H 'content-type: application/json' -d "$BODY" "$URL/api/importers/instances"
INST=$(jqb .id)

req "POST links (dry run)" -H 'content-type: application/json' -d "{\"account_id\":$ACCT,\"dry_run\":true}" "$URL/api/importers/instances/$INST/links"
req "POST links (real)" -H 'content-type: application/json' -d "{\"account_id\":$ACCT}" "$URL/api/importers/instances/$INST/links"

# the synthetic giro export (invented names), as the shared fixture renders it
G="$T/giro.csv"
printf '\357\273\277' >"$G"
cat >>"$G" <<'EOF'
Konto;Inhaber;Exportdatum
DE00 0000 0000 0000 0000 00;PRIVATE-NAME;20.08.2026, 14:30:05

Kontodaten
Konto;Inhaber;Exportdatum
DE00 0000 0000 0000 0000 00;PRIVATE-NAME;20.08.2026, 14:30:05

Kontostand
Saldo;Währung für Saldo;Datum;max. Verfügungsrahmen;Währung für max. Verfügungsrahmen
1.234,56;EUR;20.08.2026;500,00;EUR

Kontoumsätze
Buchung ;Valuta;Sender / Empfänger;IBAN;BIC;Buchungstext;Verwendungszweck;Kategorie;Stichwörter;Umsatz geteilt;Betrag;Währung
21.08.2026;vorgemerkt;Muster GmbH;DE00 1111 1111 1111 1111 11;BICXXXX1;Kartenzahlung;Vorgemerkt;n/a;n/a;n/a;-20,00;EUR
20.08.2026;20.08.2026;Beispiel Markt;DE00 2222 2222 2222 2222 22;n/a;Lastschrift;Rechnung Nummer 2026-0001;Einkauf;n/a;n/a;-10,00;EUR
19.08.2026;19.08.2026;Erika Beispiel;DE00 3333 3333 3333 3333 33;BICXXXX2;Gutschrift;Miete Zurueck;n/a;n/a;n/a;1.500,00;EUR
18.08.2026;18.08.2026;Beispiel Strom AG;DE00 4444 4444 4444 4444 44;BICXXXX3;Lastschrift;Abschlag;Wohnen;n/a;n/a;-45,50;EUR
17.08.2026;18.08.2026;Beispiel Bank;DE00 5555 5555 5555 5555 55;BICXXXX4;Hinweis;Hinweis ohne Betrag;n/a;n/a;n/a;0,00;EUR
EOF
UP="$URL/api/importers/instances/$INST/upload"

req "upload dry run" -F "file=@$G" -F "account_id=$ACCT" -F dry_run=true "$UP"
req "GET runs (a dry run leaves none)" "$URL/api/importers/runs"
req "upload real" -F "file=@$G" -F "account_id=$ACCT" -F dry_run=false "$UP"
RUN=$(jqb .run_id)
req "GET runs" "$URL/api/importers/runs?account_id=$ACCT"
req "GET /api/ledger/accounts" "$URL/api/ledger/accounts"

echo; echo "=== multipart edge cases ==="
# sizes: pad the export with newlines up to N bytes
pad() { { cat "$G"; head -c "$1" /dev/zero | tr '\0' '\n'; } | head -c "$1" >"$2"; }
MAX=$((10 * 1024 * 1024))
pad "$MAX" "$T/exact.csv";      req "file of exactly 10 MiB (dry run)" -F "file=@$T/exact.csv" -F "account_id=$ACCT" -F dry_run=true "$UP"
pad $((MAX - 1)) "$T/under.csv"; req "file of 10 MiB - 1 (dry run)" -F "file=@$T/under.csv" -F "account_id=$ACCT" -F dry_run=true "$UP"
pad $((MAX + 1)) "$T/over.csv"; req "file of 10 MiB + 1 (dry run)" -F "file=@$T/over.csv" -F "account_id=$ACCT" -F dry_run=true "$UP"
pad $((MAX + 70000)) "$T/way.csv"; req "file of 10 MiB + 70000 (past the body cap)" -F "file=@$T/way.csv" -F "account_id=$ACCT" -F dry_run=true "$UP"
rm -f "$T/exact.csv" "$T/under.csv" "$T/over.csv" "$T/way.csv"

req "filename with spaces, quotes and UTF-8" -F "file=@$G;filename=\"mein \\\"Kontoauszug\\\" für Jäner 2026.csv\"" -F "account_id=$ACCT" -F dry_run=true "$UP"
req "filename with a semicolon and an equals sign" -F "file=@$G;filename=a;b=c.csv" -F "account_id=$ACCT" -F dry_run=true "$UP"
req "no file part" -F "account_id=$ACCT" -F dry_run=true "$UP"
req "no account_id part" -F "file=@$G" -F dry_run=true "$UP"
req "duplicated account_id" -F "file=@$G" -F "account_id=$ACCT" -F "account_id=$ACCT" -F dry_run=true "$UP"
req "duplicated file" -F "file=@$G" -F "file=@$G" -F "account_id=$ACCT" -F dry_run=true "$UP"
req "unknown field" -F "file=@$G" -F "account_id=$ACCT" -F extra=1 "$UP"
req "dry_run=maybe" -F "file=@$G" -F "account_id=$ACCT" -F dry_run=maybe "$UP"
req "account_id=abc" -F "file=@$G" -F account_id=abc "$UP"
sed 's/$/\r/' "$G" >"$T/crlf.csv"
req "file with CRLF line endings (dry run)" -F "file=@$T/crlf.csv" -F "account_id=$ACCT" -F dry_run=true "$UP"
# hand-built bodies: well-formed (CRLF framing) and LF-only framing
B=XBOUNDARYX
{ printf -- "--$B\r\nContent-Disposition: form-data; name=\"account_id\"\r\n\r\n$ACCT\r\n--$B\r\nContent-Disposition: form-data; name=\"dry_run\"\r\n\r\ntrue\r\n--$B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"x.csv\"\r\nContent-Type: text/csv\r\n\r\n"; cat "$G"; printf "\r\n--$B--\r\n"; } >"$T/crlf.body"
req "hand-built body, CRLF framing" -H "content-type: multipart/form-data; boundary=$B" --data-binary "@$T/crlf.body" "$UP"
{ printf -- "--$B\nContent-Disposition: form-data; name=\"account_id\"\n\n$ACCT\n--$B\nContent-Disposition: form-data; name=\"dry_run\"\n\ntrue\n--$B\nContent-Disposition: form-data; name=\"file\"; filename=\"x.csv\"\n\n"; cat "$G"; printf "\n--$B--\n"; } >"$T/lf.body"
req "hand-built body, LF-only framing" -H "content-type: multipart/form-data; boundary=$B" --data-binary "@$T/lf.body" "$UP"
req "bogus boundary (body uses another)" -H "content-type: multipart/form-data; boundary=NOPE" --data-binary "@$T/crlf.body" "$UP"
req "no boundary parameter" -H "content-type: multipart/form-data" --data-binary "@$T/crlf.body" "$UP"
req "quoted boundary" -H "content-type: multipart/form-data; boundary=\"$B\"" --data-binary "@$T/crlf.body" "$UP"
req "truncated body (no closing delimiter)" -H "content-type: multipart/form-data; boundary=$B" --data-binary "$(head -c 400 "$T/crlf.body")" "$UP"
req "empty body" -H "content-type: multipart/form-data; boundary=$B" --data-binary "" "$UP"
req "JSON body" -H 'content-type: application/json' -d "{\"account_id\":$ACCT}" "$UP"
req "boundary string inside the file content" -H "content-type: multipart/form-data; boundary=$B" \
  --data-binary "$(printf -- "--$B\r\nContent-Disposition: form-data; name=\"account_id\"\r\n\r\n$ACCT\r\n--$B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"x.csv\"\r\n\r\nline\r\n--${B}x inside\r\nmore\r\n--$B--\r\n")" "$UP"

echo; echo "=== refusals ==="
req "unknown instance" -F "file=@$G" -F "account_id=$ACCT" "$URL/api/importers/instances/9999/upload"
req "unknown account" -F "file=@$G" -F "account_id=9999" "$UP"
req "other, unlinked account" -H 'content-type: application/json' -d '{"name":"Unlinked","kind":"checking","currency":"EUR"}' "$URL/api/ledger/accounts"
OTHER=$(jqb .account.id)
req "upload to an unlinked account" -F "file=@$G" -F "account_id=$OTHER" "$UP"
echo "not a statement at all" >"$T/junk.csv"
req "upload a non-statement file (real)" -F "file=@$T/junk.csv" -F "account_id=$ACCT" "$UP"
req "GET runs (failed one listed)" "$URL/api/importers/runs?status=failed"
NOAUTH=1 req "unauthenticated upload (no cookie)" -F "file=@$G" -F "account_id=$ACCT" "$UP"

echo; echo "=== revert ==="
req "revert dry run" -H 'content-type: application/json' -d '{"dry_run":true}' "$URL/api/importers/runs/$RUN/revert"
VERS=$(jq -c .versions "$LAST_BODY")
req "revert real (with the preview's versions)" -H 'content-type: application/json' -d "{\"expected_versions\":$VERS}" "$URL/api/importers/runs/$RUN/revert"
req "GET run" "$URL/api/importers/runs/$RUN"
req "GET /api/maintenance/check" "$URL/api/maintenance/check"
req "POST /api/logout" -X POST "$URL/api/logout"
req "GET /api/me after logout" "$URL/api/me"

echo; echo "=== server log ==="
grep -c . "$LOG" | sed 's/^/log lines: /'
grep -c ' 500 ' "$LOG" | sed 's/^/500s in the log: /'
if grep -q PRIVATE-NAME "$LOG" "$T"/b* "$T"/h*; then echo "!!! LEAK: PRIVATE-NAME found in:"; grep -l PRIVATE-NAME "$LOG" "$T"/b* "$T"/h*; LEAKS=$((LEAKS + 1)); else echo "PRIVATE-NAME: in no response and no log line"; fi
grep -v 'POST /api/importers/instances/[0-9]*/upload\|GET /api' "$LOG" | sed 's/^/  log: /' | head -40
grep -q "$PW" "$LOG" && echo "!!! the password appears in the log" || echo "password: not in the log"
rm -rf "$T"
exit $LEAKS
