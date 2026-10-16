"""Which entries are confirmed (spec §6, I20, I22, I31), from columns and keys, never from stored flags.

A UNIT is the entries of one source transaction plus, when one of them is a transfer leg that is
paired, the entries of the partner's source transaction. A source holds at most one transfer entry
(I31, `ux_le_one_transfer_per_source`) and a pair has exactly two legs (`ux_le_counterpart`,
`trg_transfer_pair`), so the closure is at most two source transactions and one self-join finds it:
the unit key of an entry is the lowest source id among its own source and its partner's, taken over
every entry of its source (so the siblings of a transfer leg share the key of the leg).

A unit is confirmed when every entry of it is complete and carries only standing keys:

* a type; for a flow a category (spec §3.4); for a transfer its pair (`counterpart_entry_id`, I22,
  so an unpaired transfer is never confirmed);
* no derivation key whose pass is not standing (`history`, `llm`, `matcher_proposal`, or a key
  without a pass);
* no document open (spec §6, documents.md §1, §7): its original entry does not await a document (an active
  document source has not covered `booked_on` plus the document window) and has no suggestions (documents
  that match it, with no automatic link possible). The test applies only to a transaction's original entry
  whose payee has a `document_provider` and which has no `document` key, so it is GATED to that small subset
  and costs every other entry nothing. `doc_awaited` and `doc_suggested` are exposed per entry (the flags
  `waiting` and `document_suggested` read them). Which importer provides which provider is the registry of
  `core/importers/providers.py`, bound as `units_binds()`.

This is computed here rather than read from `review_flags` so that it is right in the middle of a
settle, where the flags are not yet rewritten and a new entry's empty default would otherwise read as
clean. Derived entries (balance records) have no source transaction and are in no unit.
`app/core/units/state.py` is the same judgement in pure Python, pinned to this SQL by a test.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.core.importers.providers import provider_pairs
from app.core.plugins.classifier import STANDING_PASSES

STANDING = sorted(STANDING_PASSES)

# The document window (spec §5.8), read from the connection like `ledger.matching_window_days`
# (`core/settle/window.py: document_window`). Evaluated only inside the gated subqueries below.
_DOC_WINDOW = "current_setting('ledger.document_window_days')::int"

# A document of `{d}` matches the transaction `{st}` (a source_transaction alias) booked on `{on}`: exactly,
# with its sign, in the transaction's currency or its instructed one (documents.md §3), within the window of
# its booking date (§2).
_DOC_MATCHES = (
    "(({d}.currency = {st}.currency AND {d}.total = {st}.amount)"
    " OR ({d}.currency = {st}.instructed_currency AND {d}.total = {st}.instructed_amount))"
    " AND abs({d}.occurred_on - {on}) <= " + _DOC_WINDOW
)

# The original entry of a source transaction (I31), whose payee has a provider, with no `document` key:
# the only entry the document test looks at (documents.md §1).
_GATE = """pp.document_provider IS NOT NULL
                                AND NOT jsonb_exists(le.derivation, 'document')
                                AND NOT EXISTS (SELECT 1 FROM ledger_entry AS lo
                                                 WHERE lo.source_transaction_id = le.source_transaction_id
                                                   AND lo.id < le.id)"""

# awaited (documents.md §7): some instance that is not disabled, provides the provider (registry), has a
# start date not after the booking date (an instance without one has no lower bound) and whose document
# coverage has not reached booked_on plus the window; never run = no coverage = awaiting.
_AWAITED = (
    """EXISTS (SELECT 1
                                  FROM unnest(CAST(:doc_importers AS text[]),
                                              CAST(:doc_providers AS text[])) AS r(importer, provider)
                                  JOIN importer_instance AS ii ON ii.importer = r.importer
                                  LEFT JOIN v_document_coverage AS dc ON dc.importer_instance_id = ii.id
                                 WHERE r.provider = pp.document_provider
                                   AND NOT ii.disabled
                                   AND (ii.settings ->> 'start_date' IS NULL
                                        OR CAST(ii.settings ->> 'start_date' AS date) <= le.booked_on)
                                   AND (dc.covered_through IS NULL
                                        OR dc.covered_through < le.booked_on + """
    + _DOC_WINDOW
    + """))"""
)

# suggested (documents.md §3, §4): the candidates (the provider's documents carried by no entry that match)
# are several, or the one is also a candidate of another transaction no decision has been made on (an
# original entry of a payee with that provider and no `document` key): no automatic link is possible.
_SUGGESTED = (
    """(SELECT count(*) > 1 OR COALESCE(bool_or(c.shared), false)
                                  FROM (SELECT EXISTS (
                                            SELECT 1
                                              FROM ledger_entry AS o
                                              JOIN payee AS op ON op.id = o.payee_id
                                              JOIN source_transaction AS ost
                                                ON ost.id = o.source_transaction_id
                                             WHERE op.document_provider = d.provider AND o.id <> le.id
                                               AND NOT jsonb_exists(o.derivation, 'document')
                                               AND NOT EXISTS (
                                                    SELECT 1 FROM ledger_entry AS oo
                                                     WHERE oo.source_transaction_id = o.source_transaction_id
                                                       AND oo.id < o.id)
                                               AND """
    + _DOC_MATCHES.format(d="d", st="ost", on="ost.booked_on")
    + """) AS shared
                                          FROM external_document AS d
                                         WHERE d.provider = pp.document_provider
                                           AND NOT EXISTS (SELECT 1 FROM ledger_entry AS cr
                                                            WHERE cr.document_id = d.id)
                                           AND """
    + _DOC_MATCHES.format(d="d", st="st", on="st.booked_on")
    + """) AS c)"""
)

# One row per movement entry: its id, source, `unit_key` (the unit), `unit_ok` (the unit is
# confirmed), `unit_has_nonstanding` (some entry of the unit carries a key that awaits a human: what
# `unconfirmed` means), `first_id` (the lowest entry id of its SOURCE transaction: the original entry
# of a split, I31) and `doc_awaited`, `doc_suggested` (the entry's transaction awaits a document, or has
# suggestions: false for every entry the gate excludes). `{scope}` narrows to the units of given entries,
# or to all.
_UNITS = """
    SELECT m.id, m.src, m.unit_key,
           bool_and(m.complete AND m.standing AND NOT (m.doc_awaited OR m.doc_suggested))
               OVER (PARTITION BY m.unit_key) AS unit_ok,
           bool_or(NOT m.standing) OVER (PARTITION BY m.unit_key) AS unit_has_nonstanding,
           min(m.id) OVER (PARTITION BY m.src) AS first_id,
           m.doc_awaited, m.doc_suggested
      FROM (
            SELECT k.id, k.src, k.complete, k.standing, k.doc_awaited, k.doc_suggested,
                   min(k.direct_key) OVER (PARTITION BY k.src) AS unit_key
              FROM (
                    SELECT le.id, le.source_transaction_id AS src,
                           LEAST(le.source_transaction_id,
                                 COALESCE(p.source_transaction_id, le.source_transaction_id)) AS direct_key,
                           (le.type IS NOT NULL
                            AND (le.type <> 'flow' OR le.category_id IS NOT NULL)
                            AND (le.type <> 'transfer' OR le.counterpart_entry_id IS NOT NULL)) AS complete,
                           NOT EXISTS (
                               SELECT 1 FROM jsonb_each(le.derivation) AS d
                                WHERE COALESCE(d.value ->> 'pass', '') <> ALL (:standing)) AS standing,
                           CASE WHEN {gate} THEN {awaited} ELSE false END AS doc_awaited,
                           CASE WHEN {gate}
                                THEN (SELECT {suggested} FROM source_transaction AS st
                                       WHERE st.id = le.source_transaction_id)
                                ELSE false END AS doc_suggested
                      FROM ledger_entry AS le
                      LEFT JOIN ledger_entry AS p ON p.id = le.counterpart_entry_id
                      LEFT JOIN payee AS pp ON pp.id = le.payee_id
                     WHERE le.source_transaction_id IS NOT NULL{scope}
                   ) AS k
           ) AS m
"""

_ALL = ""
# the sources of the given entries, and of the partners of the transfer legs in those sources
_OF_ENTRIES = """
       AND le.source_transaction_id IN (
            SELECT x.source_transaction_id FROM ledger_entry AS x WHERE x.id = ANY(:ids)
            UNION
            SELECT q.source_transaction_id
              FROM ledger_entry AS x
              JOIN ledger_entry AS t ON t.source_transaction_id = x.source_transaction_id
              JOIN ledger_entry AS q ON q.id = t.counterpart_entry_id
             WHERE x.id = ANY(:ids))
"""


def units_sql(*, of_entries: bool = False) -> str:
    """The `units` CTE body (see above); bind `units_binds()` (and `ids` when `of_entries`)."""
    return _UNITS.format(
        scope=_OF_ENTRIES if of_entries else _ALL, gate=_GATE, awaited=_AWAITED, suggested=_SUGGESTED
    )


def units_binds() -> dict[str, object]:
    """The binds every execution of `units_sql` needs besides `ids`: the standing passes and the document
    providers of the registry (`core/importers/providers.py`)."""
    importers, providers = provider_pairs()
    return {"standing": STANDING, "doc_importers": importers, "doc_providers": providers}


_CONFIRMED_IDS = text(f"SELECT u.id FROM ({units_sql()}) AS u WHERE u.unit_ok")


def load_confirmed_ids(conn: Connection) -> set[int]:
    """The ids of every confirmed movement entry."""
    return {int(i) for i in conn.execute(_CONFIRMED_IDS, units_binds()).scalars()}
