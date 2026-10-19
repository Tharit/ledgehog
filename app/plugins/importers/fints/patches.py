"""python-fints 5.0.1, carried with the fixes Consorsbank needed (fints.md §10).

Each fix is a subclass or a method here; no attribute of the `fints` package is assigned, so nothing
leaks to another user of the library. They use members the library keeps private
(`_need_twostep_tan_for_segment`, `_bootstrap_mode`, `_new_dialog`, `_fetch_with_touchdowns`,
`_standing_dialog`), which is why `fints` is pinned exactly and why every fix has a test of its
behaviour. **A fix is deleted when its test passes without it** (upstream: python-fints PR #218).

    P1  the signature segment carries PIN profile 2 for two-step procedures, as the envelope does
    P2  a login TAN challenge is detected from a HITAN, wherever the bank attached its 0030
    P3  setup ends (`finish_setup`): a 9075 raises instead of silently closing the dialog
    P4  the account connection of the statement request is complete (IBAN, number, sub-account, bank)
    P5  a TAN request is attached to the statement request when `tan_for` names its type
    P6  the raw booked MT940 text comes back (all pages), not the library's transaction list
    P7  every HTTP request has a timeout
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from typing import Any

import requests
from fints.client import (
    HKKAZ5,
    HKKAZ6,
    HKKAZ7,
    FinTS3PinTanClient,
    NeedTANResponse,
)
from fints.connection import FinTSHTTPSConnection
from fints.dialog import FinTSDialog
from fints.formals import KTI1, BankIdentifier, SecurityMethod, SecurityProfile
from fints.models import SEPAAccount
from fints.security import PinTanTwoStepAuthenticationMechanism
from fints.segments.dialog import HIRMG2, HIRMS2

from app.plugins.importers.fints.bank import ReturnCode

HTTP_TIMEOUT_S = 30
STATEMENT_REQUEST = "HKKAZ"


# ---- P7 ------------------------------------------------------------------------------------------


class _TimeoutSession(requests.Session):
    def request(self, *args: Any, **kwargs: Any) -> requests.Response:
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = HTTP_TIMEOUT_S
        return super().request(*args, **kwargs)


class LedgerConnection(FinTSHTTPSConnection):  # type: ignore[misc]
    """P7: the library's `session.post` has no timeout, so a stuck bank would hold a worker thread."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.session = _TimeoutSession()


# ---- P1 ------------------------------------------------------------------------------------------


class LedgerTwoStep(PinTanTwoStepAuthenticationMechanism):  # type: ignore[misc]
    """P1: the library signs two-step messages with PIN profile 1 while the envelope says 2; strict
    banks answer 9010 "invalid signature structure"."""

    def sign_prepare(self, message: Any) -> None:
        super().sign_prepare(message)
        self.pending_signature.security_profile = SecurityProfile(SecurityMethod.PIN, 2)


# ---- P2 ------------------------------------------------------------------------------------------


class LedgerDialog(FinTSDialog):  # type: ignore[misc]
    def init(self, *extra_segments: Any) -> Any:
        """P2: the bank may put its 0030 on the identification segment, not on the TAN segment the
        library looks at; the HITAN is then ignored and the next request dies with 9120."""
        retval = super().init(*extra_segments)
        client = self.client
        if retval is not None and client.init_tan_response is None:
            codes = {r.code for seg in retval.find_segments(HIRMS2) for r in seg.responses}
            hitan = retval.find_segment_first("HITAN")
            if hitan is not None and codes & {"0030", "3955"}:
                try:
                    structured = client.is_challenge_structured()
                except KeyError:  # a one-step procedure has no parameters; it cannot challenge anyway
                    structured = False
                client.init_tan_response = NeedTANResponse(
                    None, hitan, "_continue_dialog_initialization", structured, "3955" in codes
                )
        return retval


# ---- the client ----------------------------------------------------------------------------------


def _join_booked(responses: Iterable[Any]) -> str:
    # Banks split the data arbitrarily over the pages, so the text is joined before it is read. MT940
    # is SWIFT characters, a subset every ISO 8859 variant shares: latin-1 is as good as any.
    return "".join((seg.statement_booked or b"").decode("iso-8859-1") for seg in responses)


class LedgerClient(FinTS3PinTanClient):  # type: ignore[misc]
    """The patched client. `codes` collects every return code of every dialog (the library's own
    callbacks miss the dialog's internal sends, which carry the login's answers)."""

    def __init__(self, bank_identifier: str, user_id: str, pin: str, server: str, **kwargs: Any) -> None:
        super().__init__(bank_identifier, user_id, pin, server, **kwargs)
        self.connection = LedgerConnection(server)
        self.tan_for: set[str] = set()
        self.codes: list[ReturnCode] = []

    def _new_dialog(self, lazy_init: bool = False) -> LedgerDialog:
        base = super()._new_dialog(lazy_init=lazy_init)
        mechanisms = [
            LedgerTwoStep(m.client, m.security_function, m.pin)  # P1
            if isinstance(m, PinTanTwoStepAuthenticationMechanism)
            else m
            for m in base.auth_mechanisms
        ]
        return LedgerDialog(  # P2
            self, lazy_init=lazy_init, enc_mechanism=base.enc_mechanism, auth_mechanisms=mechanisms
        )

    def process_response_message(self, dialog: Any, message: Any, internal_send: bool = True) -> None:
        for seg in (*message.find_segments(HIRMG2), *message.find_segments(HIRMS2)):
            self.codes.extend(ReturnCode(r.code, r.text) for r in seg.responses)
        super().process_response_message(dialog, message, internal_send=internal_send)

    def __enter__(self) -> Any:
        # Housekeeping: a login that fails inside `__enter__` leaves the library believing a dialog
        # is standing, and every later `with client:` then refuses ("cannot double __enter__").
        try:
            return super().__enter__()
        except BaseException:
            self._standing_dialog = None
            raise

    def finish_setup(self) -> None:
        """P3: the library starts in "bootstrap mode", where a 9075 closes the dialog and the call
        returns nothing, i.e. a false "no transactions"."""
        self._bootstrap_mode = False

    def _need_twostep_tan_for_segment(self, seg: Any) -> bool:
        """P5: attach a TAN request to the types in `tan_for`, whatever the bank's own parameters
        (HIPINS) say: Consorsbank answers 9075 without one."""
        if seg.header.type in self.tan_for and self.get_current_tan_mechanism() not in (None, "999"):
            return True
        return bool(super()._need_twostep_tan_for_segment(seg))

    def account_field(self, hkkaz: Any, account: SEPAAccount) -> Any:
        """P4: the library's KTI1 carries IBAN and BIC only; Consorsbank answers 9010 unless the
        account number, sub-account and bank identifier are there too."""
        field_type = hkkaz._fields["account"].type
        if field_type is not KTI1:  # versions 5 and 6 build an account-number connection already
            return field_type.from_sepa_account(account)
        return KTI1(
            iban=account.iban,
            bic=account.bic,
            account_number=account.accountnumber,
            subaccount_number=account.subaccount or "",
            bank_identifier=BankIdentifier(
                country_identifier=self.bank_identifier.country_identifier,
                bank_code=account.blz or self.bank_identifier.bank_code,
            ),
        )

    def booked_statements(self, account: SEPAAccount, start: datetime.date, end: datetime.date) -> Any:
        """P6: the raw booked MT940 text of the range, pages joined by the library's own touchdown
        loop; a `NeedTANResponse` where the bank wants a TAN first. Must run in the standing dialog."""
        dialog = self._get_dialog()
        hkkaz = self._find_highest_supported_command(HKKAZ5, HKKAZ6, HKKAZ7)
        return self._fetch_with_touchdowns(
            dialog,
            lambda touchdown: hkkaz(
                account=self.account_field(hkkaz, account),
                all_accounts=False,
                date_start=start,
                date_end=end,
                touchdown_point=touchdown,
            ),
            _join_booked,
            "HIKAZ",
        )
