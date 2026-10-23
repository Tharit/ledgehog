"""A draft's documents (spec §5.8, §6; documents.md §6, §8): what it decides, and the split it implies. Pure.

`plan_documents` is the first thing `overlay.plan_unit` does with a draft. It reads each source transaction's
ORIGINAL entry (the one that carries the link, I31/I35) and says what the draft makes of its document
(`DocDecision`): the link as stored (``keep``), a pick, "none", or the decision dropped (``reresolve``, also
what `reresolve_all` makes of ``keep``). A pick is validated against the documents the world holds: it must
exist (`stale_reference`), be at the version the client saw (`document_changed`) and not belong to another
provider than the payee's (`document_provider_mismatch`). A document other transactions carry may be picked:
its carriers are in the unit (`stored.load_drafted_unit`); a line two entries would hold is `document_taken`
(the plan's check). A payee with no provider takes any document: documents.md §9 offers a document to a
transaction "whatever its payee", found by hand. The payee judged is the draft's own when it fixes one, else
the stored one of an entry that carries no link (a link's rules may have changed it); a transaction cannot
be an unreachable duplicate here, which has no entries (I3). A transaction that the draft converts to a
transfer loses its document (``drop``, as the payee goes, I9); a pick on a transfer is a problem the plan
reports (`document_not_for_transfer`).

The split along the lines (documents.md §6) is draft state: the rows it creates are ordinary new entries of
the draft, so the rest of the plan treats them like any split. The preview issues them DETERMINISTIC negative
ids (`proposed_split_id`: original entry and line, far from those a client issues) and the client echoes them
with the `DocumentLineRef` it was shown, so an edit of a proposed row sticks to its line and a row whose
document is no longer the one its line belongs to disappears from the draft (spec §6).

The proposal is made per DOCUMENT: the carriers of a document in the draft (the originals whose link,
after the draft, is that document) are the parties of one line allocation (`matching.lines.allocate`,
committed line references preferred), and each carrier's split is built from the lines the allocation gives it
(`allocation.split_along_lines`). It is proposed for EVERY carrier of the document while ANY of them has a
link that is not yet the user's (a stored matcher key, or a pick in the draft; `split_along_lines` is an
explicit pick), replacing whatever split the carrier has: its stored entries are removed (consequences, with
their tags) and the client's own rows dropped, unless the carrier's stored split already is the proposal or
the client echoes rows of the proposal (the split is then the client's, nothing is regenerated). Once every
link is the user's nothing is proposed; the explicit mode remains. Where no line allocation exists every
link stands, unsplit. Only the stored link is considered: a link settling has yet to make is not known to the
draft.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from app.core.matching.lines import Line, Party, allocate
from app.core.resolution.allocation import DocLine, split_along_lines
from app.core.units.doc_world import DocumentInfo
from app.core.units.draft import (
    KEEP_DOCUMENT,
    DocumentDraft,
    DocumentLineRef,
    DraftEntry,
    DraftError,
    UnitDraft,
)
from app.core.units.plan import DocumentSplit, Problem, StoredSource, StoredUnit, World

PROPOSED_SPLIT_BASE: Final = 2**51  # below the counter-leg proposals' base (transfers.PROPOSED_TEMP_BASE)
SPLIT_STRIDE: Final = 1000
MAX_SPLIT_LINES: Final = SPLIT_STRIDE - 1  # a document with more lines than a stride holds is not split

KeyAction = Literal["stored", "user", "drop"]


def proposed_split_id(original_entry_id: int, line_no: int) -> int:
    """The temporary id of the entry the preview makes from `line_no` of the document the transaction whose
    original entry is `original_entry_id` carries: stable, and far from the small negative ids a client
    issues."""
    return -(PROPOSED_SPLIT_BASE + original_entry_id * SPLIT_STRIDE + line_no)


@dataclass(frozen=True, slots=True)
class DocDecision:
    """What the draft makes of one transaction's document (its original entry's).

    `link` is the document it carries from the draft on (None: none). `key` is what happens to the
    `document` derivation key: ``stored`` leaves it (a stored `matcher_proposal` becomes `user` on a commit),
    ``user`` writes the user's decision, ``drop`` removes it. `reopen`: the link changed, so every value
    after it is derived again (spec §5.9).
    """

    link: int | None
    key: KeyAction
    reopen: bool
    split: bool = False


@dataclass(frozen=True, slots=True)
class DocPlan:
    draft: UnitDraft  # with the split rows the documents imply, the stale ones dropped
    decisions: Mapping[int, DocDecision]  # by original entry id
    splits: Mapping[int, DocumentSplit]  # by original entry id: for a document of more than one line
    first_line: Mapping[
        int, int
    ]  # original entry id -> the line it takes, where the draft splits along lines
    problems: tuple[Problem, ...]


def _infos(world: World) -> Mapping[int, DocumentInfo]:
    return world.docs.infos if world.docs is not None else {}


def _amount_in(src: StoredSource, currency: str) -> int | None:
    """The transaction's amount in the document's currency: its own, or the instructed one (spec §3)."""
    if src.currency.strip() == currency:
        return src.amount
    if src.instructed_currency is not None and src.instructed_currency.strip() == currency:
        return src.instructed_amount
    return None


def carrier_splits(
    stored: StoredUnit, info: DocumentInfo, carriers: list[int], removed: set[int]
) -> dict[int, list[tuple[int, int]] | None]:
    """The proposed split of each carrier (original entry id) of `info`: [(line_no, amount)], the original's
    share first, or None where there is none (module docstring). Every carrier is None where the document's
    carriers admit no line allocation."""
    none: dict[int, list[tuple[int, int]] | None] = dict.fromkeys(carriers)
    if info.line_count > MAX_SPLIT_LINES:
        return none
    parties: list[Party] = []
    sources: dict[int, StoredSource] = {}
    for oid in carriers:
        original = stored.entry(oid)
        assert original is not None
        src = stored.sources[original.source_transaction_id]
        sources[oid] = src
        amount = _amount_in(src, info.currency)
        if amount is None:
            return none
        refs = (
            frozenset(
                e.document_line[1]
                for e in stored.entries
                if e.source_transaction_id == src.id
                and e.id not in removed
                and e.document_line is not None
                and e.document_line[0] == info.id
            )
            if original.document_id == info.id
            else frozenset[int]()
        )
        parties.append(Party(oid, src.booked_on, amount, refs))
    found = allocate([Line(n, a) for n, a, _d in info.lines], info.total, parties)
    if found is None:
        return none
    amounts = {n: a for n, a, _d in info.lines}
    out: dict[int, list[tuple[int, int]] | None] = {}
    for party in parties:
        src = sources[party.key]
        out[party.key] = split_along_lines(
            src.amount,
            src.currency.strip(),
            src.instructed_amount,
            src.instructed_currency.strip() if src.instructed_currency else None,
            [DocLine(n, amounts[n]) for n in found.of(party.key)],
            party.amount,
            info.total,
            info.currency,
        )
    return out


def drafted_type(entry: DraftEntry | None) -> str | None:
    """The type the draft itself gives an entry: the one it fixes, else the one a drafted value implies (a
    payee or a category a flow, a counter-account a transfer, as the overlay's walk reads them); None where
    the draft leaves the type to resolution."""
    if entry is None:
        return None
    kind = entry.type
    if kind.mode == "fixed" and kind.value is not None:
        return str(kind.value)
    if (entry.payee.mode == "fixed") or (entry.category.mode == "fixed" and entry.category.value is not None):
        return "flow"
    if entry.counter_account.mode == "fixed" and entry.counter_account.value is not None:
        return "transfer"
    return None


def _decide(
    stored: StoredUnit, draft: UnitDraft, world: World
) -> tuple[dict[int, DocDecision], dict[int, DocumentDraft], list[Problem]]:
    infos = _infos(world)
    problems: list[Problem] = []
    originals = {stored.original_of(s): s for s in stored.sources}
    for d in draft.entries:
        if d.is_new or d.document == KEEP_DOCUMENT:
            continue
        if stored.entry(d.id) is None:
            continue  # the plan refuses an entry that is not in the unit
        if d.id not in originals:
            raise DraftError(
                "document_not_original",
                "only a transaction's original entry has a document",
                entry_id=d.id,
                field="document",
            )
    drafted: dict[int, DocumentDraft] = {}
    decisions: dict[int, DocDecision] = {}
    picks: list[tuple[int, DocumentInfo]] = []
    for oid in sorted(originals):
        entry = stored.entry(oid)
        assert entry is not None
        listed = draft.entry(oid)
        dd = listed.document if listed is not None else KEEP_DOCUMENT
        drafted[oid] = dd
        mode = "reresolve" if dd.mode == "keep" and draft.reresolve_all else dd.mode
        had = entry.document_id
        if mode in ("pick", "split_along_lines"):
            did = dd.document_id
            assert did is not None
            info = infos.get(did)
            if info is None:
                problems.append(Problem("stale_reference", oid, "document_id", {"id": did}))
                decisions[oid] = DocDecision(
                    had, "user", False
                )  # a decision all the same: the problem is the one
                continue
            if info.version != dd.document_version:
                problems.append(
                    Problem(
                        "document_changed",
                        oid,
                        "document",
                        {"document_id": did, "version": info.version, "expected": dd.document_version},
                    )
                )
            decisions[oid] = DocDecision(did, "user", had != did, split=mode == "split_along_lines")
            picks.append((oid, info))
        elif mode == "none":
            decisions[oid] = DocDecision(None, "user", had is not None)
        elif mode == "reresolve":
            decisions[oid] = DocDecision(None, "drop", had is not None)
        elif had is not None and drafted_type(listed) == "transfer":
            # converting a linked transaction to a transfer drops its document as it drops the payee (I9)
            decisions[oid] = DocDecision(None, "drop", True)
        else:
            decisions[oid] = DocDecision(had, "stored", False)
    problems.extend(_refused_picks(stored, draft, world, picks))
    return decisions, drafted, problems


def _refused_picks(
    stored: StoredUnit,
    draft: UnitDraft,
    world: World,
    picks: list[tuple[int, DocumentInfo]],
) -> list[Problem]:
    problems: list[Problem] = []
    payee_providers = world.docs.payee_providers if world.docs is not None else {}
    for oid, info in picks:
        entry = stored.entry(oid)
        assert entry is not None
        listed = draft.entry(oid)
        payee: int | None = None
        if listed is not None and listed.payee.mode == "fixed" and isinstance(listed.payee.value, int):
            payee = listed.payee.value
        elif entry.document_id is None:
            payee = entry.payee_id
        provider = payee_providers.get(payee) if payee is not None else None
        if provider is not None and provider != info.provider:
            problems.append(
                Problem(
                    "document_provider_mismatch",
                    oid,
                    "document",
                    {"provider": info.provider, "payee_provider": provider},
                )
            )
    return problems


_MATCHER_PASSES: Final = ("matcher_decision", "matcher_proposal")


def _not_the_users(stored: StoredUnit, oid: int, decision: DocDecision, dd: DocumentDraft) -> bool:
    """Whether the link the original entry `oid` carries after the draft is not yet the user's: a pick in the
    draft (a pick of the document the transaction carries as the user's decision changes nothing), or a
    stored matcher key. `split_along_lines` is an explicit pick."""
    if decision.link is None:
        return False
    if dd.mode == "split_along_lines":
        return True
    entry = stored.entry(oid)
    key = entry.derivation.get("document") if entry is not None else None
    stored_pass = key.get("pass") if isinstance(key, Mapping) else None
    if dd.mode == "pick":
        return not (entry is not None and entry.document_id == decision.link and stored_pass == "user")
    return decision.key == "stored" and stored_pass in _MATCHER_PASSES


def _is_proposal(stored: StoredUnit, src: StoredSource, doc_id: int, found: list[tuple[int, int]]) -> bool:
    """The carrier's stored split already is `found`: every entry of the source references the line it takes,
    with its amount (nothing to replace, nothing to show)."""
    mine = [e for e in stored.entries if e.source_transaction_id == src.id]
    return (
        len(mine) == len(found)
        and all(e.document_line is not None and e.document_line[0] == doc_id for e in mine)
        and {(e.document_line[1], e.amount) for e in mine if e.document_line is not None} == set(found)
    )


def plan_documents(stored: StoredUnit, draft: UnitDraft, world: World) -> DocPlan:
    """The draft's documents decided, and its split along the lines expanded (module docstring)."""
    decisions, drafted, problems = _decide(stored, draft, world)
    infos = _infos(world)
    entries = list(draft.entries)
    removed = list(draft.removed_entry_ids)
    splits: dict[int, DocumentSplit] = {}
    first_line: dict[int, int] = {}
    gone_originals = set(removed)  # the plan refuses an original that is removed
    carriers: dict[int, list[int]] = defaultdict(list)  # document -> the originals that carry it
    for src in stored.sources.values():
        oid = stored.original_of(src.id)
        if oid not in gone_originals and (link := decisions[oid].link) is not None:
            carriers[link].append(oid)
    found: dict[int, list[tuple[int, int]] | None] = {}  # by original entry id
    proposing: set[int] = set()  # the documents whose carriers are proposed their split
    for doc_id, originals in carriers.items():
        info = infos.get(doc_id)
        if info is None or info.line_count < 2:
            continue
        found.update(carrier_splits(stored, info, sorted(originals), set(removed)))
        if any(_not_the_users(stored, o, decisions[o], drafted[o]) for o in originals):
            proposing.add(doc_id)
    for src in stored.sources.values():
        oid = stored.original_of(src.id)
        if oid in gone_originals:
            continue
        decision = decisions[oid]
        info = infos.get(decision.link) if decision.link is not None else None
        members = {e.id for e in stored.entries if e.source_transaction_id == src.id}
        mine = [e for e in entries if e.is_new and e.source_entry_id in members]
        valid = {n for n, _a, _d in info.lines} if info is not None else set()
        stale = [
            e
            for e in mine
            if e.document_line is not None
            and (
                info is None or e.document_line.document_id != info.id or e.document_line.line_no not in valid
            )
        ]
        gone = {id(e) for e in stale}
        entries = [e for e in entries if id(e) not in gone]
        mine = [e for e in mine if id(e) not in gone]
        echoed = [e for e in mine if e.document_line is not None]
        stored_split = len([e for e in stored.entries if e.source_transaction_id == src.id]) > 1
        split = found.get(oid)
        generate = False
        replaced: list[int] = []
        if info is not None and split is None and drafted[oid].mode == "split_along_lines":
            problems.append(Problem("document_split_unavailable", oid, "document", {"document_id": info.id}))
        if info is not None and info.id in proposing and split is not None:
            if not _is_proposal(stored, src, info.id, split):
                replaced = [e.id for e in stored.entries if e.source_transaction_id == src.id and e.id != oid]
                removed.extend(i for i in replaced if i not in removed)
                if not echoed:  # the client's own rows go too; echoed rows are the client's split
                    own_rows = {id(e) for e in mine}
                    entries = [e for e in entries if e.id not in set(replaced) and id(e) not in own_rows]
                    generate = True
                else:
                    entries = [e for e in entries if e.id not in set(replaced)]
        if generate and split is not None:
            assert info is not None
            for line_no, amount in split[1:]:
                entries.append(
                    DraftEntry(
                        proposed_split_id(oid, line_no),
                        amount=amount,
                        source_entry_id=oid,
                        document_line=DocumentLineRef(info.id, line_no),
                    )
                )
        if info is not None and info.line_count > 1:
            made = generate or bool(echoed)
            splits[oid] = DocumentSplit(
                document_id=info.id,
                proposed=made and (len(split or ()) > 1 or bool(replaced) or bool(echoed)),
                available=split is not None,
                replaces_stored_split=stored_split,
            )
            if made and split is not None:
                first_line[oid] = split[0][0]
    expanded = dataclasses.replace(draft, entries=entries, removed_entry_ids=removed)
    return DocPlan(expanded, decisions, splits, first_line, tuple(problems))
