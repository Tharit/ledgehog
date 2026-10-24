"""The interface between the mailbox side and the extraction side (spec/plugins/importers/email.md §5, §6).

The mailbox side hands an inner message's text and PDFs to an `Extractor`, which answers with what the model
extracted or a reason it was skipped; a `DocumentBuilder` turns an extraction into a document (completeness,
provider, signs) or a reason it is not one. Both are given to the importer, so the fetch is tested end to end
without a model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from app.core.plugins.errors import SourceUnavailable
from app.core.plugins.importer import IncomingDocument
from app.plugins.importers.email.message import PdfPart

# The fixed keys of a run's `importer_stats` (spec §8): each message and inner message is counted once.
DOCUMENTS = "documents"
SUPERSEDED = "superseded"
NOT_ACCEPTED = "not_accepted"
ALREADY_SEEN = "already_seen"
BEFORE_START = "before_start"
TOO_LARGE = "too_large"
NO_CONTENT = "no_content"
PDF_NOT_READ = "pdf_not_read"
UNREADABLE = "unreadable"
MODEL_REFUSED = "model_refused"
GAVE_UP = "gave_up"
REFUND = "refund"
UNKNOWN_CURRENCY = "unknown_currency"
INCOMPLETE = "incomplete"
NO_MERCHANT = "no_merchant"

STAT_KEYS: tuple[str, ...] = (
    DOCUMENTS, SUPERSEDED, NOT_ACCEPTED, ALREADY_SEEN, BEFORE_START, TOO_LARGE, NO_CONTENT, PDF_NOT_READ,
    UNREADABLE, MODEL_REFUSED, GAVE_UP, REFUND, UNKNOWN_CURRENCY, INCOMPLETE, NO_MERCHANT,
)  # fmt: skip
# what an extractor or a builder may give as a reason: everything but the delivered and the superseded
SKIP_REASONS: frozenset[str] = frozenset(STAT_KEYS) - {DOCUMENTS, SUPERSEDED}


@dataclass(frozen=True, slots=True)
class Skipped:
    """The inner message yields no document; `reason` is one of the `importer_stats` keys."""

    reason: str

    def __post_init__(self) -> None:
        if self.reason not in SKIP_REASONS:
            raise ValueError(f"not a reason a message is skipped for: {self.reason!r}")


@dataclass(frozen=True, slots=True)
class Extraction:
    """What the model extracted, validated against the answer's shape (§5): `answer` is the object as
    returned, `source` where it was read (text or PDF, `pdf` its file name), `model` the model's name."""

    answer: Mapping[str, Any]
    source: Literal["text", "pdf"]
    pdf: str | None = None
    model: str = ""


class AttemptFailed(SourceUnavailable):
    """A request for one message was sent and failed (a reply time-out, a dropped connection, HTTP 5xx; §8).

    A `SourceUnavailable`: the run fails and the position stays. The importer counts the attempt in `stuck`;
    the third run in a row to fail at the same message skips it as `gave_up`. A model that cannot be reached
    at all, or refuses the credentials, raises a plain `SourceUnavailable` and counts nothing."""


class Extractor(Protocol):
    def extract(
        self,
        text: str | None,
        pdfs: Sequence[PdfPart],
        *,
        accept: Callable[[Extraction], bool] = lambda extraction: True,
    ) -> Extraction | Skipped:
        """Ask the model, text first: where the text yields no document, each PDF in turn (§5).

        `text` is the converted body (None where it has none, or it was too long to send); `pdfs` its PDFs,
        at most three. `accept` says whether an extraction yields a document (the builder's verdict); the
        first accepted one is returned. Where none is, the first extraction that was read is returned, for
        the builder to name why it is no document, else `Skipped` for `no_content`, `pdf_not_read`,
        `unreadable` or `model_refused`. Raises `AttemptFailed` or `SourceUnavailable` (§8)."""
        ...


@dataclass(frozen=True, slots=True)
class MessageContext:
    """What the document is built with besides the extraction: the inner message's identity (§4), the identity
    of its outer message, where it lies in the mailbox, its date and subject."""

    identity: str
    outer_identity: str
    uid: int
    uidvalidity: int
    date: date
    subject: str | None


class DocumentBuilder(Protocol):
    def build(
        self, extraction: Extraction, context: MessageContext, *, minor_units_of: Callable[[str], int]
    ) -> IncomingDocument | Skipped:
        """Completeness, provider and signs (§6): the document, or `refund`, `unknown_currency`, `incomplete`
        or `no_merchant`. `minor_units_of` raises `KeyError` for a currency it does not know."""
        ...
