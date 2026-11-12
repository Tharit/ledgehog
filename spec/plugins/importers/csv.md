# Importer: csv

Status: **written ahead, in v1.** One generic importer for statement exports,
configured by a profile; there is no importer per bank. `spec.md` §5.1 owns
what any importer delivers — columns, sign convention, coverage, closing
balance, synthetic movements — and §5.2 what ingest does with it;
`architecture.md` owns the upload operation and its dry run. This document
covers only how a file becomes those records.

---

## 1. The profile

A profile is plain data, kept in the settings of an `importer_instance`: one
profile per file format. Accounts of the same format link to the one instance
(`spec.md` §5.4), and a file is uploaded against one of them — the file's own
account number is often masked and is never relied on. The importer never reads
the database or the clock: it receives the file, the profile, the account's
currency, a lookup from currency to its minor-unit exponent (the instructed
amount is in another currency, whose exponent differs, 0 for JPY) and today's
date, and returns records, the
reported balance and its date, coverage, where the data starts and its own
counts (`architecture.md` §5.5). A problem on its side — a file it cannot
decode, no header row, a configured label it cannot find, a value that does not
parse, no coverage — fails the run as `ParseFailed`, and the dry run (§7) shows
it.

Because a profile is data, it can be written in a settings form, loaded from a
preset (§8) or proposed by an assistant (§9), and in every case it is checked
the same way: by the dry run (§7), which parses a file and writes nothing.

## 2. Reading the file

| Setting | Notes |
|---|---|
| encoding | A byte-order mark decides (UTF-8); otherwise UTF-8 if the file decodes as it, else `cp1252`. The profile may name one. A file that does not decode fails the run. |
| delimiter, quote | Detected, overridable. A quoted cell may span lines. |
| header marker | The column names that identify the header row: the first row containing all of them. Everything above it is the preamble (§5); rows before it are never transactions. Not a fixed line number, so a preamble that grows does not break the profile. A file with no such row fails the run. |

**Spreadsheets.** An `.xls`, `.xlsx` or `.ods` file is recognised by its
first bytes and read from its first sheet; encoding, delimiter and quote do
not apply. A cell the sheet stores as a date or a number is taken as that
value, and the profile's date and number formats apply to text cells only.
Everything else in this importer applies unchanged.

**Whitespace.** Each cell is trimmed, and runs of whitespace in the normalised
columns collapse to one space; `raw` keeps the original text.

Header names are trimmed. A name that occurs twice is addressed by its
occurrence (`Betrag#2`); any column may also be addressed by position, counted
from 1 like the occurrence.

**A row is a transaction if its booking date parses, and is skipped otherwise.**
That drops footers (a `Saldo:` row) and section titles without a rule per bank.
**Blank lines are ignored**, neither read nor skipped. Skipped rows are counted
and listed in the dry run, so a column mapped wrongly shows as "every row
skipped", not as an empty import.

## 3. Mapping the columns

| Field | From |
|---|---|
| `booked_on` | a date column; the format is a profile setting, written with the tokens `dd`, `d`, `MM`, `M`, `yyyy` (`dd.MM.yyyy`, `d.M.yyyy`, `dd/MM/yyyy`; unpadded days and months parse under either; years have four digits) |
| `value_on` | a date column, optional |
| `amount` | one signed column, or a credit and a debit column; decimal and thousands separators are settings |
| `counterparty_name`, `counterparty_ref`, `bic`, `end_to_end_id`, `mandate_ref`, `booking_text` | one column each, all optional |
| `purpose` | a list of columns, joined with a space; empty cells dropped |
| instructed amount and currency | two columns, optional; ignored on a row whose currency equals the account's; the *invert amounts* setting applies to the instructed amount too |
| currency | a column, optional; where there is one it must equal the account's currency |
| `source_format` | `csv:` and the instance's label at the time of the run; the profile has no name of its own |
| `raw` | the row's cells as read — untrimmed, unparsed, in file order; the header is not repeated per row (`spec.md` §5.1) |

**Sign.** The profile has an *invert amounts* setting and, separately, an
*invert balance* setting (`spec.md` §5.1). A source that shows purchases as
positive inverts both.

**Placeholder cells** such as `n/a` or `-` are treated as empty; the placeholder
list is a setting. A row whose currency column differs from the account's
breaks the importer's contract and the run fails (`spec.md` §5.1, §5.2); the
dry run reports it as that failure, before an upload.

**Credit and debit.** With a credit and a debit column the amount is
`credit − debit`, an empty cell counting as 0; both empty is a zero booking.
A row of amount zero is dropped and counted (`filtered`, §4).

## 4. Row filters

A filter skips a row when a column equals, or matches, a value: `equals`
(trimmed, case-sensitive) or `matches` (a Python regular expression, searched
in the cell). Filters see the cell **before** it is parsed, so a pending row's
`vorgemerkt` in a date column never causes a parse error. It is the one
mechanism behind two needs: **pending rows** (a column that reads `vorgemerkt`,
which `spec.md` §5.1 excludes) and **mixed-currency files** (one currency per
run). Pending and filtered rows are reported in the dry run only, with the
skipped ones (§2), and are not stored.

**The importer's counts.** The importer returns its own counts as named
integers, which the run's statistics store (`architecture.md` §5.5): `filtered`
is the zero bookings it dropped, and only those; `synthetic_skipped` is a
statement payment not emitted (§6).

## 5. Balance and coverage

The whole file, preamble and footer included, is searched for a figure with a
**label**. A label matches a cell whose whole trimmed text it is; failing that,
a cell that contains it. The first match in file order wins. The value is read
at an **offset** from the label cell, a profile number: a count of cells to its
right (`Saldo:;;;-842,01`, offset 3) or of rows below it in the same column (a
label row above a value row). A **date** is read the same way, or extracted by a
pattern from the text of a cell (`Abrechnungsdatum: 3.8.2026`).

A label that is configured but not found, or a value that does not parse, fails
the run, naming the label: a profile that silently reported no balance would
hide a wrong setting.

The **export date** is an optional setting, read like a balance date, with the
date-time format `dd.MM.yyyy HH:mm:ss` (tokens as in §3, plus `HH`, `mm`, `ss`).
Without it the export date is the upload date the caller passes in.

A profile's balance is one of:

1. **a running-balance column** — the running value after the last row before
   the export date, dated at that row's booking date;
2. **a labelled figure** with its date, as above;
3. **none** — the account reconciles against balances entered by hand
   (`spec.md` §5.10).

`spec.md` §5.1 decides the date of the record. The importer applies the
profile's *invert balance* setting, then dates the record at the earliest of the
figure's own date, the last closed day (the day before the export date) and the
run's coverage. Where that date is earlier than the figure's date, the amounts
of the booked, unfiltered rows whose `booked_on` is after it, up to the figure's
date, are subtracted from the figure; filtered rows are excluded. So a figure
dated on the export day is rolled back to the closed day, and a quiet account,
whose last booking is earlier than the closed day, reports its balance dated at
its coverage. A figure that may include pending items is not a booked balance:
mode 3.

**Coverage** is the file's stated period end where the profile reads one (a
statement date), otherwise its last booking date after filtering; never the
export or upload date (`spec.md` §5.1). Rows dated after a stated period end
are kept and the coverage stays that end; a later fetch overlaps them and
ingest deduplicates. A file with neither a stated period end nor a row has no
coverage, and the run fails.

## 6. Statement payment

Some cards export only what was bought with them, and the payments that settle
them reach the account that pays, never the card's own export. Without help the
card's balance would never fall, and each reported balance would be reconciled
by an amount equal to the payment. A profile can therefore declare that its
statements list no payment, and the importer emits one synthetic movement per
file (`spec.md` §5.1).

| Setting | Meaning |
|---|---|
| enabled | off by default; off for a card that lists its payments |
| counter-account reference | becomes `counterparty_ref`, so pass 0 types the row a transfer to the account that pays (`spec.md` §5.9); it equals that account's `external_ref` |
| purpose | a text template; `{statement_date}` is the coverage date, rendered as ISO `YYYY-MM-DD` |
| date offset *N* | days after the run's coverage, at least 1 |

- **Amount.** The negated net sum of all transaction rows of the file —
  every row after filtering, including rows ingest then skips or marks as
  duplicates — so that the statement nets to zero. It assumes the card is paid
  in full each month. Where the account's debit differs, the transfer's offers
  and the reconciliation show the difference (`spec.md` §5.7, §5.10). A net sum
  of zero or more emits nothing and is counted as `synthetic_skipped` among the
  importer's counts (§4).
- **Date.** Coverage plus *N* days. It must fall after the balance record,
  which is dated at the coverage, or the record would include the payment and
  the interval's derived entry would be the statement itself; and within the
  matching window of the leg on the paying account. Choose *N* from when the
  debit is observed to arrive: a statement on the 3rd whose payment lands
  between the 6th and the 9th takes *N* = 4, the 7th, which the default
  window of seven days covers.
- **Provenance.** `source_format` is `csv:synthetic`; `raw` holds the profile
  settings used, the row count, the sum and the statement date. The dry run and
  the ledger show the row as derived from the statement, not as reported.
- **Re-uploading** the same file gives the same row, which ingest skips. A
  changed purpose gives a new hash, which the amount step pairs with the
  existing row as a duplicate (`spec.md` §5.2).
- **Another source later.** Should the card gain a source that lists its real
  payments, the setting is turned off. Real and synthetic rows deduplicate only
  where their dates and amounts coincide (`spec.md` §5.3).

## 7. Dry run

The dry run of an upload runs the real path in a transaction that is rolled
back (`architecture.md` §4.1) and returns the run summary with the importer's
parse report. A failure the run would end in — an importer error (§1), a currency
mismatch (§3) — is shown as that failure. The report, so that a profile can be
judged before it is used:

- the header row found and the columns it mapped, the first rows as parsed;
- the count of rows read, skipped as not transactions, filtered by a row filter
  (pending rows among them) and dropped as zero bookings, with examples of each;
- a row whose currency differs from the account's, as the failure it would be;
- the export date used and where it came from;
- the coverage and the balance record that would be written, with the figure's
  place in the file and the roll-back applied;
- the synthetic payment, if any, with its amount, date and the sum it is made
  of.

## 8. Presets

A preset is a profile without account details, shipped as a data file. A new
bank is a new file, not code. The shipped presets are the importer's tests:
`consorsbank_giro`, a giro with a preamble, a pending flag and a header
figure; `deutschebank_card`, a card with a footer balance, two `Betrag`
columns and no payments; `amex_card`, a card with inverted signs, multi-line
cells and no balance; `caixabank_giro`, a spreadsheet, newest first, with a
running balance; `olb_debt`, a loan account with no balance, whose columns
with umlauts are addressed by position. Their fixtures are written for the
purpose: real exports carry names and account numbers and are not
committed. The presets are JSON files shipped as package data, loaded as
package resources, and named after the bank and account whose export they
read (`consorsbank_giro`).

## 9. Not in this importer

MT940 and camt statements, which have their own parsers and checks
(`spec.md` §5.1). Files holding several tables or accounts, and a
spreadsheet's sheets after the first.
Extracting a counterparty from free text: the text stays in `purpose`, and
rules and history read it (`spec.md` §5.9).

A model-assisted *suggest a profile from a sample* is a separate, later
function: it proposes the semantic settings a heuristic cannot — which column
is the purpose, the sign convention, where the balance sits, what marks a row
pending — and its result is a profile like any other, judged by the dry run.
It is never part of an import.

## Appendix: the shipped presets

| | `consorsbank_giro` | `deutschebank_card` | `amex_card` | `caixabank_giro` | `olb_debt` |
|---|---|---|---|---|---|
| header marker | `Buchung`, `Valuta`, `Betrag` | `Belegdatum`, `Eingangstag`, `Verwendungszweck` | `Datum`, `Beschreibung`, `Betrag` | `Fecha`, `Fecha valor`, `Importe` | `Buchungsdatum`, `Valuta`, `Betrag` |
| `booked_on` | `Buchung` | `Eingangstag` | `Datum` | `Fecha` | `Buchungsdatum` |
| `value_on` | `Valuta` | `Belegdatum` | — | `Fecha valor` | `Valuta` |
| date format | `dd.MM.yyyy` | `d.M.yyyy` | `dd/MM/yyyy` | `dd.MM.yyyy` (text cells only; the sheet's dates are typed) | `dd.MM.yyyy` |
| amount | `Betrag`, `.` thousands, `,` decimal | `Betrag#2` | `Betrag`, inverted | `Importe`, `.` thousands, `,` decimal | `Betrag`, `.` thousands, `,` decimal |
| purpose | `Verwendungszweck` | `Verwendungszweck` | `Beschreibung` | `Movimiento`, `Más datos` | `Verwendungszweck` |
| booking text | `Buchungstext` | — | — | `Movimiento` | `Transaktions-Beschreibung` |
| counterparty | `Sender / Empfänger`, `IBAN` | — | — | — | column 4, `IBAN` |
| instructed | — | `Fremdwährung`, `Betrag#1` | — | — | — |
| currency | a currency column | a currency column | — (the account's) | — (the account's) | column 9 |
| filter | skip `Valuta = vorgemerkt` | — | — | — | — |
| placeholders | `n/a` | — | — | — | `NOTPROVIDED` |
| export date | a date-time in the preamble, by label and offset | — (the upload date) | — (the upload date) | — (the upload date) | — (the upload date) |
| balance | labelled figure `Saldo`, value below, date below, rolled back from the export date | labelled figure `Saldo:`, value six cells right, statement date by pattern from `Abrechnungsdatum:` | none | running column `Saldo` | none |
| coverage | last booking date | the statement date | last booking date | last booking date | last booking date |
| statement payment | off | on | off | off | off |
