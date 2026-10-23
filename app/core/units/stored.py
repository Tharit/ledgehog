"""Loading what a plan needs from the database (reads only): the stored closure and the world around it."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from datetime import date
from typing import Any, cast

from sqlalchemy import Connection, text

from app.core.importers.providers import instance_deliveries
from app.core.ingest.identity import canonical_text
from app.core.matching import MAX_WINDOW, Leg, PoolEntry, Summary
from app.core.matching.documents import DocInput, DocWindow
from app.core.matching.lines import Line
from app.core.resolution.doc_load import load_carriers, load_gated
from app.core.resolution.enrich import LinkedDocument
from app.core.resolution.load import load_accounts, load_rules
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import HistorySnapshot, load_votes
from app.core.settle.pairing import load_unpaired_legs
from app.core.settle.window import document_window, matching_window_days
from app.core.units.doc_world import DocumentInfo, DocWorld
from app.core.units.documents import DocumentSource
from app.core.units.draft import UnitDraft
from app.core.units.lookup import unit_ids_of
from app.core.units.plan import Stored, StoredSource, StoredUnit, World

_ENTRIES = text(
    """
    SELECT e.id, e.version, e.source_transaction_id, e.account_id, e.currency, e.booked_on, e.value_on,
           e.amount, e.type, e.payee_id, e.category_id, e.counter_account_id, e.counterpart_entry_id,
           e.description, e.note, e.derivation, e.document_id,
           l.document_id AS line_document_id, l.line_no,
           COALESCE((SELECT array_agg(t.tag_id ORDER BY t.tag_id)
                       FROM ledger_entry_tag AS t WHERE t.ledger_entry_id = e.id), '{}') AS tag_ids
      FROM ledger_entry AS e
      LEFT JOIN external_document_line AS l ON l.id = e.document_line_id
     WHERE e.id = ANY(:ids)
     ORDER BY e.id
    """
)

_SOURCES = text(
    """
    SELECT s.id, s.amount, s.account_id, s.currency, s.booked_on, s.value_on,
           (s.importer IS NULL) AS authored,
           s.counterparty_ref, s.counterparty_name, s.purpose, s.booking_text, s.mandate_ref,
           s.instructed_currency, s.end_to_end_id, s.instructed_amount
      FROM source_transaction AS s
     WHERE s.id = ANY(:ids)
    """
)


def load_stored_unit(conn: Connection, anchor_entry_id: int) -> StoredUnit | None:
    """The closure of `anchor_entry_id` as stored; None when there is no such entry or it is derived."""
    ids = unit_ids_of(conn, anchor_entry_id)
    if ids is None:
        return None
    return load_stored_entries(conn, anchor_entry_id, ids.entry_ids)


def load_stored_entries(conn: Connection, anchor_entry_id: int, entry_ids: Iterable[int]) -> StoredUnit:
    rows = conn.execute(_ENTRIES, {"ids": sorted(set(entry_ids))}).all()
    entries = tuple(
        Stored(
            id=r.id,
            version=r.version,
            source_transaction_id=r.source_transaction_id,
            account_id=r.account_id,
            currency=r.currency,
            booked_on=r.booked_on,
            value_on=r.value_on,
            amount=r.amount,
            type=r.type,
            payee_id=r.payee_id,
            category_id=r.category_id,
            counter_account_id=r.counter_account_id,
            counterpart_entry_id=r.counterpart_entry_id,
            description=r.description,
            note=r.note,
            derivation=cast(dict[str, Any], r.derivation),
            tag_ids=tuple(int(t) for t in r.tag_ids),
            document_id=r.document_id,
            document_line=None if r.line_no is None else (int(r.line_document_id), int(r.line_no)),
        )
        for r in rows
    )
    sources = {
        int(r.id): StoredSource(
            id=r.id,
            amount=r.amount,
            account_id=r.account_id,
            currency=r.currency,
            booked_on=r.booked_on,
            value_on=r.value_on,
            user_authored=r.authored,
            counterparty_ref=r.counterparty_ref,
            counterparty_name=r.counterparty_name,
            purpose=r.purpose,
            booking_text=r.booking_text,
            mandate_ref=r.mandate_ref,
            instructed_currency=r.instructed_currency,
            end_to_end_id=r.end_to_end_id,
            instructed_amount=r.instructed_amount,
        )
        for r in conn.execute(_SOURCES, {"ids": sorted({e.source_transaction_id for e in entries})})
    }
    return StoredUnit(anchor_entry_id=anchor_entry_id, sources=sources, entries=entries)


def _named(draft: UnitDraft) -> tuple[list[int], list[int]]:
    categories: set[int] = set()
    payees: set[int] = set()
    for e in draft.entries:
        if e.category.mode == "fixed" and isinstance(e.category.value, int):
            categories.add(e.category.value)
        if e.payee.mode == "fixed" and isinstance(e.payee.value, int):
            payees.add(e.payee.value)
    return sorted(categories), sorted(payees)


def load_world(conn: Connection, stored: StoredUnit, draft: UnitDraft, *, ledger_wide: bool = False) -> World:
    """Accounts, the classifiers for the current rules, and the history of every vote but the closure's own
    (the unit's entries never vote about themselves; the overlay adds the plan's confirmed units back).

    `ledger_wide` (the preview) also loads every unpaired transfer leg of the ledger, so that the simulation
    of settling can pair the unit's legs with legs outside it. A commit leaves it off: settling follows."""
    closure = {e.id for e in stored.entries}
    history = HistorySnapshot(v for v in load_votes(conn) if v.entry_id not in closure)
    categories, payees = _named(draft)
    found_categories = (
        frozenset(
            int(i)
            for i in conn.execute(
                text("SELECT id FROM category WHERE id = ANY(:ids)"), {"ids": categories}
            ).scalars()
        )
        if categories
        else frozenset[int]()
    )
    found_payees = (
        frozenset(
            int(i)
            for i in conn.execute(
                text("SELECT id FROM payee WHERE id = ANY(:ids)"), {"ids": payees}
            ).scalars()
        )
        if payees
        else frozenset[int]()
    )
    sync = {
        int(r.account_id): (bool(r.synced), r.synced_through)
        for r in conn.execute(
            text(
                "SELECT s.account_id, s.synced, c.synced_through FROM v_account_synced AS s"
                " JOIN v_account_coverage AS c ON c.account_id = s.account_id"
            )
        )
    }
    return World(
        account_sync=sync,
        matching_window=matching_window_days(conn),
        accounts=load_accounts(conn),
        classifiers=classifiers_for(load_rules(conn)),
        history=history,
        categories=found_categories,
        payees=found_payees,
        ledger_legs=load_unpaired_legs(conn) if ledger_wide else (),
        docs=load_doc_world(conn, stored, document_pick_ids(draft)),
    )


_PAYEE_PROVIDERS = text("SELECT id, document_provider FROM payee WHERE document_provider IS NOT NULL")

_SOURCES_OF_DOCUMENTS = text(
    "SELECT i.id, i.disabled, i.settings ->> 'start_date' AS start_date, c.covered_through"
    "  FROM importer_instance AS i LEFT JOIN v_document_coverage AS c ON c.importer_instance_id = i.id"
)

# the documents that can matter to the unit: those its entries carry, and those dated within the window of one
# of its sources' booking dates, in that source's currency or its instructed one, whatever payee a draft may
# give the entry (documents.md §2, §3); the carriers outside the unit are read apart
_DOCUMENTS = text(
    """
    SELECT d.id, d.provider, d.occurred_on, d.total, d.currency, d.merchant_name, d.version, d.title,
           d.external_id,
           (SELECT jsonb_agg(jsonb_build_array(l.line_no, l.amount, l.description) ORDER BY l.line_no)
              FROM external_document_line AS l WHERE l.document_id = d.id) AS lines
      FROM external_document AS d
     WHERE d.id = ANY(CAST(:carried AS bigint[]))
        OR EXISTS (SELECT 1 FROM unnest(CAST(:currencies AS text[]), CAST(:booked AS date[]))
                                AS k(currency, booked_on)
                    WHERE k.currency = d.currency
                      AND d.occurred_on BETWEEN k.booked_on - CAST(:back AS int)
                                            AND k.booked_on + CAST(:ahead AS int))
    """
)

# the documents a draft names (picks, lines echoed back), whoever carries them
_PICKED = text(
    """
    SELECT d.id, d.provider, d.occurred_on, d.total, d.currency, d.merchant_name, d.version, d.title,
           d.external_id,
           (SELECT jsonb_agg(jsonb_build_array(l.line_no, l.amount, l.description) ORDER BY l.line_no)
              FROM external_document_line AS l WHERE l.document_id = d.id) AS lines
      FROM external_document AS d
     WHERE d.id = ANY(CAST(:ids AS bigint[]))
    """
)


def _info(r: Any) -> DocumentInfo:
    return DocumentInfo(
        id=int(r.id),
        version=int(r.version),
        provider=str(r.provider),
        external_id=str(r.external_id),
        occurred_on=r.occurred_on,
        total=int(r.total),
        currency=str(r.currency).strip(),
        merchant_name=r.merchant_name,
        title=r.title,
        lines=tuple((int(n), int(a), str(d)) for n, a, d in (r.lines or ())),
    )


def load_doc_world(conn: Connection, stored: StoredUnit, picks: Collection[int] = ()) -> DocWorld:
    """What the simulation of settle steps 2 and 3 reads outside `stored` (`doc_world.DocWorld`): a few
    small queries, each cut to the transactions that have a provider payee or the documents that can match.
    `picks` are the documents the draft names: read whoever carries them."""
    payee_providers = {int(r.id): str(r.document_provider) for r in conn.execute(_PAYEE_PROVIDERS)}
    closure = sorted(e.id for e in stored.entries)
    carried = sorted({e.document_id for e in stored.entries if e.document_id is not None} | set(picks))
    if not payee_providers and not carried:
        return DocWorld(
            window=DocWindow(0, 0)
        )  # nothing can be matched, nothing is linked: judged without documents
    window = document_window(conn)
    currencies: list[str] = []
    booked: list[date] = []
    for src in stored.sources.values():
        currencies.append(src.currency.strip())
        booked.append(src.booked_on)
        if src.instructed_currency is not None and src.instructed_amount is not None:
            currencies.append(src.instructed_currency.strip())
            booked.append(src.booked_on)
    rows = conn.execute(
        _DOCUMENTS,
        {
            "carried": carried,
            "currencies": currencies,
            "booked": booked,
            "back": window.back,
            "ahead": window.ahead,
        },
    ).all()
    inside = set(closure)
    # the carriers outside the unit; the unit's own are its rows, which the overlay adds as they stand
    outside = load_carriers(conn, [int(r.id) for r in rows])
    docs: list[DocInput] = []
    details: dict[int, LinkedDocument] = {}
    infos: dict[int, DocumentInfo] = {}
    for r in rows:
        info = _info(r)
        infos[info.id] = info
        details[info.id] = LinkedDocument(merchant_name=info.merchant_name, lines=info.lines)
        docs.append(
            DocInput(
                info.id,
                info.provider,
                info.occurred_on,
                info.total,
                info.currency,
                lines=tuple(Line(n, a) for n, a, _d in info.lines),
                carriers=tuple(c for c in outside.get(info.id, ()) if c.entry_id not in inside),
            )
        )
    if picks:  # whoever carries them, a document the draft names is known
        for r in conn.execute(_PICKED, {"ids": sorted(picks)}):
            info = _info(r)
            infos[info.id] = info
            details[info.id] = LinkedDocument(merchant_name=info.merchant_name, lines=info.lines)
    others = load_gated(conn, closure)
    delivering = instance_deliveries(conn)
    sources = [
        DocumentSource(
            delivering.get(int(r.id), frozenset()),
            bool(r.disabled),
            date.fromisoformat(r.start_date) if r.start_date else None,
            r.covered_through,
        )
        for r in conn.execute(_SOURCES_OF_DOCUMENTS)
    ]
    return DocWorld(
        window=window,
        sources=sources,
        payee_providers=payee_providers,
        documents=docs,
        details=details,
        others=others,
        infos=infos,
    )


def document_pick_ids(draft: UnitDraft) -> list[int]:
    """The documents the draft names, ascending: picked, or the one a new entry's line belongs to."""
    ids = {e.document.document_id for e in draft.entries if e.document.document_id is not None}
    ids |= {e.document_line.document_id for e in draft.entries if e.document_line is not None}
    return sorted(ids)


def missing_tag(conn: Connection, draft: UnitDraft) -> tuple[int, int] | None:
    """The first `(index of the draft entry, tag id)` the draft adds that no longer exists, else None."""
    named = sorted({t for e in draft.entries for t in e.tags_add})
    if not named:
        return None
    found = {
        int(i)
        for i in conn.execute(text("SELECT id FROM tag WHERE id = ANY(:ids)"), {"ids": named}).scalars()
    }
    for i, e in enumerate(draft.entries):
        for t in sorted(e.tags_add):
            if t not in found:
                return i, t
    return None


# The movements offers are made of: for each leg (date, sign, account, counter-account or none) the entries of
# the OPPOSITE sign within `cap` days, on the counter-account where there is one, else on any other account;
# unpaired or paired transfer legs and untyped entries. One statement for all the legs, served by
# `ix_le_account_date` (a known counter-account) or `ix_le_date`; a duplicate has no entries (I3).
_POOL = text(
    """
    WITH legs AS (
        SELECT * FROM unnest(CAST(:dates AS date[]), CAST(:signs AS int[]), CAST(:accounts AS bigint[]),
                             CAST(:counters AS bigint[])) AS v(d, s, acc, counter)
    ), hit AS (
        SELECT DISTINCT e.id
          FROM legs AS v
          JOIN ledger_entry AS e
            ON e.booked_on BETWEEN v.d - CAST(:cap AS int) AND v.d + CAST(:cap AS int)
           AND (v.counter IS NULL OR e.account_id = v.counter)
           AND e.account_id <> v.acc
           AND ((v.s > 0 AND e.amount < 0) OR (v.s < 0 AND e.amount > 0))
           AND (e.type = 'transfer' OR e.type IS NULL)
           AND e.source_transaction_id IS NOT NULL
         WHERE e.id <> ALL(CAST(:skip AS bigint[]))
    )
    SELECT e.id, e.account_id, e.currency, e.amount, e.booked_on, e.type, e.counter_account_id,
           e.description, e.counterpart_entry_id,
           s.end_to_end_id, s.instructed_amount, s.instructed_currency, s.purpose,
           NOT EXISTS (SELECT 1 FROM ledger_entry AS o
                        WHERE o.source_transaction_id = e.source_transaction_id AND o.id < e.id) AS original,
           p.account_id AS p_account, p.booked_on AS p_booked_on, p.amount AS p_amount,
           p.currency AS p_currency, p.description AS p_description
      FROM hit
      JOIN ledger_entry AS e ON e.id = hit.id
      JOIN source_transaction AS s ON s.id = e.source_transaction_id
      LEFT JOIN ledger_entry AS p ON p.id = e.counterpart_entry_id
     ORDER BY e.booked_on, e.id
    """
)


def load_pool(conn: Connection, legs: Sequence[Leg], skip: Collection[int]) -> list[PoolEntry]:
    """The pool offers are made of, around `legs` and up to the widest window a pick may ask for.

    `skip` holds the entries of the plan (their planned state is what counts, not the stored one).
    """
    if not legs:
        return []
    rows = conn.execute(
        _POOL,
        {
            "dates": [leg.booked_on for leg in legs],
            "signs": [(leg.amount > 0) - (leg.amount < 0) for leg in legs],
            "accounts": [leg.account_id for leg in legs],
            "counters": [leg.counter_account_id for leg in legs],
            "cap": MAX_WINDOW,
            "skip": sorted(skip),
        },
    ).all()
    return [
        PoolEntry(
            leg=Leg(
                entry_id=r.id,
                account_id=r.account_id,
                currency=r.currency,
                amount=r.amount,
                booked_on=r.booked_on,
                type=r.type,
                counter_account_id=r.counter_account_id,
                end_to_end_id=r.end_to_end_id,
                instructed_amount=r.instructed_amount,
                instructed_currency=r.instructed_currency,
                purpose=canonical_text(r.purpose),
            ),
            original=bool(r.original),
            description=r.description,
            partner=None
            if r.counterpart_entry_id is None
            else Summary(
                entry_id=r.counterpart_entry_id,
                account_id=r.p_account,
                booked_on=r.p_booked_on,
                amount=r.p_amount,
                currency=r.p_currency,
                description=r.p_description,
            ),
        )
        for r in rows
    ]


def load_closure_of(conn: Connection, entry_ids: Iterable[int]) -> set[int]:
    """The ids of the units of `entry_ids` (each unit's entries, as `lookup.unit_ids_of`)."""
    out: set[int] = set()
    for entry_id in entry_ids:
        ids = unit_ids_of(conn, entry_id)
        if ids is not None:
            out.update(ids.entry_ids)
    return out


def pick_partner_ids(draft: UnitDraft) -> list[int]:
    """The partners the draft picks, ascending: each brings its own closure into the unit being drafted."""
    return sorted(
        {
            e.pairing.partner_entry_id
            for e in draft.entries
            if e.pairing.mode == "pick" and e.pairing.partner_entry_id is not None
        }
    )


_CARRIERS = text(
    "SELECT min(id) FROM ledger_entry WHERE document_id = ANY(CAST(:docs AS bigint[])) GROUP BY document_id"
)


def carriers_of(conn: Connection, documents: Collection[int]) -> list[int]:
    """One carrying entry of each of `documents` that has any (its unit holds the other carriers)."""
    if not documents:
        return []
    return [int(i) for i in conn.execute(_CARRIERS, {"docs": sorted(documents)}).scalars()]


def drafted_closure(conn: Connection, draft: UnitDraft, anchor_ids: Iterable[int]) -> set[int]:
    """The unit as drafted: `anchor_ids` (the anchor's own closure), the closure of every partner the draft
    picks, and the closure of every carrier of a document the draft picks (all the carriers of one document
    are one unit). A document that no entry carries brings nothing."""
    return (
        set(anchor_ids)
        | load_closure_of(conn, pick_partner_ids(draft))
        | load_closure_of(conn, carriers_of(conn, document_pick_ids(draft)))
    )


def load_drafted_unit(conn: Connection, draft: UnitDraft) -> tuple[StoredUnit, frozenset[int]] | None:
    """The closure of the anchor extended by the closure of every partner and of every document carrier the
    draft picks (the unit as drafted), and the ids of the anchor's own closure. None when the anchor is in no
    unit. A partner that is in no unit is left out: the plan refuses the pick."""
    ids = unit_ids_of(conn, draft.anchor_entry_id)
    if ids is None:
        return None
    all_ids = drafted_closure(conn, draft, ids.entry_ids)
    return load_stored_entries(conn, draft.anchor_entry_id, all_ids), frozenset(ids.entry_ids)
