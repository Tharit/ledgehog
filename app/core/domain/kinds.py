"""Account kinds that carry a fact about the account itself (spec §3.3)."""

from __future__ import annotations

# whether an account is an investment account is fixed at creation (I38); its balance records
# are valuations, not reconciliations
INVESTMENT_KINDS = frozenset({"depot", "asset"})
