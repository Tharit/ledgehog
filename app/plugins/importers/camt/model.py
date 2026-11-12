"""The statement model every reader fills and the core consumes (camt.md §2).

Only what a record, the per-report check or the balance needs. Dates are calendar days: turning a
format's own date representation into one is the reader's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Balance:
    amount: Decimal
    currency: str
    credit: bool
    on: date

    @property
    def signed(self) -> Decimal:
        """Positive for a credit, negative for a debit: a debt is negative in the ledger (spec §3.3)."""
        return self.amount if self.credit else -self.amount


@dataclass(frozen=True, slots=True)
class Detail:
    """One transaction detail of an entry, as the format gives it."""

    name: str | None = None
    account: str | None = None
    agent: str | None = None
    end_to_end_id: str | None = None
    mandate_id: str | None = None
    remittance: tuple[str, ...] = ()
    codes: tuple[str, ...] = ()  # bank transaction codes: ISO domain-family-subfamily, the German GVC


@dataclass(frozen=True, slots=True)
class Entry:
    amount: Decimal
    currency: str
    credit: bool
    booked_on: date
    value_on: date | None
    details: tuple[Detail, ...]
    xml: str  # the entry element's original text, for `raw`

    @property
    def signed(self) -> Decimal:
        return self.amount if self.credit else -self.amount


@dataclass(frozen=True, slots=True)
class Report:
    message_id: str
    opening: Balance | None
    closing: Balance | None
    entries: tuple[Entry, ...]


@dataclass(frozen=True, slots=True)
class Statement:
    reader: str  # the reader's name, `olb`
    message_type: str  # `camt.052`, `camt.053`
    export_date: date | None  # the creation date, where the file states one
    reports: tuple[Report, ...]
    pending: int  # entries the file holds that are not booked yet: never imported
