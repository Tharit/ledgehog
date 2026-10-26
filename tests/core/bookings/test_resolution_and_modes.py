"""A document booking's entries decide their type first, under the key `booking` (spec §5.9); the importers
declare their re-delivery modes in code (spec §5.5)."""

from __future__ import annotations

from app.core.resolution import Decided, diff, rederive, resolve
from app.plugins.importers.email.importer import EmailImporter
from app.plugins.importers.testdocs import TestDocumentImporter
from tests.core.resolution.helpers import Script, account, entry

ACCOUNTS = [account(1), account(2)]


def test_a_document_booking_entry_is_a_flow_under_the_booking_key_whatever_the_passes_say() -> None:
    passes = [Script("rule", {"type": "transfer", "counter_account": 2, "category": 7})]
    got = resolve(entry(booking="document"), accounts=ACCOUNTS, classifiers=passes)
    assert got["type"] == Decided("flow", "booking", {})
    assert got["category"].pass_name == "rule" and "counter_account" not in got


def test_an_entry_that_is_not_a_booking_is_left_to_the_passes() -> None:
    passes = [Script("rule", {"type": "transfer", "counter_account": 2})]
    got = resolve(entry(), accounts=ACCOUNTS, classifiers=passes)
    assert got["type"].pass_name == "rule" and got["type"].value == "transfer"


def test_a_stored_booking_key_stands_and_rederiving_changes_nothing() -> None:
    passes = [Script("history", {"category": 7})]
    current = {"type": Decided("flow", "booking", {})}
    new = rederive(entry(booking="document"), current, accounts=ACCOUNTS, classifiers=passes)
    assert new["type"] == Decided("flow", "booking", {})
    assert diff(current, new) == {"category": new["category"]}


def test_the_email_importer_keeps_and_the_test_document_importer_replaces() -> None:
    assert EmailImporter.redelivery == "keep"
    assert TestDocumentImporter.redelivery == "replace"
