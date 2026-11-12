# Overview — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §3.11, §6 and §8; the contract is
`architecture.md` §4.1 (*reporting*). `ux/design_system_mockup.png` is the
reference for the layout.

---

**The landing page**, `/`, the first item of the navigation, titled "Overview"
and described with today's date. No primary action (`ux/patterns.md` §11.7).
It is a computed view: it refetches when the ledger's change value moves and
keeps its figures on screen until the answer arrives (`ux/patterns.md` §7).

**Four figure cards**, all built the same way so that they read as one row:
an icon and the title on one line (`design.md` §6), under it a one-line
subtitle saying what the figure covers, then the figure, then quiet rows
beneath — each a label and its value — that appear only when they have
something to say. Nothing else comes between the figure and the rows, so the
four cards' rows begin on the same line.

- **Net worth**, "All accounts, today". Every account's balance at today's
  rate (`spec.md` §8). Rows: what could not be valued, per currency with the
  number of accounts; the transfers still unpaired, with their count, linking
  to the ledger filtered to unpaired legs (`spec.md` §6); what is owed to the
  household and what it owes — "Owed to you", the receivable accounts' total,
  and "You owe", the debt accounts', each with its number of accounts and
  linking to Accounts; the change since the end of last month.
- **Savings rate**, the 12 complete months it covers. Savings over income,
  "—" when income is not positive, with the marker when the period has
  unclassified entries, reconciliations or unvalued amounts (`spec.md` §8).
  Rows: last month's rate; this month so far, with its marker; and what was
  kept of the income received over the 12 months.
- **Spend**, the month so far. Expense-kind flows, refunds netting, signed.
  Its first two rows are the unclassified amount out and the month's
  reconciliations, labelled as what the figure leaves out, so that it does not
  understate itself (`spec.md` §8). Then: last month in full; last month to
  the same day. The figure and every row link to the report or the ledger with
  the equivalent filter.
- **To review**, "Imported, not yet confirmed". The review queue's count as
  the navigation shows it, the figure linking to the queue. Rows: the units to
  review; the units that need an account. At zero the figure reads
  "All reviewed", the card's icon is `check`, and there are no rows.

**Two half-width cards.**

- **Data age**, "Stalest first", its header opening Accounts as *Top expense
  categories* opens its report. Two short lists, **Synced** and **By hand**
  (`spec.md` §3.3), each its three stalest accounts by data age, accounts never
  fed first, a settled clearance account last. A row shows the account's icon,
  its name and its data age, and opens the account; the balance is the list's,
  not this card's. A synced account's age is a lapse, an unsynced one's a
  chore, so they are not ranked against each other. A list with no accounts is
  left out. A closed account is listed only while it holds a balance. No
  threshold colours (`spec.md` §3.11).
- **Top expense categories**, this month so far: the five largest top-level
  categories as bars in their colours, then "Other", then the unclassified
  amount out beneath. A row opens the ledger filtered by the category and the
  month; the header opens *By category* for the month. The card reads the
  same answer as that report, so the two cannot disagree.

**An amount that cannot be valued** is shown as `ux/patterns.md` §2 says, here
and in the reports alike.

**Empty.** With no accounts: "No accounts yet", linking to Accounts
(`ux/patterns.md` §9).
