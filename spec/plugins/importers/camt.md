# Importer: camt

Status: **written ahead, in v1.** One file importer for bank statements in
camt's terms: reports carrying an opening balance, a closing balance and their
entries (ISO 20022 camt.052 and camt.053). It has no settings. `spec.md` §5.1
owns what any importer delivers and §5.2 what ingest does with it;
`architecture.md` owns the upload operation and its dry run. This document
covers how a file becomes those records.

---

## 1. Shape

The importer is a **core** behind one or more **readers**.

- A **reader** turns one file format into the statement model (§2). It
  transcribes, and decides nothing: no sign convention, no balance dating, no
  coverage.
- The **core** turns the model into what `spec.md` §5.1 asks for: the
  per-report check, the records in ledger sign convention, the balance record,
  the coverage. It is written once, whatever the reader.

**The reader is chosen by the file, never by a setting**: each reader
recognises its format by the document's root element (§3). A file no reader
recognises fails the run as `ParseFailed`, naming what was found. So the
instance has no settings at all; the account it is linked to is the only
choice the user makes (`spec.md` §5.4). A new format is a new reader; the
model gains a field only when a reader brings one that a record needs.

The importer never reads the database or the clock: it receives the file, the
account's currency, the lookup from currency to its minor-unit exponent and
today's date, and returns the records, the reported balance and its date,
coverage, where the data starts and its counts (`architecture.md` §5.5). It
never relies on the account number in the file, as the CSV importer does not.

## 2. The statement model

Only what a record, the check or the balance needs; full ISO 20022 is not
modelled.

- **The file:** the message type it declares (`camt.052`, `camt.053`), its
  creation date (the **export date**) where it states one, and its reports in
  file order.
- **A report:** its message id, an opening and a closing booked balance, and
  its booked entries in file order.
- **A balance:** a decimal amount, its currency, a credit or debit mark, and
  its date.
- **An entry:** a decimal amount, its currency, a credit or debit mark, its
  booking and value dates, and its transaction details in order; with the
  its element serialised as read, for `raw`.
- **A transaction detail:** counterparty name, account (IBAN) and agent (BIC),
  end-to-end id, mandate id, the remittance lines, and the bank transaction
  codes as the format gives them (ISO domain–family–subfamily, the German
  GVC).
- The count of **pending** entries the file holds, which are never imported
  (`spec.md` §5.1).

Dates in the model are calendar days: converting the format's own date
representation is the reader's job (§3).

## 3. Readers

### 3.1 OLB XML

The XML export of OLB's online banking. It is not ISO 20022: it is a Java
object serialisation (XStream) of a camt report, with the library's field names
for elements. Its root element is `AccountMovementCamt`.

| Model | From |
|---|---|
| message type | `camtDescriptor` (`urn:iso:std:iso:20022:tech:xsd:camt.052.001.08`): `camt.052` or `camt.053`; any other fails the run |
| export date | the latest `groupHeader/creationDate` |
| reports | each child of `bookedCamtTransationsList`, in order |
| message id | `groupHeader/messageId` |
| balances | `report/balances/*`: `code` `OPBD` is the opening, `CLBD` the closing; `amount/value`, `amount/currencyCode`, `credDebtIndex` (`CREDIT`, `DEBIT`), `date` |
| entries | `report/entries/*`: `amount`, `credDebtIndex`, `statusCode`, `bookingDate`, `validityDate` (the value date) |
| transaction detail | `entryDetails/*/transactionDetails/*`: `foreignName`, `foreignAccount`, `foreignAgent`, `endToEndId`, `mandateId`, `remittanceInformation/string` (the lines, in order), `bankTransactionCode`, `gbiBankTransactionCode` |
| pending entries | the entries under `nonbookedCamtTransations` |

**Dates** are written as an instant in UTC — `2026-05-28 22:00:00.0 UTC` — that
is midnight in Europe/Berlin, the bank's day: the reader converts to
Europe/Berlin and takes the date, here 29 May. An instant that is not a
midnight there fails the run, since the reading would be a guess.

**An entry in a booked report whose `statusCode` is not `BOOK`** fails the run:
pending entries are the other section's.

The `outer-class` elements are the serialiser's back-references and are not
read.

### 3.2 Readers to come

ISO 20022 camt.052 and camt.053 as banks deliver them (root `Document` in the
camt namespace) are the obvious next reader, written when a real export is at
hand to test it against. It would bring the entry's `AcctSvcrRef` as
`source_id` (`spec.md` §5.2), a reversal mark, and the instructed amount,
which the model then gains. Until then such a file fails the run, saying this
format is not read yet.

## 4. Model to records

**Per report check** (`spec.md` §5.1): the opening balance plus the signed
amounts of its booked entries equals the closing balance. A report without
both balances, or whose check fails, fails the run as `ParseFailed`, naming
the report's message id and no amounts.

**Per booked entry**, in ledger sign convention (`spec.md` §5.1):

| Field | From |
|---|---|
| `amount_minor` | the decimal amount, positive for a credit and negative for a debit, times the currency's minor-unit exponent. A value that is not a whole number of minor units fails the run. Never a float. |
| `currency` | the entry's currency; ingest checks it against the account's |
| `booked_on` | the booking date |
| `value_on` | the value date |
| `counterparty_name` | the detail's name |
| `counterparty_ref` | the detail's account |
| `counterparty_bic` | the detail's agent |
| `end_to_end_id` | the detail's end-to-end id; empty and `NOTPROVIDED` (any case) mean none |
| `mandate_ref` | the detail's mandate id |
| `booking_text` | none |
| `purpose` | the remittance lines of all its details, joined with a space, whitespace runs collapsed to one space |
| `source_id` | none (the OLB reader carries no entry reference) |
| `source_format` | the message type without its dot and the reader's name: `camt052:olb` |
| `raw` | `{"report": <message id>, "entry": <the entry element, serialised as read>}` |

**Several details** on one entry (a batch booking) still make one row: the
entry is the movement of the balance. The detail columns — counterparty name, account and agent, end-to-end id, mandate id — are filled only
from an entry with exactly one detail; the bank transaction codes stay in
`raw`.

**Sign.** The format states every sign with its credit or debit mark, balances
included, so the importer has no inversion settings: a debit balance is
negative, as a debt is in the ledger (`spec.md` §3.3).

**Zero bookings** are dropped and counted: `importer_stats = {"filtered": n}`
(`spec.md` §5.1). **Pending entries** are never imported; they are counted in
the dry run only.

**Coverage** is the closing balance date of the last report — the end of the
period the file states — but never the export date or later: then it is the
day before the export date, or before `today` where the file states none
(`spec.md` §5.1). A file with no booked report has no coverage and the run
fails. **Data starts** at the earliest booking date of the records, or the
first report's opening balance date where there are none.

**Closing balance.** The figure is the closing balance of the last report, its
date that balance's date or, where the report holds entries booked after it,
the latest of those. It is dated and rolled back by the rule of `spec.md`
§5.1: to the earliest of its date, the last closed day (the day before the
export date) and the coverage, the booked entries after that date subtracted.
A closing balance whose currency differs from the account's fails the run.

**Same rows as the CSV.** A bank that offers both exports of an account, as
OLB does, renders the hashed fields alike — amount, booking date, counterparty
IBAN, purpose; spacing and line breaks do not move the hash (`spec.md` §5.2) —
so a switch between them, or an overlap, deduplicates by identity.

## 5. Reading XML safely

The file is untrusted input. It is parsed with the standard library, and a
document carrying a `DOCTYPE` is refused before parsing: no camt export has
one, and refusing it rules out entity expansion. A file that is not well-formed
XML fails the run as `ParseFailed`.

## 6. Dry run

The dry run of an upload is the CSV importer's (`architecture.md` §4.1), with
what applies to a statement format: the reader used and the message type; the
counts of entries read, emitted, dropped as zero bookings and pending; the
first rows as parsed; the export date and coverage and where each came from;
the balance record that would be written, with the report it came from and the
roll-back applied. A failure the run would end in takes their place, as for
the CSV importer.

## 7. Tests and fixtures

Each reader is tested against hand-built files with invented data, the cases
that went wrong included; the core against the model directly, a reader
not involved. Real exports carry names and account numbers and are never
committed.
