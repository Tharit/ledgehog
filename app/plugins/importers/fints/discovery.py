"""The bank's account list (the UPD) to discovered accounts (fints.md §3).

No HKSPA: the UPD carries the IBAN.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core.plugins.fetch import DiscoveredAccount
from app.plugins.importers.fints.bank import UpdAccount

_CAPABILITIES = frozenset({"transactions", "balance"})


def external_ref_of(account: UpdAccount) -> str | None:
    """The IBAN where there is one (upper case, no spaces), else the account number followed by `/` and
    the sub-account number where there is one. None for a placeholder row (no account number)."""
    if account.account_number is None:
        return None
    if account.iban:
        return re.sub(r"\s+", "", account.iban).upper()
    return f"{account.account_number}/{account.subaccount}" if account.subaccount else account.account_number


def find(accounts: Sequence[UpdAccount], external_ref: str) -> UpdAccount | None:
    return next((a for a in accounts if external_ref_of(a) == external_ref), None)


def kind_hint(account_type: int | None) -> str | None:
    """By the bank's account type (the UPD's Kontoart): 1 to 9 checking, 10 to 19 savings, 30 to 39
    depot, 50 to 59 card, else none (a hint only prefills)."""
    if account_type is None:
        return None
    if 1 <= account_type <= 9:
        return "checking"
    if 10 <= account_type <= 19:
        return "savings"
    if 30 <= account_type <= 39:
        return "depot"
    if 50 <= account_type <= 59:
        return "card"
    return None


def discover(accounts: Sequence[UpdAccount]) -> list[DiscoveredAccount]:
    found: dict[str, DiscoveredAccount] = {}
    for a in accounts:
        ref = external_ref_of(a)
        if ref is None or ref in found:
            continue
        found[ref] = DiscoveredAccount(
            external_ref=ref,
            name=a.product_name or a.account_number or ref,
            currency=a.currency,
            kind_hint=kind_hint(a.account_type),
            # the balance is part of the statements, so it has no capability of its own
            capabilities=_CAPABILITIES if a.statements else frozenset(),
        )
    return list(found.values())
