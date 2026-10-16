"""Rows for the document tests: a provider payee, a document source and its coverage, a document."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app.core.importers.providers import configure_document_providers
from tests.invariants.helpers import FINISHED, _insert

PAYEE_KEYS = json.dumps({"payee": {"pass": "rule"}})


def make_payee(conn: Connection, name: str, provider: str | None) -> int:
    return _insert(conn, "payee", {"name": name, "document_provider": provider})


def make_doc_source(
    conn: Connection,
    importer: str = "docs",
    *,
    start: date | None = date(2026, 1, 1),
    disabled: bool = False,
    covered_through: date | None = None,
    providers: frozenset[str] = frozenset({"paypal"}),
    register: bool = True,
) -> int:
    """A document importer instance (`covered_through` None: never run); registers its providers."""
    instance = _insert(
        conn,
        "importer_instance",
        {
            "importer": importer,
            "label": f"{importer} instance",
            "access": "shared",
            "emits": ["documents"],
            "disabled": disabled,
            "settings": json.dumps({} if start is None else {"start_date": start.isoformat()}),
        },
    )
    if covered_through is not None:
        _insert(
            conn,
            "import_run",
            {
                "importer": importer,
                "importer_instance_id": instance,
                "emits": "documents",
                "status": "ok",
                "covered_through": covered_through,
                "finished_at": FINISHED,
            },
        )
    if register:
        from app.core.importers.providers import document_providers

        configure_document_providers({**document_providers(), importer: providers})
    return instance


def make_document(
    conn: Connection,
    provider: str = "paypal",
    *,
    total: int = -1000,
    on: date = date(2026, 3, 10),
    currency: str = "EUR",
    external_id: str | None = None,
) -> int:
    cols: dict[str, Any] = {
        "provider": provider,
        "external_id": external_id
        or f"d{conn.execute(text('SELECT count(*) FROM external_document')).scalar_one()}",
        "occurred_on": on,
        "total": total,
        "currency": currency,
        "raw": "{}",
    }
    return _insert(conn, "external_document", cols)
