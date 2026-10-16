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


def pick_tan_mechanism(client: FinTS3PinTanClient) -> None:
    client.fetch_tan_mechanisms()  # one anonymous dialog to read BPD; populates the mechanism list
    mechs = client.get_tan_mechanisms()
    print("\nTAN mechanisms offered by bank:")
    for code, m in mechs.items():
        print(f"  {code}: {m.name}  (type={getattr(m, 'tan_process', '?')}, "
              f"zka={getattr(m, 'zka_id', '?')}, decoupled={getattr(m, 'decoupled_max_poll_number', None) is not None})")
    codes = [c for c in mechs if c != "999"] or list(mechs)
    choice = codes[0] if len(codes) == 1 else input(f"Choose mechanism {codes}: ").strip()
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
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--debug", action="store_true",
                    help="log raw FinTS segments to out/fints.log (review before sharing!)")
    args = ap.parse_args()
    if not (args.blz and args.url and args.user):
        ap.error("blz, url and user are required (flags or FINTS_* env)")

    OUT.mkdir(exist_ok=True)
    if args.debug:
        logging.basicConfig(filename=OUT / "fints.log", level=logging.DEBUG)

    pin = getpass.getpass("PIN: ")
    client = FinTS3PinTanClient(
        args.blz, args.user, pin, args.url, product_id=args.product_id,
    )

    # 1. Anonymous-ish dialog: bank parameter data (BPD) is available before login.
    pick_tan_mechanism(client)

    with client:
        # Strong customer authentication may already be demanded at dialog init.
        if client.init_tan_response:
            ask_tan(client, client.init_tan_response)

        # 2. Bank info: BPD/UPD, supported segments, account permissions.
        info = client.get_information()
        (OUT / "information.txt").write_text(pprint.pformat(info, width=120))
        print("\nBank:", info.get("bank", {}).get("name"))
        print("Supported statement formats / operations: see out/information.txt")
        for acc in info.get("accounts", []):
            print("  account:", {k: acc.get(k) for k in
                                 ("iban", "account_number", "subaccount_number", "product_name", "currency", "type", "owner_name_1")},
                  "ops:", sorted(k for k, v in (acc.get("supported_operations") or {}).items() if v))

        # 3. SEPA accounts (the objects get_transactions needs).
        accounts = ask_tan(client, client.get_sepa_accounts())
        print("\nSEPA accounts:")
        for i, a in enumerate(accounts):
            print(f"  [{i}] {a.iban}  bic={a.bic}  acct={a.accountnumber}/{a.subaccount}  blz={a.blz}")
        acc = accounts[int(input("Select account index: ") or 0)]

        end = dt.date.today()
        start = end - dt.timedelta(days=args.days)

        # 4a. Balance (informational; also tells us currency/booking conventions).
        try:
            bal = ask_tan(client, client.get_balance(acc))
            print("\nBalance:", bal)
        except Exception as e:
            print("get_balance failed:", repr(e))

        # 4b. Transactions as MT940 (the classic format, parsed by the mt-940 lib).
        print(f"\nFetching MT940 {start}..{end}")
        txs = ask_tan(client, client.get_transactions(acc, start, end))
        print(f"{len(txs)} transactions (MT940)")
        dump = []
        for t in txs:
            d = t.data
            dump.append({k: str(v) for k, v in d.items()})
            amt = d.get("amount")
            print(f"{d.get('date')}  (val {d.get('entry_date')})  {amt}  "
                  f"{d.get('applicant_name') or ''} | {d.get('purpose') or ''}")
        (OUT / "transactions_mt940.json").write_text(json.dumps(dump, indent=2, ensure_ascii=False))

        # 4c. Same range as camt.052/053 XML, if the bank supports it.
        try:
            print(f"\nFetching camt XML {start}..{end}")
            xml = ask_tan(client, client.get_transactions_xml(acc, start, end))
            docs = xml if isinstance(xml, (list, tuple)) else [xml]
            for n, doc in enumerate(docs):
                p = OUT / f"transactions_camt_{n}.xml"
                p.write_bytes(doc if isinstance(doc, bytes) else str(doc).encode())
                print("saved", p)
        except Exception as e:
            print("camt fetch not available / failed:", repr(e))

        # 5. Persist-able client state (what we'd store between runs: BPD/UPD, system id).
        (OUT / "client_state.bin").write_bytes(client.deconstruct())
        print("\nclient state saved (contains no PIN) -> out/client_state.bin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
