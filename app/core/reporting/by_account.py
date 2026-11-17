"""Money by account over a date range (spec §8, architecture §4.1): a list of links, each a `Line`.

What each account received, passed on and paid. The flows are the by-category figures cut by account:
per kind, every top-level category (with its descendants) and the accounts behind it, the categories
beyond `top` summed per account as "other", and per account the unclassified money in and out and its
reconciliations as one net link, each group with its total. The transfers are counted once, by the
outgoing leg, per sending account and counter-account (a leg with `amount < 0` and a counter-account,
paired or not). Every unpaired transfer leg is one `unpaired` line (the Overview's figure cut to the
filter); of them only an outgoing leg with a counter-account is also in a link. `stayed` is derived: what
an account received on the income side, less what it transferred out, with both components.

Two statements, both selecting through `app.core.ledger.compose` like every report, each entry valued once
(`base_value()`, I27): the flows grouped by account, class and category, and the transfer legs grouped by
account and counter-account. Every link is signed as booked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, and_, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.core.ledger import LedgerFilter, compose
from app.core.ledger.sql import le
from app.core.reporting.facts import CLASS_OF, Facts, rcat
from app.core.reporting.line import Line, add, line_of_group
from app.core.reporting.tree import Node, category_tree, pick_slices


@dataclass(frozen=True)
class AccountLink:
    account_id: int
    line: Line


@dataclass(frozen=True)
class CategoryLinks:
    category_id: int  # a top-level category
    total: Line  # with its descendants: the by-category figure
    accounts: tuple[AccountLink, ...]  # its total cut by account


@dataclass(frozen=True)
class AccountLinks:
    total: Line  # the group's Line: the sum of its links, by-category's figure for the same range
    accounts: tuple[AccountLink, ...]


@dataclass(frozen=True)
class KindLinks:
    total: Line  # the by-category total of the kind
    categories: tuple[CategoryLinks, ...]  # top-level, by magnitude; only those with entries
    slices: tuple[int, ...] | None  # with `top`: the largest top-level categories of the kind's sign
    other: tuple[AccountLink, ...] | None  # with `top`: the remaining ones summed per account; None if none


@dataclass(frozen=True)
class TransferTo:
    account_id: int  # the leg's counter-account
    line: Line  # negative: the outgoing legs


@dataclass(frozen=True)
class TransferGroup:
    from_account_id: int
    total: Line  # the sum of its `to` lines
    to: tuple[TransferTo, ...]


@dataclass(frozen=True)
class Stayed:
    account_id: int
    amount: int  # minor units of the base currency, positive: received + transferred_out
    received: int  # the drawn income-side links, summed
    transferred_out: int  # the outgoing transfers, signed as booked (<= 0)


@dataclass(frozen=True)
class ByAccount:
    income: KindLinks
    expense: KindLinks
    unclassified_in: AccountLinks
    unclassified_out: AccountLinks
    reconciliations: AccountLinks  # accounts: one net link each
    transfers: tuple[TransferGroup, ...]
    unpaired: Line
    stayed: tuple[Stayed, ...]


def _order(link: Any) -> tuple[int, ...]:
    """Largest magnitude first (an unvalued total counts as 0), then by id(s)."""
    line = link.total if hasattr(link, "total") else link.line
    ident = link.from_account_id if hasattr(link, "from_account_id") else link.account_id
    return (-abs(line.total or 0), ident)


def _links(by_account: dict[int, list[Line]]) -> tuple[AccountLink, ...]:
    return tuple(sorted((AccountLink(a, add(lines)) for a, lines in by_account.items()), key=_order))


def _flows(conn: Connection, flt: LedgerFilter) -> dict[tuple[int, str, int | None], Line]:
    """The flows and reconciliations by (account, class, category), currencies added."""
    parts = compose(flt)
    base = func.base_value(le.c.amount, le.c.currency, le.c.booked_on)
    entries = (
        select(
            le.c.account_id.label("account_id"),
            CLASS_OF.label("klass"),
            le.c.category_id.label("category_id"),
            le.c.currency.label("currency"),
            le.c.amount.label("amount"),
            base.label("base"),
        )
        .select_from(parts.source.outerjoin(rcat, rcat.c.id == le.c.category_id))
        .where(*parts.where, or_(le.c.type.is_(None), le.c.type.in_(("flow", "reconciliation"))))
        # valued once per entry: the planner may not inline the conversion into each aggregate below
        .cte("entries")
        .prefix_with("MATERIALIZED")
    )
    stmt = select(
        entries.c.account_id,
        entries.c.klass,
        entries.c.category_id,
        entries.c.currency,
        func.count().label("n"),
        func.count().filter(entries.c.base.is_(None)).label("n_unvalued"),
        func.coalesce(func.sum(entries.c.base), 0).label("base_sum"),
        func.coalesce(func.sum(entries.c.amount).filter(entries.c.base.is_(None)), 0).label("unvalued_sum"),
    ).group_by(entries.c.account_id, entries.c.klass, entries.c.category_id, entries.c.currency)
    grouped: dict[tuple[int, str, int | None], list[Line]] = {}
    for r in conn.execute(stmt):
        key = (int(r.account_id), str(r.klass), None if r.category_id is None else int(r.category_id))
        grouped.setdefault(key, []).append(
            line_of_group(str(r.currency), int(r.n), int(r.n_unvalued), int(r.base_sum), int(r.unvalued_sum))
        )
    return {key: add(lines) for key, lines in grouped.items()}


def _transfer_lines(conn: Connection, flt: LedgerFilter) -> tuple[dict[tuple[int, int], Line], Line]:
    """The outgoing legs with a counter-account by (account, counter-account), and the unpaired line.

    A link: `amount < 0` with a counter-account, paired or not. Unpaired: every transfer leg with no
    counterpart entry, either sign, with or without a counter-account (the predicate of the Overview's
    `unpaired_transfers`). An unpaired outgoing leg with a counter-account is in both; an incoming leg is
    in no link. Each leg is valued once; the two sets are told apart on the grouped rows.
    """
    parts = compose(flt)
    base = func.base_value(le.c.amount, le.c.currency, le.c.booked_on)
    in_link: ColumnElement[bool] = and_(le.c.amount < 0, le.c.counter_account_id.is_not(None))
    unpaired: ColumnElement[bool] = le.c.counterpart_entry_id.is_(None)
    entries = (
        select(
            in_link.label("in_link"),
            unpaired.label("unpaired"),
            le.c.account_id.label("account_id"),
            le.c.counter_account_id.label("counter_account_id"),
            le.c.currency.label("currency"),
            le.c.amount.label("amount"),
            base.label("base"),
        )
        .select_from(parts.source)
        .where(*parts.where, le.c.type == "transfer", or_(in_link, unpaired))
        .cte("legs")
        .prefix_with("MATERIALIZED")
    )
    stmt = select(
        entries.c.in_link,
        entries.c.unpaired,
        entries.c.account_id,
        entries.c.counter_account_id,
        entries.c.currency,
        func.count().label("n"),
        func.count().filter(entries.c.base.is_(None)).label("n_unvalued"),
        func.coalesce(func.sum(entries.c.base), 0).label("base_sum"),
        func.coalesce(func.sum(entries.c.amount).filter(entries.c.base.is_(None)), 0).label("unvalued_sum"),
    ).group_by(
        entries.c.in_link,
        entries.c.unpaired,
        entries.c.account_id,
        entries.c.counter_account_id,
        entries.c.currency,
    )
    pairs: dict[tuple[int, int], list[Line]] = {}
    left: list[Line] = []
    for r in conn.execute(stmt):
        one = line_of_group(
            str(r.currency), int(r.n), int(r.n_unvalued), int(r.base_sum), int(r.unvalued_sum)
        )
        if r.in_link:
            pairs.setdefault((int(r.account_id), int(r.counter_account_id)), []).append(one)
        if r.unpaired:
            left.append(one)
    return {key: add(lines) for key, lines in pairs.items()}, add(left)


def _roots_of(nodes: list[Node]) -> dict[int, int]:
    """Each listed category's top-level ancestor (a category with entries has every ancestor listed)."""
    parent = {n.category_id: n.parent_id for n in nodes}

    def root(cid: int) -> int:
        while (up := parent[cid]) is not None:
            cid = up
        return cid

    return {cid: root(cid) for cid in parent}


def _kind(
    conn: Connection,
    flows: dict[tuple[int, str, int | None], Line],
    kind: str,
    top: int | None,
) -> tuple[KindLinks, dict[int, dict[int, Line]], list[int]]:
    """The kind's links; also each top-level category's accounts' Lines, and the categories that count
    on the income side (the slices, or with no `top` every top-level category)."""
    own: dict[tuple[int, int], Line] = {}
    summed: dict[int, list[Line]] = {}
    for (account, klass, cat), line in flows.items():
        if klass == kind and cat is not None:
            own[(account, cat)] = line
            summed.setdefault(cat, []).append(line)
    facts = Facts({(None, kind, cat): add(lines) for cat, lines in summed.items()})
    nodes, total = category_tree(conn, facts, kind, [None])
    root = _roots_of(nodes)
    per_root: dict[int, dict[int, list[Line]]] = {}
    for (account, cat), line in own.items():
        per_root.setdefault(root[cat], {}).setdefault(account, []).append(line)
    roots = [n for n in nodes if n.parent_id is None]
    categories = tuple(
        CategoryLinks(n.category_id, n.total_sum, _links(per_root.get(n.category_id, {}))) for n in roots
    )
    accounts = {r: {a: add(ls) for a, ls in by.items()} for r, by in per_root.items()}
    if top is None:
        # no limit: the categories pick_slices would choose (not the opposite-sign ones) count as slices
        unlimited, _ = pick_slices(nodes, kind, len(roots))
        return KindLinks(total, categories, None, None), accounts, [n.category_id for n in unlimited]
    chosen, rest = pick_slices(nodes, kind, top)
    other: dict[int, list[Line]] = {}
    for n in rest:
        for a, line in accounts.get(n.category_id, {}).items():
            other.setdefault(a, []).append(line)
    links = KindLinks(
        total,
        categories,
        tuple(n.category_id for n in chosen),
        _links(other) if rest else None,
    )
    return links, accounts, [n.category_id for n in chosen]


def by_account(conn: Connection, flt: LedgerFilter, top: int | None = None) -> ByAccount:
    flows = _flows(conn, flt)
    income, income_accounts, drawn_categories = _kind(conn, flows, "income", top)
    expense, _, _ = _kind(conn, flows, "expense", top)

    def beside(klass: str) -> AccountLinks:
        links = _links({a: [line] for (a, k, _), line in flows.items() if k == klass})
        return AccountLinks(add(k.line for k in links), links)

    unclassified_in = beside("unclassified_in")
    unclassified_out = beside("unclassified_out")
    reconciliations = beside("reconciliation")
    out, unpaired = _transfer_lines(conn, flt)
    to_by_sender: dict[int, list[TransferTo]] = {}
    for (a, b), line in out.items():
        to_by_sender.setdefault(a, []).append(TransferTo(b, line))
    transfers = tuple(
        sorted(
            (
                TransferGroup(a, add(t.line for t in tos), tuple(sorted(tos, key=_order)))
                for a, tos in to_by_sender.items()
            ),
            key=_order,
        )
    )

    # what each account drew on the income side: the links with a positive total
    received: dict[int, int] = {}

    def draw(account: int, line: Line) -> None:
        if line.total is not None and line.total > 0:
            received[account] = received.get(account, 0) + line.total

    for cat in drawn_categories:
        for a, line in income_accounts.get(cat, {}).items():
            draw(a, line)
    if income.other is not None:
        for link in income.other:
            draw(link.account_id, link.line)
    for link in (*unclassified_in.accounts, *reconciliations.accounts):
        draw(link.account_id, link.line)
    transferred_out = {g.from_account_id: g.total.total or 0 for g in transfers}  # unvalued counts as 0
    stayed = tuple(
        sorted(
            (
                Stayed(a, kept, got, transferred_out.get(a, 0))
                for a, got in received.items()
                if (kept := got + transferred_out.get(a, 0)) > 0
            ),
            key=lambda s: (-s.amount, s.account_id),
        )
    )
    return ByAccount(
        income=income,
        expense=expense,
        unclassified_in=unclassified_in,
        unclassified_out=unclassified_out,
        reconciliations=reconciliations,
        transfers=transfers,
        unpaired=unpaired,
        stayed=stayed,
    )
