"""Rows for the document tests: a provider payee, a document source and its coverage, a document."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.core.importers.providers import configure_document_providers
from tests.core.units.scene import D, Scene
from tests.fixtures import rule_seed as rs
from tests.invariants.helpers import FINISHED, _insert

PAYEE_KEYS = json.dumps({"payee": {"pass": "rule"}})
CARD = "PAYPAL *SEEEDDEVELO"
STANDING = {"type": {"pass": "user"}, "category": {"pass": "user"}, "payee": {"pass": "user"}}


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


class Docs:
    """A document source covering the whole period, the provider payee PayPal and a rule setting it on the
    card text `PAYPAL *`."""

    def __init__(self, scene: Scene, *, covered: bool = True) -> None:
        self.scene = scene

        def build(c: Connection) -> int:
            provider = make_payee(c, "PayPal", "paypal")
            rs.rule(
                c,
                "paypal",
                "payee",
                provider,
                conditions=(rs.cond("counterparty_name", "starts_with", "PAYPAL"),),
            )
            make_doc_source(c, covered_through=D + timedelta(days=60) if covered else None)
            return provider

        self.provider: int = scene.tx(build)

    def charge(self, amount: int = -1000, *, on: Any = D, name: str = CARD, **cols: Any) -> int:
        _src, (entry,) = self.scene.movement(amount, counterparty=name, on=on, **cols)
        return entry

    def document(self, **kw: Any) -> int:
        return int(self.scene.tx(lambda c: make_document(c, **kw)))

    def lines(self, doc: int, *lines: tuple[str, int]) -> None:
        def go(c: Connection) -> None:
            for n, (description, amount) in enumerate(lines, start=1):
                c.execute(
                    text(
                        "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                        " VALUES (:d, :n, :t, :a)"
                    ),
                    {"d": doc, "n": n, "t": description, "a": amount},
                )

        self.scene.tx(go)

    def merchant(self, doc: int, name: str) -> None:
        self.scene.tx(
            lambda c: c.execute(
                text("UPDATE external_document SET merchant_name = :n WHERE id = :d"), {"n": name, "d": doc}
            )
        )
