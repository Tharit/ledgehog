"""The fetch protocol's values: SecretText, the prompt kinds and their wire shape, the session base."""

from __future__ import annotations

import base64
import pickle
from datetime import date

import pytest

from app.core.importers.catalog import describe
from app.core.plugins.errors import AccountUnsupported
from app.core.plugins.fetch import (
    ChoicePrompt,
    FetchImporter,
    FetchSession,
    FetchSessionBase,
    Option,
    SecretPrompt,
    SecretText,
    TanPrompt,
    TextPrompt,
    prompt_payload,
)
from app.core.plugins.importer import FileImporter


def test_secret_text_never_shows_itself() -> None:
    s = SecretText("hunter2")
    assert repr(s) == "***" and str(s) == "***" and f"{s}" == "***" and f"{s!r}" == "***"
    assert s.reveal() == "hunter2"
    assert "hunter2" not in repr({"pin": s})
    assert bool(s) and not SecretText("")
    with pytest.raises(TypeError):
        pickle.dumps(s)


def test_the_wire_shape_of_every_prompt_kind() -> None:
    assert prompt_payload(SecretPrompt("pin")) == {"kind": "secret", "subject": "pin"}
    assert prompt_payload(TanPrompt("text", "enter it", "chipTAN")) == {
        "kind": "tan",
        "medium": "text",
        "challenge": "enter it",
        "method": "chipTAN",
    }
    assert prompt_payload(TanPrompt("decoupled", "confirm in the app"))["medium"] == "decoupled"
    image = prompt_payload(TanPrompt("image", "scan", image=b"\x89PNG", image_mime="image/png"))
    assert image["image_mime"] == "image/png"
    assert base64.b64decode(image["image_b64"]) == b"\x89PNG"
    assert prompt_payload(ChoicePrompt("tan_medium", (Option("1", "Phone"), Option("2", "Card")))) == {
        "kind": "choice",
        "subject": "tan_medium",
        "options": [{"id": "1", "label": "Phone"}, {"id": "2", "label": "Card"}],
    }
    assert prompt_payload(TextPrompt("tan_medium_name")) == {"kind": "text", "subject": "tan_medium_name"}


def test_malformed_prompts_are_refused() -> None:
    with pytest.raises(ValueError):
        TanPrompt("image", "scan")  # no image
    with pytest.raises(ValueError):
        TanPrompt("voice")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ChoicePrompt("tan_medium", ())


def test_the_session_base_offers_nothing_and_raises_account_unsupported() -> None:
    base = FetchSessionBase()
    assert isinstance(base, FetchSession)
    assert base.accounts() == ()
    base.close()
    with pytest.raises(AccountUnsupported):
        base.fetch_account(
            "x", since=date(2026, 1, 1), today=date(2026, 1, 2), currency="EUR", minor_units_of=len
        )
    with pytest.raises(AccountUnsupported):
        base.fetch_documents(since=date(2026, 1, 1), today=date(2026, 1, 2))


def test_the_catalog_reads_a_fetch_importers_declared_kinds() -> None:
    class Both:
        emits = frozenset({"transactions", "documents"})
        providers = frozenset({"paypal"})

        def validate_settings(self, settings: object) -> None: ...

        def default_fetch_start(self, settings: object, *, today: date) -> date:
            return today

        def open(self, settings: object, state: object, prompter: object, *, today: date) -> object:
            return FetchSessionBase()

    both = Both()
    assert isinstance(both, FetchImporter) and not isinstance(both, FileImporter)
    entry = describe("both", both)
    assert (entry.kind, entry.emits) == ("fetch", ("documents", "transactions"))
