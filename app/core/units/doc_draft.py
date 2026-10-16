"""A draft's documents (spec §5.8, §6; documents.md §6, §8): what it decides, and the split it implies. Pure.

`plan_documents` is the first thing `overlay.plan_unit` does with a draft. It reads each source transaction's
ORIGINAL entry (the one that carries the link, I31/I35) and says what the draft makes of its document
(`DocDecision`): the link as stored (``keep``), a pick, "none", or the decision dropped (``reresolve``, also
what `reresolve_all` makes of ``keep``). A pick is validated against the documents the world holds: it must
exist (`stale_reference`), be at the version the client saw (`document_changed`), be carried by no other entry
(`document_taken`) and not belong to another provider than the payee's (`document_provider_mismatch`). A
payee with no provider takes any document: documents.md §9 offers a document to a transaction "whatever its
payee", found by hand. The payee judged is the draft's own when it fixes one, else the stored one of an entry
that carries no link (a link's enrichment may have changed it); a transaction cannot be an unreachable
duplicate here, which has no entries (I3).

The split along the lines (documents.md §6) is draft state: the rows it creates are ordinary new entries of
the draft, so the rest of the plan treats them like any split. The preview issues them DETERMINISTIC negative
ids (`proposed_split_id`: original entry and line, far from those a client issues) and the client echoes them
with the `DocumentLineRef` it was shown, so an edit of a proposed row sticks to its line and a row whose
document is no longer the one its line belongs to disappears from the draft (spec §6). A proposal is made
for a transaction that is stored unsplit, has a document of more than one line with an exact total, and that
the draft neither splits itself nor declines (`DocumentDraft.decline_split`); ``split_along_lines`` is the
explicit choice, which also replaces an existing split (deleting the other stored entries) and the client's
own rows. Only the stored link is considered: a link settling has yet to make is not known to the draft.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

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


def allocation(src: StoredSource, info: DocumentInfo) -> list[tuple[int, int]] | None:
    """The split of `src` along `info`'s lines: [(line_no, amount)], the original's share first (A2's
    `split_along_lines`), or None where there is none."""
    if info.line_count > MAX_SPLIT_LINES:
        return None
    return split_along_lines(
        src.amount,
        src.currency.strip(),
        src.instructed_amount,
        src.instructed_currency.strip() if src.instructed_currency else None,
        [DocLine(n, a) for n, a, _d in info.lines],
        info.total,
        info.currency,
    )


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
        else:
            decisions[oid] = DocDecision(had, "stored", False)
    problems.extend(_refused_picks(stored, draft, world, decisions, picks))
    return decisions, drafted, problems


def _refused_picks(
    stored: StoredUnit,
    draft: UnitDraft,
    world: World,
    decisions: Mapping[int, DocDecision],
    picks: list[tuple[int, DocumentInfo]],
) -> list[Problem]:
    problems: list[Problem] = []
    payee_providers = world.docs.payee_providers if world.docs is not None else {}
    taken: dict[int, int] = {}
    for oid, info in picks:
        entry = stored.entry(oid)
        assert entry is not None
        carrier = info.carrier_entry_id
        # carried by another entry: one outside the unit, or one of it that still carries it after the draft
        if (
            carrier is not None
            and carrier != oid
            and (carrier not in decisions or decisions[carrier].link == info.id)
        ):
            problems.append(
                Problem("document_taken", oid, "document", {"document_id": info.id, "carrier": carrier})
            )
        elif info.id in taken:
            problems.append(
                Problem(
                    "document_taken", oid, "document", {"document_id": info.id, "carrier": taken[info.id]}
                )
            )
        taken.setdefault(info.id, oid)
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


def plan_documents(stored: StoredUnit, draft: UnitDraft, world: World) -> DocPlan:
    """The draft's documents decided, and its split along the lines expanded (module docstring)."""
    decisions, drafted, problems = _decide(stored, draft, world)
    infos = _infos(world)
    entries = list(draft.entries)
    removed = list(draft.removed_entry_ids)
    splits: dict[int, DocumentSplit] = {}
    first_line: dict[int, int] = {}
    for src in stored.sources.values():
        oid = stored.original_of(src.id)
        if oid in set(removed):
            continue  # the plan refuses it
        decision = decisions[oid]
        info = infos.get(decision.link) if decision.link is not None else None
        members = {e.id for e in stored.entries if e.source_transaction_id == src.id}
        mine = [e for e in entries if e.is_new and e.source_entry_id in members]
        valid = {n for n, _a, _d in info.lines[1:]} if info is not None else set()
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
        found = allocation(src, info) if info is not None else None
        dd = drafted[oid]
        generate = False
        if decision.split:
            if found is None:
                assert info is not None
                problems.append(
                    Problem("document_split_unavailable", oid, "document", {"document_id": info.id})
                )
            else:
                replaced = [e.id for e in stored.entries if e.source_transaction_id == src.id and e.id != oid]
                removed.extend(i for i in replaced if i not in removed)
                gone_ids = set(replaced)
                own_rows = {id(e) for e in mine if e.document_line is None}  # the client's own split rows
                entries = [e for e in entries if e.id not in gone_ids and id(e) not in own_rows]
                generate = not echoed
        elif found is not None and not dd.decline_split and not stored_split and not mine:
            generate = True
        if generate and found is not None:
            assert info is not None
            for line_no, amount in found[1:]:
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
                proposed=made,
                available=found is not None,
                replaces_stored_split=stored_split,
            )
            if made and found is not None:
                first_line[oid] = found[0][0]
    expanded = dataclasses.replace(draft, entries=entries, removed_entry_ids=removed)
    return DocPlan(expanded, decisions, splits, first_line, tuple(problems))
