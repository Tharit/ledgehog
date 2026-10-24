"""The fetch-importer protocol, the prompt kinds and `SecretText` (architecture §5.5, §5.6).

An importer that fetches implements `FetchImporter`; a document importer is one of them. It opens a
`FetchSession` from its settings, its `state` and a `Prompter`. The session is the credential in
memory (the PIN the user typed, what the importer learned, the prompter), not a transport: a bank may
demand a challenge, and a fresh dialog, per data call, so any call may ask for input.

Every call of a session blocks and is made from a worker thread (architecture §3, §5.3). A file
importer (`importer.FileImporter`) is not a fetch importer: it is a pure parse of uploaded bytes.

Protocols and plain values only: no concrete importer is known here.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

from app.core.plugins.errors import AccountUnsupported
from app.core.plugins.importer import DocumentDelivery, IncomingRow


class SecretText:
    """An answer that must not leak: its `repr` and `str` are `***`.

    A PIN, a password or a TAN reaches the importer in this wrapper; the importer calls `reveal()`
    where it needs the text and keeps it in local variables only (architecture §5.6). `core` may not
    import `utils.config.Secret`, so the type lives here.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "***"

    def __str__(self) -> str:
        return "***"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __reduce__(self) -> Any:  # never serialised, whatever a framework tries
        raise TypeError("SecretText cannot be pickled")


# ---- prompts (architecture §5.5) -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Option:
    """One choice: an id (what the answer carries) and a label (the bank's own words)."""

    id: str
    label: str


@dataclass(frozen=True, slots=True)
class SecretPrompt:
    """The PIN or a password; answered with text. `subject` is a key the client maps to a label."""

    subject: str


TanMedium = Literal["text", "image", "decoupled"]
TAN_MEDIA: tuple[TanMedium, ...] = ("text", "image", "decoupled")


@dataclass(frozen=True, slots=True)
class TanPrompt:
    """A challenge, in a medium: typed `text`, an `image` (a photoTAN) or `decoupled` (a confirmation
    in the user's app, answered only by the importer's `poll`)."""

    medium: TanMedium
    challenge: str = ""
    method: str | None = None
    image: bytes | None = None
    image_mime: str | None = None

    def __post_init__(self) -> None:
        if self.medium not in TAN_MEDIA:
            raise ValueError(f"a TAN prompt's medium is one of {TAN_MEDIA}, not {self.medium!r}")
        if self.medium == "image" and (self.image is None or self.image_mime is None):
            raise ValueError("an image TAN prompt carries the image and its MIME type")


@dataclass(frozen=True, slots=True)
class ChoicePrompt:
    """One of a list of options (the TAN mechanism, the TAN medium); answered with an option id."""

    subject: str
    options: tuple[Option, ...]

    def __post_init__(self) -> None:
        if not self.options:
            raise ValueError("a choice needs at least one option")


@dataclass(frozen=True, slots=True)
class TextPrompt:
    """Free text, for a medium the bank will not list."""

    subject: str


Prompt = SecretPrompt | TanPrompt | ChoicePrompt | TextPrompt
Answer = SecretText | str | None


def prompt_payload(prompt: Prompt) -> dict[str, Any]:
    """The wire shape of a prompt (architecture §4.2 `prompt`). A photoTAN image goes out as base64."""
    match prompt:
        case SecretPrompt(subject=subject):
            return {"kind": "secret", "subject": subject}
        case TanPrompt(medium="image"):
            assert prompt.image is not None
            return {
                "kind": "tan",
                "medium": "image",
                "challenge": prompt.challenge,
                "method": prompt.method,
                "image_mime": prompt.image_mime,
                "image_b64": base64.b64encode(prompt.image).decode("ascii"),
            }
        case TanPrompt(medium=medium):
            return {"kind": "tan", "medium": medium, "challenge": prompt.challenge, "method": prompt.method}
        case ChoicePrompt(subject=subject, options=options):
            return {
                "kind": "choice",
                "subject": subject,
                "options": [{"id": o.id, "label": o.label} for o in options],
            }
        case TextPrompt(subject=subject):
            return {"kind": "text", "subject": subject}
    raise TypeError(f"not a prompt: {type(prompt).__name__}")


@runtime_checkable
class Prompter(Protocol):
    """Asks the user. One blocking call; nothing else in the protocol blocks on a person."""

    def ask(
        self,
        prompt: Prompt,
        *,
        poll: Callable[[], bool] | None = None,
        timeout_s: float | None = None,
    ) -> Answer:
        """Block until the prompt is resolved.

        Returns a `SecretText` for a `secret` and a typed or photographed TAN, the option id for a
        `choice`, text for a `text`, and `None` for a decoupled `tan`. A decoupled prompt needs `poll`:
        the importer's own "confirmed yet?", which returns True once it was, raises the taxonomy's
        error if the bank refused, and is called every few seconds on the importer's thread.

        Raises `ChallengeAbandoned` (cancelled, or the task was aborted) or `ChallengeExpired`
        (300 s unless `timeout_s`). It never retries: a wrong TAN or PIN is the bank's verdict and the
        importer decides whether to ask again or to raise `AuthRejected`.
        """
        ...


# ---- what a session returns ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoveredAccount:
    """One account reachable at the login; one per currency pocket for multi-currency providers.

    `capabilities` is a subset of {"transactions", "balance"}: what the bank can deliver for it
    (empty: nothing fetchable). `currency` is None where the source states none (a depot).
    """

    external_ref: str
    name: str
    currency: str | None = None
    kind_hint: str | None = None
    capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class FetchedTransactions:
    """What `ingest_delivery` takes, in one value. Coverage and balance follow spec §5.1."""

    rows: tuple[IncomingRow, ...]
    covered_through: date
    covered_from: date | None = None
    reported_balance: int | None = None
    balance_on: date | None = None
    importer_stats: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))


@runtime_checkable
class FetchSession(Protocol):
    """The credential in memory. Every method blocks; the orchestrator always calls `close`."""

    def accounts(self) -> Sequence[DiscoveredAccount]:
        """The accounts reachable at this login. Used by discovery only."""
        ...

    def fetch_account(
        self,
        external_ref: str,
        *,
        since: date,
        today: date,
        currency: str,
        minor_units_of: Callable[[str], int],
    ) -> FetchedTransactions:
        """Booked transactions of one account dated `since` (<= today) or later, with the coverage
        and, where the source reports one, the closing balance. `minor_units_of` is passed as to a
        file importer."""
        ...

    def fetch_documents(
        self, *, since: date, today: date, minor_units_of: Callable[[str], int]
    ) -> DocumentDelivery:
        """Documents dated `since` or later (the instance's `start_date`, spec §5.5). `minor_units_of` is
        passed as to `fetch_account`: it raises `KeyError` for a currency it does not know."""
        ...

    def close(self) -> None:
        """Release what the session holds. An error from it is logged by type and dropped."""
        ...


class FetchSessionBase:
    """Defaults for an importer that delivers only some kinds: no accounts listed, nothing fetchable,
    nothing to close. The orchestrator calls only the methods of the kinds the importer emits."""

    def accounts(self) -> Sequence[DiscoveredAccount]:
        return ()

    def fetch_account(
        self,
        external_ref: str,
        *,
        since: date,
        today: date,
        currency: str,
        minor_units_of: Callable[[str], int],
    ) -> FetchedTransactions:
        raise AccountUnsupported("the importer fetches no transactions")

    def fetch_documents(
        self, *, since: date, today: date, minor_units_of: Callable[[str], int]
    ) -> DocumentDelivery:
        raise AccountUnsupported("the importer fetches no documents")

    def close(self) -> None:
        return None


def delivers_declared(providers: frozenset[str], provider: str) -> bool:
    """An importer built for fixed providers delivers those, whatever the case of the name."""
    return provider.lower() in {p.lower() for p in providers}


@runtime_checkable
class FetchImporter(Protocol):
    """An importer that opens a session. Reads neither the database nor the clock."""

    emits: frozenset[str]  # the kinds it delivers: "transactions", "documents"
    # the document providers it names (spec §5.5), for suggestions; empty where it names none
    providers: frozenset[str]

    def delivers(self, settings: Mapping[str, Any], provider: str) -> bool:
        """Whether an instance with these settings delivers documents of `provider` (compared without
        regard to case), answered before its first run. A fixed-provider importer answers from its names
        (`delivers_declared`); one that reads receipts of any provider, from its settings."""
        ...

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        """Raise `InvalidProfile` naming the setting that is wrong."""
        ...

    def default_fetch_start(self, settings: Mapping[str, Any], *, today: date) -> date:
        """Where an account with neither coverage nor entries starts (spec §5.4). Needs no session."""
        ...

    def open(
        self,
        settings: Mapping[str, Any],
        state: MutableMapping[str, Any],
        prompter: Prompter,
        *,
        today: date,
    ) -> FetchSession:
        """Authenticate; may ask the prompter any number of times, none included.

        `state` is the working copy of `importer_instance.state`: write into it whatever is learned
        and not secret (system id, TAN mechanism and medium). The caller writes it back when the
        job ends, whatever the outcome, if it changed. No PIN, password, TAN or token that does not
        meet spec §7 may be put in it.
        """
        ...
