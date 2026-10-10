"""Synthetic exports mirroring the structure of the three real formats. Every name, number and
amount below is invented; the preamble carries the marker string PRIVATE-NAME on purpose so the
tests can prove it never reaches a report."""

from __future__ import annotations

PRIVATE = "PRIVATE-NAME"
LONG_PURPOSE = "Rechnung Nummer 2026-0001 vom 15.08.2026 fuer Beispielleistung"


def giro_bytes(*, extra_preamble: int = 0, crlf: bool = False, trailing_newline: bool = False) -> bytes:
    mini = ["Konto;Inhaber;Exportdatum", f"DE00 0000 0000 0000 0000 00;{PRIVATE};20.08.2026, 14:30:05"]
    lines = [
        *mini,
        "",
        "Kontodaten",
        *mini,
        "",
        "Kontostand",
        "Saldo;Währung für Saldo;Datum;max. Verfügungsrahmen;Währung für max. Verfügungsrahmen",
        "1.234,56;EUR;20.08.2026;500,00;EUR",
        "",
        *(f"Zusatzzeile {i}" for i in range(extra_preamble)),
        "Kontoumsätze",
        "Buchung ;Valuta;Sender / Empfänger;IBAN;BIC;Buchungstext;Verwendungszweck;Kategorie;Stichwörter;"
        "Umsatz geteilt;Betrag;Währung",
        "21.08.2026;vorgemerkt;Muster GmbH;DE00 1111 1111 1111 1111 11;BICXXXX1;Kartenzahlung;"
        "Vorgemerkt;n/a;n/a;n/a;-20,00;EUR",
        "20.08.2026;20.08.2026;Beispiel Markt;DE00 2222 2222 2222 2222 22;n/a;Lastschrift;"
        f"{LONG_PURPOSE};Einkauf;n/a;n/a;-10,00;EUR",
        "19.08.2026;19.08.2026;Erika Beispiel;DE00 3333 3333 3333 3333 33;BICXXXX2;Gutschrift;"
        "Miete Zurueck;n/a;n/a;n/a;1.500,00;EUR",
        "18.08.2026;18.08.2026;Beispiel Strom AG;DE00 4444 4444 4444 4444 44;BICXXXX3;Lastschrift;"
        "Abschlag;Wohnen;n/a;n/a;-45,50;EUR",
        "17.08.2026;18.08.2026;Beispiel Bank;DE00 5555 5555 5555 5555 55;BICXXXX4;Hinweis;"
        "Hinweis ohne Betrag;n/a;n/a;n/a;0,00;EUR",
    ]
    nl = "\r\n" if crlf else "\n"
    text = nl.join(lines) + (nl if trailing_newline else "")
    return b"\xef\xbb\xbf" + text.encode("utf-8")


def card_a_bytes() -> bytes:
    lines = [
        "Kreditkartenabrechnung",
        "Kreditkarte;Kundennummer;Kartennummer;Karteninhaber",
        f"Visa Beispiel;0000000;0000 0000 0000 0000;{PRIVATE}",
        "",
        "Abrechnungsdatum: 3.8.2026",
        "",
        "Belegdatum;Eingangstag;Verwendungszweck;Fremdwährung;Betrag;Kurs;Betrag;Währung",
        "1.8.2026;2.8.2026;Beispiel Shop;EUR;-12,00;;-12,00;EUR",
        "2.8.2026;3.8.2026;Muster Tickets USD;USD;-10,00;1,10;-9,09;EUR",
        "30.7.2026;31.7.2026;Beispiel Cafe;EUR;-30,01;;-30,01;EUR",
        "Saldo:;;;;;;-51,10;EUR",
    ]
    return b"\xef\xbb\xbf" + ("\n".join(lines) + "\n").encode("utf-8")


def card_b_bytes() -> bytes:
    lines = [
        "Datum,Beschreibung,Betrag,Weitere Details,Erscheint auf Ihrer Abrechnung als,Adresse,Stadt,PLZ,"
        "Land,Betreff,Kategorie",
        '05/08/2026,BEISPIEL SHOP,"12,50",Details,SHOP*1,"Musterstr. 1\n12345 Musterstadt",Musterstadt,12345,DE,,Einkauf',
        '06/08/2026,ZAHLUNG ERHALTEN,"-100,00"',
        '07/08/2026,BEISPIEL ABO,"1.234,56",Jahresabo,ABO*2,,,,,',
    ]
    return "\n".join(lines).encode("utf-8")
