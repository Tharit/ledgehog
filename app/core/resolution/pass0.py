"""Pass 0, own account (spec §5.9): the counterparty is one of the household's accounts.

A fact, so its keys are standing. It decides the type `transfer` and the counter-account, never
a payee or category. Closed accounts still match (the payout of a closed account is a transfer
from it); the entry's own account and a currency mismatch do not (I11).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import AccountFact, EntryInput
from app.core.resolution.accounts import own_account_match_ok
from app.core.resolution.types import Decided

PASS_NAME = "own_account"


def own_account_index(accounts: Iterable[AccountFact]) -> Mapping[str, AccountFact]:
    """Canonical `external_ref` to account. References are unique (schema), blank ones are skipped."""
    return MappingProxyType({a.external_ref: a for a in accounts if a.external_ref})


def pass0(entry: EntryInput, index: Mapping[str, AccountFact]) -> tuple[Decided, Decided] | None:
    """The (type, counter_account) decisions, or None where the pass does not apply."""
    ref = canonical_text(entry.counterparty_ref)
    account = index.get(ref) if ref else None
    if account is None or not own_account_match_ok(entry, account):
        return None
    basis = {"account_id": account.id}
    return (
        Decided("transfer", PASS_NAME, basis),
        Decided(account.id, PASS_NAME, basis),
    )
