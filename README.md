# ledgehog

A self-hosted household ledger for two people: FinTS and file import, categorisation with
correction, shared accounts, net worth tracking. Python (FastAPI, one worker) with a Svelte SPA,
PostgreSQL as the database.

- What it does and how it is built: [spec/README.md](spec/README.md) (start with `spec/spec.md`).
- Developing: [sandbox/README.md](sandbox/README.md). All installs, tests and dev servers run in
  the nono sandbox described there; `.env.example` is the development configuration.
- Deploying: below. The reasoning behind the stack (what it defends against, why a relay) is in
  [spec/deployment.md](spec/deployment.md); this guide only lists the steps.

## Deployment

The stack is two containers, the app and an nginx relay that is the app's only way in and out
(`deploy/compose.example.yaml`). PostgreSQL, the reverse proxy and DNS are the household's own.

### 1. Prerequisites

- Docker Engine with network gateway modes (`gateway_mode_ipv4: isolated`, see Docker's
  documentation for the first release that lists it; the first check in step 8 confirms it works).
- Docker Compose v2. In Portainer, that is the Compose
  version of its standalone agent/host: check with `docker compose version` on the host, and
  Portainer's release notes for the version it embeds. Swarm (`docker stack deploy`) is not
  supported.
- PostgreSQL 14 or later, reachable from the Docker host, with `pg_trgm` available (a trusted
  extension since PostgreSQL 13, part of the standard contrib package).
- A reverse proxy for TLS (Caddy below) and a DNS name for the app.

### 2. Build the image

On the Docker host, from a checkout of this repository:

```sh
docker build -t ledgehog:0.5.0 .
```

The Dockerfile names its three base images by tag (`node:22-slim`, `python:3.12-slim` twice) with a
`# pin: …@sha256:…` comment on each. The stack's images are meant to be pinned by digest: resolve
each and write it into the `FROM` line. The frontend stage also pins npm to the version that writes
`frontend/package-lock.json` (11.11.0), to be raised together with the local npm.

```sh
docker buildx imagetools inspect python:3.12-slim    # "Digest: sha256:…"
# FROM python:3.12-slim@sha256:<digest>
```

Do the same for `nginxinc/nginx-unprivileged` in the compose file. Renew the digests on purpose,
when you rebuild.

### 3. Database

As a PostgreSQL superuser (`psql -h <db-host> -U postgres`):

```sql
CREATE ROLE ledgehog LOGIN PASSWORD '<password>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE DATABASE ledgehog OWNER ledgehog;
```

The role must not hold the server-side file and program privileges (it does not, unless you grant
them): `pg_execute_server_program`, `pg_read_server_files`, `pg_write_server_files`. In the
`ledgehog` database, `dblink` and `postgres_fdw` must not be installed (`\c ledgehog`, then `\dx`;
`DROP EXTENSION` any that is listed). The app creates `pg_trgm` itself in its first migration (a
trusted extension, which the database owner may create), and migrations run automatically at every
start.

Allow the Docker host's address for the role and database in `pg_hba.conf`; the relay connects
from the host's `outside` network, so the connection arrives from the host (or from the Docker
bridge subnet).

Backups are yours (`spec/architecture.md` §10): the ledger's history cannot be rebuilt from bank
data. Set up the backup and test a restore before real history goes in.

### 4. Configure

Copy `deploy/stack.env.example`. In Portainer, paste it into the stack's *Environment variables*
(advanced mode); with the command line, save it as `.env` next to the compose file (it holds
passwords: keep it out of git and readable by you alone). Fill in the required values; leave the
optional groups commented unless you use them.

Differences from the development `.env.example`: `POSTGRES_HOST` is fixed to `relay` in the compose
file (the database is reached through the relay's forward). `BASE_URL` is the address users type, the
reverse proxy's `https://…`; it is required with OIDC. Leave `ENABLE_TEST_IMPORTERS` and
`EXPOSE_OPENAPI` unset.

### 5. Configure the relay's list

Every host the app may reach is named twice in the compose file, in `extra_hosts` of `app` and in a
map of `RELAY_CONF` (the relay service's `environment`); both lines together are all there is to adding one. Replace the
example hosts:

| What | `extra_hosts` | relay map |
|---|---|---|
| a FinTS bank (443) | `"<bank-host>=172.30.0.2"` | `$$to_https`: `<bank-host> <bank-host>;` |
| an OIDC issuer, plus token / JWKS hosts if they are other names | one line each | `$$to_https`, one entry each |
| a mailbox (IMAP, 993; set the importer's `security` to `tls`) | `"<imap-host>=172.30.0.2"` | `$$to_imaps`: `<imap-host> <imap-host>;` |
| a hosted model endpoint (443) | `"<model-host>=172.30.0.2"` | `$$to_https` |
| the database | none (`POSTGRES_HOST: relay`) | the `listen 5432` forward: set the destination |
| a model server in plain HTTP | `"<name>=172.30.0.2"` | a `listen <port>` forward of its own |

`172.30.0.2` is the relay's fixed address on `internal`; if you change the subnet, change both.
Every nginx variable is written `$$` (Compose substitutes `$`). Take the hosts from the places the
app is configured: the bank's FinTS URL, the mailbox's server, `OIDC_ISSUER`, `MODEL_ENDPOINT`.

### 6. Deploy the stack

Portainer: *Stacks → Add stack → Web editor*, paste the adapted `deploy/compose.example.yaml`,
add the environment variables of step 4, deploy. Or on the host:

```sh
docker compose -p ledgehog -f deploy/compose.example.yaml --env-file .env up -d
```

The app starts only if its configuration is valid; a refusal (missing variable, base currency
mismatch) is the first thing in `docker logs <app container>`. The port is published on the host as
`8000`. On a host that also has a public address, publish it on the LAN address alone (the
commented `ports` line).

### 7. Reverse proxy

Caddy, on the same host or another one on the LAN, terminates TLS:

```
ledger.example.org {
    reverse_proxy <host-fqdn-or-lan-address>:8000
}
```

`BASE_URL` must be that `https://ledger.example.org` (the session cookie is `Secure`).

### 8. Checks after setup

Run once and after every change to the stack (`spec/deployment.md` §5). Container names are
`<stack>-app-1` and `<stack>-relay-1` (see `docker ps`). The app image has Python only, so the
checks use it.

```sh
APP=ledgehog-app-1; RELAY=ledgehog-relay-1

# 1. The app has no way out of its own: each of these must FAIL
docker exec $APP python -c "import socket; socket.getaddrinfo('example.com', 443)"           # no outside name
docker exec $APP python -c "import socket; socket.create_connection(('1.1.1.1', 443), 3)"    # no outside address
docker exec $APP python -c "import socket; socket.create_connection(('<host-lan-ip>', 8000), 3)"   # not the host, any port
docker exec $APP python -c "print(open('/proc/net/if_inet6').read() or 'no ipv6')"           # must print: no ipv6

# 2. Through the relay
# a listed host connects, with its real certificate, on its own port (prints the subject)
docker exec $APP python -c "import socket,ssl; h='<bank-host>'; s=ssl.create_default_context().wrap_socket(socket.create_connection((h,443),5), server_hostname=h); print(s.getpeercert()['subject'])"
# must FAIL: an unlisted server name, a listed host on the other port, port 587
docker exec $APP python -c "import socket,ssl; s=ssl.create_default_context().wrap_socket(socket.create_connection(('172.30.0.2',443),5), server_hostname='example.com')"
docker exec $APP python -c "import socket,ssl; h='<imap-host>'; ssl.create_default_context().wrap_socket(socket.create_connection((h,443),5), server_hostname=h)"   # the mailbox on 443
docker exec $APP python -c "import socket,ssl; h='<bank-host>'; ssl.create_default_context().wrap_socket(socket.create_connection((h,993),5), server_hostname=h)"   # a web host on 993
docker exec $APP python -c "import socket; socket.create_connection(('<imap-host>',587),5)"
docker logs $RELAY        # one line per connection: sni, port, upstream; the refusals with status 502
```

```sh
# 3. As the app's role, from a machine that reaches the database (all refused / absent):
psql -h <db-host> -U ledgehog ledgehog
```
```sql
COPY (SELECT 1) TO PROGRAM 'true';    -- ERROR: permission denied
CREATE EXTENSION dblink;              -- ERROR: permission denied
\dx                                   -- lists plpgsql and pg_trgm; no dblink, no postgres_fdw
SELECT rolsuper FROM pg_roles WHERE rolname = current_user;                       -- f
SELECT pg_has_role(current_user, 'pg_execute_server_program', 'member');          -- f
```

4. `curl -sI https://ledger.example.org/` answers through the reverse proxy; `docker ps --format
   '{{.Names}} {{.Ports}}'` shows a published port on the relay only.
5. In the app: sync every importer instance, run a classification by the model, sign in through
   OIDC. A refused connection shows in the relay log with its server name.

### 9. Updating and changing the list

- New version: `git pull`, build the image with a new tag (step 2), change `image:` in the stack,
  redeploy. Migrations run at start; take a database backup first.
- A new bank, mailbox or other host: add its `extra_hosts` line and its map entry (step 5),
  redeploy the stack, run the relevant part of step 8.
- A changed variable (a password, a window) is a redeploy; the app has no password-change flow.
