"""The CSV profile: plain data kept in `importer_instance.settings` (csv.md §1-§6).

Frozen dataclasses with `from_dict` / `to_dict` / `validate`; JSON in, JSON out. Every
problem raises `InvalidProfile` with a message that starts with the setting's name.

A column reference (`ColRef`) is a header name, `Name#2` for the second column of that
name, or an integer position counted from 1.
"""

from __future__ import annotations

import codecs
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.plugins.errors import InvalidProfile
from app.plugins.importers.csv import dates

ColRef = str | int


def _fail(setting: str, message: str) -> InvalidProfile:
    return InvalidProfile(f"{setting}: {message}")


# -- typed readers ----------------------------------------------------------------------------


def _mapping(v: Any, setting: str) -> Mapping[str, Any]:
    if not isinstance(v, Mapping):
        raise _fail(setting, "must be an object")
    return v


def _only(d: Mapping[str, Any], allowed: set[str], setting: str) -> None:
    for key in d:
        if key not in allowed:
            raise _fail(f"{setting}.{key}" if setting else key, "unknown setting")


def _str(v: Any, setting: str) -> str:
    if not isinstance(v, str):
        raise _fail(setting, "must be text")
    return v


def _opt_str(v: Any, setting: str) -> str | None:
    return None if v is None else _str(v, setting)


def _int(v: Any, setting: str) -> int:
    if type(v) is not int:
        raise _fail(setting, "must be a whole number")
    return v


def _bool(v: Any, setting: str) -> bool:
    if type(v) is not bool:
        raise _fail(setting, "must be true or false")
    return v


def _list(v: Any, setting: str) -> list[Any]:
    if not isinstance(v, list | tuple):
        raise _fail(setting, "must be a list")
    return list(v)


def _colref(v: Any, setting: str) -> ColRef:
    if type(v) is int:
        if v < 1:
            raise _fail(setting, "a column position counts from 1")
        return v
    if isinstance(v, str):
        if not v.strip():
            raise _fail(setting, "a column name must not be empty")
        return v
    raise _fail(setting, "must be a column name or a position")


def _opt_colref(v: Any, setting: str) -> ColRef | None:
    return None if v is None else _colref(v, setting)


def _regex(v: str, setting: str) -> None:
    try:
        re.compile(v)
    except re.error as exc:
        raise _fail(setting, f"not a valid regular expression ({exc})") from exc


def _counterparty_name(v: Any) -> tuple[ColRef | None, str | None]:
    """A column, or `{"column", "pattern"}`: the name is the pattern's first group in the cell."""
    if not isinstance(v, Mapping):
        return _opt_colref(v, "counterparty_name"), None
    _only(v, {"column", "pattern"}, "counterparty_name")
    if "column" not in v:
        raise _fail("counterparty_name", "needs a column")
    return (
        _colref(v["column"], "counterparty_name.column"),
        _opt_str(v.get("pattern"), "counterparty_name.pattern"),
    )


# -- parts ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AmountSpec:
    """One signed column, or a credit and a debit column (amount = credit - debit)."""

    column: ColRef | None = None
    credit: ColRef | None = None
    debit: ColRef | None = None

    @classmethod
    def from_dict(cls, v: Any) -> AmountSpec:
        d = _mapping(v, "amount")
        _only(d, {"column", "credit", "debit"}, "amount")
        return cls(
            _opt_colref(d.get("column"), "amount.column"),
            _opt_colref(d.get("credit"), "amount.credit"),
            _opt_colref(d.get("debit"), "amount.debit"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "credit": self.credit, "debit": self.debit}

    def validate(self) -> None:
        pair = (self.credit is not None, self.debit is not None)
        if self.column is not None and any(pair):
            raise _fail("amount", "give either one signed column or a credit and a debit column")
        if self.column is None and pair != (True, True):
            raise _fail("amount", "give one signed column, or both a credit and a debit column")


@dataclass(frozen=True, slots=True)
class InstructedSpec:
    amount: ColRef
    currency: ColRef

    @classmethod
    def from_dict(cls, v: Any) -> InstructedSpec:
        d = _mapping(v, "instructed")
        _only(d, {"amount", "currency"}, "instructed")
        if "amount" not in d or "currency" not in d:
            raise _fail("instructed", "needs an amount and a currency column")
        return cls(_colref(d["amount"], "instructed.amount"), _colref(d["currency"], "instructed.currency"))

    def to_dict(self) -> dict[str, Any]:
        return {"amount": self.amount, "currency": self.currency}


@dataclass(frozen=True, slots=True)
class RowFilter:
    column: ColRef
    equals: str | None = None
    matches: str | None = None

    @classmethod
    def from_dict(cls, v: Any) -> RowFilter:
        d = _mapping(v, "filters")
        _only(d, {"column", "equals", "matches"}, "filters")
        if "column" not in d:
            raise _fail("filters", "a filter needs a column")
        return cls(
            _colref(d["column"], "filters.column"),
            _opt_str(d.get("equals"), "filters.equals"),
            _opt_str(d.get("matches"), "filters.matches"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "equals": self.equals, "matches": self.matches}

    def validate(self) -> None:
        if (self.equals is None) == (self.matches is None):
            raise _fail("filters", "a filter needs exactly one of equals and matches")
        if self.matches is not None:
            _regex(self.matches, "filters.matches")


@dataclass(frozen=True, slots=True)
class LocatedDate:
    """A date found in the file by label: a cell at an offset, or a pattern in a cell's text.

    Without `label` it is anchored at the balance label (balance dates only).
    """

    format: str
    label: str | None = None
    right: int = 0
    below: int = 0
    pattern: str | None = None

    @classmethod
    def from_dict(cls, v: Any, setting: str) -> LocatedDate:
        d = _mapping(v, setting)
        _only(d, {"format", "label", "right", "below", "pattern"}, setting)
        if "format" not in d:
            raise _fail(setting, "needs a date format")
        return cls(
            _str(d["format"], f"{setting}.format"),
            _opt_str(d.get("label"), f"{setting}.label"),
            _int(d.get("right", 0), f"{setting}.right"),
            _int(d.get("below", 0), f"{setting}.below"),
            _opt_str(d.get("pattern"), f"{setting}.pattern"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "label": self.label,
            "right": self.right,
            "below": self.below,
            "pattern": self.pattern,
        }

    def validate(self, setting: str, *, label_required: bool) -> None:
        try:
            dates.validate_format(self.format)
        except ValueError as exc:
            raise _fail(f"{setting}.format", str(exc)) from exc
        if label_required and not (self.label and self.label.strip()):
            raise _fail(setting, "needs a label")
        if self.right < 0 or self.below < 0:
            raise _fail(setting, "offsets are counts of cells right and rows below, not negative")
        if self.pattern is not None:
            _regex(self.pattern, f"{setting}.pattern")


@dataclass(frozen=True, slots=True)
class BalanceSpec:
    """`running_column` (read `column`) or `labelled` (a figure found by `label`)."""

    mode: str
    column: ColRef | None = None
    label: str | None = None
    right: int = 0
    below: int = 0
    date: LocatedDate | None = None

    @classmethod
    def from_dict(cls, v: Any) -> BalanceSpec:
        d = _mapping(v, "balance")
        _only(d, {"mode", "column", "label", "right", "below", "date"}, "balance")
        date_v = d.get("date")
        return cls(
            _str(d.get("mode"), "balance.mode"),
            _opt_colref(d.get("column"), "balance.column"),
            _opt_str(d.get("label"), "balance.label"),
            _int(d.get("right", 0), "balance.right"),
            _int(d.get("below", 0), "balance.below"),
            None if date_v is None else LocatedDate.from_dict(date_v, "balance.date"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "column": self.column,
            "label": self.label,
            "right": self.right,
            "below": self.below,
            "date": None if self.date is None else self.date.to_dict(),
        }

    def validate(self) -> None:
        if self.mode == "running_column":
            if self.column is None:
                raise _fail("balance", "a running-balance column is needed")
        elif self.mode == "labelled":
            if not (self.label and self.label.strip()):
                raise _fail("balance", "a labelled figure needs a label")
            if self.right < 0 or self.below < 0:
                raise _fail("balance", "offsets are counts of cells right and rows below, not negative")
            if self.date is not None:
                self.date.validate("balance.date", label_required=False)
        else:
            raise _fail("balance", "mode must be running_column or labelled (use null for none)")


@dataclass(frozen=True, slots=True)
class StatementPaymentSpec:
    counter_account_ref: str
    purpose: str
    date_offset_days: int

    @classmethod
    def from_dict(cls, v: Any) -> StatementPaymentSpec:
        d = _mapping(v, "statement_payment")
        _only(d, {"counter_account_ref", "purpose", "date_offset_days"}, "statement_payment")
        for key in ("counter_account_ref", "purpose", "date_offset_days"):
            if key not in d:
                raise _fail("statement_payment", f"{key} is required")
        return cls(
            _str(d["counter_account_ref"], "statement_payment.counter_account_ref"),
            _str(d["purpose"], "statement_payment.purpose"),
            _int(d["date_offset_days"], "statement_payment.date_offset_days"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "counter_account_ref": self.counter_account_ref,
            "purpose": self.purpose,
            "date_offset_days": self.date_offset_days,
        }

    def validate(self) -> None:
        if not self.counter_account_ref.strip():
            raise _fail("statement_payment", "counter_account_ref must not be empty")
        if not 1 <= self.date_offset_days <= 366:
            raise _fail("statement_payment", "date_offset_days must be between 1 and 366")


_OPTIONAL_COLUMNS = (
    "counterparty_name",
    "counterparty_ref",
    "counterparty_bic",
    "end_to_end_id",
    "mandate_ref",
    "booking_text",
)
_KEYS = {
    "encoding",
    "delimiter",
    "quote",
    "header_marker",
    "booked_on",
    "value_on",
    "date_format",
    "amount",
    "decimal_sep",
    "thousands_sep",
    "invert_amounts",
    "invert_balance",
    *_OPTIONAL_COLUMNS,
    "purpose",
    "instructed",
    "currency",
    "placeholders",
    "filters",
    "balance",
    "export_date",
    "coverage_end",
    "statement_payment",
}
_REQUIRED = ("header_marker", "booked_on", "date_format", "amount")


@dataclass(frozen=True, slots=True)
class Profile:
    header_marker: tuple[str, ...]
    booked_on: ColRef
    date_format: str
    amount: AmountSpec
    encoding: str | None = None
    delimiter: str | None = None
    quote: str = '"'
    value_on: ColRef | None = None
    decimal_sep: str = ","
    thousands_sep: str = "."
    invert_amounts: bool = False
    invert_balance: bool = False
    counterparty_name: ColRef | None = None
    counterparty_pattern: str | None = None
    counterparty_ref: ColRef | None = None
    counterparty_bic: ColRef | None = None
    end_to_end_id: ColRef | None = None
    mandate_ref: ColRef | None = None
    booking_text: ColRef | None = None
    purpose: tuple[ColRef, ...] = ()
    instructed: InstructedSpec | None = None
    currency: ColRef | None = None
    placeholders: tuple[str, ...] = ()
    filters: tuple[RowFilter, ...] = ()
    balance: BalanceSpec | None = None
    export_date: LocatedDate | None = None
    coverage_end: LocatedDate | None = None
    statement_payment: StatementPaymentSpec | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Profile:
        d = _mapping(data, "profile")
        _only(d, _KEYS, "")
        for key in _REQUIRED:
            if key not in d:
                raise _fail(key, "is required")
        optional_cols = {
            k: _opt_colref(d.get(k), k)
            for k in ("value_on", "currency", *(c for c in _OPTIONAL_COLUMNS if c != "counterparty_name"))
        }
        name_column, name_pattern = _counterparty_name(d.get("counterparty_name"))

        def part(key: str, build: Any) -> Any:
            return None if d.get(key) is None else build(d[key])

        return cls(
            header_marker=tuple(_str(m, "header_marker") for m in _list(d["header_marker"], "header_marker")),
            booked_on=_colref(d["booked_on"], "booked_on"),
            date_format=_str(d["date_format"], "date_format"),
            amount=AmountSpec.from_dict(d["amount"]),
            encoding=_opt_str(d.get("encoding"), "encoding"),
            delimiter=_opt_str(d.get("delimiter"), "delimiter"),
            quote=_str(d.get("quote", '"'), "quote"),
            decimal_sep=_str(d.get("decimal_sep", ","), "decimal_sep"),
            thousands_sep=_str(d.get("thousands_sep", "."), "thousands_sep"),
            invert_amounts=_bool(d.get("invert_amounts", False), "invert_amounts"),
            invert_balance=_bool(d.get("invert_balance", False), "invert_balance"),
            purpose=tuple(_colref(c, "purpose") for c in _list(d.get("purpose", []), "purpose")),
            instructed=part("instructed", InstructedSpec.from_dict),
            placeholders=tuple(
                _str(p, "placeholders") for p in _list(d.get("placeholders", []), "placeholders")
            ),
            filters=tuple(RowFilter.from_dict(f) for f in _list(d.get("filters", []), "filters")),
            balance=part("balance", BalanceSpec.from_dict),
            export_date=part("export_date", lambda v: LocatedDate.from_dict(v, "export_date")),
            coverage_end=part("coverage_end", lambda v: LocatedDate.from_dict(v, "coverage_end")),
            statement_payment=part("statement_payment", StatementPaymentSpec.from_dict),
            counterparty_name=name_column,
            counterparty_pattern=name_pattern,
            **optional_cols,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "quote": self.quote,
            "header_marker": list(self.header_marker),
            "booked_on": self.booked_on,
            "value_on": self.value_on,
            "date_format": self.date_format,
            "amount": self.amount.to_dict(),
            "decimal_sep": self.decimal_sep,
            "thousands_sep": self.thousands_sep,
            "invert_amounts": self.invert_amounts,
            "invert_balance": self.invert_balance,
            **{k: getattr(self, k) for k in _OPTIONAL_COLUMNS if k != "counterparty_name"},
            "counterparty_name": self.counterparty_name
            if self.counterparty_pattern is None
            else {"column": self.counterparty_name, "pattern": self.counterparty_pattern},
            "purpose": list(self.purpose),
            "instructed": None if self.instructed is None else self.instructed.to_dict(),
            "currency": self.currency,
            "placeholders": list(self.placeholders),
            "filters": [f.to_dict() for f in self.filters],
            "balance": None if self.balance is None else self.balance.to_dict(),
            "export_date": None if self.export_date is None else self.export_date.to_dict(),
            "coverage_end": None if self.coverage_end is None else self.coverage_end.to_dict(),
            "statement_payment": None if self.statement_payment is None else self.statement_payment.to_dict(),
        }

    def validate(self) -> None:
        if self.encoding is not None:
            try:
                codecs.lookup(self.encoding)
            except LookupError as exc:
                raise _fail("encoding", f"unknown encoding {self.encoding!r}") from exc
        if self.delimiter is not None and len(self.delimiter) != 1:
            raise _fail("delimiter", "must be a single character (or null to detect)")
        if len(self.quote) != 1:
            raise _fail("quote", "must be a single character")
        if not self.header_marker or any(not m.strip() for m in self.header_marker):
            raise _fail("header_marker", "needs at least one column name, none empty")
        try:
            dates.validate_format(self.date_format)
        except ValueError as exc:
            raise _fail("date_format", str(exc)) from exc
        self.amount.validate()
        if len(self.decimal_sep) != 1:
            raise _fail("decimal_sep", "must be a single character")
        if len(self.thousands_sep) > 1:
            raise _fail("thousands_sep", "must be one character or empty")
        if self.thousands_sep == self.decimal_sep:
            raise _fail("thousands_sep", "must differ from decimal_sep")
        if self.counterparty_pattern is not None:
            setting = "counterparty_name.pattern"
            _regex(self.counterparty_pattern, setting)
            if re.compile(self.counterparty_pattern).groups < 1:
                raise _fail(setting, "needs a capture group: its first group is the name")
        for f in self.filters:
            f.validate()
        if self.balance is not None:
            self.balance.validate()
        if self.export_date is not None:
            self.export_date.validate("export_date", label_required=True)
        if self.coverage_end is not None:
            self.coverage_end.validate("coverage_end", label_required=True)
        if self.statement_payment is not None:
            self.statement_payment.validate()
