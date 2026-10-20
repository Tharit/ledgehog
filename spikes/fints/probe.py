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
from fints.exceptions import FinTSNoResponseError, FinTSSCARequiredError
from fints.fields import DataElementField, DataElementGroupField
from fints.formals import KTI1
from fints.models import SEPAAccount
from fints.segments.base import FinTS3Segment

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
ACCOUNT_DATA_SEGS = {"HKKAZ", "HKSAL", "HKCAZ", "HKKKU", "HKKKS"}


class HKKKU1(FinTS3Segment):
    """Kreditkartenumsaetze anfordern, version 1. python-fints has no credit-card support; the element
    order follows the request builder of the Rust crate floatingpixels/fints (verified live there):
    account group (empty if the bank's HIKKUS says not required), card number, sub-account, from, to,
    [max entries (empty), touchdown point]."""
    account = DataElementGroupField(type=KTI1, required=False, _d="Kontoverbindung international")
    card_number = DataElementField(type="an", max_length=30, _d="Kreditkartennummer")
    subaccount = DataElementField(type="an", required=False, _d="Unterkontomerkmal")
    date_start = DataElementField(type="dat", required=False, _d="Von Datum")
    date_end = DataElementField(type="dat", required=False, _d="Bis Datum")
    max_number_responses = DataElementField(type="num", max_length=4, required=False, _d="Maximale Anzahl Eintraege")
    touchdown_point = DataElementField(type="an", max_length=35, required=False, _d="Aufsetzpunkt")


def _return_response(self, command_seg, response):
    return response


# NeedTANResponse resumes via a *named client method*, so the hook must live on the class.
FinTS3PinTanClient._return_response = _return_response

# HIKKU entry components, by position (G112 layout, as parsed by floatingpixels/fints)
_HIKKU_FIELDS = {
    0: "card_number", 1: "receipt_date", 2: "booking_date", 3: "statement_date", 4: "value_date",
    5: "original_amount", 6: "original_currency", 7: "original_direction", 8: "exchange_rate",
    9: "amount", 10: "currency", 11: "direction",
    20: "country", 21: "merchant_name", 22: "terminal", 23: "billed", 24: "booking_reference",
    25: "fee_code", 26: "statement_marker", 27: "cash_fee", 28: "foreign_use_fee",
}


def fetch_credit_card_transactions(client: FinTS3PinTanClient, acc, start, end) -> list:
    """HKKKU for one card, following touchdown points (3040). Returns the raw response messages."""
    pages, touchdown = [], None
    for _ in range(10):
        seg = HKKKU1(card_number=acc.accountnumber, subaccount=acc.subaccount or "",
                     date_start=start, date_end=end, touchdown_point=touchdown)
        dialog = client._get_dialog()
        response = ask_tan(client, client._send_with_possible_retry(dialog, seg, client._return_response))
        pages.append(response)
        touchdown = None
        for hirms in response.find_segments("HIRMS"):
            for r in hirms.responses:
                if r.code == "3040" and r.parameters:
                    touchdown = r.parameters[0]
        if not touchdown:
            break
        print("  (more data: bank gave a touchdown point, requesting the next page)")
    return pages


def _amount(value, direction) -> str:
    """'1234,56' + 'D' -> '-1234.56' (debit is negative from the cardholder's side)."""
    if value in (None, ""):
        return ""
    num = value.replace(".", "").replace(",", ".")
    return ("-" if direction == "D" else "") + num


def show_credit_card_pages(pages) -> list[dict]:
    """Print and return the entries of HIKKU responses. Card number is masked in the printout only."""
    dump = []
    for page in pages:
        for seg in page.find_segments("HIKKU"):
            data = seg._additional_data
            card = data[0] if data else ""
            masked = f"...{card[-4:]}" if card else "?"
            bal = data[2] if len(data) > 2 and isinstance(data[2], list) else None
            print(f"\nCard {masked}  statement dates: last={data[3] if len(data) > 3 else None} "
                  f"next={data[4] if len(data) > 4 else None}")
            if bal:
                print(f"  current balance: {_amount(bal[1], bal[0])} {bal[2]} as of {bal[3] if len(bal) > 3 else '?'}")
            for el in data[5:]:
                if not isinstance(el, list) or not any(c not in (None, "") for c in el):
                    continue  # empty tail group
                row = {name: el[i] for i, name in _HIKKU_FIELDS.items() if i < len(el) and el[i] not in (None, "")}
                row["description"] = [c for c in el[12:20] if c not in (None, "")]
                row["amount"] = _amount(row.get("amount"), row.get("direction"))
                dump.append(row)
                print(f"  {row.get('booking_date')} (receipt {row.get('receipt_date')})  {row['amount']:>10} "
                      f"{row.get('currency', '')}  {row.get('merchant_name', '')} | {' '.join(row['description'])}")
    if not dump:
        print("  (no HIKKU entries in the response)")
    return dump


def raw_allowed(client: FinTS3PinTanClient, account_number) -> list[str]:
    """Transaction names the bank's UPD lists for an account, as sent (the library maps only the few
    operations it knows, e.g. not the credit-card ones)."""
    out: set[str] = set()
    for seg in client.upd.find_segments("HIUPD"):
        if getattr(seg.account_information, "account_number", None) == account_number:
            out |= {t.transaction for t in seg.allowed_transactions if t.transaction}
    return sorted(out)


def supports(info: dict, account, op: str) -> bool:
    """Ask the bank's own account permissions (UPD) whether an operation is available, instead of
    trying and failing. Unknown account / operation -> True (try it)."""
    from fints.client import FinTSOperations

    for a in info.get("accounts", []):
        # Credit cards have no IBAN: match on account number then.
        same = a.get("iban") == account.iban if account.iban else a.get("account_number") == account.accountnumber
        if same:
            return bool((a.get("supported_operations") or {}).get(getattr(FinTSOperations, op), True))
    return True


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
            # Learn per bank, not per call: the SCA policy is the same for all account-data calls
            # (Consorsbank: HKKAZ/HKSAL/HKCAZ), so later calls skip the failed first attempt.
            print(f"bank demands SCA for {seg_type}; retrying in a new dialog with a TAN request "
                  f"(and doing the same for {sorted(ACCOUNT_DATA_SEGS - {seg_type})} from now on)")
            FORCE_TAN.update(ACCOUNT_DATA_SEGS)
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



def patch_full_account_kti1() -> None:
    """The library's KTI1.from_sepa_account sends only IBAN+BIC. Consorsbank answers HKKAZ/HKSAL +
    HKTAN with 9010 'Verarbeitung nicht möglich' unless account number, sub-account and bank
    identifier are present too (cf. python-fints PR #218, found via hbci4j traces)."""
    from fints.formals import KTI1, BankIdentifier

    def from_sepa_account(cls, acc):
        return cls(
            iban=acc.iban,
            bic=acc.bic,
            account_number=acc.accountnumber,
            subaccount_number=acc.subaccount or "",
            bank_identifier=BankIdentifier(country_identifier="280", bank_code=acc.blz),
        )

    KTI1.from_sepa_account = classmethod(from_sepa_account)


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


def get_tan_media_via_init(client: FinTS3PinTanClient):
    """Same as client.get_tan_media(), but sends HKTAB together with the dialog init (lazy init), as the
    library does for Postbank. Needed when the init alone is rejected for lack of a TAN medium name."""
    from fints.client import HKTAB4, HKTAB5
    from fints.formals import TANMediaClass4, TANMediaType2

    # The library appends HKTAN (process 4) to every init if it knows TAN methods. This bank answers that
    # with 9210 and an empty HITAB, so hide the methods for this one dialog: init without HKTAN.
    saved = list(client.allowed_security_functions)
    client.allowed_security_functions = []
    try:
        with client._new_dialog(lazy_init=True) as dialog:
            seg = client._find_highest_supported_command(HKTAB4, HKTAB5)(
                tan_media_type=TANMediaType2.ALL, tan_media_class=str(TANMediaClass4.ALL),
            )
            try:
                client._bootstrap_mode = True
                response = dialog.init(seg)
            finally:
                client._bootstrap_mode = False
            # internal dialog sends don't reach the response callback: show the bank's own words
            for hirm in (*response.find_segments("HIRMG"), *response.find_segments("HIRMS")):
                for r in hirm.responses:
                    if r.code[0] in "39" and r.code != "3060":
                        print(f"   [bank {r.code}] {r.text}")
            for resp in response.response_segments(seg, "HITAB"):
                if not hasattr(resp, "tan_media_list"):
                    print("  (HITAB came back empty/unparsable:", getattr(resp, "_additional_data", None), ")")
                    return None, []
                return resp.tan_usage_option, list(resp.tan_media_list)
    finally:
        client.allowed_security_functions = saved
    return None, []


def pick_tan_mechanism(client: FinTS3PinTanClient, preset: str | None = None) -> None:
    client.fetch_tan_mechanisms()  # one anonymous dialog to read BPD; populates the mechanism list
    mechs = client.get_tan_mechanisms()
    print("\nTAN mechanisms offered by bank:")
    for code, m in mechs.items():
        print(f"  {code}: {m.name}  (type={getattr(m, 'tan_process', '?')}, "
              f"zka={getattr(m, 'zka_id', '?')}, decoupled={getattr(m, 'decoupled_max_poll_number', None) is not None})")
    if preset and preset not in mechs:
        # Experiment: the bank never sent its allowed-procedures list (3920), so the library filters
        # every method out. The BPD still describes them, so declare the wanted one allowed ourselves.
        client.allowed_security_functions.append(preset)
        mechs = client.get_tan_mechanisms()
        if preset in mechs:
            print(f"\n!! {preset} ({mechs[preset].name}) was NOT offered for this user; forcing it anyway")
        else:
            raise SystemExit(f"\nMechanism {preset} is not described in the bank's parameter data either.")
    codes = [c for c in mechs if c != "999"] or list(mechs)
    if not codes:
        raise SystemExit(
            "\nThe bank offers no TAN method for this user (it did not send its list of allowed procedures, "
            "3920). The login itself worked, but no TAN procedure is active for this ID on the FinTS side; "
            "the bank usually answers 9960 'Kein aktives TAN Verfahren ermittelt' next. Ask the bank to "
            "enable FinTS/HBCI with a TAN procedure for this ID. Nothing further was sent."
        )
    choice = preset or codes[0] if preset or len(codes) == 1 else input(f"Choose mechanism {codes}: ").strip()
    client.set_tan_mechanism(choice)
    # Some banks additionally require choosing a TAN medium (device name).
    try:
        if client.is_tan_media_required() and not client.selected_tan_medium:
            result = client.get_tan_media()
            if result is None:
                # Deutsche Bank: dialog init itself fails with 9210 'Name des TAN-Medium erforderlich', so
                # the library's separate HKTAB dialog never opens. Ask in the init message instead
                # (the library only does this for Postbank).
                print("  (bank wants a TAN medium name at login; asking for the list inside the init message)")
                result = get_tan_media_via_init(client)
            _usage, media = result
            for i, m in enumerate(media):
                print(f"  medium [{i}]: {getattr(m, 'tan_medium_name', m)}")
            if media:
                client.set_tan_medium(media[int(input("Choose medium index: ") or 0)])
            else:
                # The bank gave no device list. Fall back to the name as shown in the bank's own app
                # (Miles & More app > settings/security). Wrong names are rejected with 9210/9xxx.
                name = input("TAN medium (device) name as shown in your app, or Enter to skip: ").strip()
                if name:
                    client.selected_tan_medium = name
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
    ap.add_argument("--customer-id", default=os.environ.get("FINTS_CUSTOMER_ID"),
                    help="separate customer id if the bank has one (default: same as --user)")
    ap.add_argument("--yes", action="store_true", help="skip the 'about to connect' confirmation")
    ap.add_argument("--force-tan", action="store_true",
                    help="attach a TAN request to balance calls (the bank answers 9075 otherwise)")
    ap.add_argument("--tan-for", default="",
                    help="comma list of request types that get an HKTAN (with the TAN medium name) from the "
                         "start, e.g. HKSPA,HKKKU (Deutsche Bank answers 9960 to requests without one)")
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
    patch_full_account_kti1()
    if args.force_tan:
        FORCE_TAN.add("HKSAL")
    FORCE_TAN.update(s.strip().upper() for s in args.tan_for.split(",") if s.strip())

    # A wrong user id / PIN can lock the account at the bank: make the target explicit first.
    from urllib.parse import urlparse
    print(f"\nAbout to connect:\n  bank code : {args.blz}\n  host      : {urlparse(args.url).hostname}\n"
          f"  user id   : {args.user}\n  product id: {'set' if args.product_id else 'NOT set'}")
    if not args.yes and input("Proceed and enter the PIN? [y/N] ").strip().lower() != "y":
        return 1

    pin = getpass.getpass("PIN: ")
    client = FinTS3PinTanClient(
        args.blz, args.user, pin, args.url, customer_id=args.customer_id, product_id=args.product_id,
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

        # HKSPA lists IBAN accounts only; credit cards (no IBAN) may be missing or the call may fail.
        sepa: dict = {}
        try:
            for s in ask_tan(client, client.get_sepa_accounts()):
                sepa[(s.accountnumber, s.subaccount or "")] = s
        except FinTSNoResponseError:
            # The bank answered, but with no SEPA account data (typically 3010 'Es liegen keine Eintraege vor'):
            # normal for credit cards, which have no IBAN. Check the [bank ...] lines for anything else.
            print("(HKSPA: the bank returned no SEPA accounts (expected for a card without IBAN); "
                  "using the bank's own account list)")
        except Exception as e:
            print("(HKSPA failed or unsupported, using the bank's account list only:", repr(e), ")")

        # Candidates come from the UPD (what the bank says exists); fall back to HKSPA's if UPD is empty.
        accounts = []
        for a in info.get("accounts", []):
            if not a.get("account_number"):
                continue  # the bank also sends UPD rows without an account (placeholders); ignore them
            key = (a.get("account_number"), a.get("subaccount_number") or "")
            known = sepa.get(key)
            bi = a.get("bank_identifier")
            accounts.append(SEPAAccount(
                iban=a.get("iban") or (known.iban if known else None),
                bic=known.bic if known else None,
                accountnumber=a.get("account_number"),
                subaccount=a.get("subaccount_number"),
                blz=getattr(bi, "bank_code", None) or args.blz,
            ))
        accounts = accounts or list(sepa.values())
        print("\nAccounts (from the bank):")
        for i, a in enumerate(accounts):
            ops = [a_ for a_ in info.get("accounts", []) if a_.get("account_number") == a.accountnumber]
            name = ops[0].get("product_name") if ops else ""
            print(f"  [{i}] {name}  iban={a.iban}  acct={a.accountnumber}/{a.subaccount}  blz={a.blz}  "
                  f"transactions={'yes' if supports(info, a, 'GET_TRANSACTIONS') else 'no'}")
        acc = accounts[int(input("Select account index: ") or 0)]

    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)

    # Each data call gets its own dialog: a rejected request makes the bank close the dialog.
    # 4a. Transactions as MT940 (the classic format, parsed by the mt-940 lib).
    if not supports(info, acc, "GET_TRANSACTIONS"):
        allowed = raw_allowed(client, acc.accountnumber)
        print("\nMT940 (HKKAZ): not allowed for this account; skipping. Operations the bank lists for it: "
              f"{allowed}")
        if "HKKKU" in allowed:
            print("  -> this is a credit card: transactions are HKKKU (G112 format), not in python-fints; "
                  "using the probe's own implementation")
            print(f"\nFetching credit-card transactions (HKKKU) {start}..{end}")
            pages = run(client, "HKKKU", lambda: fetch_credit_card_transactions(client, acc, start, end))
            dump = show_credit_card_pages(pages)
            (OUT / "transactions_hkkku.json").write_text(json.dumps(dump, indent=2, ensure_ascii=False))
    else:
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

    # 4b. Same range as camt.052/053 XML, only if the account permissions say the bank offers it.
    if not supports(info, acc, "GET_TRANSACTIONS_XML"):
        print("\ncamt XML: not offered for this account (UPD says no HKCAZ); skipping")
    else:
        try:
            print(f"\nFetching camt XML {start}..{end}")
            xml = run(client, "HKCAZ", lambda: client.get_transactions_xml(acc, start, end))
            for n, doc in enumerate(xml if isinstance(xml, (list, tuple)) else [xml]):
                p = OUT / f"transactions_camt_{n}.xml"
                p.write_bytes(doc if isinstance(doc, bytes) else str(doc).encode())
                print("saved", p)
        except Exception as e:
            print("camt fetch failed:", repr(e))

    # 4c. Balance (informational; also tells us currency/booking conventions).
    if not supports(info, acc, "GET_BALANCE"):
        print("\nbalance: not offered for this account; skipping")
    else:
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
