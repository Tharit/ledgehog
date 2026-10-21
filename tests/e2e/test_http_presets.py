"""Step 4 end to end over HTTP: each shipped CSV preset with its synthetic fixture, through the
real app (accounts, instance, link, upload, runs, revert, integrity check).

The expectations are computed by hand from the fixtures' known amounts, never by calling the
importer. The giro figure (1.234,56) is on its export day (20.08.), so its record is dated the
day before (19.08.) with the booked rows after it subtracted: 123456 - (-1000) = 124456.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from tests.api import importers_helpers as h
from tests.api.importers_helpers import Api, error_of
from tests.e2e.helpers import (
    BASE,
    ROW_18,
    ROW_19,
    ROW_20,
    ROW_BOOKED_21,
    RUNS,
    Http,
    giro_file,
)
from tests.invariants.helpers import make_entry, make_source
from tests.plugins.importers.csv.fixtures import PRIVATE, card_a_bytes, card_b_bytes, giro_bytes

api = h.api
make_api = h.make_api

D = date
# giro fixture, by hand: movements -45,50 (18.), +1.500,00 (19.), -10,00 (20.); the pending row
# (Valuta "vorgemerkt") and the 0,00 hint are filtered. Figure 1.234,56 on the 20th -> the 19th.
GIRO_MOVEMENTS = [("movement", -4550, D(2026, 8, 18)), ("movement", 150000, D(2026, 8, 19)),
                  ("movement", -1000, D(2026, 8, 20))]  # fmt: skip
GIRO_RECORD = ("reported", 124456, D(2026, 8, 19))
# opening = 124456 - (150000 - 4550) = -20994, the day before min(earliest movement 18., anchor 19.)
GIRO_OPENING = ("opening", -20994, D(2026, 8, 17))
GIRO_ENTRIES = [GIRO_OPENING, *GIRO_MOVEMENTS]


def _giro_world(http: Http, name: str = "Giro") -> tuple[int, int]:
    account = http.create_account(name)
    instance = http.create_instance("consorsbank_giro")
    http.link(instance, account)
    return instance, account


# ---- consorsbank_giro ---------------------------------------------------------------------


def test_giro_first_upload_by_hand(api: Api):
    http = Http(api)
    account = http.create_account("Giro")
    http.check()
    instance = http.create_instance("consorsbank_giro")
    link = http.link(instance, account)
    assert link["account_becomes_synced"] is True and link["user_authored_count"] == 0

    body = http.upload_ok(instance, account, giro_bytes())
    assert body["summary"]["inserted"] == 3 and body["summary"]["skipped_by_identity"] == 0
    assert http.entries(account) == GIRO_ENTRIES
    assert http.records(account) == [GIRO_RECORD]
    # the booked amounts as the bank's source rows carry them
    assert [(s.amount, s.booked_on, s.source_format) for s in http.sources(account)] == [
        (-4550, D(2026, 8, 18), "csv:consorsbank_giro (e2e)"),
        (150000, D(2026, 8, 19), "csv:consorsbank_giro (e2e)"),
        (-1000, D(2026, 8, 20), "csv:consorsbank_giro (e2e)"),
    ]
    # the balance report: figure and dating
    bal = body["report"]["balance"]
    assert (bal["amount_minor"], bal["dated_on"]) == (124456, "2026-08-19")
    assert (bal["figure_minor"], bal["figure_on"], bal["rolled_back_by_minor"]) == (
        123456,
        "2026-08-20",
        -1000,
    )
    # the run view: covered from the earliest booking to the last
    run = http.run(body["run_id"])
    assert (run["status"], run["covered_from"], run["covered_through"]) == ("ok", "2026-08-18", "2026-08-20")
    assert run["revertible"] is True
    f = http.facts(account)
    assert (f["anchored"], f["synced"], f["synced_through"]) == (True, True, "2026-08-20")
    assert f["unexplained_difference"] is None and f["records_since_zero"] is None
    assert PRIVATE not in str(body) and PRIVATE not in str(run)


def test_giro_reupload_skips_everything(api: Api):
    http = Http(api)
    instance, account = _giro_world(http)
    http.upload_ok(instance, account, giro_bytes())
    body = http.upload_ok(instance, account, giro_bytes())
    assert body["summary"]["inserted"] == 0 and body["summary"]["skipped_by_identity"] == 3
    assert http.entries(account) == GIRO_ENTRIES
    assert http.facts(account)["unexplained_difference"] is None


def test_giro_overlapping_file_with_the_true_balance_makes_no_reconciliation_and_reverts_cleanly(api: Api):
    http = Http(api)
    instance, account = _giro_world(http)
    http.upload_ok(instance, account, giro_bytes())
    # the control: a fresh account that only ever had run 1
    control = http.create_account("Giro control")
    http.link(instance, control)
    http.upload_ok(instance, control, giro_bytes())

    # file 2, exported on the 21st: the old rows again plus a -20,00 booking on the 21st.
    # True balance after the 21st: 123456 (the 20th) - 2000 = 121456 -> figure 1.214,56 on the 21st,
    # dated the 20th (the last closed day) with the -20,00 added back: 121456 + 2000 = 123456.
    file2 = giro_file(
        [ROW_BOOKED_21, ROW_20, ROW_19, ROW_18],
        figure="1.214,56",
        figure_on="21.08.2026",
        export="21.08.2026, 09:00:00",
    )
    body = http.upload_ok(instance, account, file2)
    assert body["summary"]["inserted"] == 1 and body["summary"]["skipped_by_identity"] == 3
    bal = body["report"]["balance"]
    assert (bal["amount_minor"], bal["dated_on"]) == (123456, "2026-08-20")
    assert http.records(account) == [GIRO_RECORD, ("reported", 123456, D(2026, 8, 20))]
    # reconciliation = (123456 - 124456) - (-1000 booked on the 20th) = 0: no entry
    assert http.entries(account) == [*GIRO_ENTRIES, ("movement", -2000, D(2026, 8, 21))]
    f = http.facts(account)
    assert f["unexplained_difference"] is None and f["records_since_zero"] is None
    assert f["synced_through"] == "2026-08-21"
    run2 = http.run(body["run_id"])
    assert (run2["covered_from"], run2["covered_through"]) == ("2026-08-18", "2026-08-21")

    # revert: the preview then the real thing; the account is as after run 1
    done = http.revert(body["run_id"])
    assert len(done["removed_entry_ids"]) == 1
    assert http.run(body["run_id"])["status"] == "reverted"
    assert http.entries(account) == http.entries(control) == GIRO_ENTRIES
    assert http.records(account) == http.records(control) == [GIRO_RECORD]
    fa, fc = http.facts(account), http.facts(control)
    for key in ("anchored", "synced", "synced_through", "unexplained_difference", "last_data_on"):
        assert fa[key] == fc[key], key


def test_giro_bank_disagrees_by_a_known_amount(api: Api):
    http = Http(api)
    instance, account = _giro_world(http)
    http.upload_ok(instance, account, giro_bytes())
    # as file 2 above but the bank says 10,00 less: figure 1.204,56 on the 21st -> 122456 on the 20th
    file2 = giro_file(
        [ROW_BOOKED_21, ROW_20, ROW_19, ROW_18],
        figure="1.204,56",
        figure_on="21.08.2026",
        export="21.08.2026, 09:00:00",
    )
    body = http.upload_ok(instance, account, file2)
    assert body["report"]["balance"]["amount_minor"] == 122456
    # reconciliation = (122456 - 124456) - (-1000) = -1000, dated on the record's date
    assert http.entries(account) == sorted(
        [*GIRO_ENTRIES, ("movement", -2000, D(2026, 8, 21)), ("reconciliation", -1000, D(2026, 8, 20))],
        key=lambda e: (e[2], e[1]),
    )
    f = http.facts(account)
    assert f["unexplained_difference"] == {"amount": -1000, "currency": "EUR"}
    with api.engine.connect() as conn:
        rec2 = conn.execute(
            text("SELECT id FROM balance_record WHERE import_run_id = :r"), {"r": body["run_id"]}
        ).scalar_one()
    assert f["records_since_zero"] == [rec2]
    # reverting the run takes the difference with it
    http.revert(body["run_id"])
    assert http.entries(account) == GIRO_ENTRIES
    assert http.facts(account)["unexplained_difference"] is None


def test_quiet_account_still_reports_its_balance_dated_at_its_coverage(api: Api):
    http = Http(api)
    instance, account = _giro_world(http)
    # last booking on the 19th, export (and figure) on the 21st: D189 dates the record at the
    # earliest of figure date 21., last closed day 20., coverage 19. -> the 19th; no rows to undo.
    quiet = giro_file(
        [ROW_19, ROW_18], figure="1.000,00", figure_on="21.08.2026", export="21.08.2026, 09:00:00"
    )
    body = http.upload_ok(instance, account, quiet)
    assert body["report"]["balance"]["amount_minor"] == 100000
    assert body["report"]["balance"]["dated_on"] == "2026-08-19"
    assert http.records(account) == [("reported", 100000, D(2026, 8, 19))]
    # opening = 100000 - (150000 - 4550) = -45450, on the 17th
    assert http.entries(account) == [
        ("opening", -45450, D(2026, 8, 17)),
        ("movement", -4550, D(2026, 8, 18)),
        ("movement", 150000, D(2026, 8, 19)),
    ]
    run = http.run(body["run_id"])
    assert run["covered_through"] == "2026-08-19"
    assert http.facts(account)["synced_through"] == "2026-08-19"


# ---- deutschebank_card -----------------------------------------------------------------


def test_card_with_footer_balance_and_a_statement_payment(api: Api):
    http = Http(api)
    giro = http.create_account("Paying giro", external_ref="GIRO-PAYER")
    card = http.create_account("Card", kind="card")
    instance = http.create_instance(
        "deutschebank_card",
        statement_payment={
            "counter_account_ref": "GIRO-PAYER",
            "purpose": "Card statement {statement_date}",
            "date_offset_days": 4,
        },
    )
    http.link(instance, card)
    body = http.upload_ok(instance, card, card_a_bytes())
    # by hand: -12,00 (booked 2.8.), -9,09 (3.8.; the 10,00 USD row is charged 9,09 EUR) and -30,01
    # (31.7.); statement date 3.8.; footer balance -51,10 = their sum; the payment is the net
    # negated, +51,10, dated 4 days after the statement: 7.8.
    assert body["summary"]["inserted"] == 4
    assert [(s.amount, s.booked_on, s.source_format) for s in http.sources(card)] == [
        (-3001, D(2026, 7, 31), "csv:deutschebank_card (e2e)"),
        (-1200, D(2026, 8, 2), "csv:deutschebank_card (e2e)"),
        (-909, D(2026, 8, 3), "csv:deutschebank_card (e2e)"),
        (5110, D(2026, 8, 7), "csv:synthetic"),
    ]
    payment = http.sources(card)[-1]
    assert payment.counterparty_ref == "GIRO-PAYER" and payment.purpose == "Card statement 2026-08-03"
    assert http.records(card) == [("reported", -5110, D(2026, 8, 3))]
    # opening = -5110 - (-3001 - 1200 - 909) = 0: no derived entry; the payment is dated after the anchor
    assert http.entries(card) == [
        ("movement", -3001, D(2026, 7, 31)),
        ("movement", -1200, D(2026, 8, 2)),
        ("movement", -909, D(2026, 8, 3)),
        ("movement", 5110, D(2026, 8, 7)),
    ]
    synthetic = body["report"]["synthetic"]
    assert (synthetic["amount_minor"], synthetic["booked_on"]) == (5110, "2026-08-07")
    run = http.run(body["run_id"])
    assert (run["covered_from"], run["covered_through"]) == ("2026-07-31", "2026-08-03")
    f = http.facts(card)
    assert (f["anchored"], f["synced"], f["synced_through"]) == (True, True, "2026-08-03")
    assert f["unexplained_difference"] is None
    # the payment's reference is the paying giro's external_ref, which pass 0 of resolution
    # (a later step: nothing sets `counter_account_id` yet) will read as the counter-account
    # (the account stores its ref canonicalised: lower case, no punctuation)
    assert http.facts(giro)["external_ref"] == "giropayer"
    assert "".join(c for c in payment.counterparty_ref.lower() if c.isalnum()) == "giropayer"

    again = http.upload_ok(instance, card, card_a_bytes())
    assert again["summary"]["inserted"] == 0 and again["summary"]["skipped_by_identity"] == 4
    assert len(http.entries(card)) == 4 and http.facts(card)["unexplained_difference"] is None
    assert PRIVATE not in str(body) and PRIVATE not in str(again)


# ---- amex_card -----------------------------------------------------------------


def test_card_with_inverted_signs_and_no_balance(api: Api):
    http = Http(api)
    card = http.create_account("Card B", kind="card")
    instance = http.create_instance("amex_card")
    http.link(instance, card)
    body = http.upload_ok(instance, card, card_b_bytes())
    # by hand: the file lists purchases positive: 12,50 -> -1250 (5.8.), -100,00 (a payment) ->
    # +10000 (6.8.), 1.234,56 -> -123456 (7.8.)
    assert body["summary"]["inserted"] == 3
    assert http.entries(card) == [
        ("movement", -1250, D(2026, 8, 5)),
        ("movement", 10000, D(2026, 8, 6)),
        ("movement", -123456, D(2026, 8, 7)),
    ]
    assert http.records(card) == [] and body["report"]["balance"] is None
    run = http.run(body["run_id"])
    assert (run["covered_from"], run["covered_through"]) == ("2026-08-05", "2026-08-07")
    f = http.facts(card)
    assert (f["anchored"], f["synced"], f["synced_through"]) == (False, True, "2026-08-07")
    assert f["unexplained_difference"] is None
    assert api.one("SELECT count(*) FROM source_transaction WHERE source_format = 'csv:synthetic'")[0] == 0
    again = http.upload_ok(instance, card, card_b_bytes())
    assert again["summary"]["inserted"] == 0 and again["summary"]["skipped_by_identity"] == 3


# ---- refusals and failures ---------------------------------------------------------------


def test_a_currency_mismatch_fails_the_run_and_writes_nothing_else(api: Api):
    http = Http(api)
    instance, account = _giro_world(http)
    usd = giro_bytes().replace(b";EUR\n", b";USD\n").replace(b";EUR;", b";EUR;")
    before = api.counts()
    dry = http.upload(instance, account, usd, dry_run=True)
    assert dry.status_code == 200, dry.text
    assert (dry.json()["failure"]["kind"], dry.json()["failure"]["rule"]) == (
        "contract_violation",
        "currency_mismatch",
    )
    assert api.counts() == before
    real = http.upload(instance, account, usd)
    err = error_of(real, 422, "contract_violation")
    assert err["details"] == {"rule": "currency_mismatch"} and PRIVATE not in real.text
    counts = api.counts()
    assert counts["import_run"] == before["import_run"] + 1
    assert (counts["source_transaction"], counts["ledger_entry"], counts["balance_record"]) == (0, 0, 0)
    failed = api.client.get(RUNS, params={"status": "failed"}).json()
    assert len(failed) == 1 and failed[0]["account_id"] == account and failed[0]["revertible"] is False
    http.check()


def test_unlinked_and_closed_accounts_refuse_the_upload(api: Api):
    http = Http(api)
    instance, account = _giro_world(http)
    other = http.create_account("Not linked")
    before = api.counts()
    for dry_run in (True, False):
        error_of(http.upload(instance, other, giro_bytes(), dry_run=dry_run), 409, "account_not_linked")
    r = api.client.post(f"/api/ledger/accounts/{account}/close", json={"closed_on": "2026-08-01"})
    assert r.status_code == 200, r.text
    for dry_run in (True, False):
        error_of(http.upload(instance, account, giro_bytes(), dry_run=dry_run), 409, "account_closed")
    assert api.counts() == before
    http.check()


def test_a_user_authored_row_before_linking_is_counted_and_never_deduplicated(api: Api):
    http = Http(api)
    account = http.create_account("Giro")
    # entered by hand before the account was ever linked: the same -10,00 on the 20th the file lists
    with api.engine.begin() as conn:
        src = make_source(conn, account, importer=None, amount=-1000, booked_on=D(2026, 8, 20))
        make_entry(conn, src)
    http.check()
    assert http.facts(account)["synced"] is False

    instance = http.create_instance("consorsbank_giro")
    url = f"{BASE}/{instance}/links"
    preview = api.client.post(url, json={"account_id": account, "dry_run": True}).json()
    assert preview["user_authored_count"] == 1
    assert (preview["first_booked_on"], preview["last_booked_on"]) == ("2026-08-20", "2026-08-20")
    assert preview["warnings"] and "not deduplicated" in preview["warnings"][0]
    real = http.link(instance, account)
    assert real["user_authored_count"] == 1 and real["account_becomes_synced"] is True

    body = http.upload_ok(instance, account, giro_bytes())
    # all three file rows are inserted, the lookalike -10,00 included: nothing dedups against a user row
    assert body["summary"]["inserted"] == 3 and body["summary"]["skipped_by_identity"] == 0
    with api.engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM source_transaction WHERE account_id = :a AND amount = -1000"),
            {"a": account},
        ).scalar_one()
    assert n == 2
    assert [e for e in http.entries(account) if e[2] == D(2026, 8, 20)] == [
        ("movement", -1000, D(2026, 8, 20)),
        ("movement", -1000, D(2026, 8, 20)),
    ]
    # the opening sums movements up to the anchor (19.) only: the user's row on the 20th is after it
    assert ("opening", -20994, D(2026, 8, 17)) in http.entries(account)
    assert http.records(account) == [GIRO_RECORD]
    # and a second delivery dedups against the file's rows, not against the hand-made one
    again = http.upload_ok(instance, account, giro_bytes())
    assert again["summary"]["inserted"] == 0 and again["summary"]["skipped_by_identity"] == 3
