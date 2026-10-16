"""A committed ledger for the preview and commit tests: real transactions on a clone database."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.settle.settle import SettleResult, settle
from app.core.units.commit import CommitResult, commit_unit
from app.core.units.draft import (
    KEEP,
    DocumentDraft,
    DraftEntry,
    FieldDraft,
    ShownBasis,
    UnitDraft,
)
from app.core.units.lookup import unit_ids_of
from app.core.units.plan import Plan
from app.core.units.preview import preview_unit
from tests.invariants.helpers import link_account, make_category, make_entry, make_instance, make_source, pair

D = date(2026, 3, 10)


def fixed(value: int | str | None, basis: tuple[str, Mapping[str, Any]] | None = None) -> FieldDraft:
    return FieldDraft("fixed", value, None if basis is None else ShownBasis(basis[0], basis[1]))


RERESOLVE = FieldDraft("reresolve")


def no_document(entry_id: int, **kw: Any) -> DraftEntry:
    """The explicit decision to commit without a document, on the transaction's original entry."""
    return DraftEntry(entry_id, document=DocumentDraft("none"), **kw)


@dataclass
class Scene:
    engine: Engine
    checking: int
    savings: int
    cash: int
    usd: int
    run: int
    cats: dict[str, int] = field(default_factory=dict)
    payees: dict[str, int] = field(default_factory=dict)

    # ---- building ----------------------------------------------------------------------------

    def tx(self, fn: Any) -> Any:
        with self.engine.begin() as conn:
            return fn(conn)

    def category(self, name: str) -> int:
        if name not in self.cats:
            self.cats[name] = self.tx(lambda c: make_category(c, name))
        return self.cats[name]

    def payee(self, name: str) -> int:
        if name not in self.payees:
            self.payees[name] = int(
                self.tx(
                    lambda c: c.execute(
                        text("INSERT INTO payee (name) VALUES (:n) RETURNING id"), {"n": name}
                    ).scalar_one()
                )
            )
        return self.payees[name]

    def tag(self, name: str) -> int:
        return int(
            self.tx(
                lambda c: c.execute(
                    text("INSERT INTO tag (name) VALUES (:n) RETURNING id"), {"n": name}
                ).scalar_one()
            )
        )

    def tag_entry(self, entry_id: int, *tag_ids: int) -> None:
        self.tx(
            lambda c: c.execute(
                text(
                    "INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id)"
                    " SELECT :e, unnest(CAST(:t AS bigint[])) ON CONFLICT DO NOTHING"
                ),
                {"e": entry_id, "t": list(tag_ids)},
            )
        )

    def tags_of(self, entry_id: int) -> tuple[int, ...]:
        return tuple(
            r.tag_id
            for r in self.q(
                "SELECT tag_id FROM ledger_entry_tag WHERE ledger_entry_id = :i ORDER BY tag_id", i=entry_id
            )
        )

    def movement(
        self,
        *amounts: int,
        account: int | None = None,
        on: date = D,
        counterparty: str | None = None,
        purpose: str | None = None,
        authored: bool = False,
        instructed: tuple[int, str] | None = None,
        end_to_end_id: str | None = None,
        currency: str = "EUR",
        lead: dict[str, Any] | None = None,
        **cols: Any,
    ) -> tuple[int, list[int]]:
        """A source transaction with entries of `amounts` (default one of -1000): (source, entry ids)."""
        parts = list(amounts) or [-1000]
        acct = account or self.checking
        columns: dict[str, Any] = {"counterparty_name": counterparty, "end_to_end_id": end_to_end_id}
        if instructed is not None:
            columns.update(instructed_amount=instructed[0], instructed_currency=instructed[1])

        def make(c: Connection) -> tuple[int, list[int]]:
            src = make_source(
                c,
                acct,
                amount=sum(parts),
                booked_on=on,
                purpose=purpose,
                currency=currency,
                importer=None if authored else "test",
                run_id=None if authored else self.run if acct == self.checking else None,
                columns=columns,
            )
            return src, [
                make_entry(c, src, amount=a, **{"type": None, **cols, **(lead if i == 0 and lead else {})})
                for i, a in enumerate(parts)
            ]

        return self.tx(make)  # type: ignore[no-any-return]

    def confirmed(self, counterparty: str, category: str, *, amount: int = -500, on: date = D) -> int:
        """A reviewed flow: history learns from it."""
        _src, (e,) = self.movement(
            amount,
            counterparty=counterparty,
            on=on,
            type="flow",
            category_id=self.category(category),
            derivation=json.dumps({"type": {"pass": "user"}, "category": {"pass": "user"}}),
        )
        return e

    def sync(self, account: int) -> None:
        """Link an importer to `account`: it is synced (I40: no user-authored row is entered on it after)."""
        self.tx(lambda c: link_account(c, account, make_instance(c)))

    def pair_up(self, a: int, b: int) -> None:
        def go(c: Connection) -> None:
            c.execute(
                text(
                    "UPDATE ledger_entry e SET counter_account_id = o.account_id,"
                    " derivation = e.derivation || CAST(:k AS jsonb)"
                    " FROM ledger_entry o WHERE (e.id, o.id) IN ((:x, :y), (:y, :x))"
                ),
                {
                    "x": a,
                    "y": b,
                    "k": json.dumps(
                        {"counter_account": {"pass": "matcher_decision", "basis": {"from": "counterpart"}}}
                    ),
                },
            )
            pair(c, a, b)

        self.tx(go)

    def transfer_pair(
        self, amount: int = -500, *, out_extra: Sequence[int] = ()
    ) -> tuple[tuple[int, list[int]], tuple[int, list[int]]]:
        """Checking -> savings: two user-keyed transfer legs, paired (a confirmed unit)."""
        user = json.dumps({"type": {"pass": "user"}})
        a = self.movement(
            amount,
            *out_extra,
            authored=True,
            counterparty="own",
            lead={"type": "transfer", "derivation": user},
            type="flow",
        )
        b = self.movement(-amount, account=self.savings, type="transfer", derivation=user, authored=True)
        self.pair_up(a[1][0], b[1][0])
        return a, b

    # ---- operating ---------------------------------------------------------------------------

    def settle(self) -> SettleResult:
        return settle(self.engine)

    def q(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def row(self, entry_id: int) -> Any:
        return self.q("SELECT * FROM ledger_entry WHERE id = :i", i=entry_id)[0]

    def rows(self, *entry_ids: int) -> dict[int, Any]:
        return {r.id: r for r in self.q("SELECT * FROM ledger_entry WHERE id = ANY(:i)", i=list(entry_ids))}

    def unit_ids(self, entry_id: int) -> tuple[int, ...]:
        with self.engine.connect() as conn:
            ids = unit_ids_of(conn, entry_id)
        assert ids is not None
        return ids.entry_ids

    def versions(self, anchor: int) -> dict[int, int]:
        ids = self.unit_ids(anchor)
        return {
            r.id: r.version
            for r in self.q("SELECT id, version FROM ledger_entry WHERE id = ANY(:i)", i=list(ids))
        }

    def draft(self, anchor: int, *entries: DraftEntry, **kw: Any) -> UnitDraft:
        kw.setdefault("versions", self.versions(anchor))
        return UnitDraft(anchor, entries, **kw)

    def preview(self, anchor: int, *entries: DraftEntry, **kw: Any) -> Plan:
        return preview_unit(self.engine, self.draft(anchor, *entries, **kw))

    def commit(self, anchor: int, *entries: DraftEntry, **kw: Any) -> CommitResult:
        return commit_unit(self.engine, self.draft(anchor, *entries, **kw))

    def commit_draft(self, draft: UnitDraft) -> CommitResult:
        return commit_unit(self.engine, draft)

    def assert_checks_clean(self) -> None:
        views = [
            r[0]
            for r in self.q(
                "SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v_check_%'"
            )
        ]
        assert views, "no integrity views found"
        for v in views:
            bad = self.q(f"SELECT * FROM {v}")  # noqa: S608
            assert not bad, f"{v} reports {bad}"

    def fingerprint(self) -> dict[str, Any]:
        """Everything a preview must leave alone: row counts and a hash of the content of every table."""
        tables = [
            r[0]
            for r in self.q(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"
            )
        ]
        out: dict[str, Any] = {}
        for t in tables:
            out[t] = self.q(f"SELECT count(*), md5(string_agg(x::text, '|' ORDER BY x::text)) FROM {t} x")[0]  # noqa: S608
        return out


__all__ = ["D", "KEEP", "RERESOLVE", "DocumentDraft", "DraftEntry", "Scene", "fixed", "no_document"]
