"""Which entries are confirmed (spec §6, I20, I22, I31), from columns and keys, never from stored flags.

A UNIT is the entries of one source transaction plus, when one of them is a transfer leg that is
paired, the entries of the partner's source transaction, plus the entries of every other transaction
carrying the same document (I21, I35). A source holds at most one transfer entry (I31,
`ux_le_one_transfer_per_source`), a pair has exactly two legs (`ux_le_counterpart`, `trg_transfer_pair`)
and a transaction carrying a document has no transfer entry (I35), so a unit is a pair or the carriers of
one document and never a chain: one step finds it. The unit key of an entry is the lowest source id among
its own source, its partner's and the carriers' of its document, taken over every entry of its source (so
the siblings of a transfer leg, or of a carrier's original, share its key).

A unit is confirmed when every entry of it is complete and carries only standing keys:

* a type; for a flow a category (spec §3.4); for a transfer its pair (`counterpart_entry_id`, I22,
  so an unpaired transfer is never confirmed);
* no derivation key whose pass is not standing (`history`, `llm`, `matcher_proposal`, or a key
  without a pass);
* no document open (spec §6, documents.md §1, §7; a transaction typed as a transfer is not considered, a
  document explains a flow, spec §5.8): its original entry does not await a document (an active
  document source has not covered `booked_on` plus the document window) and has no suggestions (documents
  that match it, with no automatic link possible). The test applies only to a transaction's original entry
  whose payee has a `document_provider` and which has no `document` key, so it is GATED to that small subset
  and costs every other entry nothing. A candidate that settling is about to link (the only one, shared with
  no other transaction) keeps the unit unconfirmed too, so that a unit whose payee rules are all standing is
  not confirmed in the same settle that would link its document (`doc_candidate`, used here only).
  `doc_awaited` and `doc_suggested` are exposed per entry (the flags
  `waiting` and `document_suggested` read them). Beside them `doc_rest`, of an original entry whose document
  key is a matcher's: it waits for the rest of its document's order (documents.md §7), which sets the flag
  `waiting` and holds no confirmation (see `_REST`). Which importer provides which provider is the registry
  of `core/importers/providers.py`; the candidates are found in Python, a line allocation not being SQL
  (`core/resolution/doc_load.py`); both are bound as `units_binds(conn)`.

This is computed here rather than read from `review_flags` so that it is right in the middle of a
settle, where the flags are not yet rewritten and a new entry's empty default would otherwise read as
clean. Derived entries (balance records) have no source transaction and are in no unit.
`app/core/units/state.py` is the same judgement in pure Python, pinned to this SQL by a test.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.core.importers.providers import delivery_pairs
from app.core.plugins.classifier import STANDING_PASSES
from app.core.resolution.doc_load import candidacy
from app.core.resolution.entry_state import COMPLETE
from app.core.resolution.entry_state import STANDING as STANDING_SQL

STANDING = sorted(STANDING_PASSES)

# The document window (spec §5.8), read from the connection like `ledger.matching_window_days`
# (`core/settle/window.py: document_window`): a document is dated within [booked_on - back, booked_on +
# ahead], and waiting runs to booked_on + ahead. Evaluated only inside the gated subqueries below.
_DOC_BACK = "current_setting('ledger.document_window_back_days')::int"
_DOC_AHEAD = "current_setting('ledger.document_window_ahead_days')::int"

# The original entry of a source transaction (I31), whose payee has a provider, with no `document` key:
# the only entry the document test looks at (documents.md §1).
_GATE = """pp.document_provider IS NOT NULL
                                AND NOT EXISTS (SELECT 1 FROM ledger_entry AS tr
                                                 WHERE tr.source_transaction_id = le.source_transaction_id
                                                   AND tr.type = 'transfer')
                                AND NOT jsonb_exists(le.derivation, 'document')
                                AND NOT EXISTS (SELECT 1 FROM ledger_entry AS lo
                                                 WHERE lo.source_transaction_id = le.source_transaction_id
                                                   AND lo.id < le.id)"""

# awaited (documents.md §7): some instance that is not disabled, delivers the provider (the registry's
# per-instance answer, compared lower-cased), has a start date not after the booking date (an instance
# without one has no lower bound) and whose document coverage has not reached booked_on plus the window's
# ahead; never run = no coverage = awaiting.
_AWAITED = (
    """EXISTS (SELECT 1
                                  FROM unnest(CAST(:doc_instances AS bigint[]),
                                              CAST(:doc_providers AS text[])) AS r(instance_id, provider)
                                  JOIN importer_instance AS ii ON ii.id = r.instance_id
                                  LEFT JOIN v_document_coverage AS dc ON dc.importer_instance_id = ii.id
                                 WHERE r.provider = lower(pp.document_provider)
                                   AND NOT ii.disabled
                                   AND (ii.settings ->> 'start_date' IS NULL
                                        OR CAST(ii.settings ->> 'start_date' AS date) <= le.booked_on)
                                   AND (dc.covered_through IS NULL
                                        OR dc.covered_through < le.booked_on + """
    + _DOC_AHEAD
    + """))"""
)


def charged_sql(document: str) -> str:
    """The SQL of what the carriers of the document aliased `document` charged: the sum of the amounts of the
    sources of every entry linking it, each in the document's currency (its own, else its instructed one; a
    source with neither counts nothing): `core.matching.documents.charged`."""
    return f"""(SELECT COALESCE(sum(CASE WHEN rs.currency = {document}.currency THEN rs.amount
                                       WHEN rs.instructed_currency = {document}.currency
                                       THEN rs.instructed_amount END), 0)
                  FROM ledger_entry AS rc
                  JOIN source_transaction AS rs ON rs.id = rc.source_transaction_id
                 WHERE rc.document_id = {document}.id)"""


# The wait for the rest of an order (documents.md §7), of an original entry (only it carries a link, I31)
# whose `document` key is a matcher's: the amounts of the document's carriers (every entry linking it; the
# transaction's own amount in the document's currency, else its instructed one, a carrier with neither
# counting nothing) fall short of its total in magnitude (`core.matching.documents.charged`,
# `fully_charged`) AND some synced account has not reached the document's date plus `back`
# (`synced_through` NULL: never fetched). The twin is `core/units/documents.py: rest_awaited`. It holds no
# confirmation (the key does): the flag `waiting` and the queue's section read it, never `unit_ok`.
_REST_GATE = """le.document_id IS NOT NULL
                                AND (le.derivation -> 'document' ->> 'pass')
                                    IN ('matcher_decision', 'matcher_proposal')"""
_REST = (
    """EXISTS (SELECT 1
                                  FROM external_document AS rd
                                 WHERE rd.id = le.document_id
                                   AND abs("""
    + charged_sql("rd")
    + """) < abs(rd.total)
                                   AND EXISTS (SELECT 1
                                                 FROM v_account_synced AS sy
                                                 JOIN v_account_coverage AS cv
                                                   ON cv.account_id = sy.account_id
                                                WHERE sy.synced
                                                  AND (cv.synced_through IS NULL
                                                       OR cv.synced_through < rd.occurred_on + """
    + _DOC_BACK
    + """)))"""
)

# The candidates (documents.md §2, §3): found in Python, since a line allocation cannot be done in SQL
# (`core/resolution/doc_load.py: candidacy`, bound as `units_binds(conn)`): one row per gated original entry
# that has a candidate, with `suggested` (documents.md §4: no automatic link is possible: several
# candidates, one shared with another transaction, a confirmed carrier, or no line allocation keeping the
# committed references). From it `doc_candidate` (there is one, so settling may link it in step 2: the unit
# is not confirmed yet, or a unit of standing values would be, and get "none", before step 2 could link the
# document) and `doc_suggested`.
_CANDIDATES = "unnest(CAST(:cand_entries AS bigint[]), CAST(:cand_suggested AS boolean[]))"

# One row per movement entry: its id, source, `unit_key` (the unit), `unit_ok` (the unit is
# confirmed), `unit_has_nonstanding` (some entry of the unit carries a key that awaits a human: what
# `unconfirmed` means), `first_id` (the lowest entry id of its SOURCE transaction: the original entry
# of a split, I31) and `doc_awaited`, `doc_suggested` (the entry's transaction awaits a document, or has
# suggestions: false for every entry the gate excludes) and `doc_rest` (it waits for the rest of its
# document's order: of a linked original entry, which the gate excludes). `{scope}` narrows to the units of
# given entries, or to all.
_UNITS = """
    SELECT m.id, m.src, m.unit_key,
           bool_and(m.complete AND m.standing AND NOT (m.doc_awaited OR m.doc_candidate))
               OVER (PARTITION BY m.unit_key) AS unit_ok,
           bool_or(NOT m.standing) OVER (PARTITION BY m.unit_key) AS unit_has_nonstanding,
           min(m.id) OVER (PARTITION BY m.src) AS first_id,
           m.doc_awaited, m.doc_suggested, m.doc_rest
      FROM (
            SELECT k.id, k.src, k.complete, k.standing, k.doc_awaited, k.doc_suggested, k.doc_candidate,
                   k.doc_rest,
                   min(k.direct_key) OVER (PARTITION BY k.src) AS unit_key
              FROM (
                    SELECT le.id, le.source_transaction_id AS src,
                           LEAST(le.source_transaction_id,
                                 COALESCE(p.source_transaction_id, le.source_transaction_id),
                                 COALESCE(CASE WHEN le.document_id IS NOT NULL
                                               THEN min(le.source_transaction_id)
                                                    OVER (PARTITION BY le.document_id) END,
                                          le.source_transaction_id)) AS direct_key,
                           {complete} AS complete,
                           {standing_sql} AS standing,
                           CASE WHEN {gate} THEN {awaited} ELSE false END AS doc_awaited,
                           COALESCE({gate} AND cd.entry_id IS NOT NULL, false) AS doc_candidate,
                           COALESCE({gate} AND cd.suggested, false) AS doc_suggested,
                           CASE WHEN {rest_gate} THEN {rest} ELSE false END AS doc_rest
                      FROM ledger_entry AS le
                      LEFT JOIN ledger_entry AS p ON p.id = le.counterpart_entry_id
                      LEFT JOIN payee AS pp ON pp.id = le.payee_id
                      LEFT JOIN {candidates} AS cd(entry_id, suggested) ON cd.entry_id = le.id
                     WHERE le.source_transaction_id IS NOT NULL{scope}
                   ) AS k
           ) AS m
"""

_ALL = ""
# the sources of the given entries, of the partners of the transfer legs in those sources, and of the other
# carriers of the documents those sources carry (the window of `direct_key` sees only the rows in scope)
_OF_ENTRIES = """
       AND le.source_transaction_id IN (
            SELECT x.source_transaction_id FROM ledger_entry AS x WHERE x.id = ANY(:ids)
            UNION
            SELECT q.source_transaction_id
              FROM ledger_entry AS x
              JOIN ledger_entry AS t ON t.source_transaction_id = x.source_transaction_id
              JOIN ledger_entry AS q ON q.id = t.counterpart_entry_id
             WHERE x.id = ANY(:ids)
            UNION
            SELECT c.source_transaction_id
              FROM ledger_entry AS x
              JOIN ledger_entry AS o ON o.source_transaction_id = x.source_transaction_id
              JOIN ledger_entry AS c ON c.document_id = o.document_id
             WHERE x.id = ANY(:ids))
"""


def units_sql(*, of_entries: bool = False) -> str:
    """The `units` CTE body (see above); bind `units_binds(conn)` (and `ids` when `of_entries`)."""
    return _UNITS.format(
        scope=_OF_ENTRIES if of_entries else _ALL,
        gate=_GATE,
        awaited=_AWAITED,
        rest_gate=_REST_GATE,
        rest=_REST,
        candidates=_CANDIDATES,
        complete=COMPLETE,
        standing_sql=STANDING_SQL,
    )


def units_binds(conn: Connection) -> dict[str, object]:
    """The binds every execution of `units_sql` needs besides `ids`: the standing passes, which instances
    deliver which providers (`core/importers/providers.py`) and the document candidacy of the ledger's
    gated transactions (`core/resolution/doc_load.py`), read now."""
    instances, providers = delivery_pairs(conn)
    found = candidacy(conn)
    return {
        "standing": STANDING,
        "doc_instances": instances,
        "doc_providers": providers,
        "cand_entries": sorted(found),
        "cand_suggested": [found[i] for i in sorted(found)],
    }


_CONFIRMED_IDS = text(f"SELECT u.id FROM ({units_sql()}) AS u WHERE u.unit_ok")


def load_confirmed_ids(conn: Connection) -> set[int]:
    """The ids of every confirmed movement entry."""
    return {int(i) for i in conn.execute(_CONFIRMED_IDS, units_binds(conn)).scalars()}
