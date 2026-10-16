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
| Frontend | Svelte 5 + SvelteKit **in SPA mode** — no SSR, no prerendering |
| UI components | shadcn-svelte, **copied into the repository**, on Bits UI primitives; Tailwind CSS, compiled at build time |
| Database | PostgreSQL, external to the container |
| Packaging | One container; local development in a venv against a separate external development database |
| Tooling | uv with a hash-pinned lockfile, npm with a committed lockfile for the frontend; pytest and hypothesis; ruff; mypy in strict mode; import-linter for the module boundaries (§5.1); httpx for API tests; argon2-cffi for password hashing |

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

### Why an SPA rather than server-rendered HTML

Three parts of the UI are interaction-heavy enough that form round-trips would
be the wrong shape: the review queue with keyboard navigation and one-keystroke
confirmation, the sync wizard with live progress and prompts, and reports that
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

**One worker process, always.** Sync task state — including a live FinTS
dialog awaiting a TAN — lives in process memory, and the SSE stream for a task
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

- Committing a unit writes its values, its split, its document decisions and
  possibly a counter-leg on another account at once, under deferred
  invariants; settling then derives whether the unit is confirmed.
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
GET    /api/ledger/entries                     filtered, paged list
GET    /api/ledger/entries/{id}                one entry, in the row shape of
                                               the list (200; 404 when missing)
GET    /api/ledger/entries/{id}/source         provenance: the source transaction

  user-authored source transactions — the entry form (spec §3.9, §5.6), on
  unsynced accounts only
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
                                               row on the account; deletes its
                                               entries through the removal
                                               routine; previewed both ways
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
                                               while they wait for a partner or
                                               a document
GET    /api/units/queue/new-count              how many units entered the queue
                                               since a queue snapshot: one cheap
                                               pass, for the passive "N new"
GET    /api/units/{entry_id}                   a unit's stored state
POST   /api/units/preview                      stored state + draft → the unit a
                                               commit would write: rows (with
                                               temporary ids for rows it would
                                               create, issued by the client),
                                               values, derivations, transfer
                                               offers and document suggestions,
                                               consequences such as a partner
                                               left behind. An in-memory
                                               overlay; writes nothing.
POST   /api/units/commit                       the full state the user saw;
                                               saves any unit; settling
                                               decides whether it is confirmed

  documents — browsed on their own; linked only through a unit's commit
  (spec §5.8)
GET    /api/documents                          filtered, paged list: provider,
                                               date, amount, text, linked or
                                               not; each with the transaction
                                               carrying it
GET    /api/documents/{id}                     a document with its lines; for
                                               one carried by no entry, the
                                               transactions it would match,
                                               confirmed ones included

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
PUT    /api/ledger/payees/{id}                 name, note, icon, colour,
                                               document_provider (a write:
                                               matching and waiting read it, so
                                               it settles)
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
GET    /api/ledger/accounts
POST   /api/ledger/accounts                    create an account; creates
                                               nothing else (spec §5.7)
PUT    /api/ledger/accounts/{id}               name, sort order, note, icon,
                                               colour, external_ref (a write: pass 0
                                               reads it, so it settles); the
                                               kind only within its class
                                               (spec I38), never the currency
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

  tags — direct writes outside the panel (spec §3.7)
GET    /api/ledger/tags
POST   /api/ledger/tags
PUT    /api/ledger/tags/{id}                   rename, colour
DELETE /api/ledger/tags/{id}                   its memberships go with it
PUT    /api/ledger/entries/{id}/tags/{tag_id}  tag one entry (not a derived
DELETE /api/ledger/entries/{id}/tags/{tag_id}  one); each settles

  importers — credentials and their runs (spec §5.11)
GET    /api/importers/instances
POST   /api/importers/instances                create a credential or profile
PUT    /api/importers/instances/{id}           settings, label, disabled
POST   /api/importers/instances/{id}/reset     clear `state`, keep `settings`
DELETE /api/importers/instances/{id}           only while it has no runs;
                                               otherwise disable it
POST   /api/importers/instances/{id}/discover-accounts
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
GET    /api/importers/runs                     the import log
POST   /api/importers/runs/{id}/revert         delete what the run produced;
                                               only the account's latest
                                               successful, non-reverted
                                               transaction run; previewed;
                                               carries the version of every
                                               entry it removes or unpairs,
                                               which its preview returns

  sync — one long-running task over several importer instances
POST   /api/sync                               start        → {task_id}
GET    /api/sync/active                        the current user's task, or 204
GET    /api/sync/tasks/{task_id}               state, for reattachment
GET    /api/sync/tasks/{task_id}/events        SSE stream
POST   /api/sync/tasks/{task_id}/input         answer a prompt (a TAN)
POST   /api/sync/tasks/{task_id}/abort

  session — password login today; OIDC replaces it, not the rest (§5.6)
POST   /api/session                            log in
DELETE /api/session                            log out: deletes the session row
GET    /api/session                            who am I

  configuration — read-only (§5.7)
GET    /api/config                             base currency, the windows,
                                               default locale; never a secret

  reporting — read-only aggregates over core/reporting (spec §8)
GET    /api/reports/dashboard                  balances, net worth, this month
                                               against last, unreviewed count,
                                               account data age and status
GET    /api/reports/spend-by-category          a date range, with the
                                               reconciliation and unclassified
                                               lines beside it
GET    /api/ledger/entries/export              CSV of the ledger list's filter,
                                               dimensions joined

  maintenance
POST   /api/maintenance/settle                 settle now: bring derived state
                                               up to date (spec §5)
GET    /api/maintenance/check                  integrity views (schema.sql §9)
```

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
creation only), the target value, the conditions (a category rule's may include payee
conditions, `{"field":"payee","op":"is","value":"<id>"}`; core checks that the
payee exists) and `priority`; it returns
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
`preview` what it implies; converting, splitting, re-pairing and picking a
document are draft edits, not server operations. Nothing persists until
`commit`. A commit is always of one whole
unit; there is no batch commit and no operation that rejects a single
derived value (spec §6). Only a commit splits (spec I7): a document's lines
reach the ledger as a split the preview proposes, never as machine output. A
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
consequence; and the version of a picked document. The server lays the draft
over the stored state again and writes the values sent. It derives the keys
itself (`spec.md` §5.9): a standing key is kept only where the stored value is
unchanged and was standing, a value equal to a shown proposal becomes `user`
with that proposal's key nested as its basis, a `user` value left unchanged
stays, anything else is `user` without one. The client may name a basis only
for the passes `history`, `llm` and `matcher_proposal`; it is stored wrapped
under `user`, never trusted as evidence, so a client can never assert a `rule`
or `own_account` key. Empty fields carry no key, with one exception: a payee
draft with `mode: fixed` and no value is the user's "no payee" decision
(`spec.md` §5.9, state 3), stored as the key `user` with a NULL `payee_id`. A
`fixed` draft of type, category or counter-account without a value is not a
decision: it is treated as re-resolve. A commit does not confirm (`spec.md`
§5.9, §6). A counter-account that a pick
fills on a leg that had none is the pair's: it takes the pair's pass with the
basis `{"from": "counterpart"}`, and leaves with the pair (`spec.md` §5.7). It refuses only on a structural
divergence: a moved version, a partner or document taken, a row the draft
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
`counter_leg_not_offered`, `counter_leg_account_synced`,
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
**Only a commit creates a counter-leg:** a user-authored source on the unsynced
account with importer NULL, its entry typed `transfer`, with the keys `user`;
the commit then follows the partner's amount where the spec says
(`spec.md` §5.7). The preview overlay runs the same pure pairing function as
settling, so the preview equals the commit plus settling.

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
  in at least one of the entry's description and note, the source transaction's counterparty name, purpose,
  end-to-end id and mandate reference, the payee's name and the category's name.
- `limit` (1 to 500, default 100) and `offset` page the result.

A value that cannot be understood or a filter that contradicts itself (`from` after `to`, `amount_min` above
`amount_max`, an amount bound without `currency`) is a 422 naming the parameter (§4.4).

**Order and paging.** Newest first by `booked_on`, then by source transaction descending (entries without
one, the derived entries, first: a balance record is the state at the end of its day, so it stands above
the day's movements), then by id descending: the order is total, so pages do
not overlap, and the entries of one split, which share a date and a source transaction, are adjacent. Paging
is by offset. The answer is `entries`, `total` (every entry the filter selects, whatever the page), `limit`
and `offset`.

**Rows.** An entry as the interpretation layer holds it: id and version, account, `booked_on` and `value_on`,
the signed amount with its currency (§4.5), type, description and note, `display_text` (derived: the
description, else the counterparty name, else the purpose; offered for uses such as the
panel title and search results, while the list's description column shows `description` alone, `patterns.md` §4.1), payee, category,
counter-account and counterpart entry, source transaction, document, `derivation`, `unit_key` (the same for every
entry of a unit), `authored` (true when its source transaction was entered by hand), review flags, tag ids and `source`. A row carries
ids only; names, icons and colours come from the account, category, payee and tag lists the client already
holds, and there is no running balance. A transfer leg also carries a read-only summary of its partner
(account, date, amount), so the list can show the partner when a filter hides it.
**`source`** is the entry's source transaction as one nested object, `null` only for derived entries, which
have none (every movement has one, imported or entered by hand: spec §3). A source entered by hand carries its
amount and purpose and no counterparty, reference, booking text or source format. It holds the fields rules read or the UI shows: counterparty name, reference and BIC, purpose,
booking text, end-to-end id, mandate reference, instructed amount and currency, and source format. It never
holds the raw record or the content hash. The client reads the counterparty name and purpose from it; there
are no flat copies on the entry. Every entry read carries it: the list, `GET /api/ledger/entries/{id}`
(behind login, like the list) and the rows of a rule's preview. There is no filter by id.
The list includes every entry, derived ones too (`type` narrows it); a duplicate source transaction has no
entries (`spec.md` I3) and so never appears. It is a read: it takes no lock, writes nothing and does not
settle.

**The lists.** `GET /api/ledger/categories` (flat, `parent_id` linking the tree, roots first, then
`sort_order` and name) and `GET /api/ledger/payees` (by name, with `document_provider`) answer with identity and presentation as
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

#### Operations return everything they touched

**A response describes every entity the operation changed, not only the one
named in the URL.** Operations cascade: a commit may pair a leg with an entry
elsewhere in the list, create a counter-leg on another account, or return a
former partner to review; marking or clearing a duplicate recomputes an
account's derived entries; settling after any write may give other unconfirmed entries new
proposals.

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
an entry's account, amount, counterpart or document — always bump it (its
source never changes),
so a commit is refused when the unit itself moved underneath the panel, a
document settling linked meanwhile included. A commit picking a document
also carries the document's own version (`spec.md` §5.5).

**The check and the write are one step.** A write locks the entries it
carries versions for (`SELECT … FOR UPDATE`, in ascending id order, after
its advisory locks, §5.2),
compares the
versions, and writes in the same transaction. A unique-index violation
during a write — a leg or document taken between the check and the insert —
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

**Event design, as guidance rather than a fixed list.** The exact event set
will settle during implementation; what the architecture fixes is its shape:

- Every event is a **named type**, and the client routes on the name. No
  untyped payloads discriminated by inspecting their contents.
- The stream carries **three kinds** of event: progress reporting (the task
  advanced), a request for input (the task is blocked until answered — a TAN;
  nothing about data ever blocks a sync, `spec.md` §5.11), and terminal
  outcomes (a run finished or failed, or the whole task ended).
  Any event that does not fall into one of these should prompt a check that
  it belongs on this channel at all.
- **A request for input carries a correlation id**, echoed back on the input
  operation, so a late or duplicate answer can be rejected rather than
  misapplied (§4.3).
- **Events carry no secrets and no domain state the client could fetch
  instead.** Progress says what happened, not the whole updated ledger; the
  client re-queries when it needs data.
- **The stream is resumable.** Event ids are monotonic per task so that SSE's
  own `Last-Event-ID` reconnect delivers what was missed.

### 4.3 The task token, reload and multiple tabs

```
POST /api/sync                  → 202 {task_id}
GET  /api/sync/tasks/{id}/events  ← SSE: progress … prompt … done
POST /api/sync/tasks/{id}/input → 204
```

The task lives on the server, not in the tab that started it. Everything below
follows from that.

**Reload.** The client does not need to remember the token. A user may have
at most one active sync task, so on mount the frontend asks for the current
user's active task and reattaches if there is one. No token in local storage,
nothing to go stale, and a reloaded tab recovers a sync in progress —
including one blocked on a TAN prompt.

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
  returns a conflict error, which the client treats as "someone already
  answered" and dismisses.

That second rule is the one the backend must get right regardless of what the
frontend does: the server assumes answers may arrive out of order, twice, or
for a prompt that has already been resolved.

**Abandonment.** A task whose clients have all disconnected keeps running to
the end of the current importer instance and then stops. A half-finished bank
dialog is not worth preserving, and every instance is independently
retryable.

Tasks are held in an in-memory registry keyed by token, with the owning user
recorded, so another user can neither attach to a stream nor answer a
prompt.

### 4.4 Error envelope

Every non-2xx response carries a machine-readable code, a human message, and
optional details. Codes come from the importer taxonomy (§5.5) plus generic
validation and auth codes. The frontend routes on the code, never on message
text — "wrong PIN" and "bank unreachable" lead to different UI, and one is
retryable while the other is not.

### 4.5 Cross-cutting constraints

Stated once here; enforcement is in §5 and §6.

**Session model.** A session references a user and records the authentication
method used. It is never coupled to a password, so adding OIDC later is a new
method rather than a rewrite. Transport is an `HttpOnly`, `SameSite=Lax`
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
                         the orchestration of the classifier plugins; the
                         allocation of document lines
    matching/            transfer pairing and offers; document matching and
                         suggestions
    units/               unit membership, drafts, preview and commit
    settle/              bringing derived state up to date after every write:
                         rederiving unconfirmed entries, pairing, document
                         matches, derived entries, flags
    reporting/           aggregate queries, all conversion via base_value()
    tasks/               registry, sync orchestration, event bus
    plugins/             PROTOCOLS ONLY: the importer and classifier
                         interfaces, the error taxonomy, the history source
                         classifiers read, the registry plugins register into
  plugins/               Concrete plugin implementations, one package each.
    importers/
      fints/
      paypal/
      csv/
    classifiers/         passes 1–3 of spec §5.9 (pass 0 is core), behind
      rules/             one protocol: propose a value and a machine-readable
      history/           basis. Ordered by authority.
      llm/               (not v1 — the protocol exists so it is a package,
                         not a refactor)
  utils/                 Infrastructure with no domain knowledge.
    db/                  engine, connection, SQL helpers
    auth/                sessions, password verification, OIDC seam
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
state, one account and a fetch window, and returns records, an optional reported
balance and the date its coverage runs through. It does not know about
identities, deduplication, ledger entries or database transactions. This is what
makes `spec.md` §5.2's guarantee structural rather than aspirational: two
importers cannot deduplicate the same account inconsistently, because neither of
them deduplicates at all.

**Invariant ownership.** Each invariant of `spec.md` §2.1 has exactly one
enforcement point:

| Invariant (`spec.md` §2.1) | Enforced in |
|---|---|
| I1 source transactions come from an importer, or are a user's on an unsynced account | `ingest`, the entry form's operations, and counter-leg creation in a commit (`core/units`) are the only writers; `CHECK ck_user_row` |
| I2 imported source transactions immutable except `duplicate_of`; user-authored ones edited through the entry form | Postgres trigger `trg_source_immutable` |
| I3 entries carry their source's account, currency and dates and sum to its amount; duplicates have no entries | Postgres deferred triggers `trg_split_sum` (on entries), `trg_source_entries` (on a source's copied columns) and `trg_duplicate_state`; `trg_entry_source_fixed` keeps an entry on its source; `ingest`, a commit, an edit through the entry form and clearing a duplicate write within one transaction |
| I4 one identity per row, unique per account over all rows | `CHECK ck_one_identity`; partial unique indexes over all rows |
| I5 one currency per account, for entries, source rows and balance records | composite foreign keys |
| I6 balance is the sum of entries | `core/reporting`; nothing else sums amounts |
| I7 one entry per new source transaction; only a commit splits | `ingest` and the entry form; `core/units` is the only writer of splits |
| I8 only entries with a source may be incomplete | Postgres `CHECK ck_complete_unless_movement` |
| I9 category implies flow; payee on flows; kind fixed; no cycles | Postgres `CHECK`, composite FK, triggers `trg_category_kind_fixed` and `trg_category_acyclic` |
| I10 transfer pair mutual, distinct accounts, opposite signs, same-currency equal; one counterpart | Postgres deferred trigger; partial unique index |
| I11 a counter-account is in the currency the money arrived in | one function in `core`, used by resolution (evidence filter), the preview and the matcher |
| I13 one derived entry per record, computed, never edited, tagged or annotated; the opening first | `core/balance` is the only writer; unique indexes; integrity views; `api` exposes no edit and no tagging for them |
| I17 no pass, matcher, settling or import creates a dimension or account | operations of §4.1; proposal types carry ids, not names |
| I18 proposals rederived, standing values kept; an entry resolved afresh when its input changes, and later fields derived again when a value changes | `core/settle` calls `core/resolution` and `core/matching` for the entries a change bears on; `core/resolution` applies the field order; the write that changes an entry's input — document ingest, an entry-form edit — resolves that entry afresh in its own transaction (§5.2) |
| I19 history learns only from confirmed values, a human's or standing ones | `core/resolution` supplies the history; a plugin never sees unconfirmed values |
| I20 no automatic process changes a reviewed entry | `core/settle` and `core/matching` select only unconfirmed units; `ingest` marks only rows it inserts; derived entries are the exception |
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
| I35 one document per transaction and per document | `ledger_entry.document_id`, with the partial unique indexes `ux_le_document` and `ux_le_document_per_transaction` |
| I36 a reported record never dated after its run's coverage | `ingest`; integrity view `v_check_reported_after_coverage` |
| I37 every write ends by settling | every write operation ends by calling `core/settle`; a model answer is a write of its own |
| I38 investment accounts fixed at creation | trigger `trg_account_investment_fixed`; integrity view `v_check_derived_type` |
| I39 ingest serialised per account, settling as a whole | the advisory locks of §5.2 |
| I40 user-authored source transactions, counter-legs included, only on unsynced accounts | Postgres trigger `trg_user_source_unsynced`; `core/units` offers and creates counter-legs nowhere else; nothing automatic creates them |
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
- **A commit is one transaction**: values, splits, link decisions, a
  counter-leg, an adjusted user-authored amount, and the removal routine for a partner left behind. It carries the
  version of every entry it writes — the drafted unit and every entry its
  preview showed as a consequence, such as a partner left behind or a picked
  leg's former partner — and of a picked document, and is refused if any has
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
  record — under the account's lock, so an account's derived entries are never stale between
  operations. The rest of settling (`spec.md` §5) — rederiving unconfirmed
  entries, pairing, document matches, flags — runs right after the write,
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
  (`spec.md` §5.9) — document ingest changing what resolution reads, for an
  unconfirmed transaction only (`spec.md` §5.5, I20), an edit
  through the entry form, which re-resolves fully, the user's values included
  (`spec.md` §5.6) — resolves that entry in its own transaction, as
  ingest resolves a new entry: a changed document's link is dropped for
  settling's matching to make again. Settling, which keeps no record of what
  an entry was resolved from, then does the rest.
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
  the settle lock come account locks, in ascending id order, then row locks,
  in ascending id order: a commit locks the accounts of every row its preview
  showed, then the rows. Where the plan under the locks needs accounts not yet
  locked (a counter-leg's), the commit runs again with them, at most three
  rounds, and then answers with the "try again" conflict. Settling takes no account lock at all — it creates no
  rows and recomputes no derived entries; the writes do that in their own
  transaction. `settle(engine)` opens its own transaction after the write it
  follows, and sets the transaction-local `ledger.settling` so that its
  rewrites do not bump versions (§4.1). Should PostgreSQL still abort a write on a deadlock, the server
  retries it once, holding its whole payload; if the retry fails too, the
  write answers with a named "try again" conflict and writes nothing.
- **The order of a settle.** One settle runs, over the units it covers:
  1. resolution, with each transaction's current link — so a linked
     transaction keeps its enriched input — and without one where none is;
  2. document matching, for transactions with no decided document — no link
     of any key, and no "none" — judged on step 1's result, which for them is
     the resolution without a document;
  3. resolution again of the fields after a link step 2 made;
  4. transfer pairing (`pair_transfers`), in booking-date order (`spec.md`
     §5.7), over every unpaired transfer leg, in every round; the matching window is the connection setting
     `ledger.matching_window_days`, which core reads from the connection like
     `ledger.max_rate_age` and never from configuration. A pair released by
     step 1 can be made again in the same round;
  5. review flags, and with them which units are confirmed — recording
     "none", keyed `matcher_decision`, for each transaction of a newly
     confirmed unit that has no document key (`spec.md` §6).

  Settling creates no rows: counter-legs come only from a commit. Units
  confirmed in step 5 teach history, which can change the proposals —
  and so the pairs and confirmation — of other unconfirmed units. Settling
  therefore repeats steps 1–5, over the unconfirmed units that share a
  history key value with a unit newly confirmed, until a round confirms
  nothing new. It terminates, because settling never unconfirms a unit —
  the "none" it records keeps a document source added later from doing so
  (`spec.md` I20) — so the confirmed set only grows; two rounds are the
  ordinary case, and a maximum round count turns a step that never converges
  into a reported failure. The five steps are an ordered list. Step 1 re-derives a paired leg of an
  unconfirmed unit like any other and releases its pair on both legs when its
  type or its own counter-account changes (`spec.md` §5.7). That is what makes settling idempotent (`spec.md` I37).
- **A settle that fails** after the write it follows committed leaves the
  write standing and reports the failure in the operation's response —
  `settle` never raises for its own failure, it returns it as
  `SettleResult.error`;
  derived state is then stale until the next write, or start, settles —
  settling is idempotent, so nothing is lost.
- **Unique indexes are not deferrable.** A write that moves a unique value —
  re-pairing legs, a new anchor taking the opening, re-picking a document —
  clears the old holder before setting the new one, within its transaction.
- **What a settle covers.** The **dirty set** of a write is the set of
  unconfirmed units whose derived state it can change:
  - a commit or any change to a confirmed value: the unconfirmed units that
    share a history key value (`spec.md` §5.9) with an entry it touched, plus
    the units it pairs or unpairs;
  - saving, changing or deleting a rule, a changed configuration, linking or
    unlinking an account: every unconfirmed unit;
  - changing a payee's `document_provider`: the unconfirmed units with that
    payee;
  - an import: the new entries, the units whose pairing candidates or document
    candidates they affect, and every unconfirmed unit when it delivers a
    balance record or coverage that moves a waiting decision.

  Key 5 of history (tokens) makes the first case broad, so the **baseline is a
  pass over every unconfirmed unit**, and narrowing to the dirty set is an
  optimisation taken only where the budget is missed. The budget is set from
  a backfill-sized fixture — a year of history, thousands of unconfirmed
  entries, one commit — and is a test, not a guess. Settling's result — everything it
  touched — is part of the operation's response (§4.1).
- **Every operation that recomputes derived entries or creates a counter-leg
  takes a per-account advisory lock** (`pg_advisory_xact_lock` on each
  affected account id, in ascending id order, following the lock order above). Unique
  indexes already make a racing double insert fail loudly; the lock prevents
  the quieter failure, two users' edits on one account each recomputing its
  derived entries from a snapshot without the other's change.

### 5.3 Task orchestration

A sync task is an `asyncio.Task` plus a queue of outbound events and a future
awaiting the next inbound answer. The orchestrator walks the instances the
user may authenticate (`spec.md` §5.11), running those that need no input
first, and emits `progress` between steps. Each instance authenticates once;
the orchestrator then asks it, against that session, for each linked account
from the account's fetch start, and for each accountless kind it emits —
each as its own run (`spec.md` §5.1).

When an importer needs a TAN it raises a prompt through the task, which emits
a `prompt` event and awaits the correlated `/input` call with a timeout. On
timeout or abort, the importer's dialog is closed and its run marked failed;
the orchestrator continues to the next instance.

Nothing about data raises a prompt: duplicates are marked at ingest
(`spec.md` §5.2) and listed in the run summary.

A partially completed authentication dialog lives only in the task, in
memory, and is dropped when the run ends, fails or is aborted. Nothing
credential-grade is written to the database (`spec.md` §7), so there is no
encryption key to manage; the cost is that a restart mid-dialog loses it
(§11).

At the end of the task: settling (`spec.md` §5). Because every write ends
with settling, a sync abandoned part-way is settled by the next write; there
is nothing to catch up on.

### 5.4 Classifier interface

Passes 1 to 3 of `spec.md` §5.9 are one protocol with three
implementations, ordered by authority. A classifier receives an entry's
inputs — its source transaction, a linked or picked document, and the
fields the review draft fixes — and returns zero or more proposals, each
carrying the field it proposes, the value and a **machine-readable basis** —
never a prose string alone. For history the basis carries the evidence: how
many matches agree, of how many, since when. The basis is what
is written to `ledger_entry.derivation` and what the review panel renders, so
producing one is part of the contract rather than an optional extra.
**Classifiers are pure**: they write nothing to the ledger, so ingest,
settling and the review preview call them alike (`spec.md` §5.9). The model's
stored answer — the field's `llm` key (below) — is read as an input.

**Classifiers do not query the database** (§5.1). `core/resolution` hands
them their evidence: the rules, read once per settle or preview, and a
read-only history source. For a key and an entry it returns the candidate
votes — confirmed entries within the lookback, excluding the given unit —
with the facts the classifier's filters need: each vote's values, booking
date and, for a counter-account, that account's currency and closing date.
Core retrieves candidates by indexed lookups, for equality keys by value and
for a token key by shared tokens; the classifier scores them — a similarity
threshold, say — and counts. What counts as a match is the classifier's to
define; how candidates are found fast enough for settling's budget is core's.

The orchestration is fixed in `core/resolution`, not in the plugins: fields are
resolved in the order of `spec.md` §5.9 — type first, then the fields the type
allows — passes run in order of authority, the first proposal per field wins,
and only pass 0 and rules write standing keys (`spec.md` §5.9); nothing history
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

- **Absent configuration, the pass does not run.** No default endpoint, no
  fallback provider. Entries fall through to the review queue unclassified
  and the system stays fully usable — this is the state a deployment without
  a model is permanently in, not a degraded mode.
- **The request payload is restricted** to the fields `spec.md` §5.9 permits:
  counterparty name, booking text and purpose, plus a linked or picked
  document's merchant and lines. Never IBAN, BIC, references, amounts, dates,
  accounts or balances. Enforcing that is the plugin's responsibility and is
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
  its own. A changed payload — a document linked to the entry — asks anew. A preview with a changed draft asks anew only when the
  user requests it. Settling never waits for the model: the request runs
  outside it, and storing the answer is a write that settles like any other.

Timeouts are short and failure is non-fatal: an unreachable model leaves the
entry unclassified, exactly as an unconfigured one would.

### 5.5 Importer interface and error taxonomy

An importer implements a small protocol: describe the settings it needs,
authenticate once per sync (possibly prompting), list reachable accounts — one
per currency pocket for multi-currency providers — fetch one account, or one
accountless kind, from a start date, and report the account's booked closing
balance if it has one. It declares the set of kinds it emits (`spec.md` §5.1)
and emits only final, booked records, in ledger sign convention. Each
transaction record carries its `source_format`, the instructed amount where the
source reports one, `source_id` when the source assigns one (`None` otherwise),
and a `raw` payload containing the original unparsed data.

Beyond the records, the protocol has an importer report:

- its **coverage** for every run — *through*, by the rules of `spec.md` §5.1
  and nothing later, including for a fetch that returned no rows — where
  its data starts, for the import log, and its own counts (zero bookings it
  filtered out, say) as named integers, which the run's statistics record;
- its **balance date** consistent with the core rule and never after the
  run's coverage (`spec.md` §5.1), and for statement formats the
  per-statement consistency check, failing with `ParseFailed` on a mismatch;
- a **default fetch start** for an account without coverage and without
  entries, shown prefilled in the sync and editable for that run;
- for documents: one per charge where the provider exposes charges, signed
  totals, merchant name and lines, and the providers it delivers documents
  for, declared in code rather than configured (`spec.md` §5.5);
- for any token it would store: the documented scopes, and the introspection
  check where the provider has one (`spec.md` §7).

A **file importer** has no session to open and nothing to fetch: it is a pure
parse of the uploaded bytes, given the profile, the account's currency, a lookup
from currency to its minor-unit exponent and today's date, and returns the rows, the reported
balance and its date, the coverage, where the data starts and its counts. A
problem on the importer's side — undecodable bytes, a missing header row, a
configured label it cannot find — raises `ParseFailed`; ingest's
`ContractViolation` checks stay as the backstop.

Errors are exception classes, not strings, because the queue's behaviour
depends on the distinction:

| Exception | Retryable | Surfaced as |
|---|---|---|
| `AuthRejected` | after correction | wrong PIN or password |
| `ChallengeExpired` | yes | TAN timed out, retry the instance |
| `ChallengeAbandoned` | yes | user cancelled |
| `SourceUnavailable` | yes | bank unreachable or timed out |
| `ParseFailed` | no | the file does not fit: the format changed, or the profile no longer finds its header or label; fix the importer or the profile |
| `ContractViolation` | no | the importer delivered what its contract forbids (wrong currency, zero amount, repeated `source_id`, no coverage); needs a fix in the importer or its profile |
| `NotRegistered` | no | FinTS product registration missing (`spec.md` §7.1) |

Outcomes that ingest decides — rows inserted as duplicates (`spec.md` §5.2) —
are not importer exceptions; they are recorded on the run and surfaced with it.
A breach of the importer's contract is a failure of the run (`ContractViolation`,
above).

### 5.6 Enforcing the cross-cutting constraints

**Sessions.** A `session` row references `app_user` and records the method
(`password` today, `oidc` later). Cookie holds an opaque id, not a JWT, so
revocation is a delete. Passwords hashed with argon2id. The OIDC seam is the
method column plus a single "establish session for this verified identity"
function. The cookie is `ledgehog_session`, `HttpOnly`, `SameSite=Lax`, and
`Secure` whenever the request is not to localhost; expiry slides, 30 days from
last use. There is no CSRF token, because the API accepts only JSON and
`SameSite=Lax` keeps the cookie off cross-site requests. There is no login rate
limiting in v1: two users, self-hosted — a conscious omission.

**Redaction.** Secrets live only in local variables inside the importer and
in the FinTS dialog object; neither is ever placed on the task, the event
stream or an exception payload. A logging filter drops known-sensitive keys as
a backstop, and request bodies are never logged for sync endpoints. The
backstop is not the mechanism — not putting secrets in loggable places is.

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
`USER_<n>_PASSWORD`, `MODEL_API_KEY`) also accepts a `_FILE` variant
naming a file (Docker and Compose secrets), and no secret is ever logged or
returned by `GET /api/config`.

| Group | Variables |
|---|---|
| Database | `POSTGRES_HOST` (`localhost`), `POSTGRES_PORT` (`5432`), `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (the last three required); no single database URL; the name stays a variable so each context has its own database (§9) |
| Ledger | `BASE_CURRENCY` (required, a three-letter code); `MAX_RATE_AGE_DAYS`, `MATCHING_WINDOW_DAYS`, `DOCUMENT_WINDOW_DAYS` (7 each, at least 0) — `spec.md` §3.8 |
| Household | `TIMEZONE` (required, an IANA zone; `spec.md` §5.4), `LOCALE` (`en`) |
| Users | indexed groups `USER_<n>_LOGIN`, `USER_<n>_NAME`, `USER_<n>_PASSWORD`, `n` contiguous from 1, logins unique; none is allowed |
| Model | `MODEL_ENDPOINT` and `MODEL_NAME` (both or neither), optional `MODEL_API_KEY`; absent means pass 3 does not run (§5.4) |
| Development | `EXPOSE_OPENAPI` (`false`; `true` or `false`, anything else fails the start): serves the OpenAPI document at `/api/openapi.json`, without a session, so the frontend's types can be generated from a running server (§6.7); a deployment leaves it off. `/docs` and `/redoc` never exist, whatever the value: they load scripts from a third-party host |

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
5. **Users.** Reconcile `app_user` with the configured users, matched by
   login: create a missing one; update the display name; set the password hash
   when the configured password no longer verifies against it, and delete that
   user's sessions. A user no longer configured is **disabled**, never deleted
   — runs and importer instances reference them — and loses their sessions. A
   password change is therefore a changed variable and a restart; the
   application has no password-change flow.
6. Set the connection settings that reach SQL (`ledger.max_rate_age`,
   `ledger.matching_window_days`) on every connection the pool opens.
7. **Settle.** Settling runs once, so a changed window or any other changed
   configuration takes effect on stored data like any other write (`spec.md`
   §5, I37).
8. Bind.

The household is two people, but nothing enforces it: any number of indexed
groups is created. There is no setup operation, wizard or sign-up. When OIDC
is added, it establishes sessions for verified identities instead
(§5.6), and the configured users remain as the password path or are dropped;
the ledger's data does not change either way.

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
    ledger/
    review/
    accounts/
    sync/
    reports/
    settings/          management: categories, payees, rules (below)
  lib/
    api/               The ONLY place fetch is called. One module per
                       operation group in §4.1 (ledger, units, importers,
                       sync, maintenance), plus shared error handling and
                       the SSE client.
    stores/            Svelte stores. Page-scoped by default; one long-lived
                       store for the active sync task.
    components/        Presentational and reusable. Props in, events out;
                       no direct api/ imports.
      ui/              shadcn-svelte components, copied in: dialog,
                       combobox, menu, tooltip, toast, date picker, button.
                       Generic, no domain knowledge; the only place Bits UI
                       is imported
      common/          composites of ui/: tables, money and date displays,
                       and the interaction components of patterns §11:
                       action dialog, row actions, icon and action
                       buttons, field, picker, page header, empty and error
                       states, notice
      ledger/          entry row, provenance widget
      units/           the unit panel — draft, preview, commit, split
                       editor — and queue rows, flag badges, evidence
      sync/            progress list, prompt modals
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
`/settings/payees`, `/settings/rules`, `/settings/rules/new` (optionally
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
the API from `components/`, and `fetch` outside `lib/api/`.

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
is the settle's own functions run on an *overlay*: resolution, matching, the
allocation of document lines and the review state all take a unit's stored
state with the draft laid over it, as an in-memory value, and return the
resulting state without writing; the rows a draft creates carry negative
temporary ids the client issues, which the preview echoes. `commit` writes that same result, and settling
calls the same functions on stored state. The entry form's `PUT` and `DELETE` are
previewed with `dry_run` instead (§4.1). This is the design's riskiest
component and is built before the panel's UI. The draft is the
user's choices for one unit; what they imply — proposals, the split a
document produces, offers, a counter-leg, a partner left behind — comes
from `preview`. The panel renders that and sends the full state back with
`commit`.

No global state library. Page-scoped stores, plus one long-lived store for the
active sync task.

### 6.4 Sync flow

Uses the sync operations of §4.1 through `lib/api/sync`; the paths there are
illustrative and this section names none of them.

Start a sync, attach to the returned task's event stream, and render from the
events. Input requests drive the modals — text TAN, photoTAN image, decoupled
confirmation with a waiting state — and answers carry the correlation id of the
request they answer. The run summary at the end lists, per account, what was
inserted, what was inserted as a duplicate and of which row, with a link to
those rows in the ledger list, and how many rows were skipped by identity; the CSV upload flow
ends with the same summary.

On mount, the app asks whether the current user has an active task and
reattaches if so, rather than remembering a token locally (§4.3). Two tabs
attaching to the same task is expected: both render the prompt, and whichever
answers first causes the other's modal to close through the shared stream. A
rejected answer means another tab was faster and is dismissed silently, not
surfaced as an error. Abandoning a sync is an explicit operation, not a
closed tab.

### 6.5 Review queue

The interaction model drives the API more than any other screen (§4.1).
Three sections — pending review, needs an account, waiting — each ordered by
booked date, then anchor entry id; whether and how to group units by shape
within a section is open until real units have been seen
(`ux/views/review-queue.md`). Each unit is committed with one keystroke, which
moves to the next. There is no batch confirmation; units decided entirely by
pass 0 and rules arrive confirmed once complete, and enter the queue only
while they wait for a partner or a document (`spec.md` §5.9, §6). Keyboard-first; the
bindings are a cross-view convention, decided once for every view.

Review is per unit (`spec.md` §6): the user opens a unit in the panel, changes
values, splits, converts, re-pairs or picks a document as draft edits, sees each
previewed, and commits the whole state at once. A unit appears once, with all
its entries — both legs of a pair, every entry of a split. The panel is the
only place an entry's interpretation is edited, apart from the merges (tags are edited there too, and directly elsewhere),
and it opens for any unit from the queue, the ledger list or a rule's preview.
Each key's evidence is shown — "1 of 1", "12 of 12" — so a thin proposal stands
out. A unit with open document suggestions, or a transfer without its partner,
can be committed but stays in review until the pick or the partner completes
it; the preview says which state the commit leads to.

**The queue is a snapshot, not a live view.** A working set is fetched when the
screen opens, and nothing is added, removed or reordered for the duration of the
session. **Each unit is previewed fresh when it is opened**, so its proposals
are current: confirming the first entry from a new merchant gives the next ones
in the list a proposal by the time the cursor reaches them, without the list
moving. Rows resolved during the session — whether acted on directly or as a
consequence of another operation — stay in place, marked as resolved, so the
list never shifts under the cursor and a mistaken action is still visible and
correctable by editing. There is no undo. Entries arriving from another sync
surface as a passive count that refetches only when the user asks.

Position stability matters more than freshness of order in a keyboard-driven
list: an item vanishing between keystrokes is how the wrong row gets
confirmed. This is why operations return their full affected set (§4.1) —
the client patches rows in place rather than refetching.

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
share an origin and the `SameSite=Lax` session cookie is sent.

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
  proposed, confirmed by one commit; a unit settling confirms keeping its
  "none" when a document source is added later;
  a counter-leg left behind by a broken pair staying, as an unpaired leg; a
  same-currency pair made unequal by a split shown invalid, with the
  split-the-difference offer whichever the legs' sources; a form edit of a
  paired user-authored amount breaking the pair, and a form edit never
  changing the account;
  pass 0 recognising a closed account's payout, history no longer proposing
  it; automatic document linking refused without uniqueness both ways;
  suggestions never stored; documents matched only to unconfirmed
  transactions, while a document carried by none offers confirmed ones too;
  waiting for a document from an instance that has never run, only for
  transactions dated from its start date on; the split a document's lines propose in the preview, confirmed unit or
  not, and its
  guards.
- **Unit tests** (review) — unit membership across a split and a pair;
  preview writing nothing; a commit applied atomically and refused on a
  structural change but not on a recomputed proposal; a pair confirmed only
  as a whole; a unit decided entirely by pass 0 and rules confirmed without
  review and teaching history, one with a single history key not; a standing
  value held while rules and history change and derived again when a
  document is linked; a commit keeping the standing keys of the values it
  leaves unchanged; a changed or deleted rule changing no existing value and
  listing both sets for review by hand; a category merge, refused across kinds and
  taking its children along; a broken pair returning the leg left behind
  to review with its confirmed values, and its split siblings', unchanged —
  all but a counter-account its pair set, which leaves with it — and
  re-resolvable in the panel; resolution
  rederiving unconfirmed entries after a confirmation and never touching a
  reviewed one; a settle whose confirmations change other proposals settling
  them in a further round until none confirms anything new, and a second settle
  changing nothing; a changed
  document and an entry-form edit resolving their entries afresh in their own
  write; history proposing only with a strict majority; re-resolving a
  confirmed unit without its own votes.
- **Invariant tests** — assert the database *rejects* what it should. A
  three-leg transfer, a non-mutual pair, a split that does not sum, entries on
  a duplicate, a duplicate on another account or of a duplicate, a duplicate
  of a user-authored row, a user-authored row created on a synced account, a source
  transaction inserted without an entry, coverage on a failed run, an
  entry with both or neither of a source transaction and a balance record, a
  document carried by two entries or a transaction carrying two documents, a
  document on a derived entry, an update to an imported source transaction other than to
  `duplicate_of`, an entry
  in a currency other than its account's, a child category of another kind, a
  change of a category's kind, a second opening on an account, a manual
  opening, a same-currency pair of unequal amounts, a reported balance record without a run, a second transfer entry
  on one source transaction, a row with both or neither identity, a source row
  or reported record on another account than its run, a transaction run
  without an account, a second linked document on one transaction or one
  document on two, a derived entry of type `flow`, a change of an account
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
  the others on the unvalued line.
- **Importer tests** — against recorded payloads committed as fixtures, never
  against a live bank.
- **API tests** — operation-level, including that another user cannot attach
  to a sync task.
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

- **OIDC provider and library.** Deferred until the password path works; the
  session model already accommodates it.
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
