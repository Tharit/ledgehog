# Reports — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §3.5 and §8; the contract is
`architecture.md` §4.1 (*reporting*).

---

**One area, three tabs**, as Settings has them: `/reports/by-category`,
`/reports/over-time`, `/reports/balances`; the navigation item "Reports" opens the
first. A report is a type. A later report (a different chart of the same
figures) is a variant inside a type, selected by a control, not a new tab.

**Shared controls**, all in the URL: the period (the ledger's date chip and
its presets, with "Last 12 months" and "Last year" among them); the kind
(Expense or Income) in *By category* and in the by-category mode of *Over
time*; and the ledger's own account and tag filters with the same parameters,
so that the cost of a trip is *By category* with a tag filter.

**Every number links to the ledger** with the equivalent filter, so there is no
report-only sum: the period as dates, the category with its descendants, the
page's account and tag filters carried over. A whole kind links by listing its
top-level categories as alternatives (`spec.md` §8); unclassified,
reconciliations and unconfirmed link to the ledger's own filters for them. A
figure derived from others (a savings figure or rate) is not a link; its
tooltip names its components.

**Tab 1: By category.** One range. A donut of the largest six top-level categories and
"Other"; a category whose net is of the opposite sign (refunds beyond
purchases) is not a slice and is named in a note. The category tree as a table:
entries, amount, share, and a bar; a parent's own entries are a child row
"*Name* (itself)". Beneath, "Not in the categories above": unclassified out
and in, reconciliations, and the count of entries not yet confirmed (the table
includes their proposed categories).

**Tab 2: Over time.** A range cut into months, quarters or years in the household's
calendar; a period the range cuts is labelled with its days. Default mode,
*Income and expense*: income above the zero line, expense below it, a savings
line over them; a table of the rows Income, Expense, Unclassified,
Reconciliations, Savings and Savings rate, so that each column visibly sums to
its savings, and a Total column. The savings and the rate are the same
computation as the Overview's. Mode *By category*: stacked bars of the top
categories and "Other"; the category tree with a column per period and a total.

**Tab 3: Balances.** The balance at each month-end of the range (the current month's
point is today), in the base currency: net worth by default, individual
accounts added by toggle, grouped by kind; a table of the lines against the
month-ends: net worth, then each kind with the net worth of its accounts, its
accounts beneath it. Openings, valuations and reconciliations are in the balances. An
account with no valued balance is listed beneath as unvalued and is not
charted.

Amounts follow `ux/patterns.md` §2: signed, and a total with unvalued entries
says so. Charts follow `ux/design.md` §8; every chart has its table beside it
as the readable data. A report is a computed view (`ux/patterns.md` §7).
A table with groups (the category tree, the accounts by kind) opens collapsed to
its top level; a group row expands as the category tree in Settings does, and a
group's figures are its whole.
