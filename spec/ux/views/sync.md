# Sync — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §5.1, §5.4, §5.11 and §7; the
contracts are `architecture.md` §4.1–§4.3, §5.3, §5.5 and §6.4. The instances
that are synced, and the discovery of their accounts, are
`ux/views/importers.md`; an account's own fetch and its runs are
`ux/views/account.md`.

---

**Sync is an item of the navigation**, `/sync`, titled "Sync", described "Fetch
what your logins and sources have new." It has no primary action in the header
(`ux/patterns.md` §11.7); "Start sync" is the verb of the plan below. One page,
the states of one task: nothing running (the plan), running (the progress),
ended (the report). The task lives on the server (`architecture.md` §4.3) and
its store outlives the page, so a sync goes on while the user is elsewhere and
a reload picks it up again.

**The task indicator is the Sync item of the navigation.** While a task runs
it shows a spinner and a second line: "Syncing…", or "Needs your input" when
the task is blocked and the page that can answer is not the one shown; after
the end "Finished · 3 ok, 1 failed", until the sync page is opened. A discovery
reads "Refreshing accounts…". The item opens the task's own page.

## Starting

**The plan** is the page with nothing running: what "sync everything" would do
(`architecture.md` §4.1). One block per login, its accounts below; a login that
another sync holds says "another sync is using this login" and is left out.
Per account its start in words — "continues from the last sync, with an
overlap", "the day after its latest entry", "the importer's default" — and,
only for an account without coverage, a date field labelled "Start",
prefilled, the start for this run (`spec.md` §5.4); a documents row shows its
start and is never editable. "Start sync" syncs every login the plan shows;
there is no selection. One login or one account alone is the account page's
"Fetch". A refused start stands above the button. Another user's logins are not
shown; their owner and last run are in Settings → Importers. With nothing to
fetch the page says so and links to Settings → Importers.

**"Fetch"** on an account's source (`ux/views/account.md`) and **"Run again"**
on a failed fetch are one-item syncs. They start at once and open this page;
only an account without coverage opens the plan narrowed to that item first,
because its start is the one thing the user is asked.

## Progress and report

One card per login in the order the sync takes them, one row per item inside:
the account, or "Documents". A row is *waiting*, *fetching from* a date,
*waiting for your input*, *done* — "12 inserted · 31 skipped", and "· 2 as
duplicates" where there are — or *failed*. A done row opens the run summary
(`ux/views/importers.md`), a report, not an alarm (`ux/patterns.md` §8): it
opens no dialog and colours nothing red. A login that could not sign in or
continue shows its error once, and its items "Not fetched".

A failure shows the server's message, and routes on whether trying again can
help (`ux/patterns.md` §8), and on nothing else. One that can offers **"Run
again"**, which fetches the login's unfinished items from the start the server
derives, and asks for the PIN afresh. One that cannot says "Trying again will
not help yet. Fix what the error says, then fetch again", with a link to the
instance.

When the task has ended the page says so in one line — "Finished: 3 runs ok, 1
failed", "Stopped. Nothing more was written.", the logins not reached by name —
and "Back to the plan". A task the server no longer knows, after a restart, is
"This sync was interrupted. What was fetched is kept; run it again." The runs
themselves are the durable report, in each account's log.

## Prompts

When the task is blocked, one dialog asks, on this page only. It is shown
whenever this page is shown while the prompt is still open: when the prompt
arrives, and equally when the page is opened later — from the indicator, a link
or a reload — for a prompt that arrived while the user was elsewhere. Elsewhere
nothing interrupts what the user is doing: the indicator says "Needs your
input" and opens this page. A prompt left unanswered expires (`architecture.md`
§5.5), and its login fails, to run again. It is a form dialog (`ux/patterns.md` §11.2) titled by what
it asks and the login, "PIN for *label*", described by the moment, "Signing in."
or "Fetching *account*.", with the bank's own words (the challenge, the method)
as given.

| Asks for | Shows | Verb |
|---|---|---|
| a PIN or password | one hidden field | Sign in |
| a TAN as text | the challenge and method, a field "TAN" | Send TAN |
| a photoTAN | the image, then the field | Send TAN |
| a decoupled confirmation | the challenge, "Confirm in your banking app", a waiting indicator, no field | none |
| a choice (TAN method, TAN medium) | the options, none preselected | Continue |
| text (a TAN medium's name) | one field | Continue |

A prompt has no countdown; it says when it expires, "Expires at 14:32". "Cancel"
ends that login's sync and says so: "Cancelling stops this login; its accounts
keep failed runs to run again." The dialog closes when the server says the
prompt is resolved, in every tab that shows it; an answer another tab was
faster with is dropped without a message. A field's refusal stands under it
and the prompt stays open. A reload while a prompt is open shows the dialog
again, empty.

**"Stop sync…"** is a button of the running page and of a sync's prompt
dialog: a decision dialog, "Stop the sync?": nothing more is written, a fetch
under way is discarded, the login under way keeps its remaining accounts as
failed runs, logins not reached are left alone. The verb is "Stop sync", Cancel
is focused. The page says "Stopping…" until the task ends.

## New data

After this session's syncs have inserted rows, the views that hold a snapshot —
the ledger list, the review queue and an account's statement — show one quiet
notice, "New data from a sync — Refresh" (`ux/patterns.md` §7), without a
count: a row is not a unit, and no view counts revisions. Refreshing refetches
the view. Lists that are not snapshots — the accounts, the importers, an
account's runs — refetch when a sync ends. A sync run by the other user reaches
a session on reload.

**Open for the first month.** Whether "Run again" should cover every failed
login at once; whether a login can be synced from Settings → Importers; whether
the report survives a reload.
