# Importer: email

Status: **written ahead, in v1.** Reads receipts and order confirmations from
one IMAP mailbox to which the household forwards them, and delivers each as a
document (`spec.md` §5.5), extracted by the deployment's model. `spec.md` §5.1
and §5.5 own what a document importer delivers, §5.8 what is done with it, §7
the credential policy; `architecture.md` §5.4 owns the model's protocol and
§5.5 the fetch-importer protocol, the prompt kinds and the error taxonomy. This
document covers what is particular to email: the settings and state, which
messages are read, who may send them, how a message becomes a document, and
what fails.

---

## 1. Settings, state and registration

**Settings** hold only what the user types (`spec.md` §5.4):

| Setting | Notes |
|---|---|
| `host` | The IMAP server's host name. A host only: no scheme, no port, no credentials. |
| `security` | `tls` (implicit TLS, IMAPS) or `starttls`. There is no unencrypted option: the password would cross the wire in the clear. The certificate is verified against the system's trust store, host name included; there is no option to accept an unverified one. |
| `port` | Optional, 1 to 65535. Empty means 993 for `tls`, 143 for `starttls`. |
| `username` | The login name at the server. |
| `mailbox` | Optional; empty means `INBOX`. The folder read, by its full name; a name outside ASCII is sent in IMAP's modified UTF-7. |
| `senders` | The addresses whose mail is accepted (§3), at least one. Each is one address (`local@domain`), stored trimmed and lower-cased; duplicates are refused. A listed address stands for its plus addresses too (§3). |
| `start_date` | The instance's start date (`spec.md` §5.5), required. |

Unknown keys are refused, naming the key (`InvalidProfile`), and so is a
setting that breaks its rule above. The password is not a setting and is never
stored (`spec.md` §7): a mailbox password is not verifiably read-only — it
reaches every account the mailbox can reset. It is asked for at every sync, as
a `secret` prompt with subject `password`, before anything touches the network.
Providers that require OAuth for IMAP (Microsoft's, at the time of writing)
cannot be used; one that issues app passwords (Gmail, iCloud) is used with one.

**Registration.** The importer reads documents with the deployment's model
(§5): it is registered only where the model is configured
(`architecture.md` §5.7). Without one it is not offered, and an existing
instance is the instance of an importer that is not registered: it delivers
nothing. The vision model is optional (§5).

**State** (`importer_instance.state`) holds exactly these keys, none secret
(`spec.md` §7):

| Key | Holds |
|---|---|
| `position_for` | a fingerprint (the first 16 hex digits of a SHA-256) of `host`, `port`, `username`, `mailbox` and `start_date` as the position below was built for |
| `uidvalidity` | the mailbox's UIDVALIDITY at the last successful run |
| `last_uid` | the highest UID a successful run handled |
| `fetched_on` | the fetch day of the last successful run |
| `seen` | `{fingerprint of a Message-ID: fetch day}`: every Message-ID a successful run handled (§2), kept for 14 days after that day and then pruned |
| `stuck` | `{uid, uidvalidity, attempts}`: the message at which runs failed in a row on the model (§8), absent otherwise |

All but `stuck` are the delivery's **position** (`architecture.md` §5.5): the
importer returns them with its documents, and they are kept only once the run's
documents are written. `stuck` is written as it is learned, so it survives the
failed run that learned it. A `position_for` that differs from the settings now
— another server, login, folder or start date — discards the position, `seen`
included, and the mailbox is read as on a first run. "Reset" clears the state:
the mailbox is read again from the start date, and documents already imported
are kept as they are (§6).

## 2. Which messages are read

The mailbox is opened **read-only** (`EXAMINE`) and every message is fetched
with `BODY.PEEK[]`: nothing is marked seen, moved, flagged or deleted.

**The candidates** of a run are the union of:

- **after the position**: the UIDs above `last_uid`, where the mailbox's
  UIDVALIDITY equals the stored one (`UID SEARCH UID <last_uid+1>:*`, which
  answers the highest UID even when it is lower, so the answer is filtered);
- **the overlap**: the messages that arrived since the day before `fetched_on`
  (`UID SEARCH SINCE`), which catches a message a server made visible late;
- **on a first run**, without a position or with a changed UIDVALIDITY: the
  messages that arrived since the day before the start date, or, where a
  position exists with another UIDVALIDITY, since the day before `fetched_on`.

They are handled in ascending UID order. A message whose own Message-ID is in
`seen` is skipped once its headers are read, its body never fetched, and
an inner message (§3) whose Message-ID is in `seen` is skipped before the model
is asked; both count as `already_seen`. Every message and inner message that a
run handles — whatever its outcome — goes into `seen`. A message without a
Message-ID is identified by the SHA-256 of its raw bytes, for `seen` and for
§6. A message larger than 25 MiB (`RFC822.SIZE`) is not fetched:
`too_large`.

**The position** after a successful run is the highest UID handled, the
mailbox's UIDVALIDITY, the fetch day and `seen`, pruned. A run that fails, or
whose delivery is discarded, leaves the position where it was, so the same
messages are read again: documents are keyed (§6) and re-delivering one changes
nothing.

## 3. Who may send

The household forwards receipts to the dedicated inbox in two ways, and both
are accepted:

- **an automatic forward** keeps the shop's `From` and names the forwarder in
  a header its provider adds;
- **a forward by hand** comes `From` the forwarder, with the original attached
  (`message/rfc822`) or quoted inline.

**A message is read when it names an address in `senders` and its sender is
authenticated.** Addresses are compared without regard to case, and **a listed
address stands for its plus addresses**: an address matches a listed one when
it is that address, or when its local part up to the first `+`, with its
domain, is that address — `martin+amazon@proton.me` is read for a listed
`martin@proton.me`. The tag is the mailbox owner's own, handed out per shop,
and the domain authentication rests on is unchanged. A listed address that
itself carries a `+` matches only itself, and only `+` separates a tag: a
provider that uses another separator is listed by whole address. The addresses
read are:

| Header | Set by | Read as |
|---|---|---|
| `From` | everyone; the forwarder on a forward by hand | the parsed address, never a display name |
| `Resent-From`, `Resent-Sender` | RFC 5322 resending (Outlook.com and others) | the parsed addresses |
| `X-Forwarded-For` | Gmail's automatic forwarding (`forwarder destination`) | every address in it |
| `X-MS-Exchange-Inbox-Rules-Loop` | Exchange and Microsoft 365 redirect rules | every address in it |
| `Delivered-To`, `X-Original-To` | the receiving server at each hop, so the forwarder's mailbox on an automatic forward where its provider adds nothing else | every address in it, every occurrence |

All but `From` are the **forwarding headers**. A message none of whose
addresses is in `senders` is skipped as `not_accepted`.

**Authentication is the inbox provider's verdict.** Every one of these headers
can be written by whoever sends the message, and a forged message would book a
purchase on a clearance account (`spec.md` §5.8). The provider hosting the
dedicated inbox checks DKIM, SPF, DMARC and ARC at delivery and records the
result in an `Authentication-Results` header (RFC 8601). The importer reads
the **topmost** one only — the last added, by the inbox's own provider; one
further down may have been written by anyone — and no setting names the
server that wrote it. A message that names a listed address is accepted when,
by that header:

- **a forward by hand**: its `From` is in `senders` and the header shows
  `dmarc=pass` for its domain, or `dkim=pass` whose `header.d` is the `From`
  address's domain or a domain it lies under — the same evidence a DMARC pass
  rests on, for a provider that records no DMARC result; the sender's provider
  vouched for that address; or
- **an automatic forward**: its `From`, the shop's, has a DKIM pass for its
  domain (`dkim=pass` whose `header.d` is the `From` address's domain or a
  domain it lies under), or the header records an ARC pass (`arc=pass`) from
  the forwarder; **and** a forwarding header names an address in `senders`.

Otherwise it is skipped as `not_authenticated`, before the model is asked; a
message without an `Authentication-Results` header is not authenticated. The
importer does not verify signatures itself: it reads a mail days or weeks
after delivery, when a signing key may have been rotated or revoked, and that
would fail genuine mail, need DNS lookups at fetch time and a dependency.

**What remains possible** is a genuine receipt of someone else's purchase,
forwarded automatically into the dedicated inbox with a forged forwarding
header naming a listed address, which needs the inbox's address. It adds a
document and, where a clearance account takes its provider, a purchase booked
there that no charge offsets: the account's balance shows it, and an entry by
hand offsets it. A forward by hand cannot be forged this way: its `From` must
be a listed address with a DMARC pass or an aligned DKIM pass. Mapping sender domains to providers, planned, narrows
which shops can be booked at all. Beyond the plus tag, matching is by exact
address: a provider's alias or dotted variant is a separate entry in `senders`.

**The inner message.** Of an accepted message, every part of type
`message/rfc822` at its first level is an inner message, handled on its own (a
forward of several receipts at once delivers each). A message with no such part
is its own inner message: an automatic forward, or a forward quoted inline. The
sender check is never applied to an inner message — its `From` is the shop.

## 4. Reading an inner message

**Its date** is the calendar date of its `Date` header, in that header's own
offset, never converted; without a parseable `Date`, the outer message's, then
the server's arrival date (`INTERNALDATE`). A forward quoted inline therefore
carries the date it was forwarded. An inner message dated before `since` (the
instance's start date) is skipped before the model is asked: `before_start`.

**Its identity** is its Message-ID, angle brackets and surrounding whitespace
removed (§2 for a message without one).

**Its text** is its HTML body, else its plain-text body. HTML becomes plain
text by the importer's own converter, which drops presentation and never
interprets: `<head>`, `<script>`, `<style>` and comments are dropped; a table
cell becomes a tab, a row or a block element a line, a list item a line with
`- `; an image is its `[alt]` text where it has one; other tags are dropped;
entities are decoded; whitespace runs collapse and empty cells and blank lines
go. **Superscript is marked `^` and subscript `_`** (`43<sup>55</sup><sup>€</sup>`
becomes `43^55^€`), so a price whose cents are only markup keeps the cue. A
text longer than 40,000 characters is not sent: `too_large`.

**Its PDFs** are its parts of type `application/pdf`, or
`application/octet-stream` with a name ending `.pdf`, attachments and inline
parts alike, at most the first three. A PDF is read as images of its first four
pages: rendered with pypdfium2 in grayscale at 150 DPI, scaled down so that the
longest side is at most 2,000 px, as PNG. A PDF that does not render is passed
over (logged).

## 5. Extraction

**The models.** The text is read by the deployment's model (`MODEL_*`), page
images by the vision model (`VISION_MODEL_*`, `architecture.md` §5.7), both
over the chat-completions protocol of `architecture.md` §5.4: `temperature` 0,
no streaming, the reasoning effort the configuration names for the text model
and none for the vision model.

**One document per inner message at most, text first.** The text is asked
first. Where it yields no document (§6), each PDF is asked in turn, if the
vision model is configured, until one yields a document. Without the vision
model a PDF is never read, and an inner message that yields nothing while it
has one counts as `pdf_not_read`; one with neither text nor PDF is
`no_content`.

**The model extracts and never classifies.** It is asked for the purchase or
payment data of whatever it is given — an order confirmation, an invoice, a
rental agreement — and for null where there is none. The caller decides what
the answer is (§6). The answer is one object:

| Field | Type | Meaning given to the model |
|---|---|---|
| `merchant` | string or null | the seller, as the source names it |
| `order_id` | string or null | the order, invoice or booking number |
| `total` | number or null | the amount the customer pays in total — shipping, fees and taxes included — positive, dot as decimal separator |
| `currency` | string or null | the total's ISO 4217 code |
| `refund` | boolean | true where the amount is returned to the customer or no longer charged: a refund, a credit note, a cancellation |
| `items` | array or null | every line that makes up the total, so that their amounts add up to it: each article, shipping, fees, taxes added on top, discounts and vouchers as negative amounts |
| `items[].name` | string | the line's description |
| `items[].quantity` | number or null | the line's quantity, as shown |
| `items[].amount` | number or null | the line's amount: the line's total, not the unit price |

The text request carries the system instruction (what is extracted, the
fields above, that superscript is marked `^` and subscript `_`, that table
cells are tab-separated, "never invent values") and the text, and asks for
**structured output**: a strict `json_schema` of exactly this object, with
`max_tokens` 8,192 (room for a reasoning model's thinking). The vision request
carries the same instruction, the keys and types spelled out, "answer with the
JSON object only, no code fences", and the page images as data URLs, **without
a schema** — constrained decoding made a vision model loop until its context was
full (spike finding 7) — and with `max_tokens` 2,048, so a loop fails fast. A
reply is parsed tolerantly — a surrounding code fence is removed, else the text
from the first `{` to the last `}` is read — and validated in code against the
object above, whichever path it came from. A reply cut off at `max_tokens`, not
JSON, not an object or not of that shape is no answer: `unreadable`. A reply is
never retried: at temperature 0 the same input gives the same answer.

Timeouts: 10 s to connect, 120 s for a text reply, 300 s for a vision reply.

## 6. From extraction to a document

**A complete document only** (`spec.md` §5.5). The answer is checked in this
order, and the first check that fails skips the inner message under its count:

1. `refund` is true: `refund`. Refunds, credit notes and cancellations are not
   delivered in this version.
2. The currency, trimmed and upper-cased, is three letters A–Z and the
   currency lookup knows it: else `unknown_currency` (a missing currency is
   `incomplete`).
3. **The lines account for the total**: `incomplete` unless `total` is a
   number of at least 0, `items` holds at least one line of non-zero amount,
   every line has a non-empty name and a number for its amount, the total and
   every amount are whole minor units of the currency (the decimal as
   written, never a float), and the total differs from the lines' sum by no
   more than the sum of the lines' magnitudes. The lines carry their amounts
   as given, unless those do not sum to the total and each amount times its
   quantity (none taken as 1), each still a whole number of minor units, does;
   the lines then carry those products. What the lines leave of the total — a
   discount the mail does not itemise, shipping, fees or tax it leaves out — is
   delivered as it is: no line is added for it, and booking spreads it over
   the lines (`spec.md` §5.8). The check guards against misreads only: a
   negative total is a misread refund; a mail that states a total without its
   lines, or a shipping notice with one item of a large order, would spread
   the whole total over too little and categorise it wrongly.
4. The merchant gives a provider (below): else `no_merchant`.

**The document**, in ledger sign convention (`spec.md` §5.1):

| Field | From |
|---|---|
| `provider` | the merchant, canonicalised (below) |
| `source_id` | the `order_id`, trimmed and whitespace collapsed, where it has one; else `message:` and the inner message's identity (§4) |
| `reference` | the `order_id`, trimmed and whitespace collapsed, where the mail names one; else none |
| `occurred_on` | the order's date: the inner message's date (§4). Under `keep` (below) a document is the first complete mail of its order, its confirmation, sent when the order was placed |
| `total_minor` | minus the total, in minor units: a charge is negative; a purchase paid entirely with a voucher has 0, and is delivered, though not booked (`spec.md` §5.8) |
| `currency` | the checked currency |
| `merchant_name` | the merchant as the model gave it, trimmed, whitespace collapsed, at most 200 characters |
| `title` | the inner message's subject, its reply and forwarding markers removed (below), at most 200 characters |
| lines | one per item, in the order given: `description` its name, `amount_minor` minus its amount (a discount becomes a positive line, which stays an entry of its own, `spec.md` §5.8), `qty` its quantity where that is a whole number from 1, else none. A line of amount zero is dropped. |
| `raw` | `{"message_id", "outer_message_id", "uid", "uidvalidity", "date", "source": "text" or "pdf", "pdf": <its file name>, "extraction": <the validated answer as returned>, "model": <the model's name>}`. The message itself stays in the mailbox and is not copied. |

**The subject's markers.** A forward by hand quoted inline is its own inner
message (§3), so its subject carries what the forwarding client put in front
of it. A leading `Re`, `Fw`, `Fwd`, `Aw` or `Wg`, followed by a colon and
optionally by a counter in brackets or parentheses (`Re[2]:`), is removed with
the whitespace around it, repeatedly and without regard to case, until the
subject starts with something else; what remains is the subject as the sender
wrote it. A subject that is nothing but markers is no title.

**The provider** is inferred from the merchant alone, deterministically: NFKC;
whitespace trimmed and collapsed; a name that is a bare domain
(`www.zalando.de`, `amazon.co.uk`) becomes its registrable label — a leading
`www.` and the last label dropped, and a second-level `co`, `com`, `org`, `net`,
`ac`, `gov` or `ne` before a two-letter country label with it, then the last
label left (`zalando`, `amazon`); then trailing legal forms are removed,
repeatedly, each as a whole word with its punctuation, without regard to case:
`GmbH & Co. KGaA`, `GmbH & Co. KG`, `GmbH`, `gGmbH`, `UG (haftungsbeschränkt)`,
`UG`, `AG`, `KGaA`, `KG`, `OHG`, `GbR`, `e.K.`, `e.V.`, `SE`, `Ltd`,
`Limited`, `PLC`, `LLP`, `LLC`, `Inc`, `Corp`, `Corporation`, `Co`, `S.A.`,
`SA`, `S.à r.l.`, `S.a.r.l.`, `SARL`, `SAS`, `S.L.`, `SL`, `S.p.A.`, `S.r.l.`,
`B.V.`, `BV`, `N.V.`, `NV`, `AB`, `AS`, `A/S`, `ApS`, `Oy`, `Sp. z o.o.`; and
trailing commas, dots and hyphens. The case is kept as given: a clearance
account's providers match without regard to case (`spec.md` §3.3). Empty after this is no provider. At
most 100 characters. `Amazon EU S.à r.l.` becomes `Amazon EU`, not `Amazon`:
there is no list of merchants, and a clearance account lists whichever
providers it takes (`spec.md` §3.3). Mapping sender domains to providers in
the settings, so that no misread decides a provider, is planned.

**The importer declares the re-delivery mode `keep`** (`spec.md` §5.5): a
later mail about an order — a shipping notice, an invoice, a cancellation —
is a partial or derived view, never the same document read again, so the
first complete mail of an order wins. **Within one delivery** the key
`(provider, source_id)` is unique (`spec.md` §5.1): where two inner
messages give the same key, the earlier — by UID, then by order within the
message — is delivered and the later counts as `same_order`. Across runs, a
document already stored is kept as it is, and ingest counts the re-delivery
as kept.

## 7. What the instance answers and covers

**Coverage**, recorded with the run (`spec.md` §5.1), is the day before the
fetch, less one day for forwarding: today minus two days, whether or not any
message came. A run's documents are dated as their messages were sent (§4),
and an automatic forward arrives within minutes, so by then every receipt of
those days is in the mailbox. Nothing waits on it: a receipt forwarded by hand
later is imported when it arrives and booked like any other. Where the data
starts is the start date, or the coverage where that is earlier.

**Default fetch start.** The start date is a required setting, so the default
is never used; it is the start date.

## 8. Failures

| What | Becomes |
|---|---|
| the server cannot be reached, the TLS handshake or certificate check fails, a time-out (30 s per IMAP command), the connection drops | `SourceUnavailable`: the run fails, the position stays |
| `starttls` chosen and the server offers no STARTTLS | `InvalidProfile` naming `security` |
| the login is refused | `AuthRejected`, at once; never retried (a provider may lock the login) |
| the mailbox does not exist | `InvalidProfile` naming `mailbox` |
| the model cannot be reached (connection refused, name not resolved, TLS), or answers 401, 403, 404 or 429 | `SourceUnavailable` ("the model could not be reached" or "the model refused the request: HTTP 401"): the run fails, the position stays |
| a request for one message was sent and failed: a reply time-out, the connection dropped, HTTP 5xx | `SourceUnavailable`, and `stuck` counts the attempt for that message; the third run in a row that fails at the same message skips it instead, as `gave_up`, and goes on |
| the model refuses one request: HTTP 400, 413 or 422 (an input too long for it, say) | that inner message is skipped: `model_refused` |
| an unusable reply | that inner message is skipped: `unreadable` (§5) |

A failure of the run writes nothing (`spec.md` §5.1). **Nothing is skipped
silently**: every message and inner message a successful run handles is counted
once, under the outcome of its last attempt, in the run's statistics
(`importer_stats`, `architecture.md` §5.5): `documents`, `same_order`,
`not_accepted`, `not_authenticated`, `already_seen`, `before_start`, `too_large`, `no_content`,
`pdf_not_read`, `unreadable`, `model_refused`, `gave_up`, `refund`,
`unknown_currency`, `incomplete`, `no_merchant`. `incomplete` is every failure
of §6's checks 2 and 3 but an unknown currency: no currency, no total or a
negative one, no line of non-zero amount, a line without name or amount, an
amount in fractions of a minor unit, or lines that account for too little of
the total. A skipped message is read again only after a Reset.

An error's message names the rule and may carry the server's or the model's
status code; never a setting, an address, a subject, any of a message or any of
a reply.

## 9. Personal data and logging

**The whole message goes to the model**: the text of the receipt and its PDF
pages — the household's names, postal and email addresses, phone numbers and
what was bought, and the same of third parties (a gift's recipient, a shared
order). This is not pass 3's restricted payload (`spec.md` §5.9); a hosted
endpoint receives all of it. It is stated next to both endpoint settings in
the configuration documentation and under the importer's form.

The importer logs per message its UID and its outcome, per run the counts,
and nothing else: no address, subject, body, attachment, model input or reply.
There is no dump of model input.

## 10. Tests, fixtures

Tests run against hand-built messages with invented data, never a live mailbox
or model (`architecture.md` §8). The importer reaches the server through one
narrow seam — connect, log in, open a mailbox read-only (its UIDVALIDITY),
search by UID and by arrival date, read a message's size and bytes, log out —
over `imaplib`, and its logic is tested against a fake of it; the model through
one client, tested against a fake transport. The corpus covers each forwarding
form of §3 (Gmail's, Exchange's, `Resent-From`, `Delivered-To`, by hand attached
and inline, several attached), each with a passing, a failing and no
`Authentication-Results` header and one written below the topmost, a plus
address matched against a listed base address and a listed plus address matched
only by itself, each count of §8, the converter's markers, the subject's reply
and forwarding markers, the two readings of item amounts, the provider
canonicalisation and a PDF. A real message never becomes a fixture as it is;
what it shows becomes a hand-built case.
