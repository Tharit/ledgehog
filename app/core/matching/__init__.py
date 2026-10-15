"""Transfer matching (spec §5.7): the pure matcher. No database, no plugins, no API."""

from app.core.matching.candidates import candidates, is_candidate, real_end_to_end_id
from app.core.matching.leg import Leg, leg_of
from app.core.matching.offers import (
    MAX_WINDOW,
    Offer,
    OfferSet,
    OfferWorld,
    PoolEntry,
    Proposal,
    Summary,
    offers,
)
from app.core.matching.pairing import PAIR_BASIS, Pair, pair_all
from app.core.matching.states import unmatched, waiting

__all__ = [
    "MAX_WINDOW",
    "PAIR_BASIS",
    "Leg",
    "Offer",
    "OfferSet",
    "OfferWorld",
    "Pair",
    "PoolEntry",
    "Proposal",
    "Summary",
    "candidates",
    "is_candidate",
    "leg_of",
    "offers",
    "pair_all",
    "real_end_to_end_id",
    "unmatched",
    "waiting",
]
