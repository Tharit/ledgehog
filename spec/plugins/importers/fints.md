# Importer: fints

Status: **written ahead, in v1.** The FinTS 3.0 PIN/TAN importer for German banks,
over python-fints (`architecture.md` §2). `spec.md` §5.1 owns what any importer
delivers and §5.2 what ingest does with it; `architecture.md` §5.5 owns the
fetch-importer protocol, the prompt kinds and the error taxonomy. This document
covers what is particular to FinTS: its settings and state, how accounts are
discovered, how a statement becomes records, and how the bank's answers become
the taxonomy. Credit cards are fetched with their own request (HKKKU, §6a); a
card a bank does not offer that way still comes in by CSV (`csv.md`).

---

## 1. Settings, state and registration

**Settings** hold only what the user types (`spec.md` §5.4):

| Setting | Notes |
|---|---|
| `url` | The bank's FinTS address. `https` only, a host, no credentials in it. A plain `http` address is refused: the PIN would cross the wire in the clear. |
| `bank_code` | The bank's Bankleitzahl, eight digits. |
| `user_id` | The login name the bank gave (its "VR-NetKey", "Anmeldename", "Legitimations-ID", whatever it calls it). |
| `customer_id` | Optional. Only where the bank has a customer id separate from the login name; empty means the same as `user_id`. |

Unknown keys are refused, naming the key (`InvalidProfile`). The PIN is not a
setting and is never stored (`spec.md` §7): it is asked for at every sync, as a
`secret` prompt with subject `pin`, before anything touches the network.

**The DK product registration id** (`spec.md` §7.1) is not a setting of the
instance: it belongs to the deployment (`FINTS_PRODUCT_ID`,
`architecture.md` §5.7) and reaches the importer when it is constructed. Without
it, `open` raises `NotRegistered` before any prompt or request.

**State** (`importer_instance.state`) holds exactly these scalars, all non-secret
(`spec.md` §7), all written as they are learned:

| Key | Holds | Why it is kept |
|---|---|---|
| `system_id` | the id the bank assigned this installation | some banks demand a stable one to avoid a TAN at every login |
| `tan_mechanism` | the chosen TAN procedure's code, e.g. `900` | so the user is not asked again |
| `tan_medium` | the chosen device's name | likewise, where the bank wants one |
| `tan_for` | the request types that need a TAN request attached, e.g. `["HKKAZ"]` | learned (§4): later runs go straight to the form that works |

Nothing else is stored. In particular **no bank parameter data (BPD), no user
parameter data (UPD) and no `deconstruct()` blob**: that blob is a pickle, which
must never be loaded from a database row, and re-reading BPD and UPD costs one
dialog the sync already makes. "Reset" clears the state and returns the
instance to asking.

## 2. Dialogs and the session

A session holds the PIN (a `SecretText`, revealed only to build the client),
the state and the prompter. It holds **no open dialog**: every data call
(discovery's account list, each account's statements) runs in its own dialog,
because a rejected request makes the bank close the dialog and a bank may demand
a challenge per call. One dialog is: log in (the PIN, possibly a login TAN,
§5), send one request (possibly with its TAN), end. A sync of two accounts is
therefore two logins, and the user may meet a challenge at each; the bank's own
exemption window usually makes later ones come back without one.

Every `ask` made on the bank's behalf is a prompt of `architecture.md` §5.5:

| When | Prompt |
|---|---|
| before the first request | `secret`, subject `pin` |
| the bank allows several TAN procedures and none is remembered | `choice`, subject `tan_mechanism`, options by the bank's code and name; with exactly one allowed procedure (the one-step procedure `999` apart) it is taken without asking. The bank's list is authoritative: where it lists no procedure, the instance ends with `BankSetupRequired` — a procedure must be activated with the bank first |
| the procedure needs a medium (device) and none is remembered | `choice`, subject `tan_medium`, from the bank's list, asked for in a login without a TAN request (a bank refuses the list in one that carries one); where the bank gives none, `text`, subject `tan_medium_name`. The chosen name goes with every TAN request |
| a challenge the user types | `tan`, medium `text`, the bank's challenge text and the procedure's name |
| a photoTAN or QR challenge | `tan`, medium `image`, with the image |
| a decoupled challenge (a push to an app) | `tan`, medium `decoupled`; `poll` asks the bank "confirmed yet?" |

A chosen mechanism or medium is written to `state` when chosen, so a login that
fails afterwards does not ask again. A remembered mechanism the bank no longer
lists is dropped and asked afresh. A challenge the library cannot present (a
chipTAN flicker code without text) is not supported and ends the instance with
`BankSetupRequired` naming the procedure: pick another one with the bank.

## 3. Discovery

Discovery runs one dialog and reads the bank's account list (the UPD) from the
login. It does not call HKSPA: the UPD carries the IBAN. Per UPD row:

- A row without an account number is a placeholder and is skipped.
- `external_ref`: the IBAN where there is one (upper case, no spaces), else the
  account number, followed by `/` and the sub-account number where there is one.
- `name`: the bank's product name for the account, else its account number.
- `currency`: the UPD's account currency; none where it states none.
- `kind_hint`: by the UPD's account type — 1 to 9 `checking`, 10 to 19
  `savings`, 30 to 39 `depot`, 50 to 59 `card`, everything else none (a hint
  only prefills the add dialog).
- `capabilities`: `transactions` and `balance` both, when the UPD allows the
  MT940 statement request (HKKAZ) or the card transaction request (HKKKU),
  read from the UPD's own list of allowed operations; empty otherwise. A depot
  (securities only) and an account the bank offers only as camt (HKCAZ) are
  therefore listed as "nothing to fetch". The balance is part of the statements
  (§6) and of the card answer (§6a), so it has no capability of its own. A
  card's `external_ref` is its card number and sub-account, by the rule above.

Fetching an account that the UPD at that moment does not list, or lists without
HKKAZ or HKKKU, fails the run as `AccountUnsupported` before any request is made.

## 4. Fetching statements

`fetch_account` asks for the MT940 statements of the account from `since` to
the day before `today` (a `since` later than that is lifted to it, so the
request is never empty-ranged). Only booked items are requested. One dialog.

**The TAN request per data call is learned per bank.** The bank's own
parameters may say a request needs no TAN and the bank may demand one anyway
(`9075`, strong authentication required, which closes the dialog). The
importer therefore starts from `state["tan_for"]`:

1. the request goes out with a TAN request attached if its type is in `tan_for`,
   plain otherwise;
2. a plain request answered `9075` is repeated once in a fresh dialog with the
   TAN request attached; where that succeeds, the type is added to `tan_for` and
   the state is persisted, so later runs start there;
3. a `9075` that remains after the attached form is not retried: it is read as
   in §7.

An attached TAN request may be answered with a challenge (`0030`, `3955`), which
is a prompt (§2), or without one (`3076`, no strong authentication required),
which is success.

**Never read an empty result as success without the return codes.** The
library can return no transactions where the bank in fact refused. A result is
accepted only when the dialog's return codes contain no error (§7); `3010`
("no entries") is an empty success only on the data request itself.

**Coverage** is the day before `today`, whether or not rows came back
(`spec.md` §5.1); the data starts at the requested `since`.

## 5. Login challenges

The bank may demand a TAN at login, and the library does not always notice
(the bank attaches `0030` to the identification segment rather than to the TAN
segment). The importer treats a login that carries a TAN challenge (a `HITAN`
with `0030` or `3955`) as a challenge to prompt for, whichever segment the code
came with. Login strong authentication is intermittent: the next login may
say `3076` and need none.

## 6. Statements to records

The importer reads the raw MT940 text of the statements, splits it into
statements (at each `:20:`), and parses each with the `mt-940` library. The
free text of every booking (field `86`) it reads itself (below), because the
library's reading of it varies with the bank's layout.

**Per statement check** (`spec.md` §5.1): the opening balance (`60F` or `60M`)
plus the signed amounts of its lines equals the closing balance (`62F` or
`62M`). A mismatch fails the run as `ParseFailed`, naming the statement's
reference and dates and no amounts; a CSV export of the period is the fallback.

**Per booking**, in ledger sign convention (`spec.md` §5.1):

| Field | From |
|---|---|
| `amount_minor` | the booking's decimal amount, signed by the credit or debit mark (a reversal mark flips as the format defines), times the currency's minor-unit exponent. A value that is not a whole number of minor units fails the run as `ParseFailed`. Never a float. |
| `currency` | the booking's currency; ingest checks it against the account's |
| `booked_on` | the **entry date** (MMDD in `:61:`, its year resolved against the value date), else the value date. The library's field `date` is the *value* date. |
| `value_on` | the value date |
| `counterparty_ref` | an IBAN, taken in order from the field's own IBAN subfield (`?31`), a leading IBAN glued to the name, an `IBAN+` tag; only a candidate that passes the mod-97 check and the length of its country counts |
| `counterparty_bic` | `?30` where it is a BIC, `BIC+`, else none |
| `counterparty_name` | the name subfields (`?32`, `?33`), joined, minus a leading IBAN taken above, whitespace collapsed |
| `end_to_end_id` | `EREF+`, whitespace stripped; empty and `NOTPROVIDED` (any case) mean none |
| `mandate_ref` | `MREF+`; a bank that does not send it leaves it none |
| `booking_text` | the posting text (`?00`) |
| `purpose` | see below |
| `source_id` | **always none**: the statement reference and the library's ids are not stable (`spec.md` §5.2 then identifies by content) |
| instructed amount, currency | none (MT940 does not carry them) |
| `source_format` | `mt940` |
| `raw` | `{"statement": <the statement's `:20:` reference>, "field86": <the unparsed text>, "line61": <the library's parsed fields, as strings>}` |

**Purpose.** The purpose subfields (`?20` to `?29`, with `?60` to `?63`) carry
the SEPA identifiers of the Deutsche Kreditwirtschaft — `EREF+`, `KREF+`,
`MREF+`, `CRED+`, `DEBT+`, `SVWZ+`, `ABWA+`, `ABWE+`, `BREF+`, `IBAN+`, `BIC+`
and the others of its list — each opening a subfield. **An identifier is
recognised only at the start of a subfield, and only from that list.** The
format has no escaping, so text a payer typed — "SVWZ+" inside a purpose — is
told apart only by its position: anywhere else it is ordinary text. The
subfields are joined without a separator (the convention: a line ends where the
format's width does, mid-word included), and each identifier's text runs to the
next identifier. The `SVWZ+` text and text under no identifier are the purpose;
an identifier with a column goes there; one without (`KREF`, `CRED`, `DEBT`,
`ABWA` and the rest) is not in the purpose and stays in `raw`. Whitespace runs
collapse to one space. A bank's own selection varies: all are read by the same
rule, and none is required.

**Zero bookings** are dropped and counted: `importer_stats = {"filtered": n}`
(`spec.md` §5.1).

**Closing balance.** Reported only from the statements, never from the bank's
balance request: its figure is the balance now, which may include pending items,
so the run would report none by the rule of `spec.md` §5.1, and the request costs
one more dialog and TAN. The figure is the closing balance of the last *final* statement (`62F`, not
`62M`) in the delivery, whatever its date: a statement that runs into `today`
is rolled back by the dating rule below, which subtracts the bookings after the
last closed day. Its date and the dating rule (earliest of the figure's date, the last
closed day and the coverage; later forward-dated lines subtracted) are those of
`spec.md` §5.1. **No final statement in the delivery means no balance**:
a quiet account whose bank issues no statement for an empty range reconciles
against balances entered by hand (`spec.md` §5.10).

## 6a. Credit cards

A card the UPD lists with the card transaction request (HKKKU) is fetched with
it instead of the MT940 statements: one dialog, the card's transactions from
`since` to the day before `today`, with a TAN request attached by the rule of §4
(a bank may mark HKKKU as needing one, and `tan_for` learns it). The request
carries the card's full account connection — card number, sub-account, country
and bank code — which a bank requires although its parameters may read
otherwise. python-fints has no card support: the request and its answer are the
importer's own segments over the library's.

**The answer** holds the card's current balance with its date and one entry
per booking. An entry the bank marks as not yet billed is the card's pending
item: it can change or disappear and carries no reference, so it is not
imported (`spec.md` §5.1). Per billed entry, in ledger sign convention:

| Field | From |
|---|---|
| `amount_minor` | the booked amount, signed by its credit or debit mark |
| `currency` | the booked currency |
| `booked_on` | the booking date |
| `value_on` | the value date |
| `counterparty_name` | the merchant name |
| `purpose` | the description lines, joined by a space |
| instructed amount, currency | the original amount and currency, where the currency differs from the booked one |
| `source_id` | **always none**: an entry has no stable id |
| `source_format` | `hkkku` |
| `raw` | the entry's fields as received |

**Coverage** is the day before `today`, or, where unbilled entries were
delivered, the day before the earliest of their booking dates: an item billed
later keeps its booking date, and the next fetch, which starts from the
coverage, must reach it.

**Closing balance.** The current balance includes the unbilled entries; minus
them it is the booked balance at its date. That figure is dated and rolled back
as the statements' figure is (§6), by the rule of `spec.md` §5.1: to the
earliest of its date, the last closed day and the coverage, the billed entries
after that date subtracted.

The card number is never logged and appears in no error message (§8).

## 7. The bank's answers

Every dialog records the return codes and texts of the bank's answers (the
library's response callback). **After** each request the codes decide, and the
library's own exceptions never do, because they hide the bank's text. The
message of an error carries a code and the bank's text, never the dialog's
data, an account number or anything the user typed (`architecture.md` §5.5).

| Codes (source) | Meaning | Becomes |
|---|---|---|
| `0020`, `0010`, `3060`, `3050`, `3920`, `3076` | accepted, warnings, lists, "no strong authentication needed" | not an error |
| `0030`, `3955` | a challenge is pending | a prompt (§2) |
| `3956` (library) | a decoupled challenge is not confirmed yet | `poll` returns false |
| `3010` | no entries | an empty result of a data request; elsewhere not an error |
| `9075` | strong authentication required; the bank closed the dialog | the retry of §4, then below |
| `9931`, `9942`, `9040` (spike 17) | login name or PIN wrong | `AuthRejected`, at once, no retry |
| `9930` | login locked | `BankSetupRequired`: unlock it with the bank |
| `9940` (spike 22), `9960` (spike 20, 21) | no active TAN device or procedure | `BankSetupRequired` |
| `9210` | TAN medium name required or not accepted | asked once as `text` (§2); again refused: `BankSetupRequired` |
| `9110`, `9120`, `9160` (spike 2) | the bank cannot read our message | `ParseFailed` |
| `9010` and any other `9xxx` not above | the bank refused the request | `SourceUnavailable` with the code and text |
| a `9075` left after the attached TAN request | the bank wants more than we can give | `BankSetupRequired` if `9940` came with it, else `SourceUnavailable` |
| connection error, timeout, TLS error, a non-200 answer | the bank is not reachable | `SourceUnavailable` |
| an answer that does not parse | | `ParseFailed` |

A rejected PIN is never retried by the importer: banks lock a login after a few
failures (`architecture.md` §5.5).

## 8. What is logged

The importer logs the bank's return codes and texts, per dialog step, and
nothing else of the exchange: no segment, no statement, no account number, no
setting, no PIN or TAN. The debug logs of python-fints and of mt-940 carry data
segments and booking lines, so both are kept at level warning and are switched
on only by hand for a capture (§9).

## 9. Fetch start, tests, fixtures

The importer's **default fetch start** is ninety days before `today`: the bank's
history that needs no strong authentication (PSD2); asking for older
bookings can itself demand a TAN. The user may change it for an account
without coverage (`spec.md` §5.4).

Tests run against synthetic payloads, never a live bank (`architecture.md`
§8). The importer reaches the bank through one narrow internal seam — log in,
list accounts, fetch an account's statements with or without a TAN request —
which the patched library implements; the importer's own logic (§2 to §7) is
tested against a fake of that seam, and the statements against a hand-built
corpus of MT940 text with invented data, the cases that went wrong included;
the card answers likewise against hand-built ones.
Each fix to the library the importer carries has its own test, beside it, so
that the fix and its test are deleted together when the library makes the test
pass without it. A capture of a real session never becomes a fixture as it is;
what it shows becomes a hand-built case.
