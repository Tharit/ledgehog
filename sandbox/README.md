# Sandboxed dev jobs (nono)

Purpose: contain supply-chain attacks. A malicious npm/PyPI package that runs during install, test, build
or at runtime should find no network to exfiltrate over, no secrets to read, and nowhere to write except
the few directories its job needs. Each job has a [nono](https://nono.sh) profile (macOS Seatbelt,
kernel-enforced); `run.sh` launches a command under one.

All profiles extend nono's built-in `default` (denies ~/.ssh, cloud credentials, keychains, browser data,
shell history and configs), mount the repo read-only, and deny `**/.env` and `test.env`
(test.env is sourced by your shell *before* nono, so the sandboxed process never needs to read it).

## Jobs

| Job | Runs | Network | Writes (beyond temp) | Env |
|---|---|---|---|---|
| `deps` | `npm ci` (in frontend/), `uv sync --locked` | proxy; only registry.npmjs.org, pypi.org, files.pythonhosted.org | frontend/node_modules, .venv, ~/.npm, ~/.cache/uv | secret-like vars stripped |
| `frontend` | `npm run check/lint/test/build`, `scripts/fe_verify.sh` | none | frontend/.svelte-kit, build, .verify, node_modules/{.vite,.vite-temp,$app} | secret-like vars stripped |
| `frontend-dev` | `vite dev` | blocked, except listen 5173-5180 and connect localhost:8000 | frontend/.svelte-kit, node_modules/{.vite,.vite-temp,$app} | secret-like vars stripped |
| `backend` | uvicorn, `scripts/dev_db.py`, `dev_seed.py` | listen 8000; connect localhost:5432; other egress via proxy to `network.allow_domain` only | none | DB creds passed through; PYTHONDONTWRITEBYTECODE=1 |
| `backend-tests` | pytest, ruff, mypy, `scripts/smoke_http.sh` | no external; localhost any port | .pytest_cache, .ruff_cache, .mypy_cache, .uv-cache | DB creds passed through; PYTHONDONTWRITEBYTECODE=1 |

"Secret-like" = `*PASSWORD* *SECRET* *TOKEN* *KEY* *CREDENTIAL*`, case-insensitive.

## Usage

`sandbox/run.sh <job> [extra nono flags...] -- <command...>` (run from anywhere; it cds to the repo root).
The command's cwd is the repo root. Source test.env in your shell first where a job needs DB credentials.

nono blocks `npm`, `rm` and similar as the *directly started* command (children are not blocked), so wrap
those in `sh -c`. For Python use `.venv/bin/<tool>`; `uv run` wants to write its cache (use `uv run --no-sync`
only with `UV_CACHE_DIR=$PWD/.uv-cache` under backend-tests).

```sh
# install
sandbox/run.sh deps -- sh -c 'cd frontend && npm ci'
sandbox/run.sh deps -- uv sync --locked

# frontend
sandbox/run.sh frontend -- scripts/fe_verify.sh --build
sandbox/run.sh frontend -- sh -c 'cd frontend && npm run check'
sandbox/run.sh frontend -- sh -c 'cd frontend && npx vitest --run src/lib/units/describe.spec.ts'
# --format / --gen write into frontend/src: grant that one directory for this run only
sandbox/run.sh frontend --allow "$PWD/frontend/src" -- scripts/fe_verify.sh --format
sandbox/run.sh frontend-dev -- sh -c 'cd frontend && npx vite dev'

# backend (. ./test.env first)
. ./test.env
sandbox/run.sh backend -- .venv/bin/uvicorn app.main:app --port 8000
sandbox/run.sh backend -- .venv/bin/python scripts/dev_seed.py
sandbox/run.sh backend --allow-domain api.example.com -- ...   # one-off extra host
# tests
sandbox/run.sh backend-tests -- .venv/bin/pytest tests/core -q
sandbox/run.sh backend-tests -- sh -c 'UV_CACHE_DIR="$PWD/.uv-cache" scripts/smoke_http.sh'
sandbox/run.sh backend-tests -- .venv/bin/ruff check app
```

## What run.sh does before and while running

- Refuses to run while `sandbox/` has uncommitted changes (a job must not run on a profile nobody reviewed).
  `SANDBOX_ALLOW_DIRTY=1` overrides, with a warning.
- **Egress canary:** asks `nono why --host egress-canary.invalid` (a static policy query, no network) and refuses
  to start if the answer is ALLOWED, i.e. the profile has neither `network.block` nor a non-empty `allow_domain`.
  Your `--allow-domain` flags are included in the query (so `--allow-domain '*'` is refused); other extra flags
  (`--allow`, `--listen-port`, ...) are not, since `nono why` does not accept them.
- Creates `frontend/node_modules/{.vite,.vite-temp,$app}` for the frontend jobs if node_modules exists (a write
  grant on a missing directory is silently skipped and the tool then fails with EPERM).
- **Watcher** (default on for `backend`; `SANDBOX_WATCH=1` enables it for another job, `SANDBOX_WATCH=0` disables
  it): follows nono's live proxy log and tinyproxy's log (refused ports); on the first denied connection it prints a red banner (time, host:port,
  reason, fix), stops the session (`nono stop`) and run.sh exits 1. Limits: it only sees proxy-mode denials.
  Jobs with `network.block` (frontend, frontend-dev, backend-tests) have no proxy and the kernel denies silently,
  so a watcher there never fires (frontend-dev: the watcher is therefore off by default); file denials are never
  reported anywhere. `nono stop` ends the started command only: if that is `sh -c '... &'`, background children
  survive, so start servers directly (`run.sh backend -- .venv/bin/uvicorn ...`). Detection lags up to ~0.5 s.
  A SIGTERM sent to run.sh itself is handled only after the command ends (bash defers traps); Ctrl-C reaches nono
  too, so it ends the job and run.sh cleans up the watcher and its temp dir.

## Network chain (proxy-mode jobs: backend, deps)

```
app -> nono proxy (host allowlist) -> tinyproxy 127.0.0.1:<free port> (CONNECT to ports 443 and 993 only) -> internet
```

nono's proxy filters by **host only** and ignores ports (`--allow-domain imap.gmail.com:993` is accepted, the
port is dropped). With a mail host on the allowlist, a malicious dependency holding the mailbox password could
also CONNECT to it on 587/465/25 and send mail. So `run.sh` starts tinyproxy per run (config and log in the
run's temp dir, listening on 127.0.0.1 only, `ConnectPort 443` and `993`) and passes
`--upstream-proxy 127.0.0.1:<port>` to nono; nono still applies its host allowlist first, tinyproxy then
restricts the port. The sandboxed process cannot reach tinyproxy directly (the kernel profile only allows
nono's proxy port). Plain HTTP is turned by nono into a CONNECT to host:port (so port 80/587 are refused
too); tinyproxy additionally refuses any non-CONNECT request (filter whitelist).

- **Requires tinyproxy** (`brew install tinyproxy`); run.sh refuses to run without it, or if it does not
  start within ~5 s. It is stopped and its temp files removed on every exit.
- Another port (e.g. 8443) means editing `ConnectPort` in run.sh.
- Refusals: the connection fails (HTTP 502/403 at the client); with the watcher the job is stopped with the
  banner (reason `port not allowed (only 443 and 993)`), without it nono prints the denial at the end of the run.
- `deps` has the watcher off by default (kept as before; a registry fetch failing is visible in the tool's
  own output); `SANDBOX_WATCH=1` turns it on.

## Configuring the backend's egress

`backend.json` lists the outbound hosts in `network.allow_domain`. It ships with only `placeholder.invalid`:
an **empty list turns the proxy off and leaves the network fully open** (run.sh's canary check refuses that),
so keep at least one entry.
Add every host your setup uses, and keep the list in sync with your env and importer config:
MODEL_ENDPOINT, VISION_MODEL_ENDPOINT, OIDC_ISSUER hosts, FinTS bank servers, IMAP servers.
A missing host fails closed (HTTP 403 from the proxy) and is reported (see below).
A `<VAR>_FILE` secret file needs a matching `"read_file": ["/path/to/file"]` under `filesystem` in
backend.json (or `--read-file /path` on the command line).

## Seeing denials

- With the watcher (backend) a denial stops the job immediately with a banner. Otherwise network denials are printed at the end of the run, with the fix:
  `deny connect example.org:443 (host example.org:443 is not in the allowlist) ... --allow-domain example.org`
- They are also recorded: `nono audit list`, then `nono audit show <session-id> [--json]` (see `network_events`).
- File denials surface only as `Operation not permitted` in the command's own output; on macOS nono's
  summary says "No path denials were observed" and the audit has no file events. `nono why --profile
  sandbox/<job>.json --path <p>` explains whether a path would be allowed.

## Known limitations

- Non-HTTP egress (IMAP, FinTS over non-HTTPS) cannot pass the HTTP(S) proxy: with `backend` it is blocked
  by the kernel profile. Using the email importer needs a looser profile or a deliberate decision.
- Ports are restricted only on the allowed hosts: 443 and 993 stay open for every listed host, and the
  restriction is the same for all of them (not per host).
- Allowed hosts are trusted completely; a compromised package can send data to any listed host.
- The sandbox does not cover the Postgres server (a hostile package can run any SQL with the creds in env
  under `backend`/`backend-tests`), `playwright-cli`, or processes you start outside `run.sh`.
- Nested sandboxing: nono cannot start inside another Seatbelt sandbox (e.g. Claude Code's own); run it
  from a normal terminal.
- Code can still tamper with what a job may write (e.g. node_modules under `deps`); jobs run later
  outside the sandbox would execute it. Always use `run.sh`.
- `scripts/smoke_http.sh` (backend-tests) creates and then **drops** the `dev_ledgehog` database; it is not a sandbox issue, but do not run it if that database holds data you want.
