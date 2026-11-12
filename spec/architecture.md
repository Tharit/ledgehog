# Household ledger — architecture

Status: draft for review. How the system is built. `spec.md` defines what it
does; see `README.md` for the document map and which decisions belong where.

---

## 1. Purpose and scope

This document covers the stack, the runtime composition, the contracts between
backend and frontend, and the module boundaries that keep `spec.md`'s
invariants enforceable in one place each.

It does not define domain concepts. Where it needs one that `spec.md` lacks,
that is a gap in the spec.

It also does not enumerate API fields. The HTTP interface sits between a
backend and a frontend that ship in the same container and are refactored in
the same commit, so a hand-written field-level contract would be a second copy
of the truth, and would rot. Generated OpenAPI is the reference. What *is*
specified here is the interface's **shape** — which operations exist and why
they are operations rather than row edits — because that shape is an
architectural decision rather than a detail of presentation. It follows from
the domain concepts in `spec.md`, it determines where each invariant is
enforced, and it fixes the boundary between the modules of §5 and the views
of §6. Fields are how an operation is expressed; the set of operations is the
architecture.

---

## 2. Stack decision

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, uvicorn |
| Data access | SQLAlchemy Core over psycopg3, **synchronous**. No ORM. `core` is plain synchronous code; the API runs it in FastAPI's threadpool (`def` endpoints) and the sync task in `asyncio.to_thread`. |
| Migrations | Alembic, explicit SQL only, autogenerate never used |
| Bank access | python-fints, in process |
| Spreadsheets | python-calamine, read only, for the CSV importer |
| Sign-in | argon2-cffi for passwords; Authlib over httpx2 for OIDC |
| Frontend | Svelte 5 + SvelteKit **in SPA mode** — no SSR, no prerendering |
| UI components | shadcn-svelte, **copied into the repository**, on Bits UI primitives; Tailwind CSS, compiled at build time |
| Charts | LayerChart, through shadcn-svelte's chart component |
| Database | PostgreSQL, external to the container |
| Packaging | One container; local development in a venv against a separate external development database |
| Tooling | uv with a hash-pinned lockfile, npm with a committed lockfile for the frontend; pytest and hypothesis; ruff; mypy in strict mode; import-linter for the module boundaries (§5.1); httpx2 for API tests |

### Why pure Python

FinTS access requires python-fints; nothing equivalent exists elsewhere
(go-hbci is at 0.4.0, unmaintained, with no PIN/TAN handling). The earlier
alternative was a Go application calling a Python bridge as a subprocess. Pure
Python removes the boundary entirely, and with it a whole class of problem:
python-fints can hold a live dialog in memory across the TAN round-trip, so
`pause_dialog()` / `deconstruct()` are not needed, and no credential-grade
blob is ever serialised or stored.

**The cost, accepted deliberately:** a much larger dependency surface than the
Go option would have had. A Python web stack plus `node_modules` for the
frontend is orders of magnitude more third-party code than Go plus four FinTS
packages. Mitigations are hash-pinned lockfiles on both sides and deliberate,
infrequent rebuilds — not the elimination of the risk.

**python-fints and mt-940 are pinned exactly.** The fixes the FinTS importer
needs are carried in the plugin as subclasses, each with its own test, and
deleted once the library makes the test pass without them
(`plugins/importers/fints.md`); an upgrade is a deliberate change that runs
those tests. The importer holds no dialog between calls and stores no
`deconstruct()` blob: it is a pickle, and nothing loads a pickle from storage.

### Why an SPA rather than server-rendered HTML

Three parts of the UI are interaction-heavy enough that form round-trips would
be the wrong shape: the review queue with keyboard navigation and one-keystroke
confirmation, the sync page with live progress and prompts, and reports that
are filtered and drilled into rather than merely displayed. The ledger list and
settings would have been fine either way.

**SvelteKit is used with all of its server-side features switched off.** The
build emits one HTML shell plus JavaScript; there is no Node process in
production and no HTML is generated at build time. Three settings, all
required:

```
adapter-static with fallback: 'index.html'   // shell, not per-route pages; in vite.config.ts
export const ssr = false                      // in +layout.ts
export const prerender = false                // in +layout.ts
```

The adapter is named for its more common use — prerendering a static site —
but with `fallback` set it is also the officially documented way to build a
single-page application. Naming it without this qualification would imply
prerendering, which is not what happens here.

What SvelteKit contributes in this configuration is file-based routing, the
build pipeline and layouts. What it costs is that its documentation and
examples are SSR-first, so answers found online routinely assume a server
that does not exist in this setup. Vite + Svelte + a standalone router would
be less framework for the same result; SvelteKit is chosen because that is
where the maintenance and the ecosystem are.

### Why shadcn-svelte for components

The screens that carry the app — the ledger list, the review queue, the unit
panel — are its own components whatever library is chosen. What a library has
to supply is the generic widgets that are hard to make accessible and
keyboard-correct: dialogs, the searchable pickers for categories, payees and
accounts (comboboxes, the most used control in review), menus, tooltips,
toasts and a date picker. Bits UI's headless primitives get focus management,
keyboard handling and ARIA right; shadcn-svelte is a set of styled components
on top of them that is **copied into the repository** rather than installed,
so the dense, keyboard-driven look the ledger needs is code this project
owns, not a theme to override.

The runtime dependencies are Bits UI and `@lucide/svelte`, the icon set
shadcn-svelte is built on, whose icons are imported one by one so only those
used are bundled. Tailwind runs at build time and ships
only the stylesheet it generates. Copied components are this project's code:
they are edited freely, and an upstream update is taken deliberately, by
copying again and reviewing the diff, never by a version bump. That keeps
the frontend's share of the dependency surface (above) small and visible.

### Rejected

- **Go + Python bridge.** See above. Smaller dependency tree, but two
  toolchains, an IPC contract to maintain, and serialised credential state.
- **Server-rendered with HTMX.** Avoids `node_modules` entirely and suits the
  ledger list well, but fights both interaction-heavy screens.
- **Flowbite-Svelte.** The largest catalogue of finished components, but an
  opinionated look that resists the density the ledger needs, uneven keyboard
  and focus behaviour, and a large installed surface; its tables are not data
  grids, so the important screens would be custom anyway.
- **Skeleton.** A coherent Tailwind design system, aimed at application and
  marketing look rather than dense data, with weaker primitives for pickers.
- **Bits UI alone, with hand-written CSS.** The same primitives and an even
  smaller surface, but every style written from scratch; shadcn-svelte is that
  plus a starting point, and adds no runtime dependency.
- **No component library.** Accessible comboboxes, dialogs and menus are
  real work and easy to get subtly wrong.
- **ORM.** The schema depends on deferred constraint triggers, partial
  indexes, and explicit transaction boundaries; the query load is reporting
  aggregates, not object graphs. An ORM would obscure the first and add
  nothing to the second.

---

## 3. Runtime composition

```
┌──────────────────────── container ────────────────────────┐
│                                                           │
│  uvicorn, ONE worker process                              │
│  ├── FastAPI app                                          │
│  │   ├── /api/…        REST                               │
│  │   ├── /api/…/events SSE                                │
│  │   └── /*            static SPA bundle, catch-all       │
│  ├── asyncio task registry (in memory)                    │
│  └── importers, incl. python-fints (blocking, threaded)   │
│                                                           │
└───────────────────────────┬───────────────────────────────┘
                            │
                    PostgreSQL (external)
```

**One worker process, always.** Sync task state — including a prompt awaiting
its answer — lives in process memory, and the SSE stream for a task
must reach the process running it. Multiple workers would require a broker and
externalised task state for no benefit at this scale. This is a deployment
constraint, not an accident: `uvicorn` with default concurrency, never
`--workers N`.

**Blocking work goes off the event loop.** python-fints is built on
`requests` and blocks. Every call into it runs via `asyncio.to_thread`, or one
slow bank stalls every other request in the process.

**The database is external.** Not in the container, so it survives image
replacement and is backed up independently.

---

## 4. Interface concept

Everything in this section is a contract both halves implement. §5 and §6 can
then be read independently.

### 4.1 Operations, not CRUD

Resources are not tables. The operations that matter are not row edits:

- Committing a unit writes its values, its split and possibly a counter-leg
  on another account at once, under deferred invariants; settling then
  derives whether the unit is confirmed, and books on a clearance account
  what the unit's decisions call for.
- Previewing a unit computes what a commit would write and writes nothing.
- Marking a source transaction as a duplicate deletes its entries; reverting
  a run deletes everything the run produced and recomputes the account's
  derived entries.
- Advancing a TAN step mutates no domain state at all.

Exposed as table writes, every client becomes responsible for upholding
invariants that `spec.md` places in one module. Exposed as operations, the
invariant has exactly one enforcement point.

Paths are grouped by the domain concept they act on, so a reader can tell what
an operation touches without consulting this document. Illustrative, not
exhaustive, and deliberately without field detail:

```
  ledger entries — the interpretation layer (spec §3.1), read here and
  changed through the units group below (spec §5.9, I21). Tags also have
  direct writes, and are part of the unit draft.
GET    /api/ledger/entries                     filtered, paged list; each
                                               entry says whether the model is
                                               still looking at it
GET    /api/ledger/entries/{id}                one entry, in the row shape of
                                               the list (200; 404 when missing)
GET    /api/ledger/sources/{id}                provenance: one source transaction
                                               — the normalised columns, `raw`,
                                               the run it arrived in and
                                               `duplicate_of` — by its id, which
                                               every entry row and statement row
                                               carries; a duplicate, which has
                                               no entry, is read the same way

  user-authored source transactions — the entry form (spec §3.9, §5.6), on
  unsynced accounts only, clearance accounts included; an imported row or a
  booking is refused (422 `not_user_authored`)
POST   /api/ledger/sources                     enter amount, purpose, date,
                                               account and sign; the client's
                                               random id makes a repeat a
                                               no-op; settles, then the panel
                                               opens on the unit
PUT    /api/ledger/sources/{id}                edit a user-authored row's
                                               amount, date or purpose, never
                                               its account; the entries absorb
                                               the change or collapse, a pair
                                               no longer equal breaks, then
                                               they are resolved afresh;
                                               confirmed by the user
DELETE /api/ledger/sources/{id}                delete a user-authored row and
                                               its entries; removal routine
POST   /api/ledger/sources/{id}/duplicate      mark as a duplicate of another
                                               row on the account (`of`);
                                               deletes its entries through the
                                               removal routine; previewed, the
                                               client previewing both
                                               directions (a second call with
                                               the roles swapped)
POST   /api/ledger/sources/{id}/not-duplicate  clear a row marked wrongly; it
                                               gets one new entry
POST   /api/ledger/tags/{id}/apply             tag every entry a ledger-list
                                               filter selects, reviewed or not
                                               (the list's filter, not a range
                                               of its own); previewed

  units — creating, reviewing and editing an interpretation, one unit at a
  time: the entries of a source transaction and of a transfer pair (spec §6)
GET    /api/units/queue                        the units not confirmed, in
                                               three sections (pending review,
                                               needs an account, waiting), each
                                               by booked date, then anchor
                                               entry id; units decided entirely
                                               by pass 0 and rules appear only
                                               while they wait for a partner;
                                               the needs-an-account section
                                               carries its currency groups and
                                               the waiting section its account
                                               groups, each with its count;
                                               a unit says what it needs or
                                               waits for, at most one of
                                               `needs_account {currency}`,
                                               `waiting {account_id,
                                               synced_through | null}`; a
                                               booking's unit says so
                                               (`booking`, with its source
                                               kind)
GET    /api/units/queue/count                  how many units can be acted on
                                               now: `count`, the sum of
                                               `pending_review` and
                                               `needs_account`, not waiting;
                                               `count` is for the Review item
                                               of the navigation, the split
                                               for the Overview
GET    /api/units/{entry_id}                   a unit's stored state
POST   /api/units/preview                      stored state + draft → the unit a
                                               commit would write: rows (with
                                               temporary ids for rows it would
                                               create, issued by the client),
                                               values, derivations, transfer
                                               offers, the bookings settling
                                               would make for it,
                                               consequences such as a partner
                                               left behind. An in-memory
                                               overlay; writes nothing.
POST   /api/units/commit                       the full state the user saw;
                                               saves any unit; settling
                                               decides whether it is confirmed

  documents — browsed on their own; booked on a clearance account by
  settling, never linked to an entry (spec §5.8)
GET    /api/documents                          filtered, paged list, newest
                                               first: provider (repeatable),
                                               from and to on the date,
                                               amount_min and amount_max
                                               (magnitudes in minor units,
                                               with currency), q (word by
                                               word over merchant, title and
                                               line descriptions), booked
                                               true or false;
                                               limit 1 to 500 (100), offset.
                                               Each row has its `booking`
                                               (the account and the booking's
                                               source transaction) or, not
                                               booked, `not_booked`, the
                                               first reason that applies
                                               (`features/documents.md` §1):
                                               `zero_total`, `no_account
                                               {currency}` (no clearance
                                               account takes its provider in
                                               its currency), `no_start
                                               {account_id}` (the account
                                               that takes it has no balance
                                               record) or `before_start
                                               {account_id, start}` (dated on
                                               or before that account's
                                               start)
GET    /api/documents/providers                the known providers, sorted,
                                               for the suggestions of a
                                               clearance account's provider
                                               list: the distinct providers
                                               of stored documents and the
                                               names importers give
GET    /api/documents/{id}                     a document with its lines, and
                                               its booking — the account, the
                                               source transaction and its
                                               entries, in line order — or
                                               `not_booked`, as in the list

  dimensions — created only by explicit user action (spec §5.9)
GET    /api/ledger/categories
POST   /api/ledger/categories
PUT    /api/ledger/categories/{id}             rename, move under another parent
                                               of its kind (never under its own
                                               descendant), sort order, icon,
                                               colour (stored as given, as on
                                               accounts and payees; the client
                                               resolves inheritance and
                                               defaults)
DELETE /api/ledger/categories/{id}             only while no entry or rule
                                               references it and it has no
                                               children; otherwise merge
POST   /api/ledger/categories/{id}/merge       into another category of the
                                               same kind, its children moving
                                               under the target, same-named
                                               children merged recursively;
                                               refused into its own descendant;
                                               keys kept; previewed (spec §3.5)
GET    /api/ledger/payees
POST   /api/ledger/payees
PUT    /api/ledger/payees/{id}                 name, note, icon, colour
DELETE /api/ledger/payees/{id}                 only while no entry references
                                               it, taking the rules that set it;
                                               otherwise merge
POST   /api/ledger/payees/{id}/merge           into another payee; previewed
POST   /api/ledger/payees/suggest-name         AI-assisted naming; returns a
                                               proposal, creates nothing

  rules — hand-written; what they decide is confirmed without review
  (spec §5.9), so every write is previewed first
GET    /api/ledger/rules
POST   /api/ledger/rules                       create: name, sets (counter
                                               account, payee or category, fixed
                                               from now on), the target value,
                                               the conditions, priority;
                                               settling applies it to what
                                               unconfirmed units have not
                                               decided. Like the change and the
                                               deletion below, previewed: the
                                               entries it would match, the
                                               units it would confirm, and the
                                               two lists of entries to check by
                                               hand (spec §5.9)
PUT    /api/ledger/rules/{id}                  change name, target value,
                                               conditions, priority (never
                                               `sets`); no existing value
                                               changes
DELETE /api/ledger/rules/{id}                  likewise
GET    /api/ledger/accounts                    the accounts; also, per kind
                                               and for the closed ones, the
                                               count and the sum of balances
                                               per currency, never converted
POST   /api/ledger/accounts                    create an account; creates
                                               nothing else (spec §5.7), but
                                               for a clearance account, which
                                               takes a `start_date` and its
                                               `providers`: its opening
                                               record, a manual record of 0
                                               at the end of the start date,
                                               written in the same
                                               transaction (spec §3.10); it
                                               settles, which books the
                                               documents it takes
PUT    /api/ledger/accounts/{id}               name, sort order, note, icon,
                                               colour, external_ref (a write: pass 0
                                               reads it, so it settles), and
                                               for a clearance account its
                                               `providers`, the whole list (a
                                               write: settling books from it);
                                               never the kind or the currency
                                               (spec I38)
DELETE /api/ledger/accounts/{id}               only an account that holds
                                               nothing: no entries, source
                                               rows, runs, records or links;
                                               otherwise close it
POST   /api/ledger/accounts/{id}/close         set the closing date; stops
                                               fetching, any balance
POST   /api/ledger/accounts/{id}/reopen        clear the closing date
POST   /api/ledger/accounts/{id}/balance-records
                                               "set balance": a manual record,
                                               on any account
PUT    /api/ledger/balance-records/{id}        correct a manual record
DELETE /api/ledger/balance-records/{id}        remove any record, reported ones
                                               included; derived entries are
                                               recomputed
GET    /api/ledger/accounts/{id}/statement     the account's source transactions
                                               and counting balance records in
                                               one list, newest first, with the
                                               each record's gap computed;
                                               paged like the ledger list

  tags — direct writes outside the panel (spec §3.7)
GET    /api/ledger/tags
POST   /api/ledger/tags
PUT    /api/ledger/tags/{id}                   rename, colour
DELETE /api/ledger/tags/{id}                   its memberships go with it
PUT    /api/ledger/entries/{id}/tags/{tag_id}  tag one entry (not a derived
DELETE /api/ledger/entries/{id}/tags/{tag_id}  one); each settles

  importers — credentials and their runs (spec §5.11)
GET    /api/importers                          the catalog: the importers this
                                               deployment registers, each with
                                               its name, whether it takes a
                                               file or fetches, the kinds it
                                               emits, and its presets
GET    /api/importers/instances
POST   /api/importers/instances                create a credential or profile
PUT    /api/importers/instances/{id}           settings, label, disabled
POST   /api/importers/instances/{id}/reset     clear `state`, keep `settings`;
                                               409 `instance_busy` while a
                                               task holds the instance
DELETE /api/importers/instances/{id}           only while it has no runs;
                                               otherwise disable it
POST   /api/importers/instances/{id}/discover-accounts
                                               start a discovery → {task_id}:
                                               a task like a sync (§5.3); the
                                               list of accounts is the result
                                               on the task's status, each with
                                               the account it is linked to or
                                               matches by external reference
POST   /api/importers/instances/{id}/links     link an account to the credential
                                               (create-or-link from discovery);
                                               previewed, listing the
                                               user-authored rows the account
                                               holds (spec §5.4); settles; for
                                               a file importer the reference
                                               is not asked for: it is `acct-`
                                               and the account's id
DELETE /api/importers/instances/{id}/links/{account_id}
                                               unlink; the account's coverage
                                               stays as history; settles
POST   /api/importers/instances/{id}/upload    a CSV file → one run per
                                               account, then settling, like a
                                               sync; with a dry-run flag it
                                               runs the real path in a
                                               transaction that is rolled back
                                               and returns the run summary and
                                               the importer's parse report. A
                                               dry run's summary is exact; the
                                               ids of what the run itself would
                                               write — the run, its rows, its
                                               balance record — name rows that
                                               were rolled back, and a client
                                               does not link them. Ids of rows
                                               that already existed are real.
GET    /api/importers/runs                     the import log; `account_id`,
                                               `instance_id`, `status`; paged
                                               as the ledger list is, `limit`
                                               (1 to 500, default 100) and
                                               `offset`, with `total`;
                                               each run with its statistics,
                                               whether it is revertible and, for
                                               a failed run, whether trying
                                               again can help (§5.5)
GET    /api/importers/runs/{id}                one run
POST   /api/importers/runs/{id}/revert         delete what the run produced;
                                               only the account's latest
                                               successful, non-reverted
                                               transaction run; previewed;
                                               carries the version of every
                                               entry it removes or unpairs,
                                               which its preview returns,
                                               with, per consequence group,
                                               its count and the number of
                                               confirmed entries among them

  sync — one long-running task over several importer instances
GET    /api/sync/plan                          what "sync everything" would
                                               do: per instance and account,
                                               the fetch start, where it
                                               comes from and whether the
                                               user may change it, and
                                               whether another task holds
                                               the instance
POST   /api/sync                               start; an empty body is every
                                               instance the user may run,
                                               else items: an instance, one
                                               account of it, or one kind,
                                               with a `since` only for an
                                               account without coverage
                                               → {task_id, busy}
GET    /api/sync/active                        the current user's running
                                               task, or 204
GET    /api/sync/tasks/{task_id}               status, for reattachment; for
                                               a discovery, its result
GET    /api/sync/tasks/{task_id}/events        SSE stream, replayed from the
                                               start
POST   /api/sync/tasks/{task_id}/input         answer a prompt, or cancel it
POST   /api/sync/tasks/{task_id}/abort

  session — a password or an OIDC sign-in (§5.6)
POST   /api/session                            log in with a password
GET    /api/session/oidc                       log in with OIDC: redirects to
                                               the provider
GET    /api/session/oidc/callback              the provider's return: signs in
                                               or refuses, back to the app
DELETE /api/session                            log out: deletes the session row
GET    /api/session                            who am I

  changes — whether what a view shows has changed (§4.2)
GET    /api/changes                            the change value of the ledger,
                                               of the documents and of each
                                               account, the current user's
                                               active task, how many entries
                                               the model still has to look
                                               at; a write's response
                                               carries the values after it

  configuration — read-only (§5.7)
GET    /api/config                             base currency, the matching window,
                                               default locale, whether OIDC
                                               sign-in is offered or enforced;
                                               never a secret, and read
                                               without a session

  reporting — read-only aggregates over core/reporting (spec §8)
GET    /api/reports/overview                   the Overview's figures and
                                               accounts: net worth, savings
                                               of the last 12 months, last
                                               month and this month, this
                                               month's spend against last,
                                               account data age and status;
                                               also the receivable and debt
                                               totals, and a clearance
                                               account's "open" age (its data
                                               age, spec §3.11)
GET    /api/reports/by-category                a date range, as a category
                                               tree, with the unclassified and
                                               reconciliation lines beside it;
                                               the Overview's top categories
                                               are this route with `top`
GET    /api/reports/over-time                  a range cut into periods: the
                                               savings and rate of each, or
                                               each category's amount
GET    /api/reports/balances                   net worth, each account kind's
                                               net worth and every account's
                                               balance at month-ends
GET    /api/ledger/entries/export              CSV of the ledger list's filter,
                                               dimensions joined

  maintenance
POST   /api/maintenance/settle                 settle now: bring derived state
                                               up to date (spec §5)
GET    /api/maintenance/check                  integrity views (schema.sql §9)
```

**Reporting answers carry the sums, so the client adds nothing** (§6.3). Every
figure is a `Line`: its total in the base currency (null when entries exist and
none could be valued), the number of entries covered, and the unvalued
remainder per currency (`spec.md` §8). Savings is one shape, computed once and
used by the Overview and the over-time report alike: income, expense,
unclassified, reconciliations, their sum, the rate, and whether it is
incomplete. A report's filters are the ledger list's (`spec.md` §8), one
predicate, so the entries behind a figure are exactly the entries its
drill-down lists.

**Starting a sync is validated as a whole**: nothing starts if any item is
refused. An unknown instance or account is 404 `not_found`, an account not
linked to the instance 409 `account_not_linked`, the other user's instance 403
`forbidden`, a disabled one 409 `instance_disabled`, a file importer 409
`not_a_fetch_source`, an importer not registered here 409
`importer_unavailable`, a closed account 409 `account_closed`, a `since` for an
account with coverage 422 `start_not_editable`, an empty plan 422
`nothing_to_sync`, a user who already has a task 409 `task_active` (its
`details.task_id` lets a client that lost its tab reattach) and an instance
another task holds 409 `instance_busy`. "Everything" leaves out silently what
an explicit item would be refused for, and reports an instance held by another
task in `busy`; if nothing remains, that is 409 `instance_busy`. A discovery is
refused likewise, and 409 `not_an_account_source` for an instance that does not
emit transactions.

**An instance the user may not run is read-only for them** (`spec.md` §5.11):
changing its settings, label or `disabled`, resetting it, deleting it, linking
or unlinking an account and discovering its accounts are 403 `forbidden`, as
starting it is. Reading it is not restricted: the other user reads everything,
settings included.

Two things the grouping is meant to make obvious. `units` acts on ledger
entries but is its own group, because an interpretation is committed per
unit, atomically, not as a sequence of field updates on entries. And
`importers/instances` are instances of an *importer* — a configured
credential — not instances of some unnamed thing.

**"Previewed" is one convention.** Every operation above marked *previewed*
— merges, marking a duplicate, a revert, a link, a rule change — takes a
dry-run flag: with it, the operation returns everything it would change, in
the shape of its real response (below), and writes nothing; without it, it
writes. The exception is the unit preview, which is an in-memory overlay over
the functions settling uses (§6.3), not a rolled-back write; the entry form's
`PUT` and `DELETE` (their effect on a unit is a real write) use the flag. Where the set it would change is a filter's result, counts stand for
the list, and the real run carries the count it confirms. There is no separate preview path to drift from the real one.

**Management writes.** Previewed are category merge, payee merge, rule create,
update and delete, payee delete (it takes the rules that set the payee and
leaves those whose condition names it dangling; the preview lists both) and
category delete; the other writes of the
dimension group go directly. Like applying a tag, the real run of a merge or
a rule write carries `expected_count`, the count of entries its preview
reported; when the number has moved nothing is written and the answer is 409
`conflict`, reason `filter_result_changed`, with `expected` and `actual`. A
rule write's request names the rule (`name`), what it sets (`sets`, on
creation only), the target value, the conditions (any rule's may include account
conditions, `{"field":"account","op":"is","value":"<id>"}`, and a category rule's
payee conditions, `{"field":"payee","op":"is","value":"<id>"}`; core checks that
the account or payee exists) and `priority`; it returns
the rule, the preview's lists (the entries matched, the units it would
confirm, lists A and B, `spec.md` §5.9) and the settle result. It also carries `settle_breakdown` next to `settle` (null on a dry run and when settling failed): the entries settling touched, counted by the final derivation pass of the field the rule sets, as `{total, this_rule, history, other_rules, other}`: decided by this rule, proposed by history, decided by another rule, and everything else (no value for the field, flag-only changes, the user's own decisions, entries that still carry a deleted rule's key). The parts add up to `total`, so the client can say where the touched entries come from without changing the settle steps. A preview row is an entry with its
`source` (above): its own fields (booked date, account, amount, the current value and key of what the rule
sets) and the nested source.

**A merge bumps the versions of the entries it repoints.** Their category or
payee changed, which is a user-meaningful change like any other: an open
panel showing the old value is refused and reloads, as for every conflict
(`patterns.md` §8). A merge still decides nothing anew (`spec.md` I18): keys
are kept, nothing is derived again, nothing returns to review. It is rare and
explicit, unlike settling's constant rederiving, so the conflicts it causes
are cheap. Independently, a client may still hold an old id — a stale lookup
list, a picker in another tab — and must not write a dangling reference
silently. A write that names a category, payee or account that no
longer exists is therefore refused as a conflict: 409, code `stale_reference`,
details naming the field, never a generic validation error. The client reloads
the lookups on that code and keeps the draft where it can, as for other
conflicts (`patterns.md` §8). A merged-away id is simply an id that no longer
exists: there is no redirect and no `merged_into`.

**Preview and commit are the whole write path for interpretation.** The
client holds a draft — the user's choices for one unit — and asks
`preview` what it implies; converting, splitting and re-pairing are draft
edits, not server operations. Nothing persists until
`commit`. A commit is always of one whole
unit; there is no batch commit and no operation that rejects a single
derived value (spec §6). Only a commit splits (spec I7), with one exception:
a booking, which settling creates split along its document's lines and which
no commit re-splits (below). A
commit does not confirm: it writes what the user saw, and settling derives
whether the unit is confirmed. It is refused, with the reason, only where the
result would break an invariant or the unit moved underneath the panel; the
preview returns the state the commit leads to.

**What a commit carries.** The draft; the value of every field as the preview
showed it, with the basis of each proposal shown; temporary ids for the rows
the draft creates — negative integers the client issues, echoed by the
preview and mapped to real ids in the commit response; a **tag change** per entry, `tag_ids_added` and
`tag_ids_removed` relative to the tags the entry had when loaded (never the full set), carried by the preview
too and omitted for an entry whose tags the draft does not touch; the version of every entry it writes or showed as a
consequence. The server lays the draft
over the stored state again and writes the values sent. It derives the keys
itself (`spec.md` §5.9): a standing key is kept only where the stored value is
unchanged and was standing, a value equal to a shown proposal becomes `user`
with that proposal's key nested as its basis, a `user` value left unchanged
stays, anything else is `user` without one. The client may name a basis only
for the passes `history` and `llm`; it is stored wrapped
under `user`, never trusted as evidence, so a client can never assert a `rule`
or `own_account` key. A field that may be empty, such as the payee, and that the
commit leaves empty — cleared (`mode: fixed`, no value) or left so — is decided
empty: the key `user` on a NULL column (`spec.md` §5.9, field order). A field
that may not be empty — type, category, counter-account — is not decided by a
`fixed` draft without a value, which is treated as re-resolve, and an empty one
carries no key. A commit does not confirm (`spec.md`
§5.9, §6). A counter-account that a pick
fills on a leg that had none is the pair's: it takes the pair's pass with the
basis `{"from": "counterpart"}`, and leaves with the pair (`spec.md` §5.7). Besides an invalid result, it
refuses only on a structural divergence: a moved version, a partner taken, a row the draft
relies on gone, or a closure that changed under the locks (409 `unit_moved`).
A commit locks in one order: the settle lock shared, then the accounts it
touches ascending, then the entry rows ascending; it reads the unit before the
locks and checks it again after.

**Tags in preview and commit.** Preview rows carry `tag_ids` with the draft applied (a new split entry starts
with the original's); tag changes are never listed as consequences and affect no state, flag or proposal, and
re-resolve never touches them. The commit applies the membership changes in the same transaction, after the
entries exist (rows the draft creates have real ids by then), under the locks above and idempotently: adding a
present tag and removing an absent one are no-ops. A tag deleted meanwhile refuses the commit as a conflict,
409 `stale_reference`, details naming the tag. An entry the draft removes takes its tags with it. A commit
that changes only tags is valid and, like any commit without a change, bumps no version; membership changes
move no `ledger_entry.version` in any case, so no version is involved in them.

**Bookings in preview and commit** (`spec.md` §5.8, §6). A booking's unit is
reviewed like any other, but its structure is its source's: the preview marks
it `booking`, with its source (`booking {kind, id, …}`, as on the ledger list's
`source`), each row carries
its `source_text`, and the panel offers no partner, convert or split controls
on it. The values open to a draft are the payee, the category, the
description, the note and the tags; the type stays `flow` on a document's
booking and `transfer` on a counter-leg. A draft that changes a booking
entry's type, amount or split, pairs or unpairs it, or removes one of its
entries is refused with 422 `invalid_draft`, reason `booking_fixed`. A booking
entry is never a transfer offer or a candidate for another leg. Settling may
change a booking under an open panel — its document changed — and the
structural columns that moves (amount, source text, an entry removed) bump the
versions, so the commit is refused with 409 `unit_moved` and the panel
reloads, as for every conflict (`patterns.md` §8).

**Pairing in preview and commit** (`spec.md` §5.7). The draft carries a `pairing`
field per transfer leg, with a mode: `keep`, `pick` (a partner entry id),
`counter_leg` (a temporary id and the amount received) or `reresolve`. The
preview response carries, on each row that is a transfer leg (`rows[].transfer`),
its `state` (`paired`, `waiting`, `unmatched`, `needs_account`), the account waited
for or the currency needed, its partner and its **offers**: each with a `kind`
(`open_leg`, `untyped_entry`, `paired_elsewhere`, `counter_leg`), `exact`,
`proposed`, the partner summary of a leg paired elsewhere (`paired_with`) and an
`effect` (typed as transfer, the difference that becomes a flow, the pairs it
breaks), in group order; the counter-leg offer carries its date, purpose and
amount, or that the amount received is needed. The leg also carries the
`proposal` and `has_more` where candidates lie beyond the window. A proposal the
preview takes as the pick it proposes is marked on the leg (`proposed_pick`, or
`proposed_counter_leg`), and a counter-leg, proposed or drafted, is a row of its
own with `counter_leg_for` naming the leg; the id of a proposed one is issued by
the server, a negative far from those the client issues. The window for one pick is
the request parameter `window_days`, at most 90 days, on preview and commit: the
preview checks a pick against the window requested, the commit against the 90-day
cap, and `window_days` on a commit names the window its proposals were shown for.
The unit's state distinguishes `waiting` from `unmatched` and carries the account
waited for; the queue's `needs_account` entries carry the currency needed. A pick
or an offer the server does not recognise is refused with a problem code:
`partner_not_offered`, `partner_in_unit`, `second_transfer`,
`counter_leg_not_offered`, `counter_leg_account_synced`, `clearance_transfer`
(an entry on a clearance account made a transfer, `spec.md` §5.7),
`received_amount_required`, `received_amount_not_needed`. An amount received that
is not positive (`received_amount_sign`) is a core error; over the API it is a 422
validation error.

A commit takes a proposal as the user's choice only where the request carries
versions for the whole closure of the proposed partner; and where it cannot make a
partner or counter-leg the preview proposed, it is refused with the problem a
chosen one would raise.

The commit's closure and locks extend to the pick: the closure includes the
picked partner's own closure and the former partners, and the lock set the
counter-leg's account — up to four accounts, locked in ascending order, then the
rows ascending — with the closure read again under the locks (409 `unit_moved`).
**Only a commit creates a user-authored counter-leg:** a source of origin
`user` on the unsynced account, its entry typed `transfer`, with the keys
`user`; the commit then follows the partner's amount where the spec says
(`spec.md` §5.7). **On a clearance account the counter-leg is a booking**,
made by settling, not by the commit (`spec.md` §5.7): a leg whose
counter-account is a clearance account has no offers, and once its type and
counter-account are decided the preview shows the booking settling will make
for it — a row with a temporary id, `booking_for` naming the leg — which the
commit does not write. The preview overlay runs the same pure pairing and
booking functions as settling, so the preview equals the commit plus
settling.

#### The ledger list and tags

**The list** is `GET /api/ledger/entries`: one page of the entries a filter selects, and the count of all of
them. The filter is the dimensions of `spec.md` §8, one query parameter each; the generated schema names
them all, these are the ones that carry a rule.

- `from`, `to` select by `booked_on`, inclusive at both ends.
- `account_id`, `category_id`, `payee_id`, `tag_id`, `type` and `flag` repeat. **Several values of one
  dimension are alternatives (OR); dimensions combine (AND).** An entry matches `tag_id` by carrying any of
  the tags, and `flag` by carrying any of the review tokens (`spec.md` §6). An entry with no type yet matches
  no `type`.
- `category_id` includes the category's descendants; `category_descendants=false` asks for the category
  itself. `uncategorised=true` adds the entries that could have a category and have none (type `flow`, or no
  type yet; never a transfer or a derived entry) to the category dimension, so with `category_id` it is an
  alternative, not a restriction.
- `amount_min` and `amount_max` bound the **magnitude** of the amount, in minor units, inclusive, never
  negative. They require `currency`, and the list then holds only entries in that currency: a range across
  currencies is meaningless and nothing is converted for it. `currency` alone selects that currency.
  `direction` (`in` or `out`) keeps amounts above or below zero.
- `q` is a text of 1 to 200 characters; every word of it must occur, case-insensitively and as a substring,
  in at least one of the entry's description, note and source text, the source transaction's counterparty name, purpose,
  end-to-end id and mandate reference, the payee's name and the category's name.
- `limit` (1 to 500, default 100) and `offset` page the result.

A value that cannot be understood or a filter that contradicts itself (`from` after `to`, `amount_min` above
`amount_max`, an amount bound without `currency`) is a 422 naming the parameter (§4.4).

**Order and paging.** Newest first by `booked_on`, then by source transaction descending (entries without
one, the derived entries, first: a balance record is the state at the end of its day, so it stands above
the day's movements), then by id descending: the order is total, so pages do
not overlap, and the entries of one split, which share a date and a source transaction, are adjacent. Paging
is by offset. The answer is `entries`, `total` (every entry the filter selects, whatever the page), `sums` (the signed sum of their amounts per
currency, `[{amount, currency}]`, one item per currency present, ordered by code; nothing is converted,
`spec.md` I27), `limit` and `offset`.

**Rows.** An entry as the interpretation layer holds it: id and version, account, `booked_on` and `value_on`,
the signed amount with its currency (§4.5), type, description and note, `display_text` (derived: the
description, else the source text, else the counterparty name, else the purpose; offered for uses such as the
panel title and search results, while the list's description column shows `description` alone, `patterns.md` §4.1), payee, category,
counter-account and counterpart entry, source transaction, `source_text` (the text its source gives the entry, null for most, `spec.md` §5.9), `derivation`, `unit_key` (the same for every
entry of a unit), `origin` (its source transaction's: `import`, `user` or `booking`), review flags, tag ids and `source`. A row carries
ids only; names, icons and colours come from the account, category, payee and tag lists the client already
holds, and there is no running balance. A transfer leg also carries a read-only summary of its partner
(account, date, amount), so the list can show the partner when a filter hides it.
**`source`** is the entry's source transaction as one nested object, `null` only for derived entries, which
have none (every movement has one, imported, entered by hand or booked: spec §3). A source entered by hand carries its
amount and purpose and no counterparty, reference, booking text or source format; a booking's carries its amount,
purpose and, from a document, counterparty name (spec §5.8), and `booking {kind, id, …}`: its source — `document`, with the document's id, `provider` and `reference`, or `transfer`, with the charge's entry id and `account_id` — read only for navigation (the work panel's "Booked from …", a row's "Open document"). It holds the fields rules read or the UI shows: counterparty name, reference and BIC, purpose,
booking text, end-to-end id, mandate reference, instructed amount and currency, and source format. It never
holds the raw record or the content hash. The client reads the counterparty name and purpose from it; there
are no flat copies on the entry. Every entry read carries it: the list, `GET /api/ledger/entries/{id}`
(behind login, like the list) and the rows of a rule's preview. There is no filter by id.
The list includes every entry, derived ones too (`type` narrows it); a duplicate source transaction has no
entries (`spec.md` I3) and so never appears. It is a read: it takes no lock, writes nothing and does not
settle.

**The lists.** `GET /api/ledger/categories` (flat, `parent_id` linking the tree, roots first, then
`sort_order` and name) and `GET /api/ledger/payees` (by name) answer with identity and presentation as
stored; the client resolves inherited icons and colours. Their writes are the dimension group's.

**Tags.** `GET /api/ledger/tags` lists every tag by name with its derived span (`starts_on`, `ends_on`) and
`entry_count`; a tag no entry carries has no span and a count of 0. A name is trimmed, not blank and unique
case-insensitively (409 `conflict`, reason `duplicate_name`); a colour is stored as given. `PUT` renames or
recolours (a field left out stays; `color: null` clears it). `DELETE` removes the tag with its memberships and
answers `removed_memberships`; it has no dry run. Every tag write is one transaction, settles after it commits
(§5.2) and answers with `settle`, whose `error` is a notice, never an HTTP error.

**Tagging one entry** is `PUT` and `DELETE /api/ledger/entries/{id}/tags/{tag_id}`. Both are idempotent: 200
either way, `changed` says whether anything was written. A derived entry is refused (409, reason
`derived_entry`). The answer is `entry` (its `id` and `tag_ids` as they now stand), `changed` and `settle`.
These direct writes (the ledger's picker, tag all, settings) move no `ledger_entry.version`, so they carry no
`expected_versions`; the work panel's tags are part of its draft instead (below, *What a commit carries*). They are also the only way to tag an entry the filter does not select: there is no
operation over a list of ids, and a client that wants to add some entries to a filter's result calls this
one for each.

**Tagging a filter's result** is `POST /api/ledger/tags/{id}/apply`. The body is the list's filter as JSON,
with the same parameter names, repeatable ones as arrays and the same validation, plus `dry_run` and
`expected_count`. It tags every selected entry that can carry tags, in one transaction, leaving an
existing membership alone, and answers `selected`, `newly_tagged`, `already_tagged` and `skipped_derived`
(derived entries are skipped and counted), `per_account` (the accounts with newly tagged entries, with their
counts), the tag's span before and after and, for a real run, `entries` (id and `tag_ids` of every newly
tagged entry as it now stands) and `settle`. With `dry_run` the same code runs and is rolled back: `entries`
is empty and `settle` null. A filter that restricts nothing would select the whole ledger and is refused
(422). Because a tag write moves no version, the rule of *Requests carry what the client believed* cannot
guard the selected set; instead a real run must carry the preview's `newly_tagged` as `expected_count`
(422 without it), and if the filter now tags another number nothing is written and the answer is 409
`conflict`, reason `filter_result_changed`, with `expected` and `actual`.

#### The account statement

The account page (`ux/views/account.md`) is a bank-layer view: the account's
source transactions, duplicates included, and its balance records, in one
list. `GET /api/ledger/accounts/{id}/statement` answers it and reads nothing
of the entry layer. It is a read: no lock, no write, no settle.

**Order and paging.** Newest first, as the ledger list is (*The ledger list and
tags*): a source transaction by `booked_on`, then source id, both descending;
a balance record stands above the rows of its own date, because it is the state
at the end of its day, and records of one date are by id, descending. The order
is total. `limit` (1 to 500, default 100) and `offset` page it, and the answer
is `items`, `total` (every item the account has, whatever the page), `limit` and
`offset`. `amount` (signed minor units) keeps only the imported source
transactions of that amount that are not duplicates, and no record: the picker
of "mark as duplicate of…". It changes no balance, which is always computed
over the whole account.

**Items** are of two kinds, told apart by `kind`:

- `source` — the source transaction's id, `booked_on`, `value_on`, `amount`
  (§4.5), counterparty name, purpose, `origin` (`import`, `user` or `booking`),
  for a booking its `booking` (as on the ledger list's `source`),
  `duplicate_of` (the row it duplicates — its id, `booked_on` and amount, so
  the row can name it — else null),
  `entry_id` (the lowest id among its entries, which opens its unit in the
  review panel; null for a duplicate), and `run_id` (null for a row not imported). It never carries `raw`: provenance is
  `GET /api/ledger/sources/{id}`.
- `record` — the record's id, `balance_on`, `record_kind` (`reported` where the
  record has a run, else `manual`), `balance`, `anchor` (true for the account's
  earliest record),
  `rows_sum` and `difference`, both null for the anchor.

**The gap** is the formula of `spec.md`
§3.10 applied to source transactions and records alone. Let the counting
records be R₁…Rₙ in order of `(balance_on, id)`, with balances Bᵢ on dates Dᵢ,
and let the *movements* be the account's source transactions that are not
duplicates. By `spec.md` I3 the entries of a non-duplicate source carry its
dates and sum to its amount, so summing sources is summing the movements of the
formula.

- **Interval.** Movements dated in (Dᵢ₋₁, Dᵢ] belong to Rᵢ; those up to D₁ to the
  anchor R₁; those after Dₙ to no record.
- **Gap.** For i > 1, `rows_sum` is the sum of the movements in Rᵢ's interval and
  `difference` = (Bᵢ − Bᵢ₋₁) − `rows_sum`: the amount of the derived entry the
  record owns, or zero where it owns none. The anchor has neither; its derived
  entry is the opening, which absorbs what precedes it and explains nothing
  (`spec.md` §5.10). The function that derives the entries computes the
  difference, and the statement calls it rather than reading the entries, so
  the two agree by construction.
- **The records add up to the ledger balance.** The opening and the differences
  telescope: the derived entries and movements dated up to Dₙ add up to Bₙ
  (`spec.md` §3.10), so Bₙ plus the movements dated after Dₙ is the account's
  balance, the sum of its entries (I6). A test asserts this for every account.
- **Edge cases.** Records sharing a date stand after that day's movements, by id,
  and a later one's interval holds no movement: its `difference` is the change
  in balance between the two. A record of a reverted run does not count
  (`spec.md` §3.10) and is not an item, and the rows that run wrote are gone.
  An investment account follows the same formula: the difference is what the
  entry layer calls a valuation (`spec.md` §3.3), and an account kept by records
  alone has `record` items and none of the other kind. A closed account is
  unchanged. No counting record means *balance not anchored*: there are no
  `record` items.

**The account's facts gain `balance`**, the sum of its entries as money, and
`balance_as_of`, the latest day it is known for (`ux/views/account.md`), next to
`synced_through`, `last_data_on`, `unexplained_difference`, `anchored` and
`records_since_zero`, and on an investment account its performance
(`spec.md` §8): `net_deposits` and `gain` as money, `return_rate` as the
savings rate is carried, and `return_as_of`, the latest record's date. They are
computed as the gap is, from source transactions and records alone: net
deposits are B₁ plus the movements dated after D₁, and gain is the balance
less them. All four are null on any other account and on one without a
record, and `return_rate` also where `spec.md` §8 shows no return. They are on
every response that carries the facts: the list, and the
`account` of every write. The list and the page need it (`ux/patterns.md` §4.4
shows the facts wherever the account is shown with its balance), and the
Overview reads the same figure.

**A clearance account's providers.** `providers` is a list of names, each
trimmed and not blank, compared without regard to case; it is accepted for a
clearance account only (422 `validation_error` naming `providers` for any
other kind), as is `start_date`, which a clearance account requires on
creation and which is no field afterwards: the start is the opening record,
corrected like any record. A name that another account in the same currency
takes is refused as a whole write, 409 `conflict`, reason `provider_taken`,
with details naming the provider and that account. The account rows carry
`providers` (empty for every other kind). A clearance account is never linked
to an importer: discovery offers no link to one, and `POST
/api/importers/instances/{id}/links` to it is 409 `conflict`, reason
`clearance_account`. Its `external_ref` is set like any account's, so that pass
0 recognises the provider's IBAN (`spec.md` §5.9).

**An account's linked importers are not a route.**
`GET /api/importers/instances` already returns every instance with its linked
accounts, and the page filters them by the account. A household has a handful
of instances; an `importers` field on the account would repeat what the
instances state and add a second place to keep right.

**Marking and clearing from the statement.** `POST /api/ledger/sources/{id}/duplicate`
takes `of` (the row it duplicates), `dry_run` and `expected_versions`, the
versions of the entries the call removes or unpairs, which its preview returns
as revert's does; `POST …/not-duplicate` takes none. Both answer with
everything they touched (*Operations return everything they touched*), the
latter including the entry the row got. Marking a booking, or marking a row as
a duplicate of one, is refused (422 `invalid_duplicate`, reason `booking`): a
booking follows its source and is never a duplicate (`spec.md` §5.8).

**The catalog.** `GET /api/importers` lists what the deployment registers, one
entry per importer: `name`, `kind` (`file` or `fetch`), `emits` (the kinds of
`spec.md` §5.1) and `presets`, a map from a preset's name to the settings it
fills, for an importer that ships any (the CSV importer's, loaded from its
package data, `plugins/importers/csv.md` §8) and empty otherwise. Presets ride
on the catalog entry rather than a route of their own: they exist only to fill
the form of that importer, and the catalog is read when the form opens. The
settings form itself belongs to the client, one component per importer
(`ux/views/importers.md`). Creating an instance takes its `emits` from the
catalog's entry, never from the client; an instance of a file importer holds
no credential and is always `shared` (`spec.md` §5.11), while one that holds a
login is created with its owner and the access the user states.

#### Operations return everything they touched

**A response describes every entity the operation changed, not only the one
named in the URL.** Operations cascade: a commit may pair a leg with an entry
elsewhere in the list, create a counter-leg on another account, or return a
former partner to review; marking or clearing a duplicate recomputes an
account's derived entries; settling after any write may give other unconfirmed entries new
proposals, or book, re-derive or remove bookings on clearance accounts.

Without this, a client holding a list has no way to know that a row it is not
looking at has become stale, and will present as pending something the server
considers resolved. With it, the client patches exactly what changed and
needs no knowledge of which operations cascade — it applies whatever comes
back.

**What the response carries.** A write response holds full rows for the unit,
its consequences and the partners whose flags changed, and ids with a
`truncated` flag for the rest (settling can touch thousands); the ids of the
entries it removed; the states of the units concerned; and, for a commit, the
map from the client's temporary ids to the real ones.

The alternative, refetching the list after every action, is simpler and wrong
here: it reorders and removes rows beneath a keyboard cursor (§6.5).

#### Requests carry what the client believed

The inverse half of the same contract: an operation carries the version of
each entity the user was acting on, and the server rejects the write if it
has moved. Another tab, or the other user's sync, can change data this client
never heard about, so patching in place without a staleness check is only a
faster way to diverge.

**The token is `ledger_entry.version`,** a monotonic integer maintained by a
database trigger. Not a timestamp: timestamps can collide within a
transaction, and a concurrency check that silently passes on collision is
worse than none, because it invites trust. Not a hash of the row either —
that requires deciding which fields count, costs a computation on every read,
and gives the client an opaque token nobody can debug.

**The version bumps only on user-meaningful change.** `review_flags` and
`derivation` are excluded, and so is everything settling writes while it
rederives unconfirmed entries — enforced by the trigger's `WHEN` clause,
which settling opts out of with a transaction-local setting, rather than by
convention. A commit writes the state the user saw (spec §6), so a proposal
recomputed by the other user's sync must not refuse it; if it did, conflicts
would fire exactly when both people are working — which is when they are
least tolerable and most likely to be dismissed unread. Structural changes —
an entry's account, amount, counterpart or source text — always bump it (its
source never changes),
so a commit is refused when the unit itself moved underneath the panel, a
booking that followed its document meanwhile included.

**The check and the write are one step.** A write locks the entries it
carries versions for (`SELECT … FOR UPDATE`, in ascending id order, after
its advisory locks, §5.2),
compares the
versions, and writes in the same transaction. A unique-index violation
during a write — a leg taken between the check and the insert —
is answered as the same named conflict, never as a server error.

**Granularity is per entity, not per request.** An operation touching twelve
entries carries one version per entry and is rejected if *any* has moved: a
commit that re-pairs a leg and leaves a former partner behind is one
transaction, and partial application would be worse than refusal. The conflict
response **names which entities moved**, so the client refetches those rows
rather than reloading the list and losing its position (§6.5).

The versions an operation carries cover **every entry it writes**, including a
partner it unpairs or a leg it leaves behind. The preview lists them, and a
write that finds an entry it would write but was given no version for is
refused as stale, naming that entry: the client's view of the unit was
incomplete.

A rejected write means "someone changed this" — refetch and show it, never
overwrite a decision. Same conflict handling as the correlation ids in §4.3,
applied to entities instead of prompts.

### 4.2 REST for state, SSE for progress

A sync is minutes long, mostly server-driven, and occasionally needs an answer
from the user. The traffic is asymmetric: frequent one-directional progress
and prompts outbound, one or two tiny messages inbound per sync.

That is Server-Sent Events plus ordinary POSTs. SSE gives automatic reconnect
with `Last-Event-ID`, passes through proxies as a normal HTTP response, and
needs no framing, ping/pong or close-code handling. The TAN travels back as
`POST /api/sync/tasks/{task_id}/input` like any other request.

**Rejected — WebSocket.** A duplex channel to carry two inbound messages per
sync, in exchange for hand-rolled reconnect and message framing.

**Rejected — one long-pending request.** A request in flight cannot receive
input, so the TAN would need a second endpoint anyway; and the connection is
held open for minutes through whatever proxy is in front, which is the problem
SSE exists to solve properly.

**Event design.** The set is ten events, and its shape is fixed:

- Every event is a **named type**, and the client routes on the name. No
  untyped payloads discriminated by inspecting their contents.
- The stream carries **three kinds** of event: progress reporting (the task
  advanced), a request for input (the task is blocked until answered — a PIN
  or a TAN; nothing about data ever blocks a sync, `spec.md` §5.11), and
  terminal outcomes (a run finished or failed, an instance could not
  continue, or the whole task ended). Any event that does not fall into one of
  these should prompt a check that it belongs on this channel at all.
- **A request for input carries a correlation id**, echoed back on the input
  operation, so a late or duplicate answer can be rejected rather than
  misapplied (§4.3).
- **Events carry no secrets and no domain state the client could fetch
  instead.** Progress says what happened, not the whole updated ledger; the
  client re-queries when it needs data. One exception: `run_finished` carries
  the run's stored statistics (the object `GET /api/importers/runs/{id}`
  returns, so the run summary renders without a query; never a ledger row). A
  discovery's account list is not an event; it is the result on the task's
  status.
- **The stream is resumable, and reattaching is replaying.** Event ids are
  1, 2, 3, … per task. Without `Last-Event-ID` the stream replays the whole
  task from id 1 and then goes live; with it, what follows. A task's events
  number tens — a replay sends only the latest `run_progress` of each run — so
  there is no cap and no snapshot, and a reloaded tab recovers a prompt that
  is still open. A `prompt` event whose prompt has been
  resolved is replayed without its prompt body (§5.6). The first bytes are
  `retry: 3000`, a comment line `: keepalive` follows every 15 s, and the
  server closes the stream after `task_ended`.

| Kind | Event | Carries |
|---|---|---|
| progress | `task_started` | `kind` (`sync` or `discovery`); the instances, each with its items |
| progress | `instance_started` | `instance_id` |
| progress | `run_started` | `run_id`, `instance_id`, `account_id` (null for documents), `kind`, `since` |
| progress | `run_progress` | `run_id`, `done`, `total`: how far a run has got, where its importer says (§5.5) |
| progress | `prompt_resolved` | `prompt_id`, `outcome`: `answered`, `confirmed` (a decoupled challenge), `cancelled`, `expired`, `aborted` |
| input | `prompt` | `prompt_id`, `instance_id`, `run_id` (null while signing in), `expires_at`, the prompt (§5.5) |
| terminal | `run_finished` | the run's ids and `kind`, its stored statistics |
| terminal | `run_failed` | the run's ids and `kind`, `code`, `message`, `retryable` |
| terminal | `instance_failed` | `instance_id`, `code`, `message`, `retryable`, `run_ids`: the runs it ended failed (every planned item for a failed sign-in, the remaining ones for an early end; none for a discovery) |
| terminal | `task_ended` | `outcome` (§5.3), the counts of ok and failed runs, `not_started`: the instances never reached |

`code` is the taxonomy's code (§5.5); `message` is the run's error text. A
failed sign-in is one `instance_failed`, not a `run_failed` per account.

**What changed is state, so it is polled.** Whether a view's data has changed
since it was fetched is not progress: nobody waits on it, and a snapshot is only
refreshed when the user asks (`ux/patterns.md` §7). The server keeps a **change
value** per key — `ledger` (every entry, for the ledger list and the review
queue alike), `documents`, and one per account (its source transactions, balance
records and derived entries, for its page) — in process memory (§3). A value is
opaque: it is a start token and a counter, so a restart makes every value new
and a view shows the notice once, never misses one. The client reads them, with
the current user's active task and the model's remaining entries, every 30 s
— every 5 s while the model has entries to look at — and whenever the tab
regains focus.
A view remembers the value of its key read before it fetched, and shows "New
data — Refresh" when it moves. A write's response carries the values after it,
so the tab that wrote takes them and shows no notice for its own change. A
stream per tab was rejected: it holds a connection for the tab's life, and over
HTTP/1.1 a few tabs exhaust the browser's connections to the origin.

### 4.3 The task token, reload and multiple tabs

```
POST /api/sync                  → 202 {task_id, busy}
GET  /api/sync/tasks/{id}/events  ← SSE: progress … prompt … task_ended
POST /api/sync/tasks/{id}/input → 204
```

The task lives on the server, not in the tab that started it. Everything below
follows from that.

**Reload.** The client does not need to remember the token. A user may have
at most one active sync task, and the change values (§4.2) carry it: on mount,
and at every later read, a tab that is not attached to the user's active task
attaches to it. No token in local storage, nothing to go stale; a reloaded tab
recovers a sync in progress — including one blocked on a prompt — and a tab
that was open before a sync started in another one follows it within a read.

**Two tabs are allowed, and both show the same thing.** Both attach to the
same event stream and both render the prompt. This is not prevented, because
preventing it means locking, and locking means a stale lock after a crash.
Instead:

- **The stream is the shared state.** When one tab answers a prompt, the task
  emits the resulting progress event to *every* attached stream, so the other
  tab's modal closes on its own. Tabs converge because they are views of one
  server-side task, not because they coordinate.
- **Late and duplicate answers are rejected, not applied.** Every input
  carries the correlation id of the prompt it answers (§4.2). The task accepts
  an answer only for the prompt it is currently waiting on; anything else
  — a late, duplicate or other-tab answer, or a task that has ended —
  returns 409 `conflict` with `details.reason` `prompt_not_open`, which the
  client treats as "someone already answered" and dismisses.

That second rule is the one the backend must get right regardless of what the
frontend does: the server assumes answers may arrive out of order, twice, or
for a prompt that has already been resolved.

**Abandonment.** A task whose clients have all disconnected keeps running to
the end of the current importer instance and then, if it has been without a
client for more than 30 s, stops, with the outcome `abandoned`. The grace
keeps a reload that straddles an instance boundary from ending a sync. A
half-finished bank dialog is not worth preserving, and every instance is
independently retryable. A prompt that nobody answers ends by its own timeout
(§5.5), so the current instance always comes to an end.

**Status.** `GET /api/sync/tasks/{id}` tells a client whether to attach: the
task's kind, whether it is running or ended, whether it is aborting, its
outcome, the id of its last event and, for an ended discovery, its result. It
does not restate what a replay says.

Tasks are held in an in-memory registry keyed by token, with the owning user
recorded, so another user can neither attach to a stream nor answer a
prompt: for another user's task, status, stream, input and abort answer 404
`not_found`, not 403. A finished task stays 15 minutes, so a client that
reconnects just after `task_ended` still gets its replay and status; the
user's finished task is evicted when they start the next one. After a restart
the registry is empty: the active task is 204 and an old token is 404, which
the client treats as an interrupted sync (§11).

### 4.4 Error envelope

Every non-2xx response carries a machine-readable code, a human message, and
optional details. Codes come from the importer taxonomy (§5.5) plus generic
validation and auth codes. The frontend routes on the code, never on message
text — "wrong PIN" and "bank unreachable" lead to different UI, and one is
retryable while the other is not.

### 4.5 Cross-cutting constraints

Stated once here; enforcement is in §5 and §6.

**Session model.** A session references a user and records the authentication
method used. It is never coupled to a password: a password and an OIDC
sign-in are two methods ending in the same session. Transport is an `HttpOnly`, `SameSite=Lax`
cookie, `Secure` except to localhost (§5.6).

**Secret redaction.** No PIN, TAN or session token ever reaches a log, a
traceback or an error response. This is the credential policy of `spec.md` §7
applied to observability.

**Time.** Domain dates (`booked_on`, `value_on`) are calendar dates as the
institution reported them and are never converted (`spec.md` §5.4). *Today* —
the fetch day that coverage and the reported balance are judged from, the
defaults of the entry form and "set balance", relative dates in the UI — is
the day in the household's zone, a deployment setting. Exactly one
component reads the system clock.

**Money.** Signed integers in the minor units of their own currency
everywhere, in ledger sign convention (`spec.md` §3.3). An amount never
travels without its currency. No
float may reach the database or arrive from the client. Parsing and formatting
of locale conventions (`1.234,56`) happens at the edges only. Conversion to
the base currency happens in exactly one place (§5.6).

---

## 5. Backend

### 5.1 Module boundaries

Four top-level packages, arranged so the folder structure *is* the dependency
direction:

```
app/
  api/                   HTTP only. Routers, request/response models, auth
                         wiring, the SSE endpoint, static mount.
  core/                  The domain and everything that reasons about it.
                         No framework imports, no HTTP, no plugin imports.
    domain/              entities, enums, Money — imports nothing
    ingest/              identity and hashing, deduplication between source
                         rows, marking and clearing duplicates, revert, entry
                         creation, the removal routine
    balance/             balance records, derived entries (openings,
                         valuations, reconciliations), unexplained differences
    resolution/          pure resolution: field order, pass 0 (own accounts),
                         the orchestration of the classifier plugins
    matching/            transfer pairing and offers
    bookings/            bookings on clearance accounts: what each source
                         calls for — a document's booking split along its
                         lines with the spread of its total, a decided
                         charge's counter-leg — as pure functions, and the
                         writes of settling's booking step
    units/               unit membership, drafts, preview and commit
    settle/              bringing derived state up to date after every write:
                         rederiving unconfirmed entries, bookings, pairing,
                         derived entries, flags
    reporting/           aggregate queries, all conversion via base_value();
                         filtered by the ledger list's own predicate
    tasks/               registry and claims, the task with its events, the
                         prompter, the per-instance job; the change values
    plugins/             PROTOCOLS ONLY: the importer (file and fetch) and
                         classifier interfaces, the prompt kinds and
                         `SecretText`, the error taxonomy, the history source
                         classifiers read, the registry plugins register into
  plugins/               Concrete plugin implementations, one package each.
    importers/
      fints/
      paypal/
      csv/
    classifiers/         passes 1–3 of spec §5.9 (pass 0 is core), behind
      rules/             one protocol: propose a value, or its absence, and a
      history/           machine-readable basis. Ordered by authority.
      llm/               the model, asked in the background (§5.4)
  utils/                 Infrastructure with no domain knowledge.
    db/                  engine, connection, SQL helpers
    auth/                sessions, password and OIDC sign-in
    clock.py             the only caller of the system clock
    config.py            the one reader of the environment: typed, validated at
                         start, read-only (§5.7)
    logging.py           structured logging with redaction filters
  main.py                composition root: builds the app, registers plugins
```

Dependency direction, strictly one way:

```
api  ──►  core  ──►  utils
             ▲
plugins ─────┘        (plugins implement core/plugins protocols)
```

This direction is enforced mechanically: import-linter contracts in
`.importlinter` cover the layering, both rules below, `core/domain` importing
nothing, `core` never importing `utils/config.py`, and web frameworks being
imported by `api` and the composition root only. The one rule it cannot
express — only `utils/clock.py` touches the system clock — is an AST test.

Two rules carry the weight:

**`core` never imports `plugins`.** The protocol lives in `core/plugins/`; the
implementations live outside and register themselves at startup, wired in
`main.py`. So adding an importer touches one new package and one line of
registration, and `core` cannot develop a special case for a particular bank.

**Plugins never import `api` or `utils/db`.** An importer receives settings,
state, a prompter, one account and a fetch window, and returns records, an optional reported
balance and the date its coverage runs through. It does not know about
identities, deduplication, ledger entries or database transactions. This is what
makes `spec.md` §5.2's guarantee structural rather than aspirational: two
importers cannot deduplicate the same account inconsistently, because neither of
them deduplicates at all.

**Invariant ownership.** Each invariant of `spec.md` §2.1 has exactly one
enforcement point:

| Invariant (`spec.md` §2.1) | Enforced in |
|---|---|
| I1 source transactions come from an importer, are a user's on an unsynced account, or are bookings on a clearance account | `ingest`, the entry form's operations, counter-leg creation in a commit (`core/units`) and settling's booking step (`core/bookings`) are the only writers; `CHECK ck_origin`; trigger `trg_authored_source_account` |
| I2 imported source transactions immutable except `duplicate_of`; user-authored ones edited through the entry form; bookings follow their source; no row changes its origin | Postgres trigger `trg_source_immutable`; `core/bookings` is the only writer of a booking |
| I3 entries carry their source's account, currency and dates and sum to its amount; duplicates have no entries | Postgres deferred triggers `trg_split_sum` (on entries), `trg_source_entries` (on a source's copied columns) and `trg_duplicate_state`; `trg_entry_source_fixed` keeps an entry on its source; `ingest`, a commit, an edit through the entry form and clearing a duplicate write within one transaction |
| I4 one identity per row, unique per account over all rows | `CHECK ck_one_identity`; partial unique indexes over all rows |
| I5 one currency per account, for entries, source rows and balance records | composite foreign keys |
| I6 balance is the sum of entries | `core/reporting`; nothing else sums amounts |
| I7 one entry per new source transaction; only a commit splits, a booking excepted | `ingest` and the entry form; `core/units` is the only writer of splits, `core/bookings` of a booking's entries |
| I8 only entries with a source may be incomplete | Postgres `CHECK ck_complete_unless_movement` |
| I9 category implies flow; payee on flows; kind fixed; no cycles | Postgres `CHECK`, composite FK, triggers `trg_category_kind_fixed` and `trg_category_acyclic` |
| I10 transfer pair mutual, distinct accounts, opposite signs, same-currency equal; one counterpart | Postgres deferred trigger; partial unique index |
| I11 a counter-account is in the currency the money arrived in | one function in `core`, used by resolution (evidence filter), the preview and the matcher |
| I13 one derived entry per record, computed, never edited, tagged or annotated; the opening first | `core/balance` is the only writer; unique indexes; integrity views; `api` exposes no edit and no tagging for them |
| I17 no pass, matcher, settling or import creates a dimension or account | operations of §4.1; proposal types carry ids, not names |
| I18 proposals rederived, standing values kept; an entry resolved afresh when its input changes, and later fields derived again when a value changes | `core/settle` calls `core/resolution` and `core/matching` for the entries a change bears on; `core/resolution` applies the field order; the write that changes an entry's input resolves that entry afresh in the same transaction: an entry-form edit, and settling's booking step for the booking entries whose source text it changes (§5.2) |
| I19 history learns only from confirmed values, a human's or standing ones | `core/resolution` supplies the history; a plugin never sees unconfirmed values |
| I20 no automatic process changes a reviewed entry, a booking following its source excepted | `core/settle` and `core/matching` select only unconfirmed units; `ingest` marks only rows it inserts; derived entries and bookings are the exceptions, and `core/bookings` changes of a booking only what its source changed |
| I21 review per unit, committed atomically | `core/units`; `api` exposes no other write to an entry's interpretation but the two merges, of payees and of categories, each previewed and one transaction |
| I22 a transfer confirmed only as a pair | `core/units`, at commit |
| I23 review flags derived, never patched | set-based recompute in `core/settle` |
| I24 no automatic pair between legs a counter-account or end-to-end id distinguishes | `core/matching`; the purpose only breaks ties |
| I26 review state never excludes an entry from balances or reports | `core/reporting` ignores review state |
| I27 base-currency values computed by one function, called only by reporting | schema function `base_value()`, called only from `core/reporting` |
| I28 no payment-capable secret stored | importers; redaction (§5.6) |
| I29 final, booked records in ledger sign convention | importer contract |
| I30 only the latest successful, non-reverted transaction run of an account is reverted | the revert operation in `core/ingest`; `CHECK ck_reverted_transactions` |
| I31 at most one transfer entry per source transaction | partial unique index `ux_le_one_transfer_per_source`; the preview refuses first |
| I32 duplicates by identity (skipped), then by amount against imported source rows only (inserted as duplicates); first in wins | `core/ingest`, nowhere else; composite FK `fk_duplicate_same_account`, trigger `trg_duplicate_state` against chains |
| I33 an automatic pair needs a known counter-account | `core/matching` |
| I36 a reported record never dated after its run's coverage | `ingest`; integrity view `v_check_reported_after_coverage` |
| I37 every write ends by settling | every write operation ends by calling `core/settle`; a model answer is a write of its own |
| I38 an account's kind fixed at creation | trigger `trg_account_kind_fixed`; integrity view `v_check_derived_type` |
| I39 ingest serialised per account, settling as a whole | the advisory locks of §5.2 |
| I40 user-authored source transactions, counter-legs included, only on unsynced accounts | Postgres trigger `trg_authored_source_account`; `core/units` offers and creates user-authored counter-legs nowhere else, and offers none toward a clearance account; nothing automatic creates them (a clearance account's counter-legs are bookings) |
| I41 bookings only on clearance accounts, which are never linked to an importer; a booking exists exactly while its source calls for it, never a duplicate, never written through the entry form | triggers `trg_authored_source_account` and `trg_account_source_not_clearance`; `CHECK ck_origin` (no duplicate, a `source_id`); settling's booking step (`core/bookings`) is the only writer of bookings and removes what no source calls for; the entry form refuses a booking (422 `not_user_authored`) |
| pass ordering and field order | `core/resolution`, never a plugin |
| history's majority rule; its lookback period | `plugins/classifiers/history`; the lookback is a tuning parameter |
| LLM payload limited to the permitted fields | `plugins/classifiers/llm` |
| copied fields are not editable | `api` + `core`, per `spec.md` §5.9 |
| concurrency token bumped only on meaningful change | Postgres trigger `trg_le_version` |

### 5.2 Data access and transactions

SQLAlchemy Core for composition — the ledger list filter is date ∩ account ∩
category ∩ payee ∩ tag ∩ amount ∩ text, which is exactly what a query builder
is for. Hand-written SQL where it reads better: reporting aggregates and the
integrity views, which are already in `schema.sql`.

Transaction boundaries:

- **One transaction per transaction run**, covering every row of the
  delivery, its ledger entry and the run's reported balance record. A run
  succeeds as a whole or fails and writes nothing (`spec.md` §5.1): a failure
  at any row rolls the delivery back, and the next run starts from the same
  position. The deduplication of `spec.md` §5.2 runs inside it in two passes —
  identity for every row of the delivery first, then the amount step — against
  the rows the account held *before* the delivery, so a row inserted by this
  delivery is never a candidate for another of its rows. The `import_run` row
  itself is committed before it (below); the transaction sets it `ok`, with
  its `finished_at`, coverage and statistics, while it holds the account's
  lock — read with `clock_timestamp()` after the lock is taken, since `now()`
  is the transaction's start — so `finished_at` orders an account's runs as
  ingest wrote them —
  the order revert follows (`spec.md` I30). Runs finishing in the same clock
  tick are ordered by their id. A run that rolls back is set
  `failed` afterwards, in a transaction of its own.
- **A commit is one transaction**: values, splits, a
  counter-leg, an adjusted user-authored amount, and the removal routine for a partner left behind. It carries the
  version of every entry it writes — the drafted unit and every entry its
  preview showed as a consequence, such as a partner left behind or a picked
  leg's former partner — and is refused if any has
  moved (§4.1). A user-authored leg on an unsynced account, its source's only
  entry, paired in one currency with a leg whose amount the draft changes,
  is written with the negated new amount — not an input change, so its values
  stay (`spec.md` §5.7). The unit is the
  closure of the panel's anchor (spec §6): the source transaction it was opened
  from.
- **Clearing a duplicate is one transaction**: clear `duplicate_of`, create
  the entry.
- **Derived entries are recomputed in the transaction that changed their
  inputs** — an import, entering, editing or deleting a user-authored
  transaction, marking or clearing a duplicate, a revert, a commit, a balance
  record, and settling's booking step for the clearance accounts it writes
  on — under the account's lock, so an account's derived entries are never stale between
  operations. The rest of settling (`spec.md` §5) — rederiving unconfirmed
  entries, bookings, pairing, flags — runs right after the write,
  scoped to what the write touched.
- **Marking a duplicate is one transaction** — set `duplicate_of`, repoint
  the rows that pointed at the marked row, delete its entries, apply the
  removal routine — because the deferred trigger `trg_duplicate_state`
  checks that a duplicate has no entries and that no chain remains.
- **Reverting a run is one transaction**, in this order: (0) the run is set
  `reverted`, so that its balance record stops counting before anything is
  recomputed; then, in the order the constraints force, (1) for each of the run's rows that rows of *other* runs
  duplicate, the lowest-id of those is cleared and given its entry and the
  rest are repointed to it; (2) the run's entries are deleted through the
  removal routine (`source_transaction_id` is `RESTRICT`); (3) the run's
  source rows are deleted in one statement, since rows of one run may point
  at each other and the duplicate foreign key is checked per statement;
  (4) the affected accounts' derived entries are recomputed.
- **A category merge** merges the colliding children first, deepest first,
  moves the remaining children, repoints entries and rules, and deletes the
  merged category last: the name index is checked row by row.
- **Resolving afresh is the writer's.** A write that changes an entry's input
  (`spec.md` §5.9) — an edit through the entry form, which re-resolves fully,
  the user's values included (`spec.md` §5.6), or settling's booking step
  re-deriving a booking, which resolves afresh the entries whose source text
  it changes or creates, confirmed or not (`spec.md` §5.8) — resolves that
  entry in the transaction that changes it, as ingest resolves a new entry.
  Document ingest changes no entry: it writes documents only, and their
  bookings follow in settling. Settling, which keeps no record of what an
  entry was resolved from, then does the rest.
- **The import run row is committed before fetching**, so a crashed run leaves
  a `running` record rather than nothing. With one worker no run can outlive
  the process, so start marks every run still `running` as `failed` (§5.7).
- **Ingest takes the account's advisory lock** at the start of the run's
  transaction and holds it to the end, so the amount step's reads and every
  insert that follows cannot interleave with another sync of the same account
  (`spec.md` I39).
- **Settling holds an advisory lock** (`pg_advisory_xact_lock` on a fixed key)
  for the reason in `spec.md` §5: concurrent settles could pair the same leg
  twice. Because every write ends with settling, it must stay fast, or every
  edit queues behind a long settle.
- **Lock order.** Every write transaction takes the settle lock **shared**,
  first; settling takes it **exclusively**. A settle therefore never overlaps
  a write: it cannot write proposals it read before a commit over that commit,
  nor race document ingest, and writes still run alongside each other. After
  the settle lock come the documents, in ascending id order, then account
  locks, in ascending id order, then row locks, in ascending id order: a
  commit locks the accounts of every row its preview showed, then the rows;
  document ingest locks only its documents. Where the plan under the locks needs accounts not yet
  locked (a counter-leg's), the commit runs again with them, at most three
  rounds, and then answers with the "try again" conflict. **Settling takes no
  account lock but in its booking step**, the one place it creates rows and
  recomputes derived entries: the step takes the locks of the accounts it
  writes on — the clearance accounts, and the accounts of the charges whose
  pairs it makes, follows or releases — in ascending id order, after the
  documents in the order above (it reads documents under the exclusive
  settle lock and locks none). This is a contained exception — only
  bookings and their pairs; every other row and derived entry is written by
  the writes, in their own transaction. `settle(engine)` opens its own transaction after the write it
  follows, and sets the transaction-local `ledger.settling` so that its
  rewrites do not bump versions (§4.1). Should PostgreSQL still abort a write on a deadlock, the server
  retries it once, holding its whole payload; if the retry fails too, the
  write answers with a named "try again" conflict and writes nothing.
- **Change values move on commit, from the locks.** The lock helpers note on
  the transaction what it touches — the shared settle lock the ledger, a
  document lock the documents, an account lock that account — and the values of
  §4.2 move when the transaction commits, never on a rollback: a dry run or a
  failed write moves nothing, and no write path reports changes by hand.
  Document ingest, which locks its documents in its own statement, notes the
  documents itself; settling moves the ledger
  when it touched an entry, and its booking step's account locks move the
  values of the clearance accounts it wrote on. A
  write made outside the server process moves nothing.
- **The order of a settle.** One settle runs, over the units it covers:
  1. resolution;
  2. **bookings on clearance accounts**, one step for all of them (`spec.md`
     §5.8). Its sources are the documents a clearance account takes — the
     provider listed in the document's currency, dated after the account's
     start — and the charges whose transfer entry is decided, under standing
     keys, as a transfer to a clearance account. For each, the step derives
     what the source calls for, by the rules of `spec.md` §5.7 and §5.8 and
     `features/documents.md`, compares it
     with what is booked under the source's `source_id`, and writes only the
     difference: it books what is not yet booked; re-derives a booking whose
     source changed — its row, and its entries matched to the document's
     lines by position, the order of the entries (an unchanged line's entry
     keeps its values and keys, a changed amount or text is written, a
     removed line's entry goes through the removal routine, a new line gets a
     new entry); and removes, through the removal routine, a booking its
     source no longer calls for. A counter-leg is written paired with its
     charge. What a source calls for is a pure function of the source, the
     provider lists and the account's start, so the unique `source_id` makes
     the step idempotent: a second run writes nothing. It locks the clearance
     accounts it writes on (lock order, above) and recomputes their derived
     entries before it ends;
  3. resolution of the booking entries step 2 created or whose source text it
     changed;
  4. transfer pairing (`pair_transfers`), in booking-date order (`spec.md`
     §5.7), over every unpaired transfer leg but booking entries, which are
     never candidates, and legs whose counter-account is a clearance account,
     which only step 2 pairs, in every round; the matching window is the connection setting
     `ledger.matching_window_days`, which core reads from the connection like
     `ledger.max_rate_age` and never from configuration. A pair released by
     step 1 can be made again in the same round;
  5. review flags, and with them which units are confirmed (`spec.md` §6).

  Settling creates rows only in step 2; every other counter-leg comes from a
  commit. Units confirmed in step 5 teach history, which can change the
  proposals — and so the pairs and confirmation — of other unconfirmed units.
  Settling therefore repeats steps 1–5, over the unconfirmed units that share
  a history key value with a unit newly confirmed, until a round confirms
  nothing new. It terminates: step 2 reads only its sources, the provider
  lists, the accounts' starts and standing decisions, none of which a round
  changes, so it writes nothing after the first round; from then on settling
  never unconfirms a unit (`spec.md` I20), so the confirmed set only grows;
  two rounds are the ordinary case, and a maximum round count turns a step
  that never converges into a reported failure. The five steps are an ordered list. Step 1 re-derives a paired leg of an
  unconfirmed unit like any other and releases its pair on both legs when its
  type or its own counter-account changes (`spec.md` §5.7); a charge so
  released from a clearance account loses its counter-leg in step 2. That is what makes settling idempotent (`spec.md` I37).
- **A settle that fails** after the write it follows committed leaves the
  write standing and reports the failure in the operation's response —
  `settle` never raises for its own failure, it returns it as
  `SettleResult.error`;
  derived state is then stale until the next write, or start, settles —
  settling is idempotent, so nothing is lost.
- **Unique indexes are not deferrable.** A write that moves a unique value —
  re-pairing legs, a new anchor taking the opening —
  clears the old holder before setting the new one, within its transaction.
- **What a settle covers.** The **dirty set** of a write is the set of
  unconfirmed units whose derived state it can change:
  - a commit or any change to a confirmed value: the unconfirmed units that
    share a history key value (`spec.md` §5.9) with an entry it touched, plus
    the units it pairs or unpairs;
  - saving, changing or deleting a rule, a changed configuration, linking or
    unlinking an account: every unconfirmed unit;
  - an import: the new entries, the units whose pairing candidates they
    affect, and every unconfirmed unit when it delivers a balance record or
    coverage that moves a waiting decision;
  - document ingest, a write of a clearance account's providers and a change
    of its start: the booking step over the clearance accounts concerned, and
    the units of the entries it creates or changes.

  The **baseline is a
  pass over every unconfirmed unit**, with the booking step over every
  clearance account, and narrowing to the dirty set is an
  optimisation taken only where the budget is missed. The budget is set from
  a backfill-sized fixture — a year of history, thousands of unconfirmed
  entries, one commit — and is a test, not a guess. Settling's result — everything it
  touched — is part of the operation's response (§4.1).
- **Every operation that recomputes derived entries or creates a counter-leg
  or a booking takes a per-account advisory lock** (`pg_advisory_xact_lock` on each
  affected account id, in ascending id order, following the lock order above). Unique
  indexes already make a racing double insert fail loudly; the lock prevents
  the quieter failure, two users' edits on one account each recomputing its
  derived entries from a snapshot without the other's change.

### 5.3 Task orchestration

A task is one sync or one discovery (its `kind`), over a list of jobs, one per
importer instance: a sync's job is an instance with its items, a discovery's
one job is "open, list the accounts, close". The orchestration is one
`asyncio.Task`; each job runs in a worker thread (§3), because an importer
blocks. The party awaiting an answer is therefore a blocked thread, not a
coroutine: the task holds its events, its one open prompt and its subscribers
under a lock, and `/input` fills a one-slot hand-off that the importer's thread
waits on. A task can be tested without an event loop.

**Instances run one after another**, in instance id order, among those the user
may authenticate (`spec.md` §5.11). Each signs in, possibly prompting, is asked
for each item in turn — each linked open account from its fetch start (§5.5),
then each accountless kind it emits — and closes before the next begins. At most
one prompt is open in a task. While an importer prompts or fetches nothing is
held open: no transaction, no lock, no connection.

**Claims.** The registry takes two claims when a task starts, in one step: the
user's one active task, and one holder per instance (§4.1 names the refusals).
A claim on an instance is released when its job ends, or at the task's end for
an instance never reached; two instances that reach one shared account are
serialised by the account lock in ingest, nothing new.

**One run per fetch.** A run is started just before its own fetch, so its
`running` status and `started_at` are true, and is ended by ingest or by a
failure. A failed sign-in starts a run per planned item and fails each at once,
so the account page shows a failed run per account, and emits `instance_failed`.
A failure's class decides what it ends (`scope`, §5.5): an **item** failure
fails that run and the next item goes on; an **instance** failure fails the
remaining items' runs with the same error and ends the instance. Either way the
other instances go on, and a failed run writes nothing (`spec.md` §5.1).

**Prompts.** When an importer needs input it asks the prompter (§5.5), which
emits a `prompt` event and blocks the importer's thread until the correlated
`/input` call, a cancel, or the timeout. A cancel or a timeout reaches the
importer as `ChallengeAbandoned` or `ChallengeExpired`, which ends its instance
by its scope; the next instance goes on.

**Abort** ends the task. It sets a flag and resolves the open prompt as
aborted; a bank call already in flight is not interrupted. Before each fetch and
each ingest the job looks at the flag: a delivery that arrives after the abort
is discarded, not ingested, and its run fails `ChallengeAbandoned`, as do the
instance's remaining runs. Instances not yet started write nothing and are
listed in `task_ended.not_started`. Aborting an ended task is a no-op.

**The end.** A task ends `completed` (every job attempted ran to its end,
whatever its runs' results), `aborted`, `abandoned` (§4.3) or `crashed` (a bug
in the orchestration: every run the jobs started and did not end is failed,
retryable). The task is marked ended and the user's slot freed before
`task_ended` is emitted, so a client reacting to it may start the next task.

Nothing about data raises a prompt: duplicates are marked at ingest
(`spec.md` §5.2) and listed in the run summary.

Nothing credential-grade is written to the database (`spec.md` §7), so there is
no encryption key to manage. The PIN lives in the importer's memory for its job
and an answer only in the hand-off (§5.6); no bank dialog is kept open between
calls. The cost is that a restart loses the task and any prompt it was waiting
on (§11).

**Settling.** Each ingest settles after its commit (`spec.md` §5), so a task
stopped at any point leaves nothing stale; the task settles once more at its end
only if a run's settling reported an error.

### 5.4 Classifier interface

Passes 1 to 3 of `spec.md` §5.9 are one protocol with three
implementations, ordered by authority. A classifier receives an entry's
inputs — its source transaction, its account, its source text where it has
one, and the fields the review draft fixes — and returns zero or more proposals, each
carrying the field it proposes, the value — or none: a proposal may explain
why the field stays empty — and a **machine-readable basis**, never a prose
string alone. For history the basis carries the evidence: how
many matches agree, of how many, since when. The basis is what
is written to `ledger_entry.derivation` and what the review panel renders, so
producing one is part of the contract rather than an optional extra.
**Classifiers are pure**: they write nothing to the ledger, so ingest,
settling and the review preview call them alike (`spec.md` §5.9). The model's
stored answer — the field's `llm` key (below) — is read as an input.
Whether a stored answer still stands for the entry as it is now is the
classifier's to judge: the model's stands while the payload it was given is
the entry's payload, and only then does its classifier propose it, value or
absence. That classifier asks nothing, so it is registered whether or not a
model is configured: without one, nothing is asked, and answers stored earlier
still stand.

**Classifiers do not query the database** (§5.1). `core/resolution` hands
them their evidence: the rules, read once per settle or preview, and a
read-only history source. For a key and an entry it returns the candidate
votes — confirmed entries within the lookback, excluding the given unit —
with the facts the classifier's filters need: each vote's values, booking
date and, for a counter-account, that account's currency and closing date.
Core retrieves candidates by indexed lookups on each key's value; the
classifier refines them — by mandate, booking text and purpose similarity —
and counts. What counts as a match is the classifier's to
define; how candidates are found fast enough for settling's budget is core's.

The orchestration is fixed in `core/resolution`, not in the plugins: fields are
resolved in the order of `spec.md` §5.9 — type first, then the fields the type
allows — passes run in order of authority, the first proposal per field wins —
save history's category where its votes are not unanimous, which gives way to
a stored model answer (`spec.md` §5.9) — and only pass 0 and rules write standing keys (`spec.md` §5.9); nothing history
or the model returns is ever confirmed without a human. A classifier without
the evidence it requires returns nothing for that field: history proposes only
what a strict majority of its matches share (`spec.md` §5.9). Pass 0 (own
accounts) is part of `core/resolution` rather than a plugin, because it reads
the household's accounts.

**A classifier may only reference existing categories and payees.** Proposals
carry ids, never names, so the type system makes invention impossible rather
than relying on a rule being observed. Creating a dimension row is a user
operation (§4.1); the name-suggestion endpoint returns a string and writes
nothing.

**The AI classifier speaks the OpenAI chat-completions protocol** against a
configured base URL, model name and optional key. That protocol is chosen for
ubiquity rather than preference: local runtimes and hosted providers alike
expose it, so pointing the deployment at an on-premise server is
configuration, not a code path. `spec.md` §5.9 requires only that the model
be external and configurable; this is how.

Three properties the implementation must have:

- **Absent configuration, nothing is asked.** No default endpoint, no
  fallback provider. Entries fall through to the review queue unclassified
  and the system stays fully usable — this is the state a deployment without
  a model is permanently in, not a degraded mode.
- **The request payload is restricted** to the fields `spec.md` §5.9 permits:
  counterparty name, booking text and purpose, and for an entry with a source
  text also its source text and the name of its account. Never IBAN, BIC,
  references, amounts, dates,
  account numbers or balances. Enforcing that is the plugin's responsibility and is
  tested explicitly; with an empty payload the plugin is not called. Restricted
  is not anonymous: names and purpose lines include private persons' details, so
  a hosted endpoint receives third-party personal data. An on-premise model is
  the expected configuration, and this statement is repeated in the
  configuration documentation next to the endpoint setting (`.env.example`)
  and in the plugin's own documentation.
- **It returns ids, not names** (above), so a malformed or hallucinated
  response fails validation rather than inventing a category.

- **It is asked at most once per input** (`spec.md` §5.9). Its answer is kept
  only as the field's `llm` key, with a fingerprint of the payload; resolution
  reuses it while the payload is unchanged, and the plugin keeps no table of
  its own. A changed payload — a booking entry whose source text its document
  changed — asks anew; a booking entry whose text a re-derivation leaves
  unchanged keeps its answer. A preview never asks the
  model: a payload the commit changes is asked by the settling that follows.
  Settling never waits for the
  model: the request runs outside it, and storing the answer is a write that
  settles like any other.

**One worker asks, in the background.** Settling puts an entry whose category
falls to the model, with no answer standing for its payload, on an in-memory
list. An entry is listed for the model where its category falls to pass 3 —
no proposal, or history's where it gives way — with the categories history
counted for it; the worker asks with those, and an answer given on categories
history has since changed is no longer proposed, so the entry is listed again.
One worker takes them in order, one request at a time, and stores each answer
with a write that settles like any other. An answer for a category a user or
a pass of higher authority decided meanwhile is dropped, so nothing changes
under the user. A restart loses the list and the start's settling
refills it. The request asks for structured output — the category as one of
the listed ids or none, and a one-line rationale — and the category list is
the same system message on every request, the whole tree in a fixed order,
so a server that caches a prompt prefix processes only the entry's text.
Timeouts are short and failure is non-fatal: an unreachable model leaves its
entries as the earlier passes left them — history's proposal where it gave
way, otherwise unclassified — exactly as an unconfigured one would; the
worker tries again after ten minutes, or when settling hands it new work.

### 5.5 Importer interface and error taxonomy

An importer that fetches implements one protocol, `FetchImporter` in
`core/plugins/fetch.py`; a document importer is one of them. It declares the
set of kinds it emits (`spec.md` §5.1) and, for documents, the providers it is
built for, if any (suggestions only), and its re-delivery mode (below);
validates its settings, gives a default fetch start, and opens a **session**
from its settings, its `state` and a prompter. The session lists reachable
accounts — one per currency pocket for multi-currency providers, each with what
it can deliver, transactions and a balance (used by discovery only) — fetches
one account from a start date and reports the account's booked closing balance
if it has one, fetches the documents from the instance's `start_date`
(`spec.md` §5.5) — given the lookup from currency to its minor-unit exponent an
account fetch is given, since a document states its own currency — and closes;
the orchestrator always closes it. The orchestrator
calls only the methods for the kinds the importer emits. An importer emits
only final, booked records, in ledger sign convention. Each
transaction record carries its `source_format`, the instructed amount where the
source reports one, `source_id` when the source assigns one (`None` otherwise),
and a `raw` payload containing the original unparsed data.

**A session is the credential in memory, not a transport.** It holds what the
user typed (the PIN), what the importer has learned (`state`) and the prompter.
A bank may demand a challenge, and a fresh dialog, per data call, so the
importer may ask for input from any call, not only from `open`: the user types
the PIN once per sync and meets challenges as the bank demands them. Every call
blocks and is made from a worker thread (§3, §5.3).

**Progress.** `fetch_account` and `fetch_documents` take a keyword parameter
`progress: Callable[[int, int], None]`, called as `progress(done, total)`. An
importer whose run works through a number of items it knows — the email
importer, its messages — calls it after each; one that does not know the number
never calls it. It carries counts only, never blocks, and core forwards it as
`run_progress` (§4.2).

Beyond the records, the protocol has an importer report:

- its **coverage** for every run — *through*, by the rules of `spec.md` §5.1
  and nothing later, including for a fetch that returned no rows — where
  its data starts, for the import log, and its own counts (zero bookings it
  filtered out, say) as named integers, which the run's statistics record;
- its **balance date** consistent with the core rule and never after the
  run's coverage (`spec.md` §5.1), and for statement formats the
  per-statement consistency check, failing with `ParseFailed` on a mismatch;
- a **default fetch start** for an account without coverage and without
  entries (`default_fetch_start`, which needs no session). The core derives
  every fetch's start when its run begins (`spec.md` §5.4) and asks the
  importer only as the last resort; the plan read (§4.1) shows the start
  prefilled, editable for that run only where there is no coverage;
- for documents: one per order or refund, complete as the provider shows it
  and dated on its own day — an order on the day it was placed — with signed totals, merchant name and lines
  (`spec.md` §5.5); and its **re-delivery mode**, `replace` or `keep`,
  declared by the importer's code like `emits`, never by an instance's
  settings and never stored. Under `replace` ingest updates a re-delivered
  document in place; under `keep` it leaves the stored one as it is and counts
  the delivery as kept in the run's statistics. Either way ingest writes only
  documents, and settling books them (§5.2). The email importer declares
  `keep`; the test document importer `testdocs` declares `replace`, so that
  path is implemented and tested;
- for any token it would store: the documented scopes, and the introspection
  check where the provider has one (`spec.md` §7).

A **file importer** has no session to open and nothing to fetch: it is a pure
parse of the uploaded bytes, given the profile, the account's currency, a lookup
from currency to its minor-unit exponent and today's date, and returns the rows, the reported
balance and its date, the coverage, where the data starts and its counts. A
problem on the importer's side — undecodable bytes, a missing header row, a
configured label it cannot find — raises `ParseFailed`; ingest's
`ContractViolation` checks stay as the backstop.

**Input is asked through a prompter**, one blocking call, `ask`, with four
kinds of prompt:

- `secret` — the PIN or a password; answered with text.
- `tan` — a challenge, in a medium: `text`, `image` (a photoTAN, carried as a
  base64 image and its MIME type) or `decoupled` (a confirmation in the user's
  app). A decoupled prompt is answered only by `poll`, a function the importer
  supplies that asks the bank "confirmed yet?" and raises the taxonomy's error
  if the bank refused; the prompter calls it every 3 s on the importer's own
  thread. Polling stays with the importer, and `ask` stays the only blocking
  primitive.
- `choice` — one of a list of options, an id and a label each: the TAN
  mechanism, the TAN medium.
- `text` — free text, for a medium the bank will not list.

Each prompt has a `subject` the client maps to a label (an unknown subject is
shown as given); a bank's own words go only into the challenge and the option
labels. `ask` returns the answer — secret text for a `secret` or a typed or
photographed TAN, the option id for a `choice`, text for a `text`, nothing for a
decoupled `tan` — or raises `ChallengeAbandoned` (cancelled, or the task was
aborted) or `ChallengeExpired` (300 s, unless the importer passes its own). It
never retries by itself: a wrong TAN or PIN is the bank's verdict, and the
importer decides whether to ask again or to raise `AuthRejected` — for a PIN, at
once, because banks lock a login after a few failures. Every answer has one
shape: `POST …/input` with `{prompt_id, value}`, or `{prompt_id, cancel: true}`;
a decoupled prompt accepts only the cancel; a value outside a choice's options
and an empty secret are 422 `validation_error` naming `value`, and the prompt
stays open. Any prompt may be cancelled; there is no "skip".

**`state` is the importer's working copy of `importer_instance.state`.** It
writes into it whatever it learns that is not secret: the system id, the TAN
mechanism and medium (chosen by prompt, not configured, so settings hold only
what the user typed and "Reset" returns the instance to asking), a learned
per-bank rule. The caller writes it back when the instance's job ends,
whatever the outcome, if it changed, so a medium chosen before a failed sign-in
is not asked for again. No PIN, password, TAN or token that does not meet
`spec.md` §7 may be put in it. What the FinTS importer keeps there is listed in
`plugins/importers/fints.md` §1.

**A document delivery may carry a position**: what the importer learned from
the data it delivered — how far into a mailbox it has read — as an update of
`state`. The caller applies it only once the run's documents are written; a
run that fails, or whose delivery is discarded after an abort, leaves the
position where it was, and the source is read again. Re-delivering a document
is harmless, since documents are keyed (`spec.md` §5.5). Everything else in
`state` is written back as above.

**A document importer may read documents with the model.** The composition
root hands it the model's configuration, and the vision model's where one is
set (§5.7); such an importer is registered only where the model is configured.
It asks for extraction, never a category. What it sends is the document whole,
not pass 3's restricted payload (§5.4): a hosted endpoint receives the
household's and third parties' personal data, which the configuration
documentation states next to both endpoints.

Errors are exception classes, not strings, because the queue's behaviour
depends on the distinction:

| Exception | Retryable | Scope | Surfaced as |
|---|---|---|---|
| `AuthRejected` | yes — every run asks for the PIN afresh | instance | wrong PIN or password; the message warns that repeated rejections can lock the login |
| `ChallengeExpired` | yes | instance | TAN timed out, retry the instance |
| `ChallengeAbandoned` | yes | instance | user cancelled, or the sync was aborted |
| `SourceUnavailable` | yes | instance | bank unreachable or timed out |
| `ParseFailed` | no | item | the file does not fit: the format changed, or the profile no longer finds its header or label; fix the importer or the profile |
| `ContractViolation` | no | item | the importer delivered what its contract forbids (wrong currency, zero amount, repeated `source_id`, no coverage); needs a fix in the importer or its profile |
| `NotRegistered` | no | instance | FinTS product registration missing (`spec.md` §7.1) |
| `BankSetupRequired` | no | instance | the bank has not activated what a sync needs — no active TAN procedure or device; the message says to finish setup with the bank, then run again |
| `AccountUnsupported` | no | item | the bank offers no booking retrieval for this account |

*Retryable* is whether running it again can help; for the last two it cannot
until the user acts elsewhere, so the client says what to fix instead of
offering to run again. *Scope* is what the failure ends (§5.3): the run
(`item`), or the instance, whose remaining runs fail with it (`instance`),
because after an expired TAN or an unreachable bank every remaining account
would wait out its own timeout. The two new classes are 422 `bank_setup_required`
and `account_unsupported` over the API. A message states the rule and may carry
a bank's return code and its text, never data segments, account numbers or
anything the user typed.

Outcomes that ingest decides — rows inserted as duplicates (`spec.md` §5.2) —
are not importer exceptions; they are recorded on the run and surfaced with it.
A breach of the importer's contract is a failure of the run (`ContractViolation`,
above).

### 5.6 Enforcing the cross-cutting constraints

**Sessions.** A `session` row references `app_user` and records the method,
`password` or `oidc`. Cookie holds an opaque id, not a JWT, so revocation is
a delete. Passwords hashed with argon2id. Both methods end in one
"establish session for this verified identity" function. The cookie is `ledgehog_session`, `HttpOnly`, `SameSite=Lax`, and
`Secure` whenever the request is not to localhost; expiry slides, 30 days from
last use. There is no CSRF token, because the API accepts only JSON and
`SameSite=Lax` keeps the cookie off cross-site requests. There is no login rate
limiting: a household, self-hosted — a conscious omission.

**OIDC sign-in** is the authorization code flow with PKCE, state and nonce,
against the issuer's discovery document. The ID token is verified —
signature, issuer, audience, expiry, nonce — and a claim it lacks is taken
from the userinfo endpoint, whose subject must match. The login claim
(`OIDC_LOGIN_ATTRIBUTE`) is the user's login, compared without regard to case; when it is `email` and the
provider marks it unverified, the sign-in is refused. A matching user signs
in; an unknown one is created, with no password. With `OIDC_ALLOWED_GROUP`
set, every OIDC sign-in needs that group in the `groups` claim, and a
missing claim refuses. A disabled user is refused. A configured user's first
OIDC sign-in hands them to the provider: from then on they have no password
and the configuration no longer manages them. The name claim
(`OIDC_DISPLAYNAME_ATTRIBUTE`), when present, becomes the display name. A
refusal returns to the login page with its reason. The login page offers
"Log in with SSO" beside the password form, and only that when
`OIDC_ENFORCED`, which also refuses `POST /api/session`. Signing out ends the
app's session, not the provider's. The provider is asked only at sign-in: a
group removed there takes effect at the next sign-in, and revoking at once
is deleting the user's sessions.

**Redaction.** Secrets live only in local variables inside the importer and
in the session it holds; neither is ever placed on the task, the event
stream or an exception payload. An answer to a prompt is a `SecretText` (defined in
`core/plugins/fetch.py`; its `repr` and `str` are `***`, and the request model
carries it as a `SecretStr`). It travels from the request handler through the
one-slot hand-off straight to the blocked importer thread and is never stored on
the task, which records only the prompt and that it was answered. A resolved
prompt loses its body in the replay log, because a photoTAN image is
credential-grade (`spec.md` §7). A logging filter drops known-sensitive keys as
a backstop, and request bodies are never logged for sync endpoints. The
backstop is not the mechanism — not putting secrets in loggable places is — and
the mechanism is proven by an end-to-end test (§8), not filtered at the exits.

**Clock.** `utils/clock.py` is the only caller of the system clock. It
exposes `now()` (an aware UTC instant) and `today(tz)` requiring an explicit
zone. There is deliberately no zero-argument `today()`: every caller must say
whose day it means. Tests inject a fixed clock.

**Money.** A `Money` type in `core/domain/` wrapping a signed integer and its
currency, with parsing and formatting as explicit constructors. Arithmetic
across currencies raises; minor units come from the `currency` table. API
models accept and emit an integer plus a currency code, never decimal
strings. A test asserts no float column binding reaches psycopg.

**Conversion.** The schema function `base_value()` is the only place an
amount is multiplied by a rate; `core/reporting` is its only caller. Changing
the valuation rule (`spec.md` §3.8) is therefore one change.

### 5.7 Configuration, startup and users

**All configuration is environment variables, with defaults where a default is
safe.** `utils/config.py` is the only code that reads the environment. It
parses and validates everything once at start, fails fast with the variable's
name on a bad or missing value, and exposes one immutable, typed object that is
passed to what needs it — `core` never reads the environment itself. Nothing at
run time writes configuration: changing a value means changing the variable and
restarting. Each variable that holds a secret (`POSTGRES_PASSWORD`,
`USER_<n>_PASSWORD`, `OIDC_CLIENT_SECRET`, `MODEL_API_KEY`, `VISION_MODEL_API_KEY`) also accepts a `_FILE` variant
naming a file (Docker and Compose secrets), and no secret is ever logged or
returned by `GET /api/config`.

Outbound connections honour the standard `HTTPS_PROXY` and `NO_PROXY` variables,
as the platform's libraries read them: the HTTP clients by their default, the
IMAP connection as an HTTP `CONNECT` tunnel before its TLS or STARTTLS. They are
not configuration of the app's own and are not in the table. The deployment sets
neither, since its relay needs nothing of the app; the development sandbox
(nono) sets them.

| Group | Variables |
|---|---|
| Database | `POSTGRES_HOST` (`localhost`), `POSTGRES_PORT` (`5432`), `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (the last three required); no single database URL; the name stays a variable so each context has its own database (§9) |
| Ledger | `BASE_CURRENCY` (required, a three-letter code); `MAX_RATE_AGE_DAYS`, `MATCHING_WINDOW_DAYS` (7 each, at least 0) — `spec.md` §3.8 |
| Household | `TIMEZONE` (required, an IANA zone; `spec.md` §5.4), `LOCALE` (`en`) |
| Users | indexed groups `USER_<n>_LOGIN`, `USER_<n>_NAME`, `USER_<n>_PASSWORD` (the password optional when `OIDC_ENFORCED`), `n` contiguous from 1, logins unique; none is allowed |
| OIDC | `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` (all three or none; none means no OIDC sign-in), and with them `BASE_URL`, the app's external address, from which the redirect address `<BASE_URL>/api/session/oidc/callback` is built; `OIDC_SCOPES` (`openid email profile`); `OIDC_LOGIN_ATTRIBUTE` (`email`); `OIDC_DISPLAYNAME_ATTRIBUTE` (`name`); `OIDC_ALLOWED_GROUP` (optional; its users need the `groups` scope); `OIDC_ENFORCED` (`false`; `true` or `false`, anything else fails the start; `true` requires OIDC and turns the password path off) |
| Model | `MODEL_ENDPOINT` and `MODEL_NAME` (both or neither), optional `MODEL_API_KEY`; absent means pass 3 does not run (§5.4) and no importer that reads documents with the model is registered (§5.5); optional `MODEL_REASONING_EFFORT` (`low`, `medium` or `high`, anything else fails the start), sent as the request's reasoning effort for a model that reasons, and not sent when unset |
| Vision model | `VISION_MODEL_ENDPOINT` and `VISION_MODEL_NAME` (both or neither), optional `VISION_MODEL_API_KEY`: a model that reads images, over the protocol of §5.4, used only by a document importer to read documents given as page images (PDF attachments); absent means such documents are not read; optional `VISION_MODEL_REASONING_EFFORT` (`low`, `medium` or `high`, anything else fails the start), sent as the vision request's reasoning effort for a model that reasons, and not sent when unset |
| Bank access | `FINTS_PRODUCT_ID` (optional): the registration number of `spec.md` §7.1, sent with every FinTS request; absent means a FinTS login stops before asking for a PIN (`NotRegistered`), and nothing else is affected |
| Development | `ENABLE_TEST_IMPORTERS` (`false`; `true` or `false`, anything else fails the start): registers the deterministic test importers in the composition root — `testdocs`, so documents can be exercised before a real document importer exists (`features/documents.md`), and `testfetch`, scripted by its settings to exercise every prompt kind and failure class without a bank; a deployment leaves it off. `EXPOSE_OPENAPI` (`false`; `true` or `false`, anything else fails the start): serves the OpenAPI document at `/api/openapi.json`, without a session, so the frontend's types can be generated from a running server (§6.7); a deployment leaves it off. `/docs` and `/redoc` never exist, whatever the value: they load scripts from a third-party host |

**Start is a fixed sequence, and the app binds only after it succeeds:**

1. Read and validate the configuration.
2. Run the migrations (§10).
3. Mark every import run still `running` as `failed`, with its `finished_at`
   set: with one worker, a run left running is one a crash interrupted, and it
   wrote nothing (§5.2).
4. **The base currency.** On the first start, write it to `ledger_setting`.
   Afterwards the configured value must equal the stored one, or the app
   refuses to start: rates are stored against it (`spec.md` §3.8), and a
   changed variable would silently misvalue every foreign amount.
5. **Users.** Reconcile the configured users with `app_user`, matched by
   login: create a missing one; update the display name; set the password
   hash when the configured password no longer verifies against it, and
   delete that user's sessions. A configured user no longer configured is
   **disabled**, never deleted — runs and importer instances reference them —
   and loses their sessions. A user who is the OIDC provider's (§5.6) is
   not the configuration's and is left alone; a configured login that names
   one is ignored, and the log says so. A password change is therefore a
   changed variable and a restart; the application has no password-change
   flow.
6. Set the connection settings that reach SQL (`ledger.max_rate_age`,
   `ledger.matching_window_days`) on every connection the pool opens.
7. **Settle.** Settling runs once, so a changed window or any other changed
   configuration takes effect on stored data like any other write (`spec.md`
   §5, I37).
8. Bind.

The household is two people, but nothing enforces it. A user comes from the
configuration or from an OIDC sign-in (§5.6); there is no setup operation,
wizard or sign-up form. How a user signs in changes nothing in the ledger's
data.

---

## 6. Frontend

### 6.1 Structure and routing

SvelteKit in SPA mode (§2): `adapter-static` with `fallback: 'index.html'`,
`ssr = false` and `prerender = false` in `+layout.ts` of the root layout (SvelteKit reads them from
no other file). Client-side routing
only, no Node process in production, no prerendered HTML.

One consequence worth stating because it is easy to violate by copying an
example: **`+page.server.*` and server `load` functions do not exist here.**
All data loading is client-side `fetch` against the API (§6.2). A route that
acquires a server load function will fail the build, and if it did not, it
would have nowhere to run.

### 6.2 Module boundaries

```
frontend/src/
  routes/              SvelteKit pages. THIN: compose components, read
                       params, call a client module. No fetch, no business
                       logic, no formatting.
    +layout.svelte     shell, nav, auth gate
    +layout.ts         ssr and prerender flags
    +page.svelte       the Overview, `/`
    ledger/
    review/
    accounts/          the account list, `/accounts/[id]` and the file upload
                       `/accounts/[id]/upload`
    sync/              the sync page: plan, progress, report
    reports/           three tabs: `by-category`, `over-time`, `balances`
    settings/          management: categories, payees, tags, rules, importers
                       (below)
  lib/
    api/               The ONLY place fetch is called. One module per
                       operation group in §4.1 (ledger, units, importers,
                       sync, reports, maintenance), plus shared error
                       handling and
                       the SSE client.
    stores/            Svelte stores. Page-scoped by default; one long-lived
                       store for the active task, a sync or a discovery.
    components/        Presentational and reusable. Props in, events out;
                       no direct api/ imports.
      ui/              shadcn-svelte components, copied in: dialog,
                       combobox, menu, tooltip, toast, date picker, button,
                       chart.
                       Generic, no domain knowledge; the only place Bits UI
                       is imported
      common/          composites of ui/: tables, money and date displays,
                       and the interaction components of patterns §11:
                       action dialog, row actions, icon and action
                       buttons, field, picker, page header, section tabs
                       (Settings and Reports), empty and error states, notice
      ledger/          entry row, provenance widget
      units/           the unit panel — draft, preview, commit, split
                       editor — and queue rows, flag badges, evidence
      accounts/        statement rows, balance markers, account facts
      importers/       the instance list, one settings form per importer, the
                       run summary (shown at the end of a sync too)
      sync/            plan, progress, prompt dialogs, the discovery list
      reports/         the figure of a total with its unvalued remainder, the
                       Overview's cards, the category tree table, the report
                       charts built on `ui/` chart
    format/            money, dates, locale (§6.6)
    types/             shared types: api.d.ts is generated from OpenAPI
                       (§6.7), the rest is what OpenAPI cannot say
```

Four rules:

- **`routes/` holds no logic.** A page assembles components and calls
  `lib/api`. Anything more moves into a component or a store.
- **`components/` never calls the API.** A component that fetches cannot be
  reused or previewed, and it hides a network call inside a render tree.
  Data arrives as props.
- **`components/ui/` knows nothing of the domain.** It is the shared kit;
  anything that knows what an entry, a unit or an amount is lives outside it.
- **`lib/api/` is the only module that knows URLs exist.** The rest of the
  frontend calls functions. When an operation's path or shape changes, one
  directory changes.

Component subfolders mirror the operation groups, so a change to the review
API has an obvious frontend counterpart. Screens compose the interaction
components of `common/` and do not restyle them; a new kind of interaction is
first a pattern in `ux/patterns.md` §11.

**Management lives under settings.** The routes are `/settings/categories`, `/settings/tags`,
`/settings/payees`, `/settings/importers`, `/settings/importers/new` (with
`?importer=`), `/settings/importers/{id}`, `/settings/importers/{id}/accounts`
(the discovery of an instance's accounts, `ux/views/importers.md`),
`/settings/rules`, `/settings/rules/new` (optionally
`?from=<entry id>`, which opens the editor on that entry as its example, read
with `GET /api/ledger/entries/{id}`; nothing is matched or written by it) and
`/settings/rules/{id}`, the page an evidence line's rule links to
(`patterns.md` §4.3). The ledger reaches them through a "Manage…" link on
category and payee chips. Rules are not started from the ledger, which does not
show the source fields; the rule editor picks its example itself, with a text
search over the entries (the list's `q`), and the review panel opens the same
editor with `?from=`.

The four rules are enforced mechanically, as import-linter enforces the backend's
(§5.1): ESLint's `no-restricted-imports` and `no-restricted-globals` forbid Bits UI outside `components/ui/`,
the API from `components/`, and `fetch` and `EventSource` outside `lib/api/`.

### 6.3 Data loading and state

**The server is the only source of truth and the only place domain logic
lives.** The client does not compute balances, does not decide whether an
entry needs review, does not evaluate rules, does not derive review flags. It
renders what the API returns and sends operations back.

**Optimistic updates are permitted, under one rule:** the client may render
the *expected* result of an operation it has sent, but may never *compute* a
domain outcome. Showing an entry as categorised the instant the key is pressed
is echoing an operation already dispatched; deciding which category a rule
would have chosen is not. Every optimistic update reconciles against the
server response and rolls back on error, and none of them is ever the source
of a subsequent write. The review queue needs this to feel usable at
keyboard speed; other screens may too, and the rule rather than a list of
exceptions is what governs them.

**The unit panel holds a draft, not a computation.** On the server, `preview`
is the settle's own functions run on an *overlay*: resolution, pairing, the
booking of a counter-leg and the review state
all take a unit's stored
state with the draft laid over it, as an in-memory value, and return the
resulting state without writing; the rows a draft creates carry negative
temporary ids the client issues, which the preview echoes. `commit` writes that same result, and settling
calls the same functions on stored state. The entry form's `PUT` and `DELETE` are
previewed with `dry_run` instead (§4.1). This is the design's riskiest
component and is built before the panel's UI. The draft is the
user's choices for one unit; what they imply — proposals, offers, a
counter-leg, a booking settling would make, a partner left behind — comes
from `preview`. The panel renders that and sends the full state back with
`commit`.

No global state library. Page-scoped stores, plus one long-lived store for the
active sync task.

### 6.4 Sync flow

Uses the sync operations of §4.1 through `lib/api/sync`; the paths there are
illustrative and this section names none of them.

The page `/sync` reads the plan, and a start sends items built from it: per
login, per account (with a `since` only where the user changed an editable
one) and per documents kind; logins that another task holds are shown as busy
and left out. The client then attaches to the returned task's event stream and
renders from the events through one reducer: the view of a task is a function
of the events seen, so a live stream and a replay give the same screen (§4.2).
Input requests drive the dialogs — text TAN, photoTAN image, decoupled
confirmation with a waiting state, a choice, a text, a PIN — and answers carry
the correlation id of the request they answer. A failure is routed on its
retryability alone (§5.5): the client offers to run the unfinished items again,
or says what to fix; it parses no message. The report lists, per account, what
was inserted, what was inserted as a duplicate and of which row, with a link to
those rows on the account's statement (a duplicate has no entry, so no row in
the ledger list), and how many rows were skipped by identity, from the
statistics of `run_finished`; the CSV upload flow ends with the same summary,
one component in `components/importers/`.

One store, mounted at the root layout, holds the active task whichever page is
shown (the task outlives navigation). The change values carry the current
user's active task, and the store attaches to it whenever the tab is not
already attached — on mount and at every later read — rather than remembering
a token locally (§4.3); a discovery is such a task, hosted by its own page. A
prompt's dialog is shown only on the page that hosts the task, and whenever
that page is shown while the prompt is open — when the prompt arrives, or on
any later visit for a prompt that arrived while another page was shown: the
page reads the open prompt from the store when it mounts, not only from the
event. Elsewhere the navigation says that the task needs input. Two tabs attaching to the same task
is expected: both render the prompt, and whichever answers first causes the
other's dialog to close through the shared stream. A rejected answer means
another tab was faster and is dismissed silently, not surfaced as an error. A
task the server no longer knows is an interrupted sync. Abandoning a sync is an
explicit operation, not a closed tab.

New data, whatever wrote it, is the change values' (§4.2), not the sync's: one
watcher reads them every 30 s and on focus; a view holding a snapshot shows "New
data — Refresh" when its key moves, and lists that are not snapshots (the
accounts, the importers, an account's runs) refetch when the ledger's does.
Nothing is counted.

### 6.5 Review queue

The interaction model drives the API more than any other screen (§4.1).
Three sections — pending review, needs an account, waiting — each ordered by
booked date, then anchor entry id; whether and how to group units by shape
within a section is open until real units have been seen
(`ux/views/review-queue.md`). Each unit is committed with one keystroke, which
moves to the next. There is no batch confirmation; units decided entirely by
pass 0 and rules arrive confirmed once complete, and enter the queue only
while they wait for a partner (`spec.md` §5.9, §6). Keyboard-first; the
bindings are a cross-view convention, decided once for every view.

Review is per unit (`spec.md` §6): the user opens a unit in the panel, changes
values, splits, converts or re-pairs as draft edits, sees each
previewed, and commits the whole state at once. A unit appears once, with all
its entries — both legs of a pair, every entry of a split. The panel is the
only place an entry's interpretation is edited, apart from the merges (tags are edited there too, and directly elsewhere),
and it opens for any unit from the queue, the ledger list or a rule's preview.
Each key's evidence is shown — "1 of 1", "12 of 12" — so a thin proposal stands
out. A transfer without its partner can be committed but stays in review until the
partner completes it; a booking's unit offers no partner, convert or split
(§4.1); the preview says which state the commit leads to.

**The queue is a snapshot, not a live view.** A working set is fetched when the
screen opens, and nothing is added, removed or reordered for the duration of the
session. **Each unit is previewed fresh when it is opened**, so its proposals
are current: confirming the first entry from a new merchant gives the next ones
in the list a proposal by the time the cursor reaches them, without the list
moving. Rows resolved during the session — whether acted on directly or as a
consequence of another operation — stay in place, marked as resolved, so the
list never shifts under the cursor and a mistaken action is still visible and
correctable by editing. There is no undo. New data from any source — a sync,
an upload, another tab, the other user — surfaces as one uncounted notice, "New
data — Refresh", which refetches only when the user asks (§4.2).

Position stability matters more than freshness of order in a keyboard-driven
list: an item vanishing between keystrokes is how the wrong row gets
confirmed. This is why operations return their full affected set (§4.1) —
the client patches rows in place rather than refetching.

**The Review item of the navigation counts what can be done now**: the units
pending review and those that need an account, not those waiting for a
partner, which complete themselves. It is a count chip, hidden at zero,
read once when the app starts and again whenever the ledger's change value
moves (§4.2), by its own read rather than on the change values: those stay a
question of whether anything changed. The Overview's To review card shows the
same number, split into its two parts, by the count route's own fields (§4.1).

A row resolved as a *consequence* rather than by direct action needs to say
so, because it changes without the user having touched it. Exactly how — and
whether resolved rows eventually collapse — is a presentation question, left
to the view.

Split editing keeps the original entry as the residual that absorbs the
remainder, so the sum invariant can never be violated in the draft, the row
keeps its place under the cursor, and the user never sees a validation error
for work in progress.

### 6.6 Money, dates and locale

Amounts cross the API as signed integers in the minor units of their
currency, always with the currency code, and are stored that way in the
client. **No float ever holds an amount**, and arithmetic on amounts is
integer arithmetic. The number of minor units comes from the currency, not
from an assumption of two.

Formatting and parsing live in `lib/format` and nowhere else, built on the
platform's `Intl.NumberFormat` and `Intl.DateTimeFormat` rather than on
hand-written German rules. The active locale is the deployment's default
locale (§5.7), which a browser may override for itself; the server stores no
per-user setting — so `1.234,56` and `1,234.56` are
both handled by configuration rather than by code, and a future user of the
deployment is not assumed to be German.

Parsing user input needs care that `Intl` does not provide directly: derive
the group and decimal separators for the active locale, normalise the input
against them, and reject ambiguous entry rather than guessing. This is
precisely why it lives in one module.

### 6.7 Build and serving

Vite builds to a static bundle baked into the image; Tailwind is compiled by
its Vite plugin in the same build, so nothing CSS-related runs at run time.
Fonts and the mascot artwork are files in the bundle; the app loads nothing
from a third-party host. FastAPI mounts it with a
catch-all that returns `index.html` for unknown paths, ordered so `/api` is
never shadowed. In development, the Vite dev server proxies `/api` to a locally running uvicorn
(`127.0.0.1:8000`, or the address in `LEDGEHOG_API`), so the page and the API
share an origin and the `SameSite=Lax` session cookie is sent. The dev server sends the
same Content-Security-Policy through SvelteKit's own `csp` setting, with the two
differences SvelteKit makes for development: its bootstrap script is allowed by a
nonce rather than a hash, and `style-src` allows the inline `<style>` elements Vite
injects for CSS and hot updates.

**Every response carries a strict Content-Security-Policy.** The bundle is the
only code the page runs and the origin the only place it talks to:
`default-src 'none'`; `script-src`, `style-src`, `img-src`, `font-src`,
`connect-src` and `manifest-src` are `'self'`, except that style attributes
are allowed (`style-src-attr 'unsafe-inline'`): SvelteKit and Bits UI write
fixed ones, and with scripts locked a style attribute can neither run code nor
reach another host; `base-uri`, `form-action` and `frame-ancestors` are
`'none'`; Trusted Types are required, Svelte's policy the only one allowed.
SvelteKit boots the SPA with one inline script: the server hashes it from
`index.html` at start and adds the hash to `script-src`, and refuses to start
if the file holds no inline script or more than one.
Alongside: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
`Cross-Origin-Opener-Policy: same-origin`. User-supplied content (a
document's file, an e-mail's HTML) is never served as a page on the app's
origin.

**The frontend lives in `frontend/`**; its `src/` is the tree of §6.2, and the
build's `frontend/build` is what the image carries (§10). Packages are managed
with npm: the lockfile is committed, versions are saved exact and install
scripts are off. SvelteKit 3 keeps its configuration (the adapter, the compiler
options) in `vite.config.ts`.

**Types are generated from the API.** `scripts/dump_openapi.py` writes
`frontend/openapi.json` from the application object, with no database and no
server; `--check` writes nothing and exits 1 when the file is stale.
`npm run gen:api` turns it into `frontend/src/lib/types/api.d.ts` with
openapi-typescript, and `npm run gen:api:check` fails when that file is stale.
Both files are committed, so a change to the API shows as a diff in review, and
both are excluded from formatting. Operation ids are the handlers' names, and
the error envelope of §4.4 is declared on every operation, so the generated
error types are what the server sends. What OpenAPI cannot say is written by
hand (the upload body, the union of error codes, a calendar date as a plain
string that is never parsed to a `Date`).

---

## 7. Schema management and migrations

Alembic, with **autogenerate never used**. The schema depends on constraint
triggers, partial indexes, `CHECK` constraints and views — all of which
autogenerate either ignores or mangles. Every migration is hand-written SQL in
`op.execute()`.

`schema.sql` is the readable reference and the source of the design comments.
The migration chain is the executable truth. A test asserts that a database
built by migrations matches `schema.sql` applied to an empty database, so the
two cannot drift.

---

## 8. Testing

Against a **real external PostgreSQL** on the development server, in a
database the run creates for itself and drops afterwards (§9). Endpoint and
credentials come from configuration; the database name does not, because
each run makes its own.

Deferred constraint triggers and partial indexes cannot be expressed in
SQLite, so there is no in-memory shortcut and no attempt at one.

Layers:

- **Core unit tests** — Money and currency arithmetic, hash canonicalisation
  and ordinals, rule evaluation: conditions combined, counter-account rules
  before payee rules before category rules, then priority, ties broken by id, a counter-account rule refused by the currency
  rule. No database.
- **Ingest tests** — a run failing at a late row leaving no rows, no balance
  record and no coverage; each breach of the importer's contract — a wrong
  currency, a zero amount, a repeated `source_id`, no coverage — failing the
  run and leaving nothing behind (the importer's own test asserts that it
  filters and counts zero bookings);
  two syncs of one account serialised over a whole delivery; deduplication of
  `spec.md` §5.2 exhaustively: identity
  matches including duplicates; identical rows with and without a
  `source_id`, delivered reordered and partially, a fetch made mid-day among
  them; the amount step against another importer's rows and an older
  rendering of the same importer, but never against user-authored rows,
  counter-legs among them, derived entries, rows of the same delivery or rows identity already matched; the
  purpose as tie-breaker; a shared account whose two credentials hash
  differently, with a late same-amount booking delivered first by the second
  credential; marking and clearing duplicates, never
  chained, and the removal routine, including deleting a user-authored
  transaction; a user-authored row entered twice with one id, edited so its
  residual absorbs the change or its split collapses, and resolved afresh; the
  fetch start without coverage derived after the latest entry, derived ones included; revert only of the account's latest successful run by ingest order — two overlapping runs of a shared account ingested in the other order than they started —, refused for document and rate runs; a revert deleting a row two others duplicate, the lowest-id one becoming the original; runs left `running` marked failed at start; coverage per run and the derived `synced_through`,
  including after a revert and after a fetch that returned no rows.
- **Balance tests** — the derived opening (first record, backfill moving it,
  a backfill that reports its own balance becoming the anchor, an anchor
  older than every entry, revert recomputing it); valuations and
  reconciliations by account type (a later count, a forgotten receipt
  shrinking the difference, a zero result deleting the entry); a reported
  record reconciling, the unexplained difference summing from the first
  reported record on — a back-dated booking's pair and a wrong manual record
  between reported ones cancelling in it, a missing row persisting until
  fixed —, a deleted record merging its interval into the next one; data age
  from coverage on synced accounts and from records on unsynced and closed
  ones; closed-day
  dating keeping a same-day late booking out of the record; a statement whose
  forward-dated lines would date the record after coverage reporting no
  balance.
- **Matching tests** — a user-authored single-entry leg following its
  partner's split on an unsynced account, and left alone on one since synced;
  settling never creating a counter-leg, a decided leg arriving with its
  counter-leg proposed only where its counter-account holds no open offer —
  an edited or leftover counter-leg, a hand-typed withdrawal, but not a leg
  pointing at another account — and a deleted counter-leg staying deleted;
  a counter-account set by a pair cleared when it breaks; candidate filters (counter-account both ways,
  end-to-end id) and the purpose as tie-breaker; no automatic pair without a
  known counter-account; date-ordered pairing, re-runs changing nothing, a
  pair standing once made and falling when a leg's counter-account guess
  changes; waiting and unmatched
  legs — unsynced and closed counter-accounts, legs dated before a synced
  counter-account's history staying unmatched, never-fetched accounts
  waiting; offers —
  untyped entries, any amount, a different-amount pick never proposed but picked, an exact open offer proposed,
  splitting the larger leg, offers on waiting legs, a counter-leg offered
  only for an unsynced counter-account, a paired leg re-paired from its
  offers, including a leg paired elsewhere — a swap fixed in one pick where
  the freed legs keep their own counter-accounts, a three-cycle in two — never preselected, sorted after unpaired offers, a
  window widened for one pick, and a leg left behind paired as on ingest
  where its counter-account is decided, and shown in the operation's result; a
  counter-account rule not matching an account closed by the booking date;
  counter-leg amounts, same- and cross-currency, with no conversion; a
  standing unit on an unsynced counter-account waiting with its counter-leg
  proposed, confirmed by one commit;
  a counter-leg left behind by a broken pair staying, as an unpaired leg; a
  same-currency pair made unequal by a split shown invalid, with the
  split-the-difference offer whichever the legs' sources; a form edit of a
  paired user-authored amount breaking the pair, and a form edit never
  changing the account;
  pass 0 recognising a closed account's payout, history no longer proposing
  it.
- **Booking tests** — a document booked on the account that takes its
  provider in its currency, dated after the account's start, one entry per
  line in line order with each line's text as its source text; the spread of
  the unitemised amount over the lines of the total's sign, half-even with the
  remainder on the largest entry, a coupon line kept as listed, zero lines
  dropped, an entry rounding to zero merged into the largest, no line of the
  total's sign giving one entry, a total of zero giving no booking; a document
  in another currency, of a provider no account takes, or dated on or before
  the start not booked, each with its reason; a re-delivered document under
  `replace` re-deriving its booking, confirmed or not — entries matched to
  lines by position, an unchanged line's entry keeping its values and keys, a
  changed amount or text written and resolved afresh, a removed line's entry
  deleted with its tags, a new line a new entry — and under `keep` changing
  nothing; a provider added booking its existing documents, removed or moved
  leaving the bookings where they are; a charge decided as a transfer to a
  clearance account — by a rule, by pass 0 or in a commit — getting its
  counter-leg paired with it, confirmed with it when its keys are standing,
  retyped or moved to another counter-account losing it, split re-deriving
  its amount, across currencies by the instructed amount; booking entries
  never offers or candidates, and a leg toward a clearance account never
  paired by step 4; the preview showing the counter-leg settling will make;
  the booking step idempotent, a second settle writing nothing; a draft
  converting, splitting or pairing a booking entry refused; the entry form
  refusing a booking and accepting a correction on a clearance account; a
  provider taken in the same currency refused, the same name on accounts of
  two currencies accepted; a link to a clearance account refused.
- **Unit tests** (review) — unit membership across a split and a pair;
  preview writing nothing; a commit applied atomically and refused on a
  structural change but not on a recomputed proposal; a pair confirmed only
  as a whole; a unit decided entirely by pass 0 and rules confirmed without
  review and teaching history, one with a single history key not; a standing
  value held while rules and history change; a commit keeping the standing keys of the values it
  leaves unchanged; a changed or deleted rule changing no existing value and
  listing both sets for review by hand; a category merge, refused across kinds and
  taking its children along; a broken pair returning the leg left behind
  to review with its confirmed values, and its split siblings', unchanged —
  all but a counter-account its pair set, which leaves with it — and
  re-resolvable in the panel; resolution
  rederiving unconfirmed entries after a confirmation and never touching a
  reviewed one; a settle whose confirmations change other proposals settling
  them in a further round until none confirms anything new, and a second settle
  changing nothing; an entry-form edit resolving its entries afresh in its own
  write; history proposing only with a strict majority, its similar-purpose
  matches first, and its category giving way to the model unless unanimous;
  re-resolving a
  confirmed unit without its own votes.
- **Invariant tests** — assert the database *rejects* what it should. A
  three-leg transfer, a non-mutual pair, a split that does not sum, entries on
  a duplicate, a duplicate on another account or of a duplicate, a duplicate
  of a user-authored row, a user-authored row created on a synced account, a source
  transaction inserted without an entry, coverage on a failed run, an
  entry with both or neither of a source transaction and a balance record, a
  source text on a derived entry, a booking on an account that is not a
  clearance account, a booking or a user-authored row with an importer, a
  run or a format, a booking without a `source_id` or marked as a duplicate,
  a change of a source transaction's origin, a clearance account linked to an
  importer, providers on another kind of account or one provider on two
  accounts of one currency, an update to an imported source transaction other than to
  `duplicate_of`, an entry
  in a currency other than its account's, a child category of another kind, a
  change of a category's kind, a second opening on an account, a manual
  opening, a same-currency pair of unequal amounts, a reported balance record without a run, a second transfer entry
  on one source transaction, a row with both or neither identity, a source row
  or reported record on another account than its run, a transaction run
  without an account, a derived entry of type `flow`, a change of an account
  between investment and other, a change of the base currency, a payee on an
  untyped entry, deleting a category a rule references, a source transaction
  or an entry of amount zero. A test that must seed a state the schema
  forbids, to show an integrity view or a re-check catches it, disables the
  relevant user triggers inside its own transaction as table owner (`ALTER
  TABLE … DISABLE TRIGGER USER`, rolled back with the transaction), never
  through a privileged setting.
- **Reporting tests** — `base_value()` rounding, a missing or too-old rate
  yielding unvalued rather than zero, and the net-worth identity: FX
  translation computed per account and zero for base-currency accounts, and
  the transfers (net) line for a pair straddling a period boundary; the
  starting balances, valuation, reconciliation and unclassified lines;
  savings including reconciliations; net worth summing valued accounts with
  the others on the unvalued line; a drill-down equals its number — for every
  cell of a seeded ledger, the entries the cell's filter lists are as many as
  it counts and sum to its total; one savings computation, the Overview's and
  the over-time report's alike, its rate null on income of zero or less and
  its marker per cause; periods bucketed in the household's zone.
- **Importer tests** — against recorded payloads committed as fixtures, never
  against a live bank. The FinTS importer is tested through its one seam to the
  bank, against a fake of it, with a hand-built MT940 corpus, and each fix it
  carries to python-fints has its own test (`plugins/importers/fints.md` §9).
  The sync's orchestration is tested against the fake
  `testfetch`, whose rows are a pure function of the date so that two
  overlapping fetches deliver the same identities (the two-run rule, below);
  the prompt hand-off, abort, timeout and abandonment are tested on the task
  itself, with no event loop.
- **API tests** — operation-level, including that another user cannot attach
  to, answer or abort a sync task, and the refusals of a start (§4.1). The SSE
  replay and framing are tested against a finished task; live streaming and the
  keepalive once, against the app served on a real port, because the in-process
  ASGI transport buffers a response until it ends.
- **Redaction test** — end to end: answer a PIN and a TAN with sentinel
  strings, fail the instance, and assert the sentinels are absent from every
  event, the status, the stored error text, `importer_instance.state` and
  `settings`, and the debug log (§5.6).
- **Start-up tests** — a bad or missing variable failing by name; the base
  currency written once and a different configured one refusing to start;
  users created, renamed and re-passworded from the environment, one removed
  from it disabled with its sessions gone; `_FILE` secrets; settling run on
  start; the configuration object read-only and the only reader of the
  environment.

**Worked examples are acceptance tests.** Every example of `spec.md` §4 is a
test, run through the two-run harness below where it involves an importer. An
example that cannot be written as a test is a gap in the spec.

**The two-run rule.** A new importer is always tested with two runs over
overlapping windows. The first run's balance record explains nothing — it is
the anchor the opening is derived from (`spec.md` §5.10) — so an importer
that drops every third transaction still looks clean on run one. Run two is
the first real check: its reconciliation must be zero.

---

## 9. Local development

A venv, `uvicorn --reload`, and the Vite dev server proxying `/api`. No Docker
required for day-to-day work; the image is built to verify packaging and to
deploy.

### The invariant is the server boundary

**Production and development are different servers, and nothing outside
production ever holds production credentials.** That is the whole rule.
Within the development server, databases are unlimited and disposable.

Stating it as a server boundary rather than as a list of databases is
deliberate: a connection string either points at the production host or it
does not, which is checkable. A naming convention is not. It also means the
role used for development can hold `CREATEDB` — necessary for everything
below, and exactly the privilege that must never exist alongside production
access. The test role needs `CREATEDB` and nothing else: never superuser, no
parameter privileges.

### Databases are ephemeral and per-context

Fixed names like `ledger_dev` are a shared mutable resource. Two worktrees —
or an agent and a human working at the same time — both running migrations
against one database corrupt each other's schema state, and the failure
presents as a migration bug rather than as a collision. So:

- **Each test run creates its own database**, seeds it, runs, and drops it.
- **Each working context creates its own** — a worktree, an agent, a branch
  with a schema change in flight — and drops it when that context ends.
- Copying a database to experiment against is normal and expected; it is a
  copy, not a shared instance.

Test databases are seeded by **cloning a template** (`CREATE DATABASE …
TEMPLATE …`) built once from the migration chain, rather than by replaying
migrations per run, which is far faster. Templating requires no other
connection to the template database, so under parallel runs the template must
be built before the workers start and left untouched while they run. The template
is `tpl_<hash of the migration chain>`: built once under a temporary name and
renamed into place, so a crashed build is never mistaken for a usable one, and
kept across runs, so it is rebuilt only when a migration changes. Each run
clones it as `test_<uuid>`.

### Cleanup is not optional

Ephemeral databases leak: an interrupted run, a killed container, a failed CI
job. Without a discipline the development server accumulates orphans until
someone drops one by hand and picks the wrong one.

- **Deterministic prefixes** — `test_<uuid>`, `tpl_<hash>`, `dev_<worktree>` —
  so anything matching is known to be disposable.
- **Teardown in a fixture that also runs on failure**, not at the end of a
  happy path.
- **A sweeper** (`scripts/sweep_dbs.py`) that drops `test_` and `tpl_`
  databases older than a day. Each database carries its creation time as a
  comment; an unstamped one counts as old. A `dev_` database is never swept: it
  is long-lived and may hold real data (below), so it is dropped by hand.

### Development data is real data

A database copied from the human's working instance **might** contain actual
bank transactions: IBANs, payee names, amounts. It is treated as if it does,
because the alternative is checking each time and eventually being wrong.
"It is only development" is not a reason to treat it as safe to leak, and it
is precisely the reasoning that leads to it being left somewhere it should
not be.

The human operating the project is responsible for either not putting real
bank data on a development server at all, or clearing it before handing that
environment to anything else — an agent, a colleague, a shared machine. This
is an operational discipline, not something the software enforces.

### Configuration

Entirely through environment variables (§5.7), with a checked-in
`.env.example` and no secrets in the repository. The database name is part of that
configuration, not compiled in, which is what makes per-context databases
practical.

---

## 10. Deployment and data durability

One image, multi-stage: a Node stage builds `frontend/`, a Python stage
installs hash-pinned dependencies and copies the bundle in. Runs uvicorn with
a single worker as a non-root user. Start is the sequence of §5.7:
migrations, the base currency and users reconciled from the environment, then
the app binds. The container is configured by environment variables or
Compose secrets alone.

**Backups are managed externally, with the database.** The database is not
part of this deployment (§3), so its backup schedule, retention and tooling
belong to whoever operates it and are out of scope here.

What *is* in scope is the requirement: this data is not reconstructible. A
bank can resend transactions; it cannot resend months of categorisation,
payee rules, splits and review decisions. So a restore must be tested before
the ledger holds real history, and the application's own upgrade path must
not assume it can be recovered by re-importing.

---

## 11. Open decisions

- **Natural-language querying** ("how much did I spend on shoes last month")
  is planned as a later feature with its own spec. Recorded here because the
  question of whether it needs accommodating *now* has been asked and
  answered: it does not, but three things should not be designed away.

  It would be a **third plugin type** alongside importers and classifiers —
  same contract shape, same configured model endpoint — so the seam already
  exists. It should **resolve before it generates**: map "shoes" to category
  and payee ids through the existing resolution passes, then query on ids, or
  a generated `ILIKE '%shoe%'` will silently miss the pair categorised as
  Clothing. And generated SQL should eventually run under a **read-only
  database role** on its own connection; adding that later is trivial,
  discovering later that everything shares one privileged connection is not.

  Nothing in the data model needs to change. Normalised dimensions with
  names, a single balance definition and `v_flows` already encoding which
  entry types count as spending are what make a generated query trustworthy,
  and they are there for other reasons. The one thing to avoid is assuming
  free-text search will never be needed: `description`, `note` and payee
  names are deliberately unindexed at current scale, and that is a scale
  decision rather than a structural one.

- **Whether the task registry needs persistence.** Currently in memory, so a
  restart mid-sync loses the task, including a TAN prompt it was waiting on.
  Acceptable — an abandoned sync is retried from the start, every run already
  ingested is complete on its own, and the next write settles whatever the
  interrupted sync left unsettled.
