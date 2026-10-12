"""What settling reads to resolve (architecture §5.1): accounts, rules and the entries to resolve.

SQLAlchemy Core, set-based: each loader is one query per settle. Nothing here writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Connection, text

from app.core.plugins.classifier import AccountFact, EntryInput, RuleSpec
from app.core.resolution.confirmed import STANDING, units_sql


def load_accounts(conn: Connection) -> list[AccountFact]:
    """Every account; `external_ref` is stored canonicalised (core/accounts.py)."""
    return [
        AccountFact(id=r.id, currency=r.currency, external_ref=r.external_ref, closed_on=r.closed_on)
        for r in conn.execute(text("SELECT id, currency, external_ref, closed_on FROM account ORDER BY id"))
    ]


def load_rules(conn: Connection) -> list[RuleSpec]:
    """Every rule; the target is the column `sets` names. The schema guarantees exactly one."""
    return [
        RuleSpec(
            id=r.id,
            name=r.name,
            sets=r.sets,
            target_id=r.target_id,
            priority=r.priority,
            condition_payee_id=r.condition_payee_id,
            counterparty_ref=r.counterparty_ref,
            mandate_ref=r.mandate_ref,
            name_exact=r.name_exact,
            name_prefix=r.name_prefix,
            purpose_regex=r.purpose_regex,
            booking_text=r.booking_text,
        )
        for r in conn.execute(
            text(
                "SELECT id, name, sets, COALESCE(counter_account_id, payee_id, category_id) AS target_id,"
                " priority, condition_payee_id, counterparty_ref, mandate_ref, name_exact, name_prefix,"
                " purpose_regex, booking_text FROM rule ORDER BY id"
            )
        )
    ]


@dataclass(frozen=True, slots=True)
class UnconfirmedEntry:
    """An entry to resolve with what is stored on it now."""

    input: EntryInput
    type: str | None
    payee_id: int | None
    category_id: int | None
    counter_account_id: int | None
    derivation: Mapping[str, Any]
    paired: bool  # a transfer leg with a partner: pairing owns its counter-account (step 8)
    original: bool  # the lowest entry id of its source transaction: the only one that may be a transfer


_UNCONFIRMED = text(
    f"""
    WITH units AS ({units_sql()})
    SELECT e.id, e.account_id, e.currency, e.booked_on, e.amount,
           (s.importer IS NULL) AS user_authored,
           s.counterparty_ref, s.counterparty_name, s.purpose, s.booking_text, s.mandate_ref,
           s.instructed_currency,
           e.type, e.payee_id, e.category_id, e.counter_account_id, e.derivation,
           (e.counterpart_entry_id IS NOT NULL) AS paired, (u.first_id = e.id) AS original
      FROM units AS u
      JOIN ledger_entry AS e ON e.id = u.id
      JOIN source_transaction AS s ON s.id = e.source_transaction_id
     WHERE NOT u.unit_ok
     ORDER BY e.booked_on, e.id
    """
)


def load_unconfirmed(conn: Connection) -> list[UnconfirmedEntry]:
    """The movement entries of every unconfirmed unit (I20: a confirmed unit is never read here)."""
    out: list[UnconfirmedEntry] = []
    for r in conn.execute(_UNCONFIRMED, {"standing": STANDING}):
        out.append(
            UnconfirmedEntry(
                input=EntryInput(
                    entry_id=r.id,
                    account_id=r.account_id,
                    currency=r.currency,
                    booked_on=r.booked_on,
                    amount=r.amount,
                    user_authored=r.user_authored,
                    counterparty_ref=r.counterparty_ref,
                    counterparty_name=r.counterparty_name,
                    purpose=r.purpose,
                    booking_text=r.booking_text,
                    mandate_ref=r.mandate_ref,
                    instructed_currency=r.instructed_currency,
                ),
                type=r.type,
                payee_id=r.payee_id,
                category_id=r.category_id,
                counter_account_id=r.counter_account_id,
                derivation=cast(Mapping[str, Any], r.derivation),
                paired=r.paired,
                original=r.original,
            )
        )
    return out
