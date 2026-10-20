"""The FinTS importer's logic against a fake `BankSession`: prompts, the code table, the learned
`tan_for`, discovery, and a fetch's mapping (fints.md §1 to §9). No library, no bank."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.core.plugins.errors import (
    AccountUnsupported,
    AuthRejected,
    BankSetupRequired,
    ChallengeAbandoned,
    InvalidProfile,
    NotRegistered,
    ParseFailed,
    SourceUnavailable,
)
from app.core.plugins.fetch import ChoicePrompt, FetchImporter, Option, TanPrompt, TextPrompt
from app.plugins.importers.fints import FintsImporter
from app.plugins.importers.fints.bank import BankLogin, CardAnswer, CardBalance, Challenge, Procedure
from tests.plugins.importers.fints.fakebank import Asker, Dialog, FakeBank, card_upd, rc, upd
from tests.plugins.importers.fints.wire import CARD

TODAY = date(2026, 11, 1)  # the request runs to the 31st
IBAN = "DE02120300000000202051"
SETTINGS = {"url": "https://bank.invalid/fints", "bank_code": "12030000", "user_id": "alice"}
CORPUS = Path(__file__).parent / "statements"
STATEMENTS = (CORPUS / "dk_basic.sta").read_text(encoding="latin-1")
SINGLE = [Procedure("900", "photoTAN")]
BOTH = [Procedure("999", "Einschritt"), Procedure("900", "photoTAN"), Procedure("901", "SecureGo")]


def make(bank: FakeBank, *, product_id: str | None = "PID") -> tuple[FintsImporter, list[BankLogin]]:
    logins: list[BankLogin] = []

    def connect(login: BankLogin) -> FakeBank:
        logins.append(login)
        return bank

    return FintsImporter(product_id, "0.1.0-dev", connect=connect), logins


def open_session(
    bank: FakeBank,
    *answers: Any,
    state: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    product_id: str | None = "PID",
) -> tuple[Any, Asker, dict[str, Any], list[BankLogin]]:
    importer, logins = make(bank, product_id=product_id)
    asker = Asker("123456", *answers)
    state = {} if state is None else state
    session = importer.open(SETTINGS if settings is None else settings, state, asker, today=TODAY)
    return session, asker, state, logins


def fetch(session: Any, ref: str = IBAN, since: date = date(2026, 10, 1)) -> Any:
    return session.fetch_account(ref, since=since, today=TODAY, currency="EUR", minor_units_of=lambda c: 2)


def refused(bank: FakeBank, exc: type[Exception], **kw: Any) -> pytest.ExceptionInfo[Exception]:
    session, *_ = open_session(bank, **kw)
    with pytest.raises(exc) as err:
        fetch(session)
    return err


# ---- shape and settings ------------------------------------------------------------------------------


def test_it_is_a_fetch_importer_for_transactions_only() -> None:
    importer, _ = make(FakeBank(Dialog()))
    assert isinstance(importer, FetchImporter)
    assert importer.emits == frozenset({"transactions"}) and importer.providers == frozenset()


def test_valid_settings_pass_and_the_customer_id_is_optional() -> None:
    importer, _ = make(FakeBank(Dialog()))
    importer.validate_settings(SETTINGS)
    importer.validate_settings({**SETTINGS, "customer_id": ""})
    importer.validate_settings({**SETTINGS, "customer_id": "4711"})


@pytest.mark.parametrize(
    ("change", "key"),
    [
        ({"url": "http://bank.invalid/fints"}, "url"),
        ({"url": "https://user:secret@bank.invalid/fints"}, "url"),
        ({"url": "https:///fints"}, "url"),
        ({"url": "ftp://bank.invalid"}, "url"),
        ({"url": None}, "url"),
        ({"bank_code": "1203000"}, "bank_code"),
        ({"bank_code": "1203000a"}, "bank_code"),
        ({"bank_code": None}, "bank_code"),
        ({"user_id": "  "}, "user_id"),
        ({"user_id": None}, "user_id"),
        ({"customer_id": 4711}, "customer_id"),
        ({"pin": "123456"}, "pin"),
        ({"password": "x"}, "password"),
    ],
)
def test_a_bad_setting_is_refused_naming_it(change: dict[str, Any], key: str) -> None:
    importer, _ = make(FakeBank(Dialog()))
    settings = {**SETTINGS, **change}
    settings = {k: v for k, v in settings.items() if v is not None}
    with pytest.raises(InvalidProfile) as err:
        importer.validate_settings(settings)
    assert str(err.value).startswith(f"{key}:")
    assert "secret" not in str(err.value)  # never echoes a value


def test_the_default_fetch_start_is_ninety_days_before_today() -> None:
    importer, _ = make(FakeBank(Dialog()))
    assert importer.default_fetch_start(SETTINGS, today=date(2026, 11, 1)) == date(2026, 8, 3)


# ---- registration and the PIN ---------------------------------------------------------------------------


def test_without_a_product_id_open_raises_not_registered_before_any_prompt() -> None:
    bank = FakeBank(Dialog())
    importer, logins = make(bank, product_id=None)
    asker = Asker()
    with pytest.raises(NotRegistered, match="FINTS_PRODUCT_ID"):
        importer.open(SETTINGS, {}, asker, today=TODAY)
    assert asker.asked == [] and logins == []


def test_the_pin_is_asked_first_and_reaches_the_bank_as_a_secret_with_the_product() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE)
    _, asker, _, logins = open_session(bank, settings={**SETTINGS, "customer_id": " 4711 "})
    assert asker.kinds() == ["pin"]
    (login,) = logins
    assert login.pin.reveal() == "123456" and "123456" not in repr(login)
    assert (login.url, login.bank_code, login.user_id, login.customer_id) == (
        "https://bank.invalid/fints",
        "12030000",
        "alice",
        "4711",
    )
    assert (login.product_id, login.product_version) == (
        "PID",
        "0.1.0",
    )  # five characters, the field's length


def test_an_empty_customer_id_means_none() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE)
    _, _, _, logins = open_session(bank, settings={**SETTINGS, "customer_id": ""})
    assert logins[0].customer_id is None


# ---- the TAN procedure and the medium --------------------------------------------------------------------


def test_one_allowed_procedure_is_taken_without_asking_and_remembered() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE)
    _, asker, state, _ = open_session(bank)
    assert asker.kinds() == ["pin"] and bank.used_procedure == "900"
    assert state["tan_mechanism"] == "900" and bank.setup_finished


def test_several_procedures_are_a_choice_by_code_and_name_and_the_one_step_one_is_not_offered() -> None:
    bank = FakeBank(Dialog(), procedures=BOTH)
    _, asker, state, _ = open_session(bank, "901")
    choice = asker.asked[1]
    assert isinstance(choice, ChoicePrompt) and choice.subject == "tan_mechanism"
    assert choice.options == (Option("900", "photoTAN"), Option("901", "SecureGo"))
    assert bank.used_procedure == "901" and state["tan_mechanism"] == "901"


def test_a_remembered_procedure_is_not_asked_again() -> None:
    bank = FakeBank(Dialog(), procedures=BOTH)
    _, asker, state, _ = open_session(bank, state={"tan_mechanism": "900"})
    assert asker.kinds() == ["pin"] and bank.used_procedure == "900" and state["tan_mechanism"] == "900"


def test_a_remembered_procedure_the_bank_no_longer_lists_is_dropped_and_asked_afresh() -> None:
    bank = FakeBank(Dialog(), procedures=BOTH)
    _, asker, state, _ = open_session(bank, "901", state={"tan_mechanism": "777", "tan_medium": "Old phone"})
    assert asker.kinds() == ["pin", "tan_mechanism"]
    assert state["tan_mechanism"] == "901" and "tan_medium" not in state


def test_a_bank_that_allows_only_the_one_step_procedure_is_not_asked_and_nothing_is_remembered() -> None:
    bank = FakeBank(Dialog(), procedures=[Procedure("999", "Einschritt")])
    _, asker, state, _ = open_session(bank)
    assert asker.kinds() == ["pin"] and bank.used_procedure == "999" and "tan_mechanism" not in state


def test_a_bank_that_lists_no_procedure_goes_on_one_step_and_lets_the_bank_say() -> None:
    bank = FakeBank(Dialog(), procedures=[])
    _, _, state, _ = open_session(bank)
    assert bank.used_procedure == "999" and state == {}


def test_a_cancelled_or_invalid_procedure_choice_ends_the_open() -> None:
    bank = FakeBank(Dialog(), procedures=BOTH)
    with pytest.raises(ChallengeAbandoned):
        open_session(bank, "555")
    assert bank.closed  # the session is released when open fails


def test_a_required_medium_is_a_choice_from_the_banks_list_and_remembered() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE, medium_required=True, media=["iPhone", "iPad"])
    _, asker, state, _ = open_session(bank, "iPad")
    choice = asker.asked[1]
    assert isinstance(choice, ChoicePrompt) and choice.subject == "tan_medium"
    assert choice.options == (Option("iPhone", "iPhone"), Option("iPad", "iPad"))
    assert state["tan_medium"] == "iPad" and bank.used_media == ["iPad"]


def test_a_single_medium_is_taken_without_asking() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE, medium_required=True, media=["iPhone"])
    _, asker, state, _ = open_session(bank)
    assert asker.kinds() == ["pin"] and state["tan_medium"] == "iPhone"


def test_a_remembered_medium_is_used_and_the_list_is_not_fetched() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE, medium_required=True, media=["iPhone", "iPad"])
    _, asker, _, logins = open_session(bank, state={"tan_mechanism": "900", "tan_medium": "iPad"})
    assert asker.kinds() == ["pin"] and bank.listed_media == 0 and bank.used_media == ["iPad"]
    assert logins[0].tan_medium == "iPad"


@pytest.mark.parametrize(
    "listing", [{"media": None}, {"media": []}, {"media_codes": [rc("9210", "Name fehlt")]}]
)
def test_a_medium_the_bank_does_not_list_is_asked_as_text(listing: dict[str, Any]) -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE, medium_required=True, **listing)
    _, asker, state, _ = open_session(bank, "  My Phone ")
    assert isinstance(asker.asked[1], TextPrompt) and asker.asked[1].subject == "tan_medium_name"
    assert state["tan_medium"] == "My Phone" and bank.used_media == ["My Phone"]


def test_a_medium_that_is_not_needed_is_never_asked() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE, medium_required=False)
    _, asker, state, _ = open_session(bank)
    assert asker.kinds() == ["pin"] and "tan_medium" not in state and bank.listed_media == 0


def test_a_wrong_pin_while_listing_the_procedures_is_auth_rejected() -> None:
    bank = FakeBank(Dialog(), procedures_codes=[rc("9931", "Anmeldename oder PIN falsch")])
    with pytest.raises(AuthRejected):
        open_session(bank)
    assert bank.closed


def test_any_other_failure_while_listing_media_is_mapped_by_the_table() -> None:
    bank = FakeBank(
        Dialog(), procedures=SINGLE, medium_required=True, media_codes=[rc("9940", "kein Geraet")]
    )
    with pytest.raises(BankSetupRequired):
        open_session(bank)


# ---- the table of the bank's answers ----------------------------------------------------------------------


def test_a_successful_dialog_with_warnings_is_not_an_error() -> None:
    bank = FakeBank(
        Dialog(
            login_codes=[
                rc("0010"),
                rc("0020"),
                rc("3060", "Bitte beachten"),
                rc("3076", "keine SCA"),
                rc("3920"),
            ],
            request_codes=[rc("3010", "Es liegen keine Eintraege vor")],
            text="",
        ),
        procedures=SINGLE,
    )
    session, *_ = open_session(bank)
    result = fetch(session)
    assert (
        result.rows == () and result.reported_balance is None and result.covered_through == date(2026, 10, 31)
    )


@pytest.mark.parametrize("code", ["9931", "9942", "9040"])
def test_a_wrong_pin_is_auth_rejected_at_once_and_never_retried(code: str) -> None:
    bank = FakeBank(Dialog(fail_login=[rc(code, "Anmeldename oder PIN falsch")]), procedures=SINGLE)
    err = refused(bank, AuthRejected)
    assert bank.opened == 1 and bank.requests == []
    assert code in str(err.value) and "lock" in str(err.value) and "Anmeldename" in str(err.value)


def test_a_refusal_in_the_login_answer_without_an_exception_sends_no_request() -> None:
    bank = FakeBank(Dialog(login_codes=[rc("0010"), rc("9942", "PIN ungueltig")]), procedures=SINGLE)
    refused(bank, AuthRejected)
    assert bank.opened == 1 and bank.requests == []


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (["9930"], BankSetupRequired),
        (["3938"], BankSetupRequired),
        (["9940"], BankSetupRequired),
        (["9960"], BankSetupRequired),
        (["9110"], ParseFailed),
        (["9120"], ParseFailed),
        (["9160"], ParseFailed),
        (["9010"], SourceUnavailable),
        (["9999"], SourceUnavailable),
        (["9340"], SourceUnavailable),
        (["9931", "9940"], AuthRejected),  # the PIN comes first
        (["9940", "9010"], BankSetupRequired),
    ],
)
def test_the_code_table(codes: list[str], expected: type[Exception]) -> None:
    bank = FakeBank(Dialog(fail=[rc(c, f"Text {c}") for c in codes]), procedures=SINGLE)
    err = refused(bank, expected)
    assert codes[0] in str(err.value)  # the code and the bank's own text
    assert f"Text {codes[0]}" in str(err.value) or expected is AuthRejected
    assert bank.opened == 1  # none of these is retried


def test_an_unmapped_refusal_names_the_code_and_the_text() -> None:
    bank = FakeBank(Dialog(fail=[rc("9010", "Verarbeitung nicht moeglich")]), procedures=SINGLE)
    err = refused(bank, SourceUnavailable)
    assert "9010 Verarbeitung nicht moeglich" in str(err.value)


def test_an_empty_result_is_never_success_when_the_bank_refused() -> None:
    bank = FakeBank(
        Dialog(request_codes=[rc("9010", "Verarbeitung nicht moeglich")], text=""), procedures=SINGLE
    )
    refused(bank, SourceUnavailable)


def test_a_library_failure_without_a_code_is_parse_failed_naming_the_exception_class_only() -> None:
    bank = FakeBank(Dialog(fail=[]), procedures=SINGLE)
    err = refused(bank, ParseFailed)
    assert "FinTSSCARequiredError" in str(err.value)


def test_a_wrong_pin_in_a_discovery_dialog_is_auth_rejected() -> None:
    bank = FakeBank(Dialog(fail_login=[rc("9931")]), procedures=SINGLE)
    session, *_ = open_session(bank)
    with pytest.raises(AuthRejected):
        session.accounts()


# ---- 9075: learned per bank -------------------------------------------------------------------------------


def sca_then_ok() -> FakeBank:
    return FakeBank(
        Dialog(fail=[rc("9075", "Starke Authentifizierung erforderlich")]),
        Dialog(text=STATEMENTS, request_codes=[rc("3076", "keine SCA")]),
        procedures=SINGLE,
    )


def test_a_plain_request_answered_9075_is_repeated_once_with_a_tan_request_and_the_type_is_learned() -> None:
    bank = sca_then_ok()
    session, _, state, _ = open_session(bank)
    result = fetch(session)
    assert [r[3] for r in bank.requests] == [False, True]
    assert state["tan_for"] == ["HKKAZ"]
    assert len(result.rows) == 2 and bank.opened == 2


def test_a_learned_type_goes_out_with_the_tan_request_from_the_start() -> None:
    bank = FakeBank(Dialog(text=STATEMENTS), procedures=SINGLE)
    session, _, _, _ = open_session(bank, state={"tan_for": ["HKKAZ"]})
    fetch(session)
    assert [r[3] for r in bank.requests] == [True] and bank.opened == 1


def test_a_9075_that_remains_after_the_attached_request_is_not_retried() -> None:
    bank = FakeBank(Dialog(fail=[rc("9075", "Starke Authentifizierung erforderlich")]), procedures=SINGLE)
    session, _, state, _ = open_session(bank)
    with pytest.raises(SourceUnavailable) as err:
        fetch(session)
    assert [r[3] for r in bank.requests] == [False, True] and "9075" in str(err.value)
    assert "tan_for" not in state  # nothing learned from a failure


def test_a_9075_with_9940_after_the_attached_request_is_bank_setup_required() -> None:
    bank = FakeBank(
        Dialog(fail=[rc("9075", "SCA"), rc("9940", "Kein aktives TAN-Geraet")]), procedures=SINGLE
    )
    refused(bank, BankSetupRequired)
    assert bank.opened == 2


def test_the_learned_type_is_kept_when_a_later_run_fails_for_another_reason() -> None:
    bank = FakeBank(Dialog(text=STATEMENTS), procedures=SINGLE)
    _, _, state, _ = open_session(bank, state={"tan_for": ["HKKAZ", "HKSAL"]})
    assert state["tan_for"] == ["HKKAZ", "HKSAL"]


def test_discovery_does_not_retry_a_9075() -> None:
    bank = FakeBank(Dialog(login_codes=[rc("9075", "SCA")]), procedures=SINGLE)
    session, *_ = open_session(bank)
    with pytest.raises(SourceUnavailable):
        session.accounts()
    assert bank.opened == 1


# ---- 9210 at login -----------------------------------------------------------------------------


def test_a_medium_name_refused_at_login_is_asked_once_as_text_and_the_dialog_repeated() -> None:
    bank = FakeBank(
        Dialog(login_codes=[rc("9210", "Name des TAN-Mediums erforderlich")]),
        Dialog(text=STATEMENTS),
        procedures=SINGLE,
        medium_required=True,
        media=["iPhone", "iPad"],
    )
    session, asker, state, _ = open_session(bank, "iPhone", "My Phone")
    result = fetch(session)
    assert asker.kinds() == ["pin", "tan_medium", "tan_medium_name"]
    assert state["tan_medium"] == "My Phone" and bank.used_media == ["iPhone", "My Phone"]
    assert len(result.rows) == 2 and bank.opened == 2


def test_a_medium_name_refused_again_is_bank_setup_required_and_asks_no_third_time() -> None:
    bank = FakeBank(
        Dialog(login_codes=[rc("9210", "Name des TAN-Mediums erforderlich")]),
        procedures=SINGLE,
        medium_required=True,
        media=None,
    )
    session, asker, _, _ = open_session(bank, "My Phone")  # asked once at setup, the list being empty
    with pytest.raises(BankSetupRequired):
        fetch(session)
    assert asker.kinds() == ["pin", "tan_medium_name"] and bank.opened == 1


# ---- TAN challenges ----------------------------------------------------------------------------


def test_a_login_challenge_in_text_is_a_tan_prompt_and_the_answer_is_revealed_to_the_bank_only() -> None:
    challenge = Challenge("text", "Bitte TAN eingeben", "photoTAN")
    bank = FakeBank(Dialog(challenge=challenge, text=STATEMENTS), procedures=SINGLE)
    session, asker, _, _ = open_session(bank, "987654")
    fetch(session)
    prompt = asker.asked[1]
    assert prompt == TanPrompt("text", "Bitte TAN eingeben", "photoTAN")
    assert bank.answers == ["987654"]


def test_a_photo_challenge_carries_its_image() -> None:
    challenge = Challenge("image", "Scannen", "photoTAN", b"\x89PNG", "image/png")
    bank = FakeBank(Dialog(challenge=challenge, text=STATEMENTS), procedures=SINGLE)
    session, asker, _, _ = open_session(bank, "1")
    fetch(session)
    prompt = asker.asked[1]
    assert isinstance(prompt, TanPrompt) and (prompt.medium, prompt.image, prompt.image_mime) == (
        "image",
        b"\x89PNG",
        "image/png",
    )


def test_a_decoupled_challenge_hands_the_banks_poll_to_the_prompter() -> None:
    challenge = Challenge("decoupled", "In der App bestaetigen", "SecureGo")
    bank = FakeBank(Dialog(challenge=challenge, text=STATEMENTS), procedures=SINGLE)
    bank.polls_left = 2
    session, asker, _, _ = open_session(bank)
    fetch(session)
    assert asker.kinds()[1] == "tan:decoupled" and bank.polls_left == 0
    assert bank.answers == [None]


def test_a_challenge_answered_by_cancelling_ends_the_dialog_with_the_prompters_error() -> None:
    class Cancels(Asker):
        def ask(self, prompt: Any, **kw: Any) -> Any:
            if isinstance(prompt, TanPrompt):
                raise ChallengeAbandoned("cancelled")
            return super().ask(prompt, **kw)

    bank = FakeBank(Dialog(challenge=Challenge("text", "TAN", None)), procedures=SINGLE)
    importer, _ = make(bank)
    session = importer.open(SETTINGS, {}, Cancels("123456"), today=TODAY)
    with pytest.raises(ChallengeAbandoned):
        fetch(session)


# ---- discovery ---------------------------------------------------------------------------------


def test_discovery_maps_the_banks_account_list() -> None:
    rows = [
        upd(),
        upd(iban=" de02 1203 0000 0000 2020 52 ", number="0000202052", name=None, kind=12, currency=None),
        upd(iban=None, number="777", sub="01", name="Tagesgeld", kind=15),
        upd(iban=None, number="888", sub=None, name="Depot", kind=None, statements=False),
        upd(iban=None, number=None, name="Platzhalter"),  # a row without an account number
        upd(iban=None, number="999", name=None, kind=40, currency="USD", statements=False),
    ]
    bank = FakeBank(Dialog(accounts=rows), procedures=SINGLE)
    session, *_ = open_session(bank)
    found = session.accounts()
    assert [(a.external_ref, a.name, a.currency, a.kind_hint, sorted(a.capabilities)) for a in found] == [
        (IBAN, "Girokonto", "EUR", "checking", ["balance", "transactions"]),
        ("DE02120300000000202052", "0000202052", None, "savings", ["balance", "transactions"]),
        ("777/01", "Tagesgeld", "EUR", "savings", ["balance", "transactions"]),
        ("888", "Depot", "EUR", None, []),
        ("999", "999", "USD", None, []),
    ]
    assert bank.opened == 1  # one dialog, no HKSPA


@pytest.mark.parametrize(
    ("kind", "hint"),
    [
        (1, "checking"),
        (9, "checking"),
        (10, "savings"),
        (19, "savings"),
        (30, "depot"),
        (39, "depot"),
        (50, "card"),
        (59, "card"),
        (0, None),
        (20, None),
        (40, None),
        (None, None),
    ],
)
def test_the_kind_hint_follows_the_banks_account_type(kind: int | None, hint: str | None) -> None:
    bank = FakeBank(Dialog(accounts=[upd(kind=kind)]), procedures=SINGLE)
    session, *_ = open_session(bank)
    assert session.accounts()[0].kind_hint == hint


# ---- fetching ----------------------------------------------------------------------------------


def test_a_fetch_asks_for_since_to_the_day_before_today_and_maps_the_statements() -> None:
    bank = FakeBank(Dialog(text=STATEMENTS), procedures=SINGLE)
    session, *_ = open_session(bank)
    result = fetch(session, since=date(2026, 10, 1))
    (account, since, until, with_tan) = bank.requests[0]
    assert (account.iban, since, until, with_tan) == (IBAN, date(2026, 10, 1), date(2026, 10, 31), False)
    assert (result.covered_from, result.covered_through) == (date(2026, 10, 1), date(2026, 10, 31))
    assert [r.amount_minor for r in result.rows] == [-1234, 10000]
    assert (result.reported_balance, result.balance_on) == (108766, date(2026, 10, 5))
    assert dict(result.importer_stats) == {"filtered": 0}


def test_a_since_after_the_closed_day_is_lifted_so_the_request_is_never_empty_ranged() -> None:
    bank = FakeBank(Dialog(text=""), procedures=SINGLE)
    session, *_ = open_session(bank)
    result = fetch(session, since=date(2026, 11, 5))
    assert bank.requests[0][1:3] == (date(2026, 10, 31), date(2026, 10, 31))
    assert result.covered_from == date(2026, 10, 31) and result.covered_through == date(2026, 10, 31)


def test_the_coverage_is_the_day_before_today_whether_or_not_rows_came_back() -> None:
    bank = FakeBank(Dialog(text="", request_codes=[rc("3010", "keine Eintraege")]), procedures=SINGLE)
    session, *_ = open_session(bank)
    result = fetch(session)
    assert result.rows == () and result.covered_through == date(2026, 10, 31)
    assert result.reported_balance is None and result.balance_on is None


def test_an_account_the_bank_does_not_list_is_unsupported_before_any_request() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE)
    session, *_ = open_session(bank)
    with pytest.raises(AccountUnsupported):
        fetch(session, ref="DE89370400440532013000")
    assert bank.requests == []


def test_an_account_listed_without_the_statement_request_is_unsupported() -> None:
    bank = FakeBank(Dialog(accounts=[upd(statements=False)]), procedures=SINGLE)
    session, *_ = open_session(bank)
    with pytest.raises(AccountUnsupported):
        fetch(session)
    assert bank.requests == []


def test_the_account_is_found_by_account_number_and_sub_account_where_the_bank_gives_no_iban() -> None:
    bank = FakeBank(
        Dialog(accounts=[upd(iban=None, number="777", sub="01")], text=STATEMENTS), procedures=SINGLE
    )
    session, *_ = open_session(bank)
    fetch(session, ref="777/01")
    assert bank.requests[0][0].account_number == "777"


def test_a_statement_that_does_not_add_up_fails_the_run_as_parse_failed() -> None:
    text = (CORPUS / "unbalanced.sta").read_text(encoding="latin-1")
    bank = FakeBank(Dialog(text=text), procedures=SINGLE)
    session, *_ = open_session(bank)
    with pytest.raises(ParseFailed):
        fetch(session)


def test_the_importer_fetches_no_documents() -> None:
    session, *_ = open_session(FakeBank(Dialog(), procedures=SINGLE))
    with pytest.raises(AccountUnsupported):
        session.fetch_documents(since=date(2026, 1, 1), today=TODAY)


# ---- state and logs ----------------------------------------------------------------------------


def test_the_state_holds_the_four_scalars_and_nothing_else() -> None:
    bank = FakeBank(
        Dialog(fail=[rc("9075", "SCA")], system_id="SYS1"),
        Dialog(text=STATEMENTS),
        procedures=BOTH,
        medium_required=True,
        media=["iPhone", "iPad"],
    )
    session, _, state, _ = open_session(bank, "900", "iPad")
    fetch(session)
    assert state == {"tan_mechanism": "900", "tan_medium": "iPad", "tan_for": ["HKKAZ"], "system_id": "SYS1"}
    assert not any("123456" in str(v) for v in state.values())  # no PIN


def test_a_system_id_the_bank_assigns_while_the_run_fails_is_still_kept() -> None:
    bank = FakeBank(Dialog(system_id="SYS2", fail=[rc("9010", "x")]), procedures=SINGLE)
    session, _, state, _ = open_session(bank)
    with pytest.raises(SourceUnavailable):
        fetch(session)
    assert state["system_id"] == "SYS2"


def test_a_remembered_system_id_goes_to_the_bank() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE)
    _, _, _, logins = open_session(bank, state={"system_id": "SYS3"})
    assert logins[0].system_id == "SYS3"


def test_close_releases_the_bank_session() -> None:
    bank = FakeBank(Dialog(), procedures=SINGLE)
    session, *_ = open_session(bank)
    session.close()
    assert bank.closed


def test_only_return_codes_and_texts_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    bank = FakeBank(
        Dialog(
            login_codes=[rc("0010", "Nachricht entgegengenommen"), rc("3076", "keine SCA")], text=STATEMENTS
        ),
        procedures=SINGLE,
    )
    session, *_ = open_session(bank)
    with caplog.at_level(logging.DEBUG):
        fetch(session)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "3076 keine SCA" in logged
    for private in ("123456", "alice", IBAN, "PAYEE", "E2E-0001", "Miete"):
        assert private not in logged


# ---- credit cards (fints.md §6a) ------------------------------------------------------------------------

CARD_REF = f"{CARD}/01"


def booking(booked: str, amount: str, direction: str = "D", **more: str) -> dict[str, str]:
    return {
        "booking_date": booked,
        "amount": amount,
        "currency": "EUR",
        "direction": direction,
        "merchant_name": "SHOP",
        "billed": "J",
        **more,
    }


def card_answer(*entries: dict[str, str], balance: CardBalance | None = None) -> CardAnswer:
    return CardAnswer(balance, tuple(entries))


def card_bank(*dialogs: Dialog) -> FakeBank:
    return FakeBank(*dialogs, procedures=SINGLE)


def test_a_card_row_is_discovered_by_its_card_number_and_sub_account_with_the_card_hint() -> None:
    bank = card_bank(Dialog(accounts=[upd(), card_upd(), upd(iban=None, number="888", statements=False)]))
    session, *_ = open_session(bank)
    found = session.accounts()
    assert [(a.external_ref, a.name, a.currency, a.kind_hint, sorted(a.capabilities)) for a in found] == [
        (IBAN, "Girokonto", "EUR", "checking", ["balance", "transactions"]),
        (CARD_REF, "Credit Card", "EUR", "card", ["balance", "transactions"]),
        ("888", "Girokonto", "EUR", "checking", []),
    ]


def test_a_card_fetch_sends_the_card_request_not_the_statement_request_and_maps_the_answer() -> None:
    answer = card_answer(
        booking("20261012", "12,50", description_1="Kaffee", value_date="20261014"),
        booking("20261014", "9,20", "C", original_amount="10,00", original_currency="USD"),
    )
    bank = card_bank(Dialog(accounts=[card_upd()], card=answer))
    session, *_ = open_session(bank)
    result = fetch(session, ref=CARD_REF, since=date(2026, 10, 1))
    assert bank.requests == []
    ((account, since, until, with_tan),) = bank.card_requests
    assert (account.account_number, with_tan) == (CARD, False)
    assert (since, until) == (date(2026, 10, 1), date(2026, 10, 31))
    assert [(r.amount_minor, r.source_format, r.source_id) for r in result.rows] == [
        (-1250, "hkkku", None),
        (920, "hkkku", None),
    ]
    assert result.rows[1].instructed_amount_minor == 1000
    assert (result.covered_from, result.covered_through) == (date(2026, 10, 1), date(2026, 10, 31))
    assert result.reported_balance is None
    assert dict(result.importer_stats) == {"filtered": 0}


def test_unbilled_entries_hold_the_coverage_and_the_balance_is_the_booked_one_rolled_back() -> None:
    answer = card_answer(
        booking("20261020", "40,00"),
        booking("20261029", "15,00"),
        booking("20261028", "12,50", billed="N"),
        booking("20261030", "7,50", billed="N"),
        balance=CardBalance("D", "500,00", "EUR", "20261030"),
    )
    bank = card_bank(Dialog(accounts=[card_upd()], card=answer))
    session, *_ = open_session(bank)
    result = fetch(session, ref=CARD_REF)
    assert [r.amount_minor for r in result.rows] == [-4000, -1500]  # the unbilled are not imported
    assert result.covered_through == date(2026, 10, 27)
    assert (result.reported_balance, result.balance_on) == (-46500, date(2026, 10, 27))


def test_a_card_request_answered_9075_is_repeated_with_a_tan_request_and_hkkku_is_learned() -> None:
    bank = card_bank(
        Dialog(accounts=[card_upd()], fail=[rc("9075", "Starke Authentifizierung erforderlich")]),
        Dialog(accounts=[card_upd()], card=card_answer(booking("20261012", "1,00"))),
    )
    session, _, state, _ = open_session(bank)
    result = fetch(session, ref=CARD_REF)
    assert [r[3] for r in bank.card_requests] == [False, True]
    assert state["tan_for"] == ["HKKKU"] and len(result.rows) == 1


def test_a_learned_card_request_goes_out_with_the_tan_request_and_the_statement_request_does_not() -> None:
    bank = card_bank(Dialog(accounts=[card_upd(), upd()], card=card_answer(), text=STATEMENTS))
    session, _, _, _ = open_session(bank, state={"tan_for": ["HKKKU"]})
    fetch(session, ref=CARD_REF)
    fetch(session)
    assert [r[3] for r in bank.card_requests] == [True] and [r[3] for r in bank.requests] == [False]


def test_a_row_that_lists_both_requests_is_fetched_by_its_account_type() -> None:
    both = [
        upd(iban=None, number="111", kind=1, statements=True, cards=True),
        upd(iban=None, number="222", kind=50, statements=True, cards=True),
    ]
    bank = card_bank(Dialog(accounts=both, text=STATEMENTS, card=card_answer(booking("20261012", "1,00"))))
    session, *_ = open_session(bank)
    fetch(session, ref="111")
    fetch(session, ref="222")
    assert [r[0].account_number for r in bank.requests] == ["111"]
    assert [r[0].account_number for r in bank.card_requests] == ["222"]


def test_an_account_listed_with_neither_request_is_unsupported_and_the_message_names_no_number() -> None:
    bank = card_bank(Dialog(accounts=[upd(iban=None, number=CARD, sub="01", statements=False, cards=False)]))
    session, *_ = open_session(bank)
    with pytest.raises(AccountUnsupported) as err:
        fetch(session, ref=CARD_REF)
    assert CARD not in str(err.value) and bank.requests == [] and bank.card_requests == []


def test_an_entry_that_cannot_be_read_fails_the_run_without_the_card_number_or_the_amount() -> None:
    bank = card_bank(Dialog(accounts=[card_upd()], card=card_answer(booking("20261012", "12,505"))))
    session, *_ = open_session(bank)
    with pytest.raises(ParseFailed) as err:
        fetch(session, ref=CARD_REF)
    assert CARD not in str(err.value) and "12,505" not in str(err.value)


def test_a_refused_card_request_is_told_by_its_code_and_the_card_number_is_in_no_message() -> None:
    bank = card_bank(
        Dialog(accounts=[card_upd()], fail=[rc("9210", "Angabe der Kontoverbindung erforderlich")])
    )
    session, *_ = open_session(bank)
    with pytest.raises(Exception) as err:
        fetch(session, ref=CARD_REF)
    assert CARD not in str(err.value) and "9210" in str(err.value)


def test_a_card_fetch_logs_return_codes_and_texts_only_never_the_card_number(
    caplog: pytest.LogCaptureFixture,
) -> None:
    answer = card_answer(
        booking("20261012", "12,50", merchant_name="PAYEE-X", description_1="Kaffee"),
        balance=CardBalance("D", "500,00", "EUR", "20261030"),
    )
    bank = card_bank(
        Dialog(accounts=[card_upd()], login_codes=[rc("0010", "ok"), rc("3076", "keine SCA")], card=answer)
    )
    session, *_ = open_session(bank)
    with caplog.at_level(logging.DEBUG):
        fetch(session, ref=CARD_REF)
        session.accounts()
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "3076 keine SCA" in logged
    for private in (CARD, "123456", "alice", "PAYEE-X", "Kaffee", "12,50", "500,00"):
        assert private not in logged
