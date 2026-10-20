"""`BankSession` over the patched python-fints client (fints.md §2, §10).

The only module that drives the library. It turns the library's objects into the plain values of
`bank.py`, runs every data call in its own dialog, answers TAN challenges through the importer's
handler, and reports the return codes it recorded. What the codes mean is the importer's business
(`codes.py`), never this module's: a library exception only ever becomes `DialogFailed` carrying the
codes, except for a connection that failed (`SourceUnavailable`) and an operation the bank does not
offer (`AccountUnsupported`).
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable, Sequence
from typing import Any, NoReturn

from fints.client import FinTSOperations, NeedTANResponse
from fints.exceptions import FinTSConnectionError, FinTSSCARequiredError, FinTSUnsupportedOperation
from fints.models import SEPAAccount

from app.core.plugins.errors import (
    AccountUnsupported,
    BankSetupRequired,
    ChallengeAbandoned,
    ImporterError,
    SourceUnavailable,
)
from app.plugins.importers.fints.bank import (
    BankLogin,
    BankSession,
    CardAnswer,
    Challenge,
    DialogFailed,
    Procedure,
    ReturnCode,
    TanHandler,
    UpdAccount,
)
from app.plugins.importers.fints.hkku import CARD_REQUEST
from app.plugins.importers.fints.patches import STATEMENT_REQUEST, LedgerClient

log = logging.getLogger("ledgehog.fints")


def connect_bank(login: BankLogin) -> BankSession:
    # The library's debug log carries data segments; it stays at warning (fints.md §8).
    logging.getLogger("fints").setLevel(logging.WARNING)
    return LibrarySession(login)


class LibrarySession:
    def __init__(self, login: BankLogin) -> None:
        self._login = login
        self._client = LedgerClient(
            login.bank_code,
            login.user_id,
            login.pin.reveal(),
            login.url,
            customer_id=login.customer_id,
            tan_medium=login.tan_medium,
            system_id=login.system_id,
            product_id=login.product_id,
            product_version=login.product_version,
        )

    @property
    def system_id(self) -> str | None:
        value = self._client.system_id
        return None if value in (None, "", "0") else str(value)

    # ---- setup: one dialog each ----

    def procedures(self) -> Sequence[Procedure]:
        start = len(self._client.codes)
        try:
            self._client.fetch_tan_mechanisms()
            mechanisms = self._client.get_tan_mechanisms()
        except Exception as exc:
            self.raise_failure(start, exc)
        return [Procedure(str(code), str(p.name)) for code, p in mechanisms.items()]

    def use_procedure(self, code: str) -> None:
        self._client.set_tan_mechanism(code)

    def procedure_name(self) -> str | None:
        current = self._client.get_current_tan_mechanism()
        found = self._client.get_tan_mechanisms().get(current)
        return None if found is None else str(found.name)

    def medium_required(self) -> bool:
        try:
            return bool(self._client.is_tan_media_required())
        except KeyError:  # one-step procedure: it has no parameters and needs no medium
            return False

    def media(self) -> Sequence[str] | None:
        start = len(self._client.codes)
        try:
            result = self._client.tan_media_without_tan_request()
        except Exception as exc:
            self.raise_failure(start, exc)
        names = [str(m.tan_medium_name) for m in result if getattr(m, "tan_medium_name", None)]
        return names or None

    def use_medium(self, name: str) -> None:
        self._client.selected_tan_medium = name

    def finish_setup(self) -> None:
        self._client.finish_setup()

    def close(self) -> None:
        try:
            self._client.connection.session.close()
        except Exception as exc:  # nothing to release that matters: log the type and go on
            log.warning("closing the connection failed: %s", type(exc).__name__)

    # ---- dialogs ----

    def dialog(self, tan: TanHandler) -> LibraryDialog:
        return LibraryDialog(self, tan)

    def failure(self, start: int, exc: BaseException) -> Exception:
        """What a library exception becomes. `start` is where this step's codes begin."""
        if isinstance(exc, ImporterError):
            return exc
        if isinstance(exc, FinTSConnectionError):
            cause = type(exc.__cause__).__name__ if exc.__cause__ is not None else "no answer"
            return SourceUnavailable(f"the bank could not be reached ({cause})")
        if isinstance(exc, FinTSUnsupportedOperation):
            return AccountUnsupported("the bank offers no MT940 statement request for this account")
        return DialogFailed(self._client.codes[start:], type(exc).__name__)

    def raise_failure(self, start: int, exc: BaseException) -> NoReturn:
        err = self.failure(start, exc)
        if err is exc:
            raise exc
        raise err from exc

    @property
    def client(self) -> LedgerClient:
        return self._client

    @property
    def login(self) -> BankLogin:
        return self._login


class LibraryDialog:
    """One open dialog of the session, used as a context manager (`bank.Dialog`)."""

    def __init__(self, session: LibrarySession, tan: TanHandler) -> None:
        self._session = session
        self._client = session.client
        self._tan = tan
        self._start = len(self._client.codes)
        self._entered = False
        self._sca = False
        self._accounts: tuple[UpdAccount, ...] = ()

    def __enter__(self) -> LibraryDialog:
        client = self._client
        client.init_tan_response = None
        client.tan_for = set()
        try:
            client.__enter__()
            self._entered = True
            if client.init_tan_response is not None:
                self._resolve(client.init_tan_response)
            self._accounts = tuple(_upd_accounts(client))
        except Exception as exc:
            self.__exit__(type(exc), exc, None)
            self._session.raise_failure(self._start, exc)
        return self

    def __exit__(self, *exc: object) -> None:
        if not self._entered:
            return
        self._entered = False
        # Ending a dialog the bank closed already (9075) is an error the library knows how to skip.
        exc_type = FinTSSCARequiredError if self._sca else None
        try:
            self._client.__exit__(exc_type, None, None)
        except Exception as err:  # the bank's answer to the end of a dialog changes nothing
            log.warning("ending the dialog failed: %s", type(err).__name__)

    @property
    def accounts(self) -> Sequence[UpdAccount]:
        return self._accounts

    @property
    def codes(self) -> Sequence[ReturnCode]:
        return self._client.codes[self._start :]

    def statements(
        self, account: UpdAccount, since: datetime.date, until: datetime.date, *, with_tan: bool
    ) -> str:
        client = self._client
        before = len(client.codes)
        result = self._request(
            STATEMENT_REQUEST, with_tan, lambda: client.booked_statements(self._sepa(account), since, until)
        )
        if not isinstance(result, str):
            raise DialogFailed(client.codes[before:], type(result).__name__)
        return result

    def card(
        self, account: UpdAccount, since: datetime.date, until: datetime.date, *, with_tan: bool
    ) -> CardAnswer:
        client = self._client
        before = len(client.codes)
        result = self._request(
            CARD_REQUEST, with_tan, lambda: client.card_transactions(self._sepa(account), since, until)
        )
        if not isinstance(result, CardAnswer):
            raise DialogFailed(client.codes[before:], type(result).__name__)
        return result

    def _sepa(self, account: UpdAccount) -> SEPAAccount:
        # a card has no IBAN: its card number is the account number
        return SEPAAccount(
            iban=account.iban,
            bic=None,
            accountnumber=account.account_number,
            subaccount=account.subaccount,
            blz=account.bank_code or self._session.login.bank_code,
        )

    def _request(self, request: str, with_tan: bool, send: Callable[[], Any]) -> Any:
        """One data request of this dialog, its challenges answered; a library failure is told by the
        codes it left (`before`), and a 9075 marks the dialog as closed by the bank."""
        client = self._client
        client.tan_for = {request} if with_tan else set()
        before = len(client.codes)
        try:
            return self._resolve(send())
        except Exception as exc:
            if isinstance(exc, FinTSSCARequiredError):
                self._sca = True
            self._session.raise_failure(before, exc)

    # ---- TAN challenges ----

    def _resolve(self, response: Any) -> Any:
        """Answer challenges until the bank has none left; return the final response."""
        client = self._client
        while isinstance(response, NeedTANResponse):
            name = self._session.procedure_name()
            if response.decoupled:
                response = self._decoupled(response, name)
                continue
            if response.challenge_hhduc and not response.challenge_matrix and not response.challenge.strip():
                # a chipTAN flicker code without a text: nothing here can show it
                raise _unsupported_challenge(name)
            matrix = response.challenge_matrix
            if matrix is not None:
                challenge = Challenge(
                    "image", response.challenge or "", name, bytes(matrix[1]), str(matrix[0])
                )
            else:
                challenge = Challenge("text", response.challenge or "", name)
            typed = self._tan(challenge, None)
            response = client.send_tan(response, typed or "")
        return response

    def _decoupled(self, response: NeedTANResponse, name: str | None) -> Any:
        client = self._client
        held: dict[str, Any] = {"pending": response, "result": None, "done": False}
        start = len(client.codes)

        def poll() -> bool:
            try:
                result = client.send_tan(held["pending"], "")
            except Exception as exc:
                self._session.raise_failure(start, exc)
            if isinstance(result, NeedTANResponse):
                held["pending"] = result
                return False
            held["result"], held["done"] = result, True
            return True

        self._tan(Challenge("decoupled", response.challenge or "", name), poll)
        if not held["done"]:
            raise ChallengeAbandoned("the confirmation did not arrive")
        return held["result"]


def _unsupported_challenge(name: str | None) -> Exception:
    which = f" ({name})" if name else ""
    return BankSetupRequired(
        f"the TAN procedure{which} shows its challenge as a flicker code, which is not supported: "
        "pick another procedure with the bank, then run again"
    )


def _upd_accounts(client: LedgerClient) -> list[UpdAccount]:
    rows: list[UpdAccount] = []
    accounts = client.get_information()["accounts"]
    # The library's own operation table does not show the card request: read what the bank listed.
    allowed = [
        {t.transaction for t in seg.allowed_transactions if t.transaction}
        for seg in client.upd.find_segments("HIUPD")
    ]
    for index, a in enumerate(accounts):
        bank = a.get("bank_identifier")
        kind = a.get("type")
        rows.append(
            UpdAccount(
                iban=_text(a.get("iban")),
                account_number=_text(a.get("account_number")),
                subaccount=_text(a.get("subaccount_number")),
                bank_code=_text(getattr(bank, "bank_code", None)),
                account_type=int(kind) if isinstance(kind, int | str) and str(kind).isdigit() else None,
                product_name=_text(a.get("product_name")),
                currency=_text(a.get("currency")),
                statements=bool((a.get("supported_operations") or {}).get(FinTSOperations.GET_TRANSACTIONS)),
                cards=CARD_REQUEST in (allowed[index] if index < len(allowed) else ()),
            )
        )
    return rows


def _text(value: Any) -> str | None:
    return None if value is None or str(value).strip() == "" else str(value).strip()
