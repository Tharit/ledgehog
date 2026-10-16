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

## Open questions

- Resolved: Consorsbank account-data access (full KTI1 + HKTAN on HKKAZ/HKSAL).
- What does the challenge look like when the SCA window expires (0030 typed TAN with 900, 3955 app push with
  901)? Not seen yet for account data; the login-time challenge handling is patched, the 901 push is untested.
- Pagination/touchdown for long ranges, pending items, the 90-day SCA-free history limit.
- Does a second bank behave differently (camt, IBAN fields, SCA rules)? Worth one more probe run.
