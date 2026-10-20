"""Offline test of the HKKKU request and HIKKU parsing with made-up data (no bank involved)."""
import datetime as dt
import warnings

from fints.parser import FinTS3Parser, FinTS3Serializer

import probe

# request rendering
seg = probe.HKKKU1(card_number="1111222233334444", subaccount="01", date_start=dt.date(2026, 9, 20),
                   date_end=dt.date(2026, 10, 20))
seg.header.number = 3
print(FinTS3Serializer().serialize_segment(seg))

# response parsing: header, balance, dates, two entries (29 components) + empty tail group
entry1 = ["1111222233334444", "20261012", "20261013", "", "20261014", "", "", "", "", "12,50", "EUR", "D",
          "Zeile 1", "Zeile 2", "", "", "", "", "", "", "DE", "SHOP", "T1", "J", "REF1", "", "", "", ""]
entry2 = ["1111222233334444", "20261014", "20261015", "", "20261015", "10,00", "USD", "D", "0,92", "9,20", "EUR", "C",
          "Erstattung", "", "", "", "", "", "", "", "US", "Store", "", "J", "REF2", "", "", "", ""]
tail = [""] * 29


def deg(components):
    return ":".join(components)


raw = ("HIKKU:5:1:4+1111222233334444+ACC1+D:1234,56:EUR:20261016:101500+20260901+20261001+"
       + deg(entry1) + "+" + deg(entry2) + "+" + deg(tail) + "'").encode()
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    page = FinTS3Parser().parse_message(raw)

dump = probe.show_credit_card_pages([page])
assert len(dump) == 2, dump
assert dump[0]["amount"] == "-12.50" and dump[1]["amount"] == "9.20", dump
assert dump[0]["merchant_name"] == "SHOP" and dump[0]["description"] == ["Zeile 1", "Zeile 2"]
assert dump[1]["original_amount"] == "10,00" and dump[1]["exchange_rate"] == "0,92"
print("ok")
