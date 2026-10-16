"""FinTS spike: connect, authenticate, list accounts, pull last week's transactions.

Not part of the app. Goal is to learn what FinTS gives us (formats, TAN flows,
quirks), so it prints a lot and dumps raw data to ./out/.

Config (env or flags): FINTS_BLZ, FINTS_URL, FINTS_USER, FINTS_PRODUCT_ID
PIN is always prompted (never stored, never taken from env).

    uv run probe.py --blz 12345678 --url https://... --user myuser
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import logging
import os
import pprint
import sys
from pathlib import Path

from fints.client import FinTS3PinTanClient, NeedTANResponse
from fints.exceptions import FinTSSCARequiredError

OUT = Path(__file__).parent / "out"


def ask_tan(client: FinTS3PinTanClient, resp):
    """Drive any TAN challenge to completion and return the final response."""
    while isinstance(resp, NeedTANResponse):
        print("\n--- TAN required ---")
        print("challenge:      ", resp.challenge)
        print("decoupled:      ", getattr(resp, "decoupled", False))
        print("hhduc (flicker):", bool(getattr(resp, "challenge_hhduc", None)))
        raw = getattr(resp, "challenge_raw", None)
        if raw:
            print("challenge_raw:  ", raw)
        matrix = getattr(resp, "challenge_matrix", None)
        if matrix:
            # photoTAN: (mime_type, bytes). Save for viewing.
            OUT.mkdir(exist_ok=True)
            p = OUT / "tan_challenge.png"
            p.write_bytes(matrix[1])
            print(f"photoTAN image saved: {p} ({matrix[0]})")
        if getattr(resp, "decoupled", False):
            input("Approve in your banking app, then press Enter...")
            resp = client.send_tan(resp, "")
        else:
            resp = client.send_tan(resp, input("TAN: ").strip())
    return resp


def patch_hnshk_profile_v2() -> None:
    """Experiment: the library signs two-step messages with PIN profile version 1 in HNSHK
    (while HNVSK says 2). Strict banks may reject that as 9010 'Ungültiger Signaturaufbau'."""
    from fints.formals import SecurityMethod, SecurityProfile
    from fints.security import PinTanTwoStepAuthenticationMechanism as M

    orig = M.sign_prepare

    def sign_prepare(self, message):
        orig(self, message)
        self.pending_signature.security_profile = SecurityProfile(SecurityMethod.PIN, 2)

    M.sign_prepare = sign_prepare


FORCE_TAN: set[str] = set()  # segment types that get an HKTAN (process 4) attached


def run(client: FinTS3PinTanClient, seg_type: str, fn):
    """Run one data call in its own dialog. If the bank answers 9075 (SCA required) although its
    HIPINS says no TAN is needed, retry once in a fresh dialog with a TAN request attached."""
    for _ in range(2):
        client.init_tan_response = None
        try:
            with client:
                if client.init_tan_response:
                    ask_tan(client, client.init_tan_response)
                return ask_tan(client, fn())
        except FinTSSCARequiredError:
            if seg_type in FORCE_TAN:
                raise
            print(f"bank demands SCA for {seg_type}; retrying in a new dialog with a TAN request")
            FORCE_TAN.add(seg_type)
    raise RuntimeError("unreachable")


def patch_force_tan() -> None:
    """Attach HKTAN (process 4) to the segment types in FORCE_TAN even though the bank's HIPINS says
    no TAN is needed. Consorsbank answers 9075 'Starke Authentifizierung erforderlich' otherwise
    (and closes the dialog), e.g. when the login itself was SCA-exempt (3076)."""
    from fints.client import FinTS3PinTanClient as C

    orig = C._need_twostep_tan_for_segment

    def need(self, seg):
        # Consorsbank rejects a redundant HKTAN on SCA-exempt calls (9010 + 3076 'Keine starke
        # Authentifizierung erforderlich'), so this is opt-in per segment type, set by run().
        if seg.header.type in FORCE_TAN and self.get_current_tan_mechanism() not in (None, "999"):
            return True
        return orig(self, seg)

    C._need_twostep_tan_for_segment = need


def patch_login_tan_detection() -> None:
    """Consorsbank attaches its 0030 'Sicherheitsfreigabe erforderlich' to the HKIDN segment, not
    to the HKTAN segment the library looks at, so the login TAN challenge (HITAN, process 4) is
    ignored and the next request fails with 9120. Re-detect it from the init response."""
    from fints.client import NeedTANResponse
    from fints.dialog import FinTSDialog
    from fints.segments.dialog import HIRMS2

    orig = FinTSDialog.init

    def init(self, *extra):
        retval = orig(self, *extra)
        client = self.client
        if client.init_tan_response is None:
            codes = {r.code for seg in retval.find_segments(HIRMS2) for r in seg.responses}
            hitan = retval.find_segment_first("HITAN")
            if hitan and codes & {"0030", "3955"}:
                print("(login TAN challenge not flagged by library; detected from HITAN, codes:",
                      sorted(codes & {"0030", "3955"}), ")")
                client.init_tan_response = NeedTANResponse(
                    None, hitan, "_continue_dialog_initialization",
                    client.is_challenge_structured(), "3955" in codes,
                )
        return retval

    FinTSDialog.init = init


def pick_tan_mechanism(client: FinTS3PinTanClient, preset: str | None = None) -> None:
    client.fetch_tan_mechanisms()  # one anonymous dialog to read BPD; populates the mechanism list
    mechs = client.get_tan_mechanisms()
    print("\nTAN mechanisms offered by bank:")
    for code, m in mechs.items():
        print(f"  {code}: {m.name}  (type={getattr(m, 'tan_process', '?')}, "
              f"zka={getattr(m, 'zka_id', '?')}, decoupled={getattr(m, 'decoupled_max_poll_number', None) is not None})")
    codes = [c for c in mechs if c != "999"] or list(mechs)
    choice = preset or codes[0] if preset or len(codes) == 1 else input(f"Choose mechanism {codes}: ").strip()
    client.set_tan_mechanism(choice)
    # Some banks additionally require choosing a TAN medium (device name).
    try:
        if client.is_tan_media_required() and not client.selected_tan_medium:
            _usage, media = client.get_tan_media()
            for i, m in enumerate(media):
                print(f"  medium [{i}]: {getattr(m, 'tan_medium_name', m)}")
            if media:
                client.set_tan_medium(media[int(input("Choose medium index: ") or 0)])
    except Exception as e:  # media listing is bank-specific; keep going and learn from the error
        print("(tan media step failed:", repr(e), ")")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blz", default=os.environ.get("FINTS_BLZ"))
    ap.add_argument("--url", default=os.environ.get("FINTS_URL"))
    ap.add_argument("--user", default=os.environ.get("FINTS_USER"))
    ap.add_argument("--product-id", default=os.environ.get("FINTS_PRODUCT_ID"),
                    help="DK-registered product id; banks may reject requests without one")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--no-debug", action="store_true",
                    help="don't log raw FinTS segments to out/fints.log (contains account data; PIN is masked)")
    ap.add_argument("--mechanism", help="TAN mechanism code (skips the prompt), e.g. 900 / 901")
    ap.add_argument("--hnshk-v2", action="store_true",
                    help="experiment: sign two-step messages with PIN profile version 2 (library uses 1)")
    ap.add_argument("--force-tan", action="store_true",
                    help="attach a TAN request to balance calls (the bank answers 9075 otherwise)")
    args = ap.parse_args()
    if not (args.blz and args.url and args.user):
        ap.error("blz, url and user are required (flags or FINTS_* env)")

    OUT.mkdir(exist_ok=True)
    if not args.no_debug:
        logging.basicConfig(filename=OUT / "fints.log", filemode="w", level=logging.DEBUG)
    if args.hnshk_v2:
        patch_hnshk_profile_v2()
    patch_login_tan_detection()
    patch_force_tan()
    if args.force_tan:
        FORCE_TAN.add("HKSAL")

    pin = getpass.getpass("PIN: ")
    client = FinTS3PinTanClient(
        args.blz, args.user, pin, args.url, product_id=args.product_id,
    )

    # 1. Anonymous-ish dialog: bank parameter data (BPD) is available before login.
    pick_tan_mechanism(client, args.mechanism)

    # The library starts in 'bootstrap mode', where a 9075 (SCA required) silently closes the dialog
    # instead of raising -> empty results. Only get_tan_media() resets it; do it explicitly.
    client._bootstrap_mode = False
    client.add_response_callback(
        lambda seg, r: print(f"   [bank {r.code}] {r.text}") if r.code[0] != "0" or r.code == "0030" else None
    )

    # 2./3. One dialog: bank info + SEPA accounts.
    with client:
        # Strong customer authentication may already be demanded at dialog init.
        if client.init_tan_response:
            ask_tan(client, client.init_tan_response)

        # Bank info: BPD/UPD, supported segments, account permissions.
        info = client.get_information()
        (OUT / "information.txt").write_text(pprint.pformat(info, width=120))
        print("\nBank:", info.get("bank", {}).get("name"))
        print("Supported statement formats / operations: see out/information.txt")
        for acc in info.get("accounts", []):
            print("  account:", {k: acc.get(k) for k in
                                 ("iban", "account_number", "subaccount_number", "product_name", "currency", "type", "owner_name_1")},
                  "ops:", sorted(getattr(k, "name", str(k)) for k, v in (acc.get("supported_operations") or {}).items() if v))

        accounts = ask_tan(client, client.get_sepa_accounts())
        print("\nSEPA accounts:")
        for i, a in enumerate(accounts):
            print(f"  [{i}] {a.iban}  bic={a.bic}  acct={a.accountnumber}/{a.subaccount}  blz={a.blz}")
        acc = accounts[int(input("Select account index: ") or 0)]

    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)

    # Each data call gets its own dialog: a rejected request makes the bank close the dialog.
    # 4a. Transactions as MT940 (the classic format, parsed by the mt-940 lib).
    print(f"\nFetching MT940 {start}..{end}")
    txs = run(client, "HKKAZ", lambda: client.get_transactions(acc, start, end))
    print(f"{len(txs)} transactions (MT940)")
    dump = []
    for t in txs:
        d = t.data
        dump.append({k: str(v) for k, v in d.items()})
        print(f"{d.get('date')}  (val {d.get('entry_date')})  {d.get('amount')}  "
              f"{d.get('applicant_name') or ''} | {d.get('purpose') or ''}")
    (OUT / "transactions_mt940.json").write_text(json.dumps(dump, indent=2, ensure_ascii=False))

    # 4b. Same range as camt.052/053 XML, if the bank supports it (Consorsbank: no HICAZS).
    try:
        print(f"\nFetching camt XML {start}..{end}")
        xml = run(client, "HKCAZ", lambda: client.get_transactions_xml(acc, start, end))
        for n, doc in enumerate(xml if isinstance(xml, (list, tuple)) else [xml]):
            p = OUT / f"transactions_camt_{n}.xml"
            p.write_bytes(doc if isinstance(doc, bytes) else str(doc).encode())
            print("saved", p)
    except Exception as e:
        print("camt fetch not available / failed:", repr(e))

    # 4c. Balance (informational; also tells us currency/booking conventions).
    try:
        print("\nBalance:", run(client, "HKSAL", lambda: client.get_balance(acc)))
    except Exception as e:
        print("get_balance failed:", repr(e))

    # 5. Persist-able client state (what we'd store between runs: BPD/UPD, system id).
    (OUT / "client_state.bin").write_bytes(client.deconstruct())
    print("\nclient state saved (contains no PIN) -> out/client_state.bin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
