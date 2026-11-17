# Reports — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §3.5 and §8; the contract is
`architecture.md` §4.1 (*reporting*).

---

**One area, four tabs**, as Settings has them: `/reports/by-category`,
`/reports/by-account`, `/reports/over-time`, `/reports/balances`; the
navigation item "Reports" opens the first. A report is a type. A later report (a different chart of the same
figures) is a variant inside a type, selected by a control, not a new tab.

**Shared controls**, all in the URL: the period (the ledger's date chip and
its presets, with "Last 12 months" and "Last year" among them); the kind
(Expense or Income) in *By category* and in the by-category and by-account
modes of *Over time*, where the by-account mode adds Transfers in and
Transfers out; and the ledger's own account and tag filters with the same
parameters, so that the cost of a trip is *By category* with a tag filter.
The *By account* tab has the period and the tag filter only: its accounts are
what it shows. Beside the period, two arrows step it to the span before or
after, of the same length: by calendar months when the period is whole months
(a month, a quarter, a year, the last twelve months), by its days otherwise.
The next arrow is off once the period reaches today.

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

**Tab 2: By account.** One range. A sankey in four columns: the largest ten
top-level income categories and "Other"; the accounts that received money; the
accounts that paid; the largest ten top-level expense categories and "Other".
An account stands in the second column when it received income or sent a
transfer, and in the third when it received a transfer, kept income or paid an
expense, so it may stand in both. Between the two account columns a link from
one account to another is a transfer, at its booked amount in its own
direction; a transfer there and back is two links. A node "Unpaired" stands in
both account columns for the transfer legs that have no partner yet: in the
third as receiver of the outgoing ones, in the second as sender of the
incoming ones. The band from an account to itself is the income that stayed in
it: what it received less what it transferred out. It is derived, so it is not
a link to the ledger; its tooltip gives the amount alone, since its components
are the links beside it. An account block taller than what leaves it shows
money kept; one with more leaving than arriving shows money drawn from its
balance. Unclassified money in and out and reconciliations are nodes of their
own on the side of their sign. A link whose net is of the opposite sign
(refunds beyond purchases on one account) is not drawn and is named in a note.
The table: Income and Expense, each category with its accounts beneath it;
Transfers, each sending account with the receiving accounts beneath it,
"Unpaired" on either side; and "Not in the categories above" as *By category*
has it, each line with its accounts beneath it. A category's row is its *By
category* figure.

**Tab 3: Over time.** A range cut into months, quarters or years in the household's
calendar; a period the range cuts is labelled with its days. Default mode,
*Income and expense*: income above the zero line, expense below it, a savings
line over them; a table of the rows Income, Expense, Unclassified,
Reconciliations, Savings and Savings rate, so that each column visibly sums to
its savings, and a Total column. The savings and the rate are the same
computation as the Overview's. Mode *By category*: stacked bars of the top
categories and "Other"; the category tree with a column per period and a total.
Mode *By account*: stacked bars of the top accounts and "Other", each with its
amount of the kind; the accounts chosen in the account filter are the ones
stacked, every account when none is chosen. Transfers in and Transfers out are
an account's transfer legs by direction, paired or not. The table has the
accounts grouped by kind, as *Balances* has them, with a column per period and
a total.

**Tab 4: Balances.** The balance at each month-end of the range (the current month's
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
