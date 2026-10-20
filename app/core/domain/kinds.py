"""Account kinds that carry a fact about the account itself (spec §3.3)."""

from __future__ import annotations

# an account's kind is fixed at creation, and with it whether it is an investment account (I38);
# an investment account's balance records are valuations, not reconciliations
INVESTMENT_KINDS = frozenset({"depot", "asset"})
