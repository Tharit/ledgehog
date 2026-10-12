"""Invented data for the development seed (scripts/dev_seed.py). Everything here is SYNTHETIC:
merchants, names, IBANs (DE00 ...), amounts. Nothing is derived from a real export.

Pure and deterministic: `build_plan(seed=, end=, months=)` draws every transaction from one
`random.Random` per account, and renders the CSV files in the three shipped preset formats
(giro with preamble, card with footer balance, card with inverted signs) so they can be pushed
through the real `upload()`. No database, no clock.
"""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

OWNER = "Erika Beispiel"
IBAN = {"giro": "DE00 0000 0000 0000 0000 00", "savings": "DE00 0000 0000 0000 0000 01"}
SUFFIX = " [seed]"  # marks the accounts (and instances) the seed created

ACCOUNTS: tuple[tuple[str, str, str, str | None], ...] = (
    # key, name, kind, external_ref
    ("giro", "Girokonto", "checking", IBAN["giro"]),
    ("savings", "Tagesgeld", "savings", IBAN["savings"]),
    ("visa", "Visa Karte", "card", None),
    ("amex", "Amex Karte", "card", None),
    ("paypal", "PayPal", "paypal", None),
    ("cash", "Bargeld", "cash", None),
)

# -- the prototype-only classification vocabulary (design.md §3, §6) ------------------------------


@dataclass(frozen=True)
class Category:
    name: str
    kind: str  # income | expense
    parent: str | None = None
    icon: str | None = None  # NULL takes the parent's
    color: str | None = None


CATEGORIES: tuple[Category, ...] = (
    Category("Housing", "expense", None, "house", "brown"),
    Category("Rent", "expense", "Housing", "building-2"),
    Category("Utilities", "expense", "Housing", "zap"),
    Category("Food", "expense", None, "utensils", "olive"),
    Category("Groceries", "expense", "Food", "shopping-basket"),
    Category("Restaurants", "expense", "Food", "pizza"),
    Category("Transport", "expense", None, "train-front", "slate"),
    Category("Leisure", "expense", None, "ticket", "plum"),
    Category("Travel", "expense", "Leisure", "plane", "teal"),
    Category("Subscriptions", "expense", "Leisure", "repeat", "lavender"),
    Category("Health", "expense", None, "heart-pulse", "sage"),
    Category("Shopping", "expense", None, "shirt", "ochre"),
    Category("Insurance", "expense", None, "shield", "stone"),
    Category("Income", "income", None, "wallet", "forest"),
    Category("Salary", "income", "Income", "banknote"),
)


@dataclass(frozen=True)
class Payee:
    name: str
    icon: str | None = None
    color: str | None = None


PAYEES: tuple[Payee, ...] = (
    Payee("Frischemarkt Lindenhof", "shopping-basket", "sage"),
    Payee("Naturkost Ahorn", "shopping-basket", "olive"),
    Payee("Discounter Preisbär", "shopping-cart"),
    Payee("Bäckerei Sonnenkorn", "coffee", "ochre"),
    Payee("Trattoria Bella Vista", "utensils", "brown"),
    Payee("Nordbahn AG", "train-front", "slate"),
    Payee("Tankstelle Westring", "fuel", "stone"),
    Payee("Versandhaus Kometa", "package"),
    Payee("Möbelhaus Nordlicht", "house", "brown"),
    Payee("Apotheke Am Brunnen", "pill", "sage"),
    Payee("Stadtwerke Beispielstadt", "zap", "ochre"),
    Payee("NetzWerk Telekom", "wifi", "teal"),
    Payee("Funkwerk Mobil", "smartphone"),
    Payee("StreamBox", "film", "plum"),
    Payee("Tonwelle", "music", "lavender"),
    Payee("FitPunkt Studio", "dumbbell", "forest"),
    Payee("Hausverwaltung Muster GmbH", "building-2"),
    Payee("Beispiel Maschinenbau AG", "building-2", "slate"),
    Payee("Atlantik Air", "plane", "teal"),
    Payee("Schutzbrief Versicherung", "shield"),
    Payee("Buchhandlung Seitenweise", "book-open", "plum"),
)


@dataclass(frozen=True)
class Tag:
    name: str
    color: str | None = None


TAGS: tuple[Tag, ...] = (
    Tag("Lisbon trip", "teal"),
    Tag("Tax deductible", "slate"),
    Tag("Reimbursable", "ochre"),
    Tag("Birthday gift", "plum"),
    Tag("Home office"),
)

# (lowercase keyword in "name purpose", category, payee). First match wins.
_RULES: tuple[tuple[str, str, str | None], ...] = (
    ("hausverwaltung", "Rent", "Hausverwaltung Muster GmbH"),
    ("stadtwerke", "Utilities", "Stadtwerke Beispielstadt"),
    ("netzwerk", "Utilities", "NetzWerk Telekom"),
    ("funkwerk", "Utilities", "Funkwerk Mobil"),
    ("möbelhaus", "Housing", "Möbelhaus Nordlicht"),
    ("frischemarkt", "Groceries", "Frischemarkt Lindenhof"),
    ("naturkost", "Groceries", "Naturkost Ahorn"),
    ("preisbär", "Groceries", "Discounter Preisbär"),
    ("sonnenkorn", "Groceries", "Bäckerei Sonnenkorn"),
    ("bella vista", "Restaurants", "Trattoria Bella Vista"),
    ("café kastanie", "Restaurants", None),
    ("cervejaria alfama", "Restaurants", None),
    ("pastelaria belém", "Restaurants", None),
    ("nordbahn", "Transport", "Nordbahn AG"),
    ("tankstelle", "Transport", "Tankstelle Westring"),
    ("metro lisboa", "Transport", None),
    ("taxi lisboa", "Transport", None),
    ("kometa", "Shopping", "Versandhaus Kometa"),
    ("modehaus", "Shopping", None),
    ("bürobedarf", "Shopping", None),
    ("spielwaren", "Shopping", None),
    ("apotheke", "Health", "Apotheke Am Brunnen"),
    ("zahnarzt", "Health", None),
    ("kino capitol", "Leisure", None),
    ("seitenweise", "Leisure", "Buchhandlung Seitenweise"),
    ("fitpunkt", "Leisure", "FitPunkt Studio"),
    ("fado", "Leisure", None),
    ("streambox", "Subscriptions", "StreamBox"),
    ("tonwelle", "Subscriptions", "Tonwelle"),
    ("cloudnotes", "Subscriptions", None),
    ("schutzbrief", "Insurance", "Schutzbrief Versicherung"),
    ("beispiel maschinenbau", "Salary", "Beispiel Maschinenbau AG"),
    ("atlantik air", "Travel", "Atlantik Air"),
    ("hotel bairro alto", "Travel", None),
    ("steuerverwaltung", "Income", None),
)


# keyword -> tag names
_TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lisboa", ("Lisbon trip",)),
    ("alfama", ("Lisbon trip",)),
    ("belém", ("Lisbon trip",)),
    ("bairro alto", ("Lisbon trip",)),
    ("atlantik air", ("Lisbon trip",)),
    ("fado", ("Lisbon trip",)),
    ("steuerberatung", ("Tax deductible",)),
    ("bürobedarf", ("Tax deductible", "Home office")),
    ("nordbahn", ("Reimbursable",)),
    ("spielwaren", ("Birthday gift",)),
)


@dataclass(frozen=True)
class Classification:
    category: str
    payee: str | None


def classify(name: str | None, purpose: str | None) -> Classification | None:
    haystack = f"{name or ''} {purpose or ''}".lower()
    for keyword, category, payee in _RULES:
        if keyword in haystack:
            return Classification(category, payee)
    return None


def tags_for(name: str | None, purpose: str | None) -> tuple[str, ...]:
    haystack = f"{name or ''} {purpose or ''}".lower()
    found: list[str] = []
    for keyword, tags in _TAG_RULES:
        if keyword in haystack:
            found.extend(t for t in tags if t not in found)
    return tuple(found)


# -- merchants ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Merchant:
    name: str
    texts: tuple[str, ...]
    low: int  # minor units of an expense
    high: int
    weight: int
    channels: tuple[str, ...]


_ALL = ("giro", "visa", "amex", "paypal")
_CARDS = ("visa", "amex", "paypal")
_MERCHANTS: tuple[Merchant, ...] = (
    Merchant(
        "Frischemarkt Lindenhof", ("Kartenzahlung Frischemarkt", "Einkauf Lindenhof"), 700, 8900, 9, _ALL
    ),
    Merchant("Naturkost Ahorn", ("Naturkost Einkauf",), 600, 5200, 2, _ALL),
    Merchant(
        "Discounter Preisbär", ("PREISBAER Filiale 12", "Preisbär Einkauf"), 500, 7400, 5, ("giro", "visa")
    ),
    Merchant("Bäckerei Sonnenkorn", ("Kartenzahlung Backwaren",), 180, 1700, 4, ("giro", "visa", "amex")),
    Merchant("Café Kastanie", ("Kartenzahlung Cafe",), 280, 2100, 5, _CARDS),
    Merchant("Trattoria Bella Vista", ("Kartenzahlung Bella Vista",), 1800, 8800, 4, _CARDS),
    Merchant("Imbiss Zum Anker", ("Imbiss Zum Anker",), 450, 1600, 3, _CARDS),
    Merchant("Sushi Haus Kirsche", ("Sushi Haus Kirsche Tisch 4",), 2200, 6400, 2, _CARDS),
    Merchant(
        "Nordbahn AG",
        ("Fahrkarte Nordbahn", "Nordbahn Ticket Online"),
        1400,
        11900,
        3,
        ("giro", "visa", "paypal"),
    ),
    Merchant(
        "Tankstelle Westring",
        ("TANKSTELLE WESTRING", "Tanken Westring"),
        3200,
        8800,
        4,
        ("giro", "visa", "amex"),
    ),
    Merchant("Parkhaus Mitte", ("Parkgebühr Mitte",), 250, 1800, 2, ("giro", "amex")),
    Merchant(
        "Versandhaus Kometa",
        ("Kometa Bestellung", "KOMETA Marktplatz"),
        600,
        14900,
        6,
        ("giro", "paypal", "amex", "visa"),
    ),
    Merchant("Möbelhaus Nordlicht", ("Nordlicht Einrichtung",), 1500, 38000, 1, ("giro", "visa")),
    Merchant("Modehaus Fink", ("Modehaus Fink Kasse 2",), 1900, 16500, 2, ("visa", "amex", "paypal")),
    Merchant("Bürobedarf Schreiber", ("Bürobedarf Rechnung",), 400, 6200, 1, ("giro", "paypal")),
    Merchant("Spielwaren Kunterbunt", ("Spielwaren Kunterbunt",), 1200, 4800, 1, ("visa", "amex")),
    Merchant(
        "Apotheke Am Brunnen",
        ("APOTHEKE AM BRUNNEN", "Apotheke Kartenzahlung"),
        350,
        4900,
        3,
        ("giro", "visa", "amex"),
    ),
    Merchant("Zahnarzt Dr. Beispiel", ("Zahnarzt Rechnung",), 2500, 19000, 1, ("giro",)),
    Merchant("Kino Capitol", ("Kino Capitol Tickets",), 1100, 3400, 2, _CARDS),
    Merchant("Buchhandlung Seitenweise", ("Seitenweise Buchkauf",), 900, 4200, 2, _CARDS),
    Merchant("Max Mustermann", ("Privat Rückzahlung", "Essen geteilt"), 1000, 6000, 2, ("giro", "paypal")),
)
_SHOP_TAIL = ("giro", "paypal")
_RECURRING: tuple[tuple[str, str, str, int, int, str], ...] = (
    # name, booking text, purpose, amount (negative = expense), day of month, channel
    ("Hausverwaltung Muster GmbH", "Dauerauftrag", "Miete Wohnung 3.OG", -95000, 1, "giro"),
    ("Stadtwerke Beispielstadt", "Lastschrift", "Abschlag Strom und Gas", -8500, 4, "giro"),
    ("NetzWerk Telekom", "Lastschrift", "Internet Anschluss", -3999, 9, "giro"),
    ("Funkwerk Mobil", "Lastschrift", "Mobilfunk Vertrag", -2499, 15, "giro"),
    ("Schutzbrief Versicherung", "Lastschrift", "Haftpflicht Beitrag", -4500, 20, "giro"),
    ("FitPunkt Studio", "Lastschrift", "Mitgliedsbeitrag", -2990, 11, "giro"),
    ("Beispiel Maschinenbau AG", "Gutschrift", "Gehalt", 285000, 27, "giro"),
    ("StreamBox", "StreamBox Abo", "STREAMBOX.EXAMPLE", -1299, 12, "visa"),
    ("Tonwelle", "Tonwelle Abo", "TONWELLE MUSIC", -1099, 7, "amex"),
)
_FOREIGN: tuple[tuple[str, str, str, int, int, int], ...] = (
    # name, purpose, ccy, low, high (foreign minor), rate x10000 (foreign per EUR)
    ("CloudNotes Inc", "CLOUDNOTES.EXAMPLE SUBSCRIPTION", "USD", 999, 999, 10850),
    ("PixelForge Studio", "PIXELFORGE ASSETS", "USD", 1500, 6900, 10850),
    ("Thames Books Ltd", "THAMES BOOKS LONDON", "GBP", 1200, 4800, 8600),
)
_TRIP: tuple[tuple[str, str, int, int, str, int], ...] = (
    # name, purpose, low, high, channel, day offset (-1 = random within the week)
    ("Atlantik Air", "Flug Lisboa Hin und Zurueck", 33000, 33000, "giro", 0),
    ("Hotel Bairro Alto", "HOTEL BAIRRO ALTO LISBOA", 41000, 41000, "visa", 1),
    ("Cervejaria Alfama", "CERVEJARIA ALFAMA LISBOA", 2400, 6800, "visa", -1),
    ("Cervejaria Alfama", "CERVEJARIA ALFAMA LISBOA", 2400, 6800, "visa", -1),
    ("Pastelaria Belém", "PASTELARIA BELEM LISBOA", 300, 1400, "amex", -1),
    ("Pastelaria Belém", "PASTELARIA BELEM LISBOA", 300, 1400, "amex", -1),
    ("Metro Lisboa", "METRO LISBOA VIVA VIAGEM", 650, 2000, "amex", -1),
    ("Taxi Lisboa", "TAXI LISBOA", 900, 2800, "visa", -1),
    ("Fado Abend Alfama", "FADO ABEND TICKETS", 3500, 5500, "paypal", -1),
)
_OPENING = {"giro": 320_000, "savings": 500_000, "visa": -18_000}
_PENDING_NAMES = ("Frischemarkt Lindenhof", "Café Kastanie", "Parkhaus Mitte")


# -- the plan -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Txn:
    booked_on: date
    name: str
    purpose: str
    amount: int  # minor units, signed as the account sees it (expense negative)
    booking_text: str = "Kartenzahlung"
    ref: str = ""
    foreign: tuple[str, int, int] | None = None  # (currency, signed minor units, rate x10000)


@dataclass(frozen=True)
class SeedFile:
    """One generated upload. `balance_before_file` is what the account held before its first row."""

    label: str
    account: str
    preset: str
    data: bytes
    importable_rows: int
    balance: int | None
    balance_on: date | None
    balance_before_file: int | None
    first: date
    last: date


@dataclass
class SeedPlan:
    seed: int
    end: date
    start: date
    txns: dict[str, list[Txn]]
    trip: tuple[date, date]
    cash_records: tuple[tuple[date, int], ...]
    _files: list[SeedFile] = field(default_factory=list, repr=False)

    def files(self) -> list[SeedFile]:
        if not self._files:
            self._files = _render_all(self)
        return list(self._files)


def _month_starts(end: date, months: int) -> list[date]:
    y, m = end.year, end.month - (months - 1)
    while m < 1:
        y, m = y - 1, m + 12
    out = []
    for _ in range(months):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _iban(index: int) -> str:
    return f"DE00 {1000 + index:04d} {index:04d} 0000 0000 00"


def giro_counterparty_iban(name: str) -> str:
    """The (invented) IBAN the giro rows of a merchant carry, so that a rule can name it."""
    return _iban(40 + len(name))


@dataclass(frozen=True)
class SeedRule:
    """A named rule to click around in (spec §5.9). `target` is an account key (`sets` counter_account),
    a payee name or a category name; `condition_payee` a payee name (category rules only)."""

    name: str
    sets: str  # counter_account | payee | category
    target: str
    counterparty_ref: str | None = None
    name_prefix: str | None = None
    purpose_regex: str | None = None
    condition_payee: str | None = None
    priority: int = 100


RULES: tuple[SeedRule, ...] = (
    SeedRule("Cash withdrawals", "counter_account", "cash", name_prefix="Geldautomat"),
    SeedRule("Hausverwaltung", "payee", "Hausverwaltung Muster GmbH", name_prefix="Hausverwaltung"),
    SeedRule(
        "Rent by IBAN",
        "category",
        "Rent",
        counterparty_ref=giro_counterparty_iban("Hausverwaltung Muster GmbH"),
    ),
    SeedRule("Fado tickets", "category", "Leisure", purpose_regex="^fado .*tickets?$"),
    SeedRule(
        "Frischemarkt groceries",
        "category",
        "Groceries",
        condition_payee="Frischemarkt Lindenhof",
        priority=50,
    ),
)


def _everyday(rng: random.Random, channel: str, first: date, last: date, base: int) -> list[Txn]:
    days = (last - first).days + 1
    pool = [m for m in _MERCHANTS if channel in m.channels]
    count = max(1, round(base * days / 30))
    out = []
    for _ in range(count):
        m = rng.choices(pool, weights=[p.weight for p in pool])[0]
        amount = -rng.randint(m.low, m.high)
        income = m.name == "Max Mustermann" and rng.random() < 0.3
        out.append(
            Txn(
                booked_on=first + timedelta(days=rng.randrange(days)),
                name=m.name if channel == "giro" or channel == "visa" else "",
                purpose=rng.choice(m.texts)
                if channel in ("giro", "visa")
                else f"{m.name.upper()} {rng.choice(m.texts)}",
                amount=-amount if income else amount,
                booking_text="Lastschrift" if channel == "giro" and rng.random() < 0.5 else "Kartenzahlung",
                ref=_iban(_MERCHANTS.index(m) + 1) if channel == "giro" else "",
            )
        )
    return out


def build_plan(*, seed: int, end: date, months: int) -> SeedPlan:
    """`end` is the export day; bookings stop the day before (the importer rolls figures back to it)."""
    last_day = end - timedelta(days=1)
    if months < 1:
        raise ValueError("months must be at least 1")
    starts = _month_starts(last_day, months)
    start = starts[0]
    rngs = {k: random.Random(f"{seed}:{k}") for k in ("giro", "visa", "amex", "paypal", "trip", "savings")}
    txns: dict[str, list[Txn]] = {k: [] for k in ("giro", "savings", "visa", "amex", "paypal")}

    for first in starts:
        last = min(_month_end(first), last_day)
        for channel, base in (("giro", 16), ("visa", 24), ("amex", 25), ("paypal", 24)):
            txns[channel].extend(_everyday(rngs[channel], channel, first, last, base))
        for name, booking, purpose, amount, day, channel in _RECURRING:
            booked = first.replace(day=day)
            if booked <= last_day:
                txns[channel].append(
                    Txn(
                        booked,
                        name,
                        purpose,
                        amount,
                        booking,
                        _iban(40 + len(name)) if channel == "giro" else "",
                    )
                )
        r = rngs["visa"]
        for name, purpose, ccy, low, high, rate in _FOREIGN:
            if r.random() < (1.0 if name == "CloudNotes Inc" else 0.45):
                booked = first.replace(day=min(_month_end(first).day, r.randint(2, 26)))
                if booked <= last_day:
                    minor = r.randint(low, high)
                    txns["visa"].append(
                        Txn(booked, name, purpose, -round(minor * 10000 / rate), foreign=(ccy, -minor, rate))
                    )
        # savings plan out of the giro, interest on the savings account
        if first.replace(day=2) <= last_day:
            booked = first.replace(day=2)
            txns["giro"].append(
                Txn(
                    booked,
                    "Tagesgeld Sparplan",
                    "Sparplan Tagesgeld",
                    -30000,
                    "Dauerauftrag",
                    IBAN["savings"],
                )
            )
            txns["savings"].append(Txn(booked, OWNER, "Sparplan", 30000, "Gutschrift", IBAN["giro"]))
        if first.replace(day=28) <= last_day:
            txns["savings"].append(
                Txn(
                    first.replace(day=28),
                    "Beispiel Bank",
                    "Zinsertrag",
                    rngs["savings"].randint(300, 900),
                    "Zinsen",
                )
            )
        for _ in range(2):  # cash withdrawals
            if last >= first.replace(day=14):
                booked = first + timedelta(days=rngs["giro"].randint(5, 25))
                if booked <= last_day:
                    txns["giro"].append(
                        Txn(
                            booked,
                            "Geldautomat Hauptstraße",
                            "Bargeldauszahlung",
                            -10000,
                            "Auszahlung",
                            _iban(90),
                        )
                    )

    # the Visa is settled from the giro on the 5th for the month before
    for first in starts:
        spent = -sum(
            t.amount for t in txns["visa"] if first <= t.booked_on <= _month_end(first) and t.amount < 0
        )
        nxt = _month_end(first) + timedelta(days=5)
        if spent > 0 and nxt <= last_day:
            txns["giro"].append(
                Txn(nxt, "Visa Kartenabrechnung", "Ausgleich Kreditkarte", -spent, "Lastschrift", _iban(95))
            )
            txns["visa"].append(Txn(nxt, "", "ZAHLUNG ERHALTEN DANKE", spent, "Zahlung"))

    span = (last_day - start).days
    trip_start = start + timedelta(days=max(0, round(span * 0.45)))
    trip_end = trip_start + timedelta(days=6)
    if trip_end > last_day:
        trip_start, trip_end = last_day - timedelta(days=6), last_day
    tr = rngs["trip"]
    for name, purpose, low, high, channel, offset in _TRIP:
        booked = trip_start + timedelta(days=tr.randint(0, 6) if offset < 0 else offset)
        text_name = name if channel in ("giro", "visa") else ""
        text_purpose = purpose if channel in ("giro", "visa") else f"{name.upper()} {purpose}"
        txns[channel].append(
            Txn(
                booked,
                text_name,
                text_purpose,
                -tr.randint(low, high),
                ref=_iban(70) if channel == "giro" else "",
            )
        )

    # an occasional adviser invoice and tax refund on the giro
    ar = rngs["giro"]
    for first in starts[::2]:
        booked = first.replace(day=18)
        if booked <= last_day:
            txns["giro"].append(
                Txn(
                    booked,
                    "Steuerberatung Wagner",
                    "Rechnung Beratung",
                    -ar.randint(9000, 24000),
                    "Überweisung",
                    _iban(60),
                )
            )
    if starts[-1].replace(day=10) <= last_day and months >= 3:
        txns["giro"].append(
            Txn(
                starts[-2].replace(day=10),
                "Steuerverwaltung Beispielstadt",
                "Erstattung",
                41200,
                "Gutschrift",
                _iban(61),
            )
        )

    for rows in txns.values():
        rows.sort(key=lambda t: (t.booked_on, t.name, t.amount))
    cash = ((start, 25_000), (max(start, last_day - timedelta(days=9)), 18_000))
    return SeedPlan(
        seed=seed, end=end, start=start, txns=txns, trip=(trip_start, trip_end), cash_records=cash
    )


# -- rendering ------------------------------------------------------------------------------------


def _money(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    whole, cents = divmod(abs(minor), 100)
    return f"{sign}{whole:,}".replace(",", ".") + f",{cents:02d}"


def _dmy(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _short(d: date) -> str:
    return f"{d.day}.{d.month}.{d.year}"


def _giro_file(
    label: str, account: str, rows: list[Txn], *, opening: int, balance: int, export_on: date, pending: date
) -> SeedFile:
    iban = IBAN[account]
    mini = ["Konto;Inhaber;Exportdatum", f"{iban};{OWNER};{_dmy(export_on)}, 14:30:05"]
    lines = [
        *mini,
        "",
        "Kontodaten",
        *mini,
        "",
        "Kontostand",
        "Saldo;Währung für Saldo;Datum;max. Verfügungsrahmen;Währung für max. Verfügungsrahmen",
        f"{_money(balance)};EUR;{_dmy(export_on)};500,00;EUR",
        "",
        "Kontoumsätze",
        "Buchung;Valuta;Sender / Empfänger;IBAN;BIC;Buchungstext;Verwendungszweck;Kategorie;Stichwörter;"
        "Umsatz geteilt;Betrag;Währung",
        f"{_dmy(pending)};vorgemerkt;{_PENDING_NAMES[0]};{_iban(1)};n/a;Kartenzahlung;Vorgemerkt;n/a;n/a;n/a;-17,40;EUR",
    ]
    for t in sorted(rows, key=lambda x: x.booked_on, reverse=True):
        lines.append(
            f"{_dmy(t.booked_on)};{_dmy(t.booked_on)};{t.name};{t.ref or 'n/a'};n/a;{t.booking_text};"
            f"{t.purpose};n/a;n/a;n/a;{_money(t.amount)};EUR"
        )
    lines.append(
        f"{_dmy(export_on)};{_dmy(export_on)};Beispiel Bank;{_iban(2)};n/a;Hinweis;"
        "Hinweis ohne Betrag;n/a;n/a;n/a;0,00;EUR"
    )
    data = b"\xef\xbb\xbf" + ("\n".join(lines) + "\n").encode("utf-8")
    return SeedFile(
        label,
        account,
        "giro_with_preamble",
        data,
        len(rows),
        balance,
        max(t.booked_on for t in rows),
        opening,
        min(t.booked_on for t in rows),
        max(t.booked_on for t in rows),
    )


def _visa_statement(label: str, rows: list[Txn], *, opening: int, statement_on: date) -> SeedFile:
    balance = opening + sum(t.amount for t in rows)
    lines = [
        "Kreditkartenabrechnung",
        "Kreditkarte;Kundennummer;Kartennummer;Karteninhaber",
        f"Visa Beispiel;0000000;0000 0000 0000 0000;{OWNER}",
        "",
        f"Abrechnungsdatum: {_short(statement_on)}",
        "",
        "Belegdatum;Eingangstag;Verwendungszweck;Fremdwährung;Betrag;Kurs;Betrag;Währung",
    ]
    for t in rows:
        purpose = t.purpose if not t.name else f"{t.name} {t.purpose}"
        beleg = t.booked_on - timedelta(days=1) if t.amount < 0 else t.booked_on
        if t.foreign:
            ccy, minor, rate = t.foreign
            rate_text = f"{rate / 10000:.4f}".replace(".", ",")
            lines.append(
                f"{_short(beleg)};{_short(t.booked_on)};{purpose};{ccy};{_money(minor)};{rate_text};{_money(t.amount)};EUR"
            )
        else:
            lines.append(
                f"{_short(beleg)};{_short(t.booked_on)};{purpose};EUR;{_money(t.amount)};;{_money(t.amount)};EUR"
            )
    lines.append(f"Saldo:;;;;;;{_money(balance)};EUR")
    data = b"\xef\xbb\xbf" + ("\n".join(lines) + "\n").encode("utf-8")
    return SeedFile(
        label,
        "visa",
        "card_footer_balance",
        data,
        len(rows),
        balance,
        statement_on,
        opening,
        min(t.booked_on for t in rows),
        max(t.booked_on for t in rows),
    )


def _inverted_file(label: str, account: str, rows: list[Txn]) -> SeedFile:
    lines = ["Datum,Beschreibung,Betrag,Kategorie"]
    for t in rows:
        lines.append(
            f'{t.booked_on.day:02d}/{t.booked_on.month:02d}/{t.booked_on.year},{t.purpose},"{_money(-t.amount)}",n/a'
        )
    data = "\n".join(lines).encode("utf-8")
    return SeedFile(
        label,
        account,
        "card_inverted_signs",
        data,
        len(rows),
        None,
        None,
        None,
        min(t.booked_on for t in rows),
        max(t.booked_on for t in rows),
    )


def _render_all(plan: SeedPlan) -> list[SeedFile]:
    end, giro = plan.end, plan.txns["giro"]
    last_day = end - timedelta(days=1)
    files: list[SeedFile] = []
    # giro: a first export that stops short of today, then a longer, overlapping one
    first_cut = last_day - timedelta(days=18)
    one = [t for t in giro if t.booked_on <= first_cut]
    base = _OPENING["giro"]
    files.append(
        _giro_file(
            "giro export 1",
            "giro",
            one,
            opening=base,
            balance=base + sum(t.amount for t in one),
            export_on=first_cut + timedelta(days=1),
            pending=first_cut + timedelta(days=1),
        )
    )
    overlap_from = last_day - timedelta(days=40)
    two = [t for t in giro if t.booked_on >= overlap_from]
    before = base + sum(t.amount for t in giro if t.booked_on < overlap_from)
    files.append(
        _giro_file(
            "giro export 2 (overlaps 1)",
            "giro",
            two,
            opening=before,
            balance=base + sum(t.amount for t in giro),
            export_on=end,
            pending=end + timedelta(days=1),
        )
    )
    savings = plan.txns["savings"]
    files.append(
        _giro_file(
            "savings export",
            "savings",
            savings,
            opening=_OPENING["savings"],
            balance=_OPENING["savings"] + sum(t.amount for t in savings),
            export_on=end,
            pending=end + timedelta(days=1),
        )
    )
    # visa: one statement per calendar month
    running = _OPENING["visa"]
    for first in _month_starts(
        last_day, max(1, (last_day.year - plan.start.year) * 12 + last_day.month - plan.start.month + 1)
    ):
        last = min(_month_end(first), last_day)
        rows = [t for t in plan.txns["visa"] if first <= t.booked_on <= last]
        if rows:
            files.append(
                _visa_statement(f"visa statement {first:%Y-%m}", rows, opening=running, statement_on=last)
            )
            running += sum(t.amount for t in rows)
    for account in ("amex", "paypal"):
        files.append(_inverted_file(f"{account} export", account, plan.txns[account]))
    return files
