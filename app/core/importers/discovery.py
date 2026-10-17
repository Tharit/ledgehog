"""Matching a discovered account list to the household's accounts (spec §5.4, architecture §4.1).

A discovery lists what a credential can reach; the UI offers create-or-link for what is not yet
known. The match is computed when the result is read, never stored with the task, so it is current:
first by this instance's own links (`account_source.external_ref`), then by `account.external_ref`
under the canonicalisation accounts are stored with (spec §5.2). A match to a closed account is
reported as closed: closed accounts are not offered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.core.ingest.identity import canonical_text
from app.core.plugins.fetch import DiscoveredAccount


@dataclass(frozen=True, slots=True)
class AccountMatch:
    id: int
    closed: bool


@dataclass(frozen=True, slots=True)
class DiscoveryEntry:
    """One discovered account with what it already is here."""

    account: DiscoveredAccount
    linked_account_id: int | None  # already linked to this instance under this reference
    matches_account: AccountMatch | None  # not linked, but an account holds this external reference


def match_discovered(
    conn: Connection, instance_id: int, accounts: Sequence[DiscoveredAccount]
) -> list[DiscoveryEntry]:
    """Each discovered account, in order, with the account it is linked to by this instance or, failing
    that, the one carrying its reference."""
    linked = {
        str(r.external_ref): int(r.account_id)
        for r in conn.execute(
            text("SELECT external_ref, account_id FROM account_source WHERE importer_instance_id = :i"),
            {"i": instance_id},
        )
    }
    canonical = {a.external_ref: canonical_text(a.external_ref) for a in accounts}
    by_ref = {
        str(r.external_ref): AccountMatch(int(r.id), r.closed_on is not None)
        for r in conn.execute(
            text("SELECT id, external_ref, closed_on FROM account WHERE external_ref = ANY(:refs)"),
            {"refs": sorted({c for c in canonical.values() if c})},
        )
    }
    out: list[DiscoveryEntry] = []
    for account in accounts:
        if (account_id := linked.get(account.external_ref)) is not None:
            out.append(DiscoveryEntry(account, account_id, None))
        else:
            out.append(DiscoveryEntry(account, None, by_ref.get(canonical[account.external_ref])))
    return out
