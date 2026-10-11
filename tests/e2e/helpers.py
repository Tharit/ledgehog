"""Helpers for the HTTP end-to-end tests. Everything is driven through the real app (TestClient);
the database is only read, to assert what the endpoints left behind. All data is synthetic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text

from app.plugins.importers.csv import load_presets
from tests.api.importers_helpers import Api, error_of

BASE = "/api/importers/instances"
RUNS = "/api/importers/runs"

# the giro export, line by line, as the shared fixture renders them (own copies: the e2e file
# builds variants of it, e.g. a second file whose rows overlap the first)
ROW_PENDING = (
    "21.08.2026;vorgemerkt;Muster GmbH;DE00 1111 1111 1111 1111 11;BICXXXX1;Kartenzahlung;"
    "Vorgemerkt;n/a;n/a;n/a;-20,00;EUR"
)
ROW_BOOKED_21 = (
    "21.08.2026;21.08.2026;Muster GmbH;DE00 1111 1111 1111 1111 11;BICXXXX1;Kartenzahlung;"
    "Vorgemerkt;n/a;n/a;n/a;-20,00;EUR"
)
ROW_20 = (
    "20.08.2026;20.08.2026;Beispiel Markt;DE00 2222 2222 2222 2222 22;n/a;Lastschrift;"
    "Rechnung Nummer 2026-0001 vom 15.08.2026 fuer Beispielleistung;Einkauf;n/a;n/a;-10,00;EUR"
)
ROW_19 = (
    "19.08.2026;19.08.2026;Erika Beispiel;DE00 3333 3333 3333 3333 33;BICXXXX2;Gutschrift;"
    "Miete Zurueck;n/a;n/a;n/a;1.500,00;EUR"
)
ROW_18 = (
    "18.08.2026;18.08.2026;Beispiel Strom AG;DE00 4444 4444 4444 4444 44;BICXXXX3;Lastschrift;"
    "Abschlag;Wohnen;n/a;n/a;-45,50;EUR"
)


def giro_file(
    rows: list[str],
    *,
    figure: str = "1.234,56",
    figure_on: str = "20.08.2026",
    export: str = "20.08.2026, 14:30:05",
) -> bytes:
    """A giro export in the shipped preset's layout: preamble, balance block, then the rows."""
    mini = ["Konto;Inhaber;Exportdatum", f"DE00 0000 0000 0000 0000 00;PRIVATE-NAME;{export}"]
    lines = [
        *mini,
        "",
        "Kontodaten",
        *mini,
        "",
        "Kontostand",
        "Saldo;Währung für Saldo;Datum;max. Verfügungsrahmen;Währung für max. Verfügungsrahmen",
        f"{figure};EUR;{figure_on};500,00;EUR",
        "",
        "Kontoumsätze",
        "Buchung ;Valuta;Sender / Empfänger;IBAN;BIC;Buchungstext;Verwendungszweck;Kategorie;Stichwörter;"
        "Umsatz geteilt;Betrag;Währung",
        *rows,
    ]
    return b"\xef\xbb\xbf" + "\n".join(lines).encode("utf-8")


@dataclass
class Http:
    """Thin driver over the signed-in client of an `Api`: one HTTP call per step."""

    api: Api

    # ---- steps ---------------------------------------------------------------------------

    def create_account(self, name: str, *, kind: str = "checking", **extra: Any) -> int:
        r = self.api.client.post(
            "/api/ledger/accounts", json={"name": name, "kind": kind, "currency": "EUR", **extra}
        )
        assert r.status_code == 201, r.text
        return int(r.json()["account"]["id"])

    def create_instance(self, preset: str, **override: Any) -> int:
        settings = load_presets()[preset]
        settings.update(override)
        r = self.api.client.post(
            BASE, json={"importer": "csv", "label": f"{preset} (e2e)", "settings": settings}
        )
        assert r.status_code == 201, r.text
        return int(r.json()["id"])

    def link(self, instance: int, account: int) -> dict[str, Any]:
        """Dry run, then real; returns the real result (the two must agree on the shape)."""
        url = f"{BASE}/{instance}/links"
        before = self.api.counts()
        dry = self.api.client.post(url, json={"account_id": account, "dry_run": True})
        assert dry.status_code == 200, dry.text
        assert self.api.counts() == before, "a link dry run wrote something"
        assert dry.json()["dry_run"] is True
        real = self.api.client.post(url, json={"account_id": account})
        assert real.status_code == 200, real.text
        assert set(real.json()) == set(dry.json())
        self.check()
        return real.json()

    def upload(self, instance: int, account: int, data: bytes, *, dry_run: bool = False):
        return self.api.upload(instance, account, data, dry_run=dry_run)

    def upload_ok(self, instance: int, account: int, data: bytes) -> dict[str, Any]:
        """A dry run that must write nothing, then the real upload; the real body."""
        before = self.api.counts()
        dry = self.upload(instance, account, data, dry_run=True)
        assert dry.status_code == 200, dry.text
        assert dry.json()["dry_run"] is True and dry.json()["failure"] is None, dry.text
        assert self.api.counts() == before, "an upload dry run persisted something"
        real = self.upload(instance, account, data)
        assert real.status_code == 200, real.text
        body = real.json()
        assert body["failure"] is None and body["settle"]["error"] is None, body
        # the dry run previewed what the real run then did
        assert body["summary"]["inserted"] == dry.json()["summary"]["inserted"]
        self.check()
        return body

    def check(self) -> None:
        r = self.api.client.get("/api/maintenance/check")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True, {k: v for k, v in r.json()["checks"].items() if v["rows"]}

    def facts(self, account: int) -> dict[str, Any]:
        r = self.api.client.get("/api/ledger/accounts")
        assert r.status_code == 200, r.text
        (found,) = [a for a in r.json()["accounts"] if a["id"] == account]
        return found

    def run(self, run_id: int) -> dict[str, Any]:
        r = self.api.client.get(f"{RUNS}/{run_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def revert(self, run_id: int) -> dict[str, Any]:
        """Preview (writes nothing), then the real revert carrying the preview's versions."""
        before = self.api.counts()
        preview = self.api.client.post(f"{RUNS}/{run_id}/revert", json={"dry_run": True})
        assert preview.status_code == 200, preview.text
        assert self.api.counts() == before, "a revert preview wrote something"
        versions = {int(k): v for k, v in preview.json()["versions"].items()}
        real = self.api.client.post(f"{RUNS}/{run_id}/revert", json={"expected_versions": versions})
        assert real.status_code == 200, real.text
        assert real.json()["removed_entry_ids"] == preview.json()["removed_entry_ids"]
        self.check()
        return real.json()

    # ---- what the database holds ---------------------------------------------------------

    def entries(self, account: int) -> list[tuple[str, int, date]]:
        """(kind, amount, booked_on) of every entry, oldest first: kind is the derived entry's
        type (opening, reconciliation, valuation) or `movement`."""
        with self.api.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT CASE WHEN e.balance_record_id IS NULL THEN 'movement' ELSE e.type END AS kind,"
                    " e.amount, e.booked_on FROM ledger_entry e WHERE e.account_id = :a"
                    " ORDER BY e.booked_on, e.amount, e.id"
                ),
                {"a": account},
            ).all()
        return [(r.kind, int(r.amount), r.booked_on) for r in rows]

    def records(self, account: int) -> list[tuple[str, int, date]]:
        """(kind, balance, balance_on) of the records that count (those of a reverted run do not)."""
        with self.api.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT b.kind, b.balance, b.balance_on FROM balance_record b"
                    " LEFT JOIN import_run r ON r.id = b.import_run_id"
                    " WHERE b.account_id = :a AND (r.status IS NULL OR r.status <> 'reverted')"
                    " ORDER BY b.balance_on, b.id"
                ),
                {"a": account},
            ).all()
        return [(r.kind, int(r.balance), r.balance_on) for r in rows]

    def sources(self, account: int) -> list[Any]:
        with self.api.engine.connect() as conn:
            return list(
                conn.execute(
                    text(
                        "SELECT s.amount, s.booked_on, s.source_format, s.counterparty_ref, s.purpose,"
                        " s.importer FROM source_transaction s WHERE s.account_id = :a"
                        " ORDER BY s.booked_on, s.amount"
                    ),
                    {"a": account},
                ).all()
            )


__all__ = ["BASE", "RUNS", "Http", "error_of", "giro_file"]
