"""Transfer matching (spec §5.7): the pure matcher. No database, no plugins, no API."""

from app.core.matching.candidates import candidates, is_candidate, real_end_to_end_id
from app.core.matching.documents import (
    DocInput,
    DocTxn,
    DocWindow,
    Matching,
    amount_in,
    automatic_links,
    charged,
    fully_charged,
    line_allocation,
    match,
    reverse_matches,
    suggestions,
)
from app.core.matching.documents import (
    candidates as document_candidates,
)
from app.core.matching.leg import Leg, leg_of
from app.core.matching.lines import MAX_PARTIAL_LINES, Allocation, Line, Party, allocate
from app.core.matching.offers import (
    MAX_WINDOW,
    Offer,
    OfferSet,
    OfferWorld,
    PoolEntry,
    Proposal,
    Summary,
    counter_leg_amount,
    offers,
)
from app.core.matching.pairing import PAIR_BASIS, Pair, pair_all
from app.core.matching.states import unmatched, waiting

__all__ = [
    "MAX_PARTIAL_LINES",
    "MAX_WINDOW",
    "PAIR_BASIS",
    "Allocation",
    "DocInput",
    "DocTxn",
    "DocWindow",
    "Leg",
    "Line",
    "Matching",
    "Offer",
    "OfferSet",
    "OfferWorld",
    "Pair",
    "Party",
    "PoolEntry",
    "Proposal",
    "Summary",
    "allocate",
    "amount_in",
    "automatic_links",
    "candidates",
    "charged",
    "document_candidates",
    "fully_charged",
    "counter_leg_amount",
    "is_candidate",
    "leg_of",
    "line_allocation",
    "match",
    "offers",
    "pair_all",
    "real_end_to_end_id",
    "reverse_matches",
    "suggestions",
    "unmatched",
    "waiting",
]
