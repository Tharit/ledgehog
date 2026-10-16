# FinTS spike: findings

Library: `python-fints` 5.0.1 (+ `mt-940` 5.1.1). Bank tested: Consorsbank (BLZ 76030080, `brokerage-hbci.consorsbank.de/hbci`).
Probe: `probe.py`. Debug log `out/fints.log` is the ground truth (contains account data, PIN masked).

## Status

| Step | Result |
|---|---|
| Connect, BPD sync, product id accepted | works |
| Login (PIN) | works, **only with `--hnshk-v2`** (see 1) |
| TAN at login | works when bank asks (see 2) |
| Account discovery (`HKSPA`, UPD) | works |
| MT940 transactions (`HKKAZ`) | **works** (17 tx / 30 days) once HKTAN is attached and KTI1 is complete (see 4) |
| Balance (`HKSAL`) | same flow as HKKAZ |
| camt (`HKCAZ`) | not offered by this bank; known up front from UPD `supported_operations` (see 13) |

## Things the importer must know

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

Per Deutsche Bank and Outbank docs: FinTS URL `https://fints.deutsche-bank.de/`; card-only customers use BLZ
50070439 (BLZ 50070010 for customers with other DB products); login = Deutsche Bank ID + its password (not the
phone PIN, not the BestSign password); 2FA via (Miles & More) BestSign; FinTS for the card exists since
~2026-04-22. Credit cards have no IBAN: select accounts from UPD, not from HKSPA (probe does).

16. **PIN accepted but no TAN procedure** (so far, not resolved): the bank's BPD lists photoTAN 902, BestSign 920,
    photoTAN-Push 903, BestSign-Push 921, but for this user it never sends the allowed-procedures answer
    (`3920`), and the next dialog is rejected with `9960 Kein aktives TAN Verfahren ermittelt. Bitte
    Kundenservice kontaktieren.` `0940` says last login 1901 (never logged in via an online channel). Likely
    cause: BestSign is registered for the Miles & More app/portal but not as a TAN procedure for FinTS under
    this ID. The BPD's mechanism list is global, not per user: only the 3920 list says what a user may use.
    Importer: treat "no allowed TAN method" as its own, user-facing state (needs bank-side activation), not a
    generic failure.

17. **The 9960 was caused by the empty method choice, not by a missing activation.** The bank never sends the
    allowed-procedures list (3920) for this user, so the library lists no methods and, with an empty choice, falls
    back to one-step (999) -> `9960`. Naming the method explicitly (`--mechanism 921`, BestSign-Push, forced past
    the library's filter) works. The bank's own TAN-method list can't be trusted to be present; importer needs a
    configured/remembered method per bank connection. Login credential here: the Deutsche Bank ID password (the
    BestSign password is rejected with `9040 Anmeldung fehlgeschlagen`).
18. **TAN medium name required at login (`9210`).** The init with HKTAN is rejected until the device name is
    given, and the library's separate HKTAB dialog can't open for the same reason (it only works around this
    for Postbank): ask for HKTAB inside the init message (`get_tan_media_via_init`).
19. **Credit cards are a different product on the wire.** UPD account type 50 (`Lufthansa Senator Credit Card`),
    no IBAN, account number = masked card number, allowed ops: HKKKU (transactions), HKKKS (balance), HKSPA,
    HKTAB, HKPRO ... but **not HKKAZ/HKSAL**. BPD advertises HIKKUS/HIKKSS. Transactions come as G112 segment
    data (not MT940); python-fints has no HKKKU/HKKKS support (a Rust crate `floatingpixels/fints` claims
    it, verified live). So for cards the importer needs its own segment definitions + G112 parser, or another
    library. Also: the UPD contains placeholder rows without account (ignore), and a library helper
    (`KTV4.from_sepa_account`) crashes without a BIC.
    The debug log and `information.txt` contain the full card number: keep `out/` private.

20. **Deutsche Bank card: final state of this spike = blocked bank-side.** With method 921 forced and the TAN
    medium name in HKTAN the *login* is accepted (0020, 3076 'no SCA needed', last-login timestamp updates),
    but every following request in the dialog (HKSPA, also with HKTAN(4)+medium name) gets `9960 Kein aktives
    TAN Verfahren ermittelt`, and the bank never sends the allowed-procedures list (3920) for this ID. Other
    card-only users get 921 in that list. Reading: the ID has no TAN procedure that the FinTS channel treats as
    active (BestSign registered in the Miles & More app only); login is merely SCA-exempt. Next steps are
    outside the code: check the card portal login, complete the Deutsche Bank website enrollment, or ask
    support (cite: login OK with 921 + device name, 3076, then 9960 on any request, no 3920).
    TAN medium name entered = the device name shown in the app (the 'Seal One-ID' was not needed).
    Even then: transactions need HKKKU/G112, unsupported by python-fints.

21. **Resolution of 9960: the TAN procedure must be activated on the bank's side, via the Deutsche Bank website/app
    enrollment.** After starting it, the bank immediately lists 920 BestSign and 921 BestSign-Push for the ID
    (the allowed-procedures list now exists), but full activation needs a **physical activation letter** by
    post. So for a card-only Miles & More customer the FinTS setup has a multi-day offline step, and until it is
    done the symptoms are: login OK (SCA-exempt), no 3920 list, `9960` on every request. The importer's
    onboarding for this bank needs a clear "not activated yet" state and instructions, not a generic error.
    The M&M-app BestSign alone does NOT make FinTS usable.

22. **What "enrolled but not yet activated" looks like on the wire** (after starting the DB website enrollment):
    - the login works (0020, 3076) and now returns the allowed-procedures list `3920` = 920, 921;
    - a request that needs a TAN device is answered `9075 Dialog abgebrochen - starke Authentifizierung
      erforderlich` plus `9940 Kein aktives TAN-Geraet verfuegbar. Die Freigabe von Auftraegen ist nicht moeglich`
      / `9940 Melden Sie sich im Online-Banking an oder kontaktieren den Support`;
    - the TAN-media request (HKTAB) then returns an empty HITAB without `tan_usage_option`, which python-fints'
      parser rejects (`FinTSParserWarning ... HITAB4.tan_usage_option was not present`, generic object);
    - HKSPA for a card is answered normally with `3010 Es liegen keine Eintraege vor` (no IBAN, no SEPA
      accounts) and the library raises FinTSNoResponseError: that is not an auth failure.
    So the distinguishing signal for "not activated" is `9940`, not `9960`. The importer should map 9940 to a
    clear user-facing state, and treat a data-less 3010 as "empty", not as failure.

### Resuming the Deutsche Bank experiment (after the activation letter)

1. Activate per the letter. Check the bank now lists 920/921 with the probe.
2. `uv run probe.py --blz 50070439 --url https://fints.deutsche-bank.de/ --user <Deutsche Bank ID> --product-id <ID> --hnshk-v2 --mechanism 921`
   (PIN prompt = Deutsche Bank ID password, NOT the BestSign password; enter the device name when asked;
   approve the BestSign push on the phone). Add `--tan-for HKSPA` if requests still get 9960.
3. Expected next wall: the card's transactions are HKKKU (G112 data), which python-fints cannot do. Decide
   then between a hand-built HKKKU segment + G112 parser, another library, or leaving cards out of FinTS.

## Open questions

- Resolved: Consorsbank account-data access (full KTI1 + HKTAN on HKKAZ/HKSAL).
- What does the challenge look like when the SCA window expires (0030 typed TAN with 900, 3955 app push with
  901)? Not seen yet for account data; the login-time challenge handling is patched, the 901 push is untested.
- Pagination/touchdown for long ranges, pending items, the 90-day SCA-free history limit.
- Does a second bank behave differently (camt, IBAN fields, SCA rules)? Worth one more probe run.
