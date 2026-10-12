# Step 5: spec, architecture and pattern text

Status: **for review.** Nothing here is applied. This is the exact wording for the decisions accepted in
`2026-10-11-step-5-plan-and-decisions.md` (B1–B16, C1–C12, D1–D9, "Units in the list") and for option B of
"without a category" (chosen 2026-10-12), written so that it says what the code does. Revised 2026-10-12 after the tag UI and the review iterations
landed: every statement about the frontend and the backend was checked again against the code AS BUILT (HEAD
`90af91e`) and `frontend/openapi.json` (the generated schema is the authority for field names). Where a
statement is about something not built yet it carries "[to be built]" and says which step builds it: the
"N new" count, the transfer partner summary and the joined split (steps 7 and 8), the unit panel, the account
strip, saved filters, narrow-width handling.
Each item gives *where* (document, section heading, a quoted anchor), *now*, *becomes*, and the files it
touches. When you answer "accept all recommended", I apply items 1–9 exactly as written, taking the option
marked *R* in "Questions for the author"; items marked "no change" apply nothing.

Contents: **1** architecture §4.1 list, lookups, tags · **2** architecture §11 · **3** architecture §2, §6.1,
§6.2, §6.7, §10 frontend · **4** architecture §5.7 `EXPOSE_OPENAPI` · **5** spec §8 and §3.7 ·
**6** patterns §4.1, §5, §7, §10 (6a rows, 6b units, 6c keys, 6d snapshot and live numbers, 6e open items) ·
**7** design.md · **8** plan.md (no change) · **9** decisions D192–D197 ·
**Questions for the author**.

Citation rules held: architecture cites `spec.md` only; patterns cite spec and architecture; decisions are
new entries D192 onwards (the last is D191), cited by no other document; nothing under `spec/` is touched
by this file.

---

## 1. architecture.md §4.1: the ledger list, the read-only lists, tags

**Rationale.** §4.1 lists `GET /api/ledger/entries` and the tag group "deliberately without field detail".
Both are built now, and the rules a client depends on are not field detail: what a filter means, in what order
the list comes, what the apply operation promises. Field names stay with the generated schema (§1 of the
architecture says OpenAPI is the reference); only the parameters that carry a rule are named.

**Files.** `spec/architecture.md` (§4.1: one line in the paths block, one new sub-block).

### 1a. The apply line in the paths block is marked previewed

**Where.** §4.1, the paths block, the `POST   /api/ledger/tags/{id}/apply` entry.

**Now.**
```
POST   /api/ledger/tags/{id}/apply             tag every entry a ledger-list
                                               filter selects, reviewed or not
                                               (the list's filter, not a range
                                               of its own)
```

**Becomes.**
```
POST   /api/ledger/tags/{id}/apply             tag every entry a ledger-list
                                               filter selects, reviewed or not
                                               (the list's filter, not a range
                                               of its own); previewed
```

### 1b. New sub-block "The ledger list and tags"

**Where.** §4.1, a new `####` heading inserted immediately before the heading
`#### Operations return everything they touched` (so after the paragraph ending "…a partner or document
taken, a row the draft relies on gone.").

**Now.** Nothing (the paths block is all there is).

**Becomes.**

````markdown
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
one, the derived entries, after the day's movements), then by id descending: the order is total, so pages do
not overlap, and the entries of one split, which share a date and a source transaction, are adjacent. Paging
is by offset. The answer is `entries`, `total` (every entry the filter selects, whatever the page), `limit`
and `offset`.

**Rows.** An entry as the interpretation layer holds it: id and version, account, `booked_on` and `value_on`,
the signed amount with its currency (§4.5), type, description and note, the source's counterparty name and
purpose, `display_text` (the description, else the counterparty name, else the purpose), payee, category,
counter-account and counterpart entry, source transaction, document, review flags and tag ids. A row carries
ids only; names, icons and colours come from the account, category, payee and tag lists the client already
holds, and there is no running balance. A transfer leg will also carry a read-only summary of its partner
(account, date, amount), so the list can show the partner when a filter hides it [to be built with pairing].
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
Tags are not part of review and move no `ledger_entry.version`, so these operations carry no
`expected_versions`. They are also the only way to tag an entry the filter does not select: there is no
operation over a list of ids, and a client that wants to add some entries to a filter's result calls this
one for each.

**Tagging a filter's result** is `POST /api/ledger/tags/{id}/apply`. The body is the list's filter as JSON,
with the same parameter names, repeatable ones as arrays and the same validation, plus `dry_run`,
`expected_count` and `all`. It tags every selected entry that can carry tags, in one transaction, leaving an
existing membership alone, and answers `selected`, `newly_tagged`, `already_tagged` and `skipped_derived`
(derived entries are skipped and counted), `per_account` (the accounts with newly tagged entries, with their
counts), the tag's span before and after and, for a real run, `entries` (id and `tag_ids` of every newly
tagged entry as it now stands) and `settle`. With `dry_run` the same code runs and is rolled back: `entries`
is empty and `settle` null. A filter that restricts nothing selects the whole ledger and is refused (422, at
`all`) unless `all` is true. Because a tag write moves no version, the rule of *Requests carry what the client
believed* cannot guard the selected set; the confirming request instead carries the preview's `newly_tagged`
as `expected_count`, and if the filter now tags another number nothing is written and the answer is 409
`conflict`, reason `filter_result_changed`, with `expected` and `actual`.
````

---

## 2. architecture.md §11: delete the pagination bullet

**Rationale.** Decided: offset (D192). The second bullet, whether generated types are worth the build step,
is settled too (D197); I propose deleting it with the first, your call (2b).

**Files.** `spec/architecture.md` §11.

**Where.** §11 "Open decisions", the second bullet.

**Now.**
```
- **Pagination style** for the ledger list — offset is simpler, keyset is
  correct under concurrent inserts. Probably offset, given two users.
```
**Becomes.** The bullet is deleted. (The decision, with the rejected keyset, is D192; §4.1 states the behaviour.)

### 2b. (optional, same edit) the OpenAPI bullet

**Now.**
```
- **Whether the API models are the OpenAPI source**, or whether generated
  client types are worth the build step for a single frontend.
```
**Becomes.** Deleted (types are generated, D197; §6.7 states the flow). *R: delete both.*

---

## 3. architecture.md §2, §6.1, §6.2, §6.7, §10: the frontend as built

**Rationale.** The text says `src/` and "root layout"; the code puts the frontend in `frontend/`, the two
flags in `+layout.ts` (the only file SvelteKit reads them from), the SvelteKit configuration in
`vite.config.ts` (there is no `svelte.config.js`), and types are generated. Rule 4 of the README: the
document follows the implementation.

**Files.** `spec/architecture.md` (§2 table and code block, §6.1, §6.2, §6.7, §10).

### 3a. §2, the Tooling row

**Where.** §2 table, row `| Tooling |`.

**Now.** `| Tooling | uv with a hash-pinned lockfile; pytest and hypothesis; …`

**Becomes.** `| Tooling | uv with a hash-pinned lockfile, npm with a committed lockfile for the frontend; pytest and hypothesis; …` (the rest of the row unchanged).

### 3b. §2, the three settings

**Where.** §2 "Why an SPA…", the code block after "Three settings, all required:".

**Now.**
```
adapter-static with fallback: 'index.html'   // shell, not per-route pages
export const ssr = false                      // in the root layout
export const prerender = false                // in the root layout
```
**Becomes.**
```
adapter-static with fallback: 'index.html'   // shell, not per-route pages; in vite.config.ts
export const ssr = false                      // in +layout.ts
export const prerender = false                // in +layout.ts
```

### 3c. §6.1

**Where.** §6.1, first paragraph.

**Now.** "`ssr = false` and `prerender = false` in the root layout. Client-side routing"

**Becomes.** "`ssr = false` and `prerender = false` in `+layout.ts` of the root layout (SvelteKit reads them from
no other file). Client-side routing"

### 3d. §6.2, the tree

**Where.** §6.2, the code block.

**Now.**
```
src/
  routes/              SvelteKit pages. THIN: compose components, read
```
and
```
    +layout.svelte     shell, nav, auth gate, ssr/prerender flags
```
and
```
    types/             shared types, generated from OpenAPI where possible
```
**Becomes.**
```
frontend/src/
  routes/              SvelteKit pages. THIN: compose components, read
```
and
```
    +layout.svelte     shell, nav, auth gate
    +layout.ts         ssr and prerender flags
```
and
```
    types/             shared types: api.d.ts is generated from OpenAPI
                       (§6.7), the rest is what OpenAPI cannot say
```

### 3e. §6.2, the module rules are enforced

**Where.** §6.2, the paragraph "Component subfolders mirror the operation groups, so a change to the review
API has an obvious frontend counterpart." (add after it).

**Becomes (new paragraph).** "The four rules are enforced mechanically, as import-linter enforces the backend's
(§5.1): ESLint's `no-restricted-imports` and `no-restricted-globals` forbid Bits UI outside `components/ui/`,
the API from `components/`, and `fetch` outside `lib/api/`."

### 3f. §6.7

**Where.** §6.7, after the last sentence "In development, the Vite dev server proxies `/api` to a locally
running uvicorn." (replace that sentence, then add the two paragraphs).

**Now.** "In development, the Vite dev server proxies `/api` to a locally running uvicorn."

**Becomes.**

````markdown
In development, the Vite dev server proxies `/api` to a locally running uvicorn
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
````

### 3g. §10

**Where.** §10, first sentence.

**Now.** "One image, multi-stage: a Node stage builds the frontend, a Python stage"

**Becomes.** "One image, multi-stage: a Node stage builds `frontend/`, a Python stage"

(The text "installs hash-pinned dependencies and copies the bundle in" stays; no Dockerfile exists yet, so
the `frontend/build` path is stated in §6.7 only.)

---

## 4. architecture.md §5.7: `EXPOSE_OPENAPI`

**Rationale.** A new variable must be in the table (§5.7: all configuration is environment variables,
read only in `utils/config.py`). Verified: `Config.from_env` reads it through the strict `boolean`
parser; the app mounts the document only when it is true, and the docs pages never.

**Files.** `spec/architecture.md` §5.7 (the table).

**Where.** §5.7 table, after the row beginning `| Model |`.

**Now.** (no such row)

**Becomes.** A new last row:
```
| Development | `EXPOSE_OPENAPI` (`false`; `true` or `false`, anything else fails the start): serves the OpenAPI document at `/api/openapi.json`, without a session, so the frontend's types can be generated from a running server (§6.7); a deployment leaves it off. `/docs` and `/redoc` never exist, whatever the value: they load scripts from a third-party host |
```
(`.env.example` carries the variable; I could not read that file in this sandbox, so please confirm it does.)

---

## 5. spec.md §8 (end) and §3.7

**Rationale.** §8 says only "Filters are multiplicative: date ∩ … ∩ text". The built filter has semantics a
reader (and a drill-down from a report) must know: OR within a dimension, descendants, magnitude, the text
fields, `uncategorised`. §3.7 lacks what tagging a filter's result promises. The spec states behaviour only;
parameter names, paging and sort are the architecture's (§4.1).

**Files.** `spec/spec.md` §8 (last paragraph), §3.7.

### 5a. §8, the last paragraph

**Where.** §8, the paragraph beginning "Filters are multiplicative:" (the last text before the `---`).

**Now.**
```
Filters are multiplicative: date ∩ account ∩ category ∩ payee ∩ tag ∩ amount
range ∩ text. One good filter bar replaces most reports.
```

**Becomes.**
```
Filters are multiplicative: date ∩ account ∩ category ∩ payee ∩ tag ∩ amount
range ∩ text, and the entry's type and review flag narrow it further. Several
values of one dimension are alternatives; the dimensions combine. One good
filter bar replaces most reports.

- **Dates** select by `booked_on` and are inclusive at both ends.
- **A category includes its descendants,** unless the filter asks for exactly
  that category. **Uncategorised** selects the entries that could have a
  category and have none — flows, and entries with no type yet, never
  transfers or derived entries — and is an alternative to the categories
  chosen beside it.
- **An amount range compares magnitudes,** in the one currency it names: a
  range across currencies is meaningless, and nothing is converted for it
  (I27). A direction narrows it to money in or money out.
- **Text** is searched in the entry's description and note, the source
  transaction's counterparty, purpose, end-to-end id and mandate reference,
  the payee's name and the category's name; every word of the text must be
  found, in any of them.
- **The list holds entries.** Derived entries are among them unless the type
  excludes them; a duplicate has none (I3) and never appears.
```

### 5b. §3.7, tagging a filter's result

**Where.** §3.7, second paragraph.

**Now.**
```
Tagging every entry the ledger list's current filter selects is one action —
a date range, perhaps narrowed to some accounts, is the usual filter — and it
applies to every selected entry that can carry tags, reviewed or not. Tags are
not part of review, so they stay editable on unreviewed entries (§6).
```

**Becomes.**
```
Tagging every entry the ledger list's current filter selects is one action —
a date range, perhaps narrowed to some accounts, is the usual filter — and it
applies to every selected entry that can carry tags, reviewed or not; derived
entries in the selection are skipped and counted. It is previewed — how many
entries it would tag, how many already carry the tag, how many were skipped —
and confirmed before it runs, and if the filter's result has changed since
the preview, nothing is written. A filter that restricts nothing would tag the
whole ledger, and is refused unless the request asks for exactly that. Tags are not part of review, so they stay
editable on unreviewed entries (§6).

A tag's name is unique, compared without regard to case. A tag comes off one
entry at a time, or goes with the tag. Removing a tag from a filter's result
and merging two tags are not in v1.
```

(`schema.sql` already has `ux_tag_name ON tag (lower(name))`; the sentence only states it.)

**Already there, no duplication.** "on entries other than derived ones" (§3.7) and I13 say derived entries are
never tagged. C8 (a duplicate never appears in the list) is I3, now cited in 5a; nothing more.

---

## 6. ux/patterns.md: rows, units, keys, snapshot, open items

**Rationale.** The row description lists columns in an order the built list does not use; the sentence "In
the ledger list, a split shows as one row that expands" is replaced by the accepted "Units in the list"; the
keys `t`, `/`, `↓` and `?` are built and the table says something else for two of them; the list is a snapshot
too, and an action on a filter's result speaks in the server's numbers; the prototype leaves a few things open
for the first month. Patterns may cite spec and architecture. **As built at HEAD:** the keys, the tag picker,
"Tag all…" with its dialog, the marking of rows, the row columns, the quiet notices. **[to be built]:** the
"N new" count, the transfer partner summary (step 8), the joined split (step 7), the unit panel (`Enter` is a
stub), the account strip; statements about them carry the marker, so the text is true of the code today.

**Files.** `spec/ux/patterns.md` (§4.1, §5, §7, §10).

### 6a. §4.1, the columns of a row

**Where.** §4.1 "Rows", first paragraph.

**Now.**
```
An entry row shows, in this order: date, account (where several are listed),
description (the entry's `description`, else the source's counterparty name or
purpose), payee, category or the transfer's destination ("→ Cash"), tags,
amount. Derived entries (opening, valuation, reconciliation) render in the same
row shape with their type in place of a category and no review affordances
(spec §3.9).
```

**Becomes.** (The order is the ledger list's, defined once in `columns.ts`; whether it stays is open, §10.)
```
An entry row shows, in this order: date, account (always in the ledger list; a
view of one account may leave it out), category or the transfer's destination
("→ Cash"), payee, tags, description (the entry's `description`, else the
source's counterparty name or purpose; the one column that takes the remaining
width), the review badges (§4.2) and the amount. Derived entries (opening,
valuation, reconciliation) render in the same row shape with their type in
place of a category and no review affordances (spec §3.9).
```

### 6b. §4.1, units in the list

**Where.** §4.1 "Rows", last paragraph.

**Now.**
```
The entries of one unit (spec §6) are shown together wherever a unit is shown:
a split's entries under their source, a pair's two legs side by side. In the
ledger list, a split shows as one row that expands.
```

**Becomes.** (Built: every row an entry, adjacency, no parent row, no expander. Marked: the rest.)
```
The entries of one unit (spec §6) are shown together wherever a unit is shown:
a split's entries under their source, a pair's two legs side by side.

**In the ledger list, every entry is a row, and a unit is never a row of its
own.** Filtering, counting, paging and tagging all act on entries
(architecture §4.1); anything grouped is only how rows are drawn. The entries
of a split are adjacent, because the list's order keeps them together. There
is no parent row and no expander. The whole unit opens in the panel [to be
built: `Enter` does nothing until the panel exists]. The entries of a split are
also visually joined, with a marker on the first row whose tooltip gives the
unit's total [to be built, with splits]. A transfer leg shows its partner —
account, date and amount — from a read-only summary the row carries, so it
works when a filter hides the partner; the partner's own row is highlighted
when it is in view [to be built, with pairing].
```

### 6c. §5, keys

**Where.** §5 table rows and the paragraph under it.

**Now.**
```
| `↑` / `↓` (also `k` / `j`) | move the cursor in a list |
```
```
| `/` | focus the filter bar |
| `t` | tag the row (or the filter's result, after a confirmation, spec §3.7) |
```
```
| `?` | show the bindings |
```
```
The cursor is the selection; there is no multi-select for interpretation,
because there is no batch confirmation (spec §6). After a commit the cursor
moves to the next row; a resolved row stays in place, marked (§7).
```

**Becomes.** (All built, except that `Enter` in the ledger list is a stub until the panel; its row is not changed.)
```
| `↑` / `↓` (also `k` / `j`) | move the cursor in a list; `↓` in the filter bar's text box moves it to the first row |
```
```
| `/` | focus the filter bar's text box |
| `t` | tag the row under the cursor: a searchable list of tags, `Enter` toggles the one under the highlight, a name no tag has can be created in place; a derived entry refuses with a quiet notice |
```
```
| `?` | show or hide the bindings (a panel fixed to the corner of the view, not a dialog) |
```
```
The cursor is the selection; there is no multi-select, for interpretation
because there is no batch confirmation (spec §6), and for tagging because a
filter's result is tagged through the filter. That is a visible action of the
filter bar, "Tag all…", never a key: it is unavailable, with its reason as
tooltip, while the list loads, when the filter restricts nothing and when
there is nothing to tag. It opens a dialog that shows the preview of
architecture §4.1 (how many would be tagged, how many already carry the tag,
how many are skipped, the accounts affected, the tag's span before and after)
and asks before it writes (§6). After a commit the cursor moves to the next
row; a resolved row stays in place, marked (§7).
```

### 6d. §7, the list is a snapshot too; a filter's result is the server's

**Where.** §7, the bullet "**Snapshots stay snapshots.**", and a new bullet after it.

**Now.**
```
- **Snapshots stay snapshots.** A list fetched for a session (the review queue,
  architecture §6.5) does not add or reorder rows; new data from another sync
  appears as a passive count ("12 new — refresh") that refetches only on
  request.
```

**Becomes.**
```
- **Snapshots stay snapshots.** A list fetched for a session (the review queue,
  architecture §6.5; the ledger list, whose filter is in its address) does not
  add or reorder rows; new data from another sync appears as a passive count
  ("12 new — refresh") that refetches only on request [the ledger list does
  not show the count yet]. An action patches the rows it touched in place and
  never removes or moves one: a row that the action takes out of the list's
  filter (a tag removed under a tag filter) stays, marked, until the list is
  fetched again.
- **A filter's result is the server's, not the list's.** An action on a
  filter's result (spec §3.7) states how many entries it will touch from the
  server's count for the filter as it stands, not from the rows the list holds,
  which may be a snapshot, and it captures the filter when it opens. If the
  result has moved when the user confirms, nothing is written and the action
  shows the new number and asks again. Rows the user changed that the filter no
  longer matches are not in the result: the action says so, and offers to
  include those that are still shown as a choice that is off by default.
```

### 6e. §10, open for the first month

**Where.** §10, after the third bullet ("whether resolved rows in a snapshot collapse after a while…"); the existing bullet "the key bindings of §5, especially commit and tag" stays.

**Becomes (five new bullets).**
```
- the ledger list's columns: their order (in particular whether the amount
  comes before the description) and which columns give way first at a narrow
  width (the prototype's table simply overflows);
- how the ledger list counts what is new since it was fetched ("12 new"), and
  how a joined split and a transfer's partner are drawn (§4.1);
- whether the ledger list shows the account's facts (§4.4) when one account is
  filtered; the prototype leaves them to the account view;
- where a quiet notice appears (the prototype reserves one line under the
  filter bar, so that it never moves a row; the alternative is a floating
  notice) and how a partly failed action is worded and styled (the prototype
  reports it inside the dialog in plain text);
- whether the filter-bar action "Tag all…", its dialog and the opt-in to tag
  the marked rows suit real use.
```

---

## 7. ux/design.md: two small additions

**Rationale.** Only rules the implemented UI relies on and the document lacks. The four fixed icons for
transfer, opening, valuation and reconciliation are already in §6; the type filter (in the category chip) lists
all five types with the row's icons and so needs one for a flow, and clickable elements need a stated cursor
(Tailwind 4 stopped giving buttons the pointer). The review filter uses the badge icons of §6, and the marked
row ("changed by your last action", 2px `ochre` bar) is already in the §7 table: no change for either.

**Files.** `spec/ux/design.md` (§6 "Fixed icons", §7 states table).

### 7a. §6, the flow's icon

**Where.** §6 "Fixed icons", after the table, the sentence "An unclassified entry shows no category icon: its category slot is the absent value "Unclassified" (§7)."

**Becomes (a sentence appended to that paragraph).** "The type filter shows the four icons above for their types and names a flow with `coins`, drawn the same way; a flow in a row shows its category, never this icon."

### 7b. §7, the pointer

**Where.** §7 table, after the row `| hover |`.

**Becomes (a new row).**
```
| clickable | the pointer cursor on every control that acts on a click; `not-allowed` on a disabled one |
```

The help panel's placement (fixed to the corner of the view) is a behaviour and is in patterns §5 (6c), not here.
The reserved line for quiet notices is not proposed as a rule: it is open for the first month (6e).

---

## 8. plan.md: no change

plan.md has no progress marking (no checkmarks, no "done"; the file's own status line says what gets built
and in what order, and `git log` shows no step ever marked). Step 5's line, "Ledger list and the filter bar;
tags, and tagging a filter's result (`spec.md` §3.7)", is still true. I propose none.

---

## 9. decisions.md: new entries

**Rationale.** Rule 5 of the README: reasons and rejected alternatives live in `decisions.md`. Six entries,
appended after D191 as D192–D197, each citing the sections it explains. The `t` key (plan C6) adds no
reasoning beyond patterns §5 and D194 and is folded into D194; what the "Tag all…" dialog says and does is
D195. Nothing here is normative.

**Files.** `spec/decisions.md` (appended at the end).

````markdown
## D192 The ledger list pages by offset and sorts so a split stays together

Architecture §4.1, spec §8. The list answers one page of the entries a filter selects, with the count.

- **Offset and limit, with `total`** (limit 1 to 500, default 100). The count is needed anyway: "Tag all…"
  confirms a number, and the list says "N of M". Keyset paging is correct under concurrent inserts, but the
  list is a snapshot patched in place (patterns §7), so no row appears or moves under a page, and two users
  rarely write at once. A page of 100 plus the count stayed within its budget on 8,000 entries, a deep page
  included. Rejected: *keyset* — it buys an insert-stability the list does not need and cannot give `total`
  or a jump to a place cheaply.
- **Order `booked_on` descending, source transaction descending (none last), id descending.** The siblings of
  a split share a date and a source transaction, so they are adjacent without any grouping; derived entries
  have no source transaction and follow the day's movements, an opening sorting before everything else on its
  account (I13). The order is total, so pages never overlap. Rejected: *`booked_on` and id only* — siblings
  would be adjacent only when their ids happen to be, and an entry from another source could fall between
  them; *sorting by `value_on`* — the domain buckets by `booked_on` (spec §8). Changing the order later
  would change what a page holds, so it is part of the contract.
- A split that straddles a page edge is rare and acceptable (D196).

## D193 Filter semantics: OR within a dimension, descendants by default, amounts by magnitude

Spec §8, architecture §4.1. One filter serves the list, the tag operation and the report drill-downs, so
what it means is stated once.

- **Several values of one dimension are alternatives, dimensions combine.** Picking two accounts or two tags
  widens; adding a dimension narrows. Rejected: *AND within a dimension* — an entry has one account and one
  payee, so two of them would match nothing, and "either of these tags" is the useful question.
- **A category includes its descendants by default;** `category_descendants=false` asks for exactly one.
  Choosing "Groceries" and seeing only the entries filed directly under it would hide most of them.
  Rejected: *exact by default* — a parent would then be a category of its own rather than a group, which is not how a tree of categories is read (spec §3.5).
- **Amounts are compared by magnitude, in one currency named with the bounds,** with an optional direction.
  A signed range reads wrongly for spending (−50 to −10), and a range over currencies is meaningless; the
  currency is required and nothing is converted, because only reporting converts (I27). Rejected: *a signed
  range* — "between 10 and 50" would match refunds but not purchases; *converting to the base currency* —
  a rate-dependent filter would change as rates arrive.
- **Text is a case-insensitive substring match, every word required, over the entry's description and note,
  the source's counterparty, purpose, end-to-end id and mandate reference, the payee's and the category's
  name.** These are the places a user remembers a transaction by. Rejected: *description only* — the
  counterparty is often the only text; *full-text search* — an unindexed scan took under 30 ms on 8,000
  entries, so no index is needed yet (architecture §11 keeps the scale caveat).
- **`uncategorised` selects the entries that could have a category and have none: type `flow` or no type yet,
  and no category; never a transfer or a derived entry.** It is an alternative to the categories chosen beside
  it. Rejected: *flows only* (option A) — entries that an import has produced and nothing has typed yet are
  the first thing a user wants to find, and they are the "no type yet" half of the report's Unclassified
  line (§8); *every entry with no category* (option C) — transfers and derived entries have none by nature
  and would drown the result.
- **Type and review flag are dimensions too,** because the dashboard's drill-downs need them. Derived entries
  are listed unless the type excludes them (patterns §4.1 shows them).

## D194 Tagging a filter's result is previewed, guarded by a count, and never a keystroke

Spec §3.7, architecture §4.1, D137. Applying a tag to a filter can touch thousands of entries.

- **Always previewed and confirmed.** The preview reports how many entries would be tagged, how many already
  carry the tag, how many derived ones are skipped, the accounts affected and the tag's span before and
  after. Confirmation scales with cost (patterns §6).
- **`expected_count` guards what the preview counted.** Tags move no `ledger_entry.version` (they are not
  part of review), so the version rule cannot protect the selected set. The confirming request carries the
  preview's number, and a different one writes nothing and answers 409. Rejected: *locking the set between
  preview and confirm* — the user may think for a minute; *no guard* — another sync or the other user could
  widen the set after the user looked; *a token for the preview* — more state for the same protection.
- **An empty filter is refused unless `all` is set.** Otherwise a cleared filter bar and one confirmation
  would tag the whole ledger. The list's action never sets it: with an empty filter the button is disabled
  ("Narrow the filter first"). Rejected: *refusing it outright in the API* — tagging everything is
  occasionally right for another client; *an "everything" button in the list* — nobody needs it in a
  prototype, and the API keeps the door open.
- **Tagging moves no version and takes no account lock;** it takes the settle lock shared and settles after
  commit, like every write. Derived entries are skipped and counted, not an error (I13).
- **The `t` key tags the row under the cursor; "Tag all…" is a visible action of the filter bar,** with no
  count on its label (the dialog states it, D195). The dangerous action is never one keystroke. `t` opens a
  searchable list of tags for the row (`Enter` toggles through the single-entry operations, a new name is
  created in place); a derived entry refuses with a quiet notice, as the API does. Rejected: *`t` for both, the second after a confirmation* (the
  earlier patterns text) — the same key meaning two operations of very different reach.
- **Untagging by filter and merging tags are deferred.** A tag comes off one entry, or goes with the tag
  (the answer counts the memberships removed); neither was needed to try the list. Revisit after the
  prototype.

## D195 "Tag all…" states the server's numbers and leaves the rows you changed to an opt-in

Patterns §5 and §7, D194, plan C10. A tag action leaves rows in the list that an active tag filter no longer
matches: they stay, marked, until the list is fetched again (nothing moves under the cursor). The filter-based
apply works on the server's result, and that result no longer holds those rows, so the dialog has two sets to
account for.

- **The numbers are live and the filter is captured when the dialog opens.** The preview is a dry run; its
  headline ("Tag all N entries") is the server's `selected`, not the number of rows held nor the list's
  `total`, which belong to a snapshot; the button carries no number for the same reason. The confirming
  request carries the preview's `newly_tagged`; when the result has moved (409 `filter_result_changed`) the
  dialog previews again, says what the number was and is now, and asks again. Rejected: *the list's total as
  the headline* — it may be stale, and the user would confirm a number the server will not use; *a count on
  the button* — it would need a request per filter change or show a stale number; *re-running silently
  with the new number* — the user would confirm something they have not seen.
- **Marked rows are explained, and tagging them is an opt-in that is off by default.** When the list holds
  marked rows the dialog says that the filter does not include them; for those the chosen tag would still
  change (not derived, not already tagged) it offers "Also tag the N rows you changed that are still shown".
  They are tagged after the filter-based apply, through the single-entry operation, up to four at a time; a
  failure for some is reported inside the dialog (what worked, how many failed and why), the preview is
  taken again, and nothing already written is undone. Confirm is possible when the filter would tag nothing
  but the opted-in rows would be. There is no new server operation (architecture §4.1: none works on a list
  of ids). Rejected: *"Tag all" acting on the rows shown (a selection)* — the filter is the selection
  (patterns §5), "all" would then mean two things, and the rows shown depend on how many pages were loaded;
  *the explanation alone* — it leaves the user to tag those rows one by one, though they are exactly the
  rows they just handled; *reloading the list when the dialog opens* — it would drop the marks and move
  rows under the user (patterns §7) before they decided anything; *including the rows by default* — the
  action would then do more than the filter says, which is the surprise the preview exists to prevent.

## D196 The ledger list is a list of entries; units are drawn, never rows

Spec §6, architecture §4.1, patterns §4.1, D192. Built: every row an entry and the sort that keeps a split
adjacent; the joined marker and the partner summary are to be built (steps 7 and 8). A split's entries share a date and adjoin in the sort; a
transfer's legs may be days apart.

- **Every row is an entry.** Filter, order, count, page, tag and any later sum are defined on entries and
  never change; grouping is presentation. A split's entries sit next to each other, visually joined, with a
  marker on the first row; the unit opens in the panel.
- **A transfer leg carries a read-only summary of its partner** (account, date, amount: one join, an additive
  field, added with pairing). It works when an account filter hides the partner, and the partner's row is
  highlighted when visible. Sorting cannot bring the legs together without lying about a date.
- Rejected: *a parent row per unit with an expander* — a split's total is not an entry, so the row could not
  be filtered, counted or tagged like one, and an expander moves rows under the cursor; *one row per
  transfer pair* — it hides a leg from an account filter and needs a rule for which date the pair sorts by;
  *sorting a pair by one of its dates* — the other leg's date would be wrong; *paging by units* — it breaks
  the count and offsets. Where a page edge cuts a split badly, the server may extend a page to the end of the
  unit; the paging stays by entry.

## D197 The OpenAPI document is generated, committed and exposed only in development

Architecture §4.4, §5.7, §6.7. The frontend's types should come from the API, not from a second hand-written
copy.

- **`EXPOSE_OPENAPI` (default off) serves `/api/openapi.json`; `/docs` and `/redoc` never exist.** They load
  scripts from a third-party host, and the app loads nothing from one (§6.7). Rejected: *always on* — an
  unauthenticated description of the API in a deployment for no need.
- **`scripts/dump_openapi.py` writes `frontend/openapi.json` from the application object,** with no database
  and no server, deterministically (sorted keys), and `--check` fails when it is stale. Rejected: *dumping from
  a running server* — it would need a database and a started process just to refresh a file.
- **The generated schema and `frontend/src/lib/types/api.d.ts` are committed.** A change to the API then shows
  as a diff, and an agent or a CI job without network access can check them. Rejected: *generating on every
  build* — it hides contract changes and needs the Python environment in the frontend build.
- **The document says what the server does:** operation ids are the handlers' names, and the error envelope
  (§4.4) replaces FastAPI's default validation error on every operation, so the generated error types are
  right. Rejected: *FastAPI's default 422 schema* — it describes a body the API never sends.
- **`openapi-typescript` generates the types, and the client stays a thin hand-written `request()`** that
  routes on the error `code`. The generator's own TypeScript dependency is overridden by npm to the
  project's (TypeScript 6). Rejected: *a generated client with a runtime* — one more dependency between the
  views and `fetch`, which only `lib/api` may call (§6.2).
````

---

## Questions for the author

**Q1. Statements marked "[to be built]" in patterns (reworded; the larger question is settled).** The text
that ran ahead of the UI is now small. Built and stated plainly: the keys (`t`, `/`, `↓` from the box, `?`),
the tag picker, "Tag all…" with its dialog, the marked rows, the columns. Marked "[to be built]": the unit
panel (`Enter`), the joined split (step 7), the transfer partner summary (step 8), the "N new" count in the
ledger list. CLAUDE.md says the implementation must follow the spec; a marker is how a spec sentence can be
ahead of the code without being false.
- **A (R).** Apply with the markers (items 6b and 6d); the build removes a marker when it delivers the part.
- B. Leave the four statements out until they are built, and add them then; the spec says less, and the text
  of 6b about "no parent row, no expander" would wait for step 7 too.
- C. Apply with no markers and let the missing UI be a defect list.

**Q2. The dry run and the "previewed" convention.** §4.1 says a previewed operation "returns everything it
would change, in the shape of its real response". The apply preview returns counts, `per_account` and the
span, with `entries` empty and `settle` null: it does not list the thousands of entries it would tag. Item 1b
states exactly that.
- **A (R).** Keep item 1b (it names the empty `entries` and null `settle`), leave the convention paragraph as
  it is: the shape is the real response's, the count says what the list would.
- B. Add a clause to the convention: "where the set is a filter's result, a count stands for the list".
- C. Make the preview return the ids too (up to the whole ledger on `all`), which the code does not do.

**Q3. Parameter names in the architecture.** Architecture §1 says the document does not enumerate API fields
and that generated OpenAPI is the reference; item 1b names the filter parameters. I kept it to the ones that
carry a rule and to the shared vocabulary of the list and the apply body.
- **A (R).** As drafted: rules and the parameters they attach to; everything else defers to the schema.
- B. Semantics only, no parameter names ("the date range", "a category's descendants…"); shorter, but a
  reader has to open the schema to learn that `uncategorised` is a parameter.
- C. Add a table of every parameter; it would be a second copy of the schema.

**Q4. The `type` and `flag` query parameters are untyped strings in the schema.** The list's `type` and `flag`
are `string[]` in the generated schema (the code validates them and answers 422), while the apply body types
them as enums (`EntryType`, `ReviewFlag`). The spec text of item 1b is true either way, but the generated
list parameter types are looser than the body's.
- **A (R).** No spec change; I tell the code side (a one-line router fix would give the list the same enums).
- B. State the closed sets in §4.1 (the five types, the five review tokens).
- C. Leave it.

**Q5. "Development only" for `EXPOSE_OPENAPI`.** Item 4 says "a deployment leaves it off". Nothing in the code
refuses to start with it on in a deployment (the config comment says "development only"), so the text is a
convention, not a check.
- **A (R).** Keep the wording (a convention, as `TIMEZONE` and the rest are plain variables).
- B. Add a start-up check that refuses `EXPOSE_OPENAPI=true` unless some development marker is set (code
  change, a new rule; I do not recommend it for a two-person household tool).
- C. Say "off by default" and drop "a deployment leaves it off".
