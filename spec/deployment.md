# Household ledger — deployment

How the image of `architecture.md` §10 is run: one Compose stack, a relay that
is the app's only way out, and the settings that harden each container. It
depends on `architecture.md` (§3, §5.5–§5.7, §10) and the email importer's
spec (`plugins/importers/email.md`), and asks nothing of the application: the
app connects to its hosts as if directly.

---

## 1. What the deployment defends against

The backend holds the ledger, a PIN or mailbox password while a sync runs, and
model keys. The deployment assumes a dependency of the image may one day be
malicious. Whatever runs in the app's process reads everything the app reads,
so nothing inside the process is a boundary.

**The boundary is the network: the app's only peer is a relay that forwards
to listed destinations alone, and no destination the household runs can be
made to reach further for it.** The list lives in the stack, where the app
cannot write it; the database and a model server are held to the second half
by §4. Code running in the app can still read every secret; it cannot send one
anywhere the household did not choose.

What this does not stop:

- **Data sent through a listed host to an account the attacker owns on it**: a
  hosted model API, a public mail provider; or to another site of the same
  provider, named inside the encrypted request where the relay cannot see it
  (domain fronting), where the provider allows that.
- **A compromise on a developer's machine**, which the development sandbox
  contains (`architecture.md` §5.7), not the deployment.

---

## 2. The stack

```
  Caddy ──► <host>:8000 (published) ─┐
                                      │
                                    relay (nginx) ──► listed hosts, :443 and :993 only
                                      │           └─► PostgreSQL, :5432 (fixed forward)
  ─────────── internal (internal: true, gateway isolated) ───────────
          │                           │
         app ─────────────────────────┘
```

The app's only peer is the relay: every connection it makes, in or out,
database included, passes through it.

**Two networks:**

- `internal`: `internal: true`, so Docker gives it no route out, and gateway
  mode `isolated` (`com.docker.network.bridge.gateway_mode_ipv4: isolated`),
  so it has no address on the host either. Without it, a container on an
  internal network can reach any host service listening on the network's
  gateway address, which includes every port another container publishes.
- `outside`: an ordinary bridge, the relay's route out and where its one
  port is published.

Gateway modes need a Docker Engine whose documentation lists them; the
host's version is checked before deploying, and §5's first check confirms the
host is unreachable.

| Service | Networks | Role |
|---|---|---|
| `app` | `internal` | The image of `architecture.md` §10. Publishes no port |
| `relay` | `internal` (fixed address), `outside` | The way out, and the one way in (§3). Publishes one port, 8000 |
| PostgreSQL | its own | Not part of this stack (`architecture.md` §10), reached through a fixed forward on the relay, the way the household's other services reach it |

**The way in.** The relay publishes port 8000 on the host and forwards it to
`app:8000` and nothing else. The household's reverse proxy reaches it the way
it reaches every other service on the host, and terminates TLS. The reverse
proxy is not on `internal`: from there the app could reach every service it
fronts. The published port speaks plain HTTP to anyone on the LAN; the session
cookie is `Secure` (`architecture.md` §5.6), so no session rides it, and only
a password typed into the app opened over that port would cross the LAN in
the clear. On a host that also has a public address, the port is published on
the LAN address alone (`"192.168.1.10:8000:8000"`): Docker's published ports
are not filtered by the host's firewall.

**The way out.** The app finds each listed host at the relay's address through
`extra_hosts`, connects to its real name, and checks its real certificate. The
relay reads the server name from the TLS handshake and forwards the connection
unchanged, so TLS runs end to end and the relay sees no content or
credentials. A name that is not listed for the port it is reached on, or a
port the relay does not listen on, goes nowhere. Anything else the app tries to resolve fails: `internal`
forwards no lookups out.

---

## 3. The relay

nginx's `stream` module with `ssl_preread`, its configuration inline in the
stack — an environment variable the relay writes to its `/tmp` at start, since
Compose cannot create a `content` config in a read-only container — so the
whole deployment, list included, is the one stack file.

```yaml
services:
  app:
    image: ledgehog@sha256:…
    networks: [internal]
    environment: { POSTGRES_HOST: relay }  # the database, through its fixed forward
    sysctls: { net.ipv6.conf.all.disable_ipv6: 1 }
    extra_hosts:                          # every listed host, at the relay
      - "fints.example-bank.de=172.30.0.2"
      - "imap.gmail.com=172.30.0.2"
      - "auth.example.org=172.30.0.2"

  relay:
    image: nginxinc/nginx-unprivileged@sha256:…
    entrypoint: ["/bin/sh", "-c"]
    command: ['printf "%s\n" "$$RELAY_CONF" > /tmp/nginx.conf && exec nginx -c /tmp/nginx.conf -g "daemon off;"']
    environment:
      RELAY_CONF: |
        pid /tmp/nginx.pid;
        events {}
        stream {
          resolver 127.0.0.11 valid=30s ipv6=off;    # Docker's DNS, IPv4 answers only
          log_format relay '$$remote_addr :$$server_port sni=$$ssl_preread_server_name '
                           'to=$$upstream_addr status=$$status';
          access_log /dev/stdout relay;     # every connection, the refused ones with status 502
          map $$ssl_preread_server_name $$to_https {    # reached on 443
            fints.example-bank.de  fints.example-bank.de;
            auth.example.org       auth.example.org;
            default                blocked.invalid;
          }
          map $$ssl_preread_server_name $$to_imaps {    # reached on 993
            imap.gmail.com         imap.gmail.com;
            default                blocked.invalid;
          }
          server { listen 443; ssl_preread on; proxy_pass $$to_https:443; }
          server { listen 993; ssl_preread on; proxy_pass $$to_imaps:993; }
          server { listen 5432; set $$db  db.home.lan; proxy_pass $$db:5432;  }    # the database
          server { listen 8000; set $$app app;         proxy_pass $$app:8000; }    # the way in, from the reverse proxy
        }
    networks:
      internal: { ipv4_address: 172.30.0.2 }
      outside: {}
    ports: ["8000:8000"]                  # the way in; 443 and 993 are not published
    sysctls:
      net.ipv6.conf.all.disable_ipv6: 1
      net.ipv4.ip_unprivileged_port_start: 0    # binds 443 and 993 without root

networks:
  internal:
    internal: true
    enable_ipv6: false
    driver_opts: { com.docker.network.bridge.gateway_mode_ipv4: isolated }
    ipam: { config: [{ subnet: 172.30.0.0/24 }] }
  outside:
    enable_ipv6: false
```

- **No IPv6, stated rather than assumed.** The stack needs none. Docker
  documents IPv6 only as something a network turns on, so both networks say
  `enable_ipv6: false`, the app and the relay turn it off in their own kernel
  namespace (`sysctls`), and the relay asks its resolver for IPv4 addresses
  alone. A path that does not exist needs no rules.
- **`$$`, not `$`.** Compose substitutes variables in values, so every
  nginx variable is written with a doubled dollar.
- **A host is named twice**: an `extra_hosts` line and an entry in the map of
  the port it is reached on. Adding a bank or a mailbox is those two lines
  and a redeploy of the stack.
- **Only 443 and 993 exist, and each listed name has only its own.** A web
  host is listed for 443, a mailbox for 993; a TLS destination on another port
  gets a listener and a map of its own, the same way. No SMTP port is reachable
  through any listed name, which is why a mailbox password cannot be used to
  send from the app, and a mail host's web side is no more reachable than a
  bank's IMAP port. A mailbox uses implicit TLS (the email importer's `security`
  set to `tls`, port 993): STARTTLS carries no server name to route by.
- **A listed name may point at a service the household runs**: the map's
  value, in the 443 map, is then the name the relay reaches it at on the
  LAN, for example an identity provider behind the reverse proxy
  (`auth.example.org caddy.home.lan;`).
- **Fixed forwards** carry what has no server name to route by: the database,
  and a model server spoken to in plain HTTP, each on its own port to one
  destination set here
  (`server { listen 11434; set $$llm llm.home.lan; proxy_pass $$llm:11434; }`,
  with an `extra_hosts` line for the name the endpoint uses). The app cannot
  change where a fixed forward goes. Each names its destination through a
  variable (`set`), so, like the maps, it is resolved on every connection and
  cached for 30 s: nothing is resolved when the relay starts, a destination
  that is down then does not keep the relay from starting, and a changed
  address, the app's after its container is recreated included, is followed
  within 30 s. A model server has no way out of its own (§4).
- **A refused connection** fails like a host that cannot be reached
  (`architecture.md` §5.5, `SourceUnavailable`), and the relay's access log
  shows its server name and port with nothing reached.

---

## 4. Hardening

**Every container in the stack:**

- a non-root user (`architecture.md` §10; nginx's unprivileged image);
- `read_only: true`, with a size-limited `tmpfs` at `/tmp`;
- `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`;
- `mem_limit` and `pids_limit`;
- images pinned by digest, renewed on purpose;
- no Docker socket, no host path mounted.

**The app also:** secrets as environment variables, from the stack's
environment like every other setting: Compose cannot create a secret in a
read-only container, and reading one takes the access that reads the
container's environment (`architecture.md` §5.7 keeps the `_FILE` variants
for other setups); `PYTHONDONTWRITEBYTECODE=1`; a health check.

**The database cannot act for the app.** Postgres can reach out itself
(`COPY … TO PROGRAM`, `dblink`, `postgres_fdw`), and its own networks are its
stack's business, so the app's role is the protection: it is not a superuser,
holds none of `pg_execute_server_program`, `pg_read_server_files` and
`pg_write_server_files`, and owns only its own database. Such a role can
create trusted extensions alone, which `pg_trgm`, the one the schema needs,
is; `dblink` and `postgres_fdw` are not, and are not installed in its
database by anyone else either, since once installed a role without
privileges can still use them to connect out.

**A model server has no way out either.** Some fetch on request: Ollama pulls
a model from whatever registry its name names, so a request for
`attacker.example/<data>:tag` is a connection out carrying data. Models are
pulled on purpose, with the server given a route out only while pulling.

**The image** (`architecture.md` §10): the Python stage installs with
`uv sync --locked --no-dev`, building nothing from source but the project
itself, under the release cooldown of development; the Node stage with
`npm ci`, install scripts off; the final stage holds the virtual environment
and the bundle, and no compiler, Node or package manager.

---

## 5. Checks after setup

Run once, and again after any change to the stack:

1. From `app`: resolving an outside name fails; connecting to an outside
   address fails; connecting to the host's address on any port fails; the
   container has no IPv6 address, not even a link-local one.
2. Through the relay: a listed host connects with its real certificate on
   its own port; an unlisted server name, a listed host on the other port
   (the mailbox on 443, a web host on 993) and port 587 are refused.
3. As the app's database role: `COPY … TO PROGRAM` and
   `CREATE EXTENSION dblink` are refused, and `dblink` and `postgres_fdw` are
   not installed.
4. The app answers through the reverse proxy; of the stack, only the relay's
   port 8000 is published on the host.
5. A sync from every importer instance, a classification by the model, and
   an OIDC sign-in each succeed.
