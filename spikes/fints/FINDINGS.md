# FinTS spike: findings

Library: `python-fints` 5.0.1 (+ `mt-940` 5.1.1). Banks tested: Consorsbank (a normal account, MT940) and the
Deutsche Bank Miles & More credit card (`HKKKU`, G112). Probe: `probe.py`. Debug log `out/fints.log` is the
ground truth (contains account data, PIN masked). Sections: Consorsbank (items 1-15), Deutsche Bank card
(items 16-21), cross-bank lessons, how to run, open questions.

## Status

| Step | Deutsche Bank card | Consorsbank |
|---|---|---|
| Login, TAN device | works after DB-side activation (17, 18) | works (1, 2) |
| Account discovery | works from UPD, `HKSPA` has nothing for a card (19) | works |
| Transactions | `HKKKU`/G112, own implementation (20, 21): 36 bookings / 30 days | MT940 via `HKKAZ` (4): 17 tx / 30 days |
| Balance | not implemented (`HKKKS`) | `HKSAL`, same flow as `HKKAZ` |

Consorsbank details (BLZ 76030080, `brokerage-hbci.consorsbank.de/hbci`):

| Step | Result |
|---|---|
| Connect, BPD sync, product id accepted | works |
| Login (PIN) | works, **only with `--hnshk-v2`** (see 1) |
| TAN at login | works when bank asks (see 2) |
| Account discovery (`HKSPA`, UPD) | works |
| MT940 transactions (`HKKAZ`) | **works** (17 tx / 30 days) once HKTAN is attached and KTI1 is complete (see 4) |
| Balance (`HKSAL`) | same flow as HKKAZ |
| camt (`HKCAZ`) | not offered by this bank; known up front from UPD `supported_operations` (see 13) |

## Things the importer must know (Consorsbank, MT940)

1. **Signature profile.** The library writes `HNSHK` with PIN profile v1 even for two-step; the bank wants v2
   (matching `HNVSK`). Otherwise `9010 Ungültiger Signaturaufbau`. Needs a patch/subclass of
   `PinTanTwoStepAuthenticationMechanism.sign_prepare` (`patch_hnshk_profile_v2`).
2. **Login TAN is not detected by the library for this bank.** The bank attaches `0030 Sicherheitsfreigabe
   erforderlich` to the `HKIDN` segment, the library only looks at `HKTAN`'s responses, so the HITAN
   challenge is ignored and the next request dies with `9120 Unexpected message`. Workaround: wrap
   `FinTSDialog.init` and re-detect from `HITAN` + 0030/3955 (`patch_login_tan_detection`).
   Login SCA is intermittent: first session asked for a TAN, later ones said `3076 Keine starke
   Authentifizierung erforderlich`.
3. **The library can swallow errors.** `client._bootstrap_mode` starts `True`; while true a `9075` silently
   closes the dialog and `get_transactions` returns `[]`, i.e. a false "0 transactions". Set
   `client._bootstrap_mode = False` after setup. Never treat an empty result as success without checking
   bank return codes (`client.add_response_callback`).
4. **SCA per call is unpredictable.** Bank params (`HIPINS`/`HITANS`) say HKKAZ/HKSAL need no TAN, but the
   bank answers `9075 Starke Authentifizierung erforderlich` and closes the dialog. Retrying with
   `HKTAN` (process 4, segment_type=HKKAZ) in a fresh dialog gets `9010 Verarbeitung nicht möglich` +
   `3076`. Same with mechanism 900 (photoTAN/SecurePlus) and 901 (decoupled app); the app never prompted.
   **Likely cause of the 9010: `KTI1.from_sepa_account` in 5.0.1 sends only IBAN+BIC; Consorsbank needs
   account number, sub-account and bank identifier too** (python-fints PR #218, found by diffing hbci4j
   traces; that PR also has our HNSHK-v2, HKIDN-login-TAN and forced-HKTAN-for-HKKAZ/HKSAL/HKCCS fixes,
   i.e. Consorsbank needs HKTAN on these although HIPINS says N). Patched in `patch_full_account_kti1`;
   not yet verified against the bank. A plain resend after the 9010 in the same dialog still gets 9075
   (tried, no use). Older notes: forum reports of identical 9075 on statement retrieval since the bank's
   security changes (VoP, ~Nov 2025), and that HBCI still needs the SecurePlus app, not the new
   Consorsbank app. Another report: "a dialog can only be opened with HKTAN6 in dialog init, otherwise 9075".
5. **Return codes.** 9010 is generic "processing not possible" (the library's "check BLZ" message is
   misleading). Read the text in the log. 9075 = SCA required, bank closes the dialog. 3076 = no SCA required.
   3955 = decoupled challenge pending. 0030 = TAN needed.
6. **A rejected request ends the dialog**; every data call should use its own dialog (`run()` in probe.py).
7. **Bank error text is hidden by the library's exceptions**; log or callback it ourselves.
8. **Formats.** MT940 only (no camt/`HICAZS`). Statement fields are in `Transaction.data`.
9. **Account list** (UPD) includes non-cash accounts: here a Depot (only `HKWPD`, no HKSAL/HKKAZ), a Tagesgeld
   and a Giro account. `supported_operations` per account tells which. IBAN is `None` for the Depot.
10. **Dependencies.** 17 packages, all PyPI, hashes verified; only egress is `requests.post` to the bank
    URL. `deconstruct()` state holds no PIN; never `set_data()` an untrusted blob (pickle).
11. **Environment.** A TLS-inspecting VPN/ZTA breaks `uv` and would see the PIN on the wire; disable
    when running against a bank.
12. **Product ID** (DK-registered) was accepted; version string sent is the library's.

13. **Don't try-and-fail; ask the bank first, and learn per bank.**
    - Capabilities: per account, UPD `supported_operations` already says HKCAZ/HKSAL/HKKAZ/HKWPD yes/no, and
      the BPD lists supported formats (HICAZS absent = no camt). Choose the format and skip unsupported ops
      from that (`supports()` in the probe). The library does check HICAZS client-side, without contacting
      the bank, but the probe was still entering a dialog first.
    - SCA envelope: HIPINS says HKKAZ/HKSAL need no TAN, reality: they do (Consorsbank). A plain attempt costs
      a login + rejected request (9075), the retry another login. Working sequence: `HKKAZ` plain -> 9075 ->
      new dialog, `HKKAZ`+`HKTAN`(process 4) -> `3076 Keine starke Authentifizierung erforderlich` + data
      (no challenge: exempt inside the SCA window; a challenge 0030/3955 is expected once it expires).
      Learn the policy per bank and persist it (here: HKTAN on HKKAZ/HKSAL/HKCAZ) so later runs go
      straight to the working form; keep the 9075-retry as the safety net because it can change.
14. **MT940 data shape** (library `Transaction.data`, 17/17 rows, ~40 keys, most empty):
    - Populated: `date`, `entry_date`, `guessed_entry_date`, `amount` (string, e.g. `-9.99 EUR`; parse it),
      `currency`, `status` (C/D), `applicant_name`, `applicant_bin`, `purpose`, `posting_text` (GVC text),
      `transaction_code`, `transaction_reference`, `customer_reference`, `end_to_end_reference`, `id`.
    - **Counterparty IBAN is not in its own field here**: `applicant_name` comes as `<IBAN><name>` (IBAN glued
      to the name), `applicant_bin` holds the BIC; `gvc_applicant_iban` is empty. Needs parsing.
    - `end_to_end_reference` is space-padded, `customer_reference` can contain newlines: normalize.
    - No stable unique transaction id (`id`/`transaction_reference` are not reliable): dedup needs a
      synthetic key (account, booking date, amount, purpose/reference).
    - Booked items only by default (pending is a separate flag in the library).

15. **Creditor ID / mandate reference are not available from this bank over FinTS** (the Consorsbank app shows
    them, FinTS does not). Raw `:86:` uses the DK structured layout (`?00` text, `?20-?29` purpose lines with
    `TAG+`, `?30` BIC, `?31` IBAN, `?32/33` name) but the bank sends only `EREF+`, `KREF+`, `SVWZ+`; never
    `MREF+`/`CRED+`, even on the 10/17 direct debits (GVC 005 'Lastschrift (Einzugsermaechtigung)'). The
    library maps what arrives (`applicant_creditor_id`, mandate etc. exist but are empty). Not in the free
    text either (no `xx99ZZZ...` creditor ids, no 'Mandat'). The BPD advertises only HIKAZS (MT940, v3-7),
    HISALS, HIWPDS, HICCSS, HIIPZS, HISPAS: no HICAZS (camt, which would carry MndtId/CdtrId), no statement
    or PDF services. The mt-940 `?NN` layout is a per-bank convention, so other banks may populate more tags
    (MREF+, CRED+, ABWA+, ...): the importer should map all tags generically and treat these fields as optional.
    Only non-FinTS routes (bank CSV/PDF export) can give the missing fields for this bank.

## Second bank: Deutsche Bank / Miles & More credit card (card-only customer)

**Result: works end to end** (login, BestSign device selection, card discovery, `HKKKU` transactions: 36 bookings
in 30 days), after a multi-day bank-side activation and a custom `HKKKU` implementation. What it took:

16. **Connection data.** URL `https://fints.deutsche-bank.de/`, BLZ `50070439` (the card-only code; the regular
    Deutsche Bank code `50070010` was not tried). Login name = Deutsche Bank ID, PIN = the Deutsche Bank ID
    *password*. Not the BestSign password (rejected at login with `9040 Anmeldung fehlgeschlagen`), not the phone PIN.
17. **A TAN device must be activated on the bank's side; the Miles & More app's BestSign alone was not enough for
    this ID.** The ID was card-only with BestSign inside the M&M app. Symptoms until fixed: login OK (SCA-exempt,
    `3076`), the bank never sent the allowed-procedures list (`3920`) and answered every request with `9960 Kein
    aktives TAN Verfahren ermittelt`, even with the method forced and the TAN device name sent. What fixed it: the
    Deutsche Bank website/app enrollment (own BestSign), then activation (SMS, or a letter by post, 2-3 working
    days). After enrolling but before activation the bank lists 920/921 (`3920`) but answers TAN-needing requests
    with `9075` + `9940 Kein aktives TAN-Geraet verfuegbar` and returns an empty `HITAB` (python-fints' parser
    warns `HITAB4.tan_usage_option was not present`). Public sources disagree about card-only access (StarMoney:
    'in progress'; support: 'not yet possible'; Outbank/one forum user: works), so expect this to vary per
    customer. The importer needs distinct user-facing states: wrong password (`9040`), no TAN procedure (`9960`),
    enrolled but not activated (`9940`).
18. **TAN medium (device) name is required at login (`9210`).** It is the device name shown in the bank app (the
    'Seal One-ID' is not needed). The bank cannot deliver the device list in an init that carries an `HKTAN`
    (`9210` + empty `HITAB`), and the library's own HKTAB dialog fails the same way (it only works around it for
    Postbank). Working approach: ask for HKTAB in an init *without* HKTAN (`get_tan_media_via_init`), then send
    the chosen name in every `HKTAN`. A method not listed by the bank can still be forced (`--mechanism 921`
    with `allowed_security_functions`), the bank's list is not authoritative.
19. **Credit cards are a different product on the wire.** UPD account type 50 (`Lufthansa Senator Credit Card`), no
    IBAN, account number = card number (sensitive), sub-account set. Allowed operations: `HKKKU` (transactions),
    `HKKKS` (balance), `HKSPA`, `HKTAB`, ... but **not `HKKAZ`/`HKSAL`**; so `supported_operations` in
    python-fints shows nothing useful for it (read the raw UPD, `raw_allowed()`). The UPD also contains placeholder
    rows without an account (ignore). `HKSPA` answers `3010 Es liegen keine Eintraege vor` (no IBAN, no SEPA
    accounts): normal, but python-fints raises `FinTSNoResponseError`. A library helper (`KTV4.from_sepa_account`)
    crashes without a BIC. python-fints has no credit-card support at all.
20. **`HKKKU` v1 (credit-card transactions), implemented in the probe** (`HKKKU1`, `fetch_credit_card_transactions`,
    `show_credit_card_pages`; offline test `test_hkku.py`). The layout comes from the open-source Rust crate
    `floatingpixels/fints` and worked here on the second try.
    - Request: `HKKKU:n:1 + <account group> + <card number> + <sub-account> + <from YYYYMMDD> + <to> [+ <max
      entries, empty> + <touchdown point>]`. The account group (`IBAN:BIC:account:sub-account:country:bank code`,
      for a card `::<card>:<sub>:280:<BLZ>`) **is required** (`9210 Angabe der Kontoverbindung erforderlich`
      without it) although the BPD `HIKKUS` parameters read like 'not required'. `HIPINS` marks `HKKKU` as
      TAN-requiring (`J`), so the library attaches `HKTAN`; inside the SCA window the bank answers `3076` and
      delivers the data with no push. NeedTANResponse resumes through a *named client method*, so the resume hook
      must be a method on the client class (`_return_response`).
    - Response `HIKKU:n:1` (parsed from python-fints' generic segment, `_additional_data`): element 1 card number,
      2 account id, 3 current balance (`D/C:amount:currency:date[:time]`), 4 last statement date, 5 next statement
      date, 6+ one group per booking, last group empty. Booking group (29 components): 0 card, 1 receipt date,
      2 booking date, 3 statement date, 4 value date, 5-7 original amount/currency/direction, 8 exchange rate,
      9-11 booked amount/currency/direction (`C`/`D`), 12-19 description lines, 20 country, 21 merchant name,
      22 terminal, 23 billed flag (`J`/`N`), 24 booking reference, 25 fee code, 26 statement marker, 27 cash fee,
      28 foreign-use fee. Decimal comma, dates `YYYYMMDD`. 'G112' is not MT940.
21. **What this bank actually delivered for 36 bookings:** always present: card number (full, on every row: treat
    as sensitive and never log it), receipt date (equal to the booking date on all rows), booking date, booked
    amount + currency + `C`/`D` (35 debits, 1 credit), original amount + currency + direction (also when it
    equals the booked one; 2 rows in CZK/USD), merchant name, 1-2 description lines. Present on billed items only
    (34 of 36): statement date, value date, booking reference. `billed = N` marks items not yet billed (2 rows, no
    statement date/value date/reference): the card equivalent of pending, and they can change or disappear.
    Never sent: exchange rate, country, terminal, fee fields (even for the foreign-currency rows). Whole 30-day
    window in one response, no touchdown point needed. No stable booking id for the unbilled ones.

## Cross-bank lessons for the importer

- Bank parameters (`HIPINS`, `HITANS`, `HIKKUS`, TAN-method lists) do not reliably predict behavior on either
  bank. React to the answer: `9075` means 'wrap in HKTAN', `3076` means 'exempt, data follows', `9210` means a
  required field (account group, device name) is missing; keep a per-bank learned profile as a first guess.
- Per-connection settings to store: BLZ, URL, login name, TAN method code, TAN device name, learned
  'needs HKTAN' set, account list with raw UPD operations, and which statement operation applies per account
  type (`HKKAZ` for accounts, `HKKKU` for cards).
- python-fints needs several patches for these two banks (signature profile v2, login-TAN detection, bootstrap
  mode, full account group, card operations) or the importer should own its FinTS layer; the Rust crate above
  supports cards and was the best reference found.
- Never print or log full card or account numbers, and keep raw dialog logs private: the debug log contains
  them (PINs are masked by the library).

## Running the probe

```
uv sync
uv run probe.py --blz <BLZ> --url <FINTS URL> --user <login name> --product-id <DK product id> --hnshk-v2 [--mechanism <code>]
```
Consorsbank: BLZ 76030080, `https://brokerage-hbci.consorsbank.de/hbci`, method 900/901.
Deutsche Bank card: BLZ 50070439, `https://fints.deutsche-bank.de/`, `--mechanism 921`, enter the TAN device name.
The PIN is prompted (the bank-account password), `--yes` skips the 'about to connect' confirmation.

## Open questions

- What the challenge looks like once the SCA-exempt window ends: typed TAN (Consorsbank 900) or app push (901 on
  Consorsbank, 921 on Deutsche Bank) for account data. Every call in this spike fell inside the exemption
  (`3076`), so the push flow for operations was never exercised.
- Deutsche Bank card balance (`HKKKS`) and the `HKKKU` touchdown/paging for long ranges (not needed for 36 rows).
- Whether BLZ `50070010` (regular Deutsche Bank access) also lists the card.
- Whether a card-only ID can ever work with only the Miles & More app's BestSign (it did not for this ID).
