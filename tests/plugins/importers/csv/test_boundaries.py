"""The plugin imports only app.core.plugins.* and app.core.domain.* (architecture §5.1)."""

from __future__ import annotations

import ast
from pathlib import Path

import app.plugins.importers.csv as pkg
from tests.plugins.importers.csv.helpers import CARD, card_profile, run


def test_package_imports_only_core_plugins_and_domain() -> None:
    root = Path(pkg.__file__).parent
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                if name.startswith("app."):
                    assert name.startswith(
                        ("app.core.plugins", "app.core.domain", "app.plugins.importers.csv")
                    ), f"{path.name} imports {name}"


def test_a_mapping_that_skips_every_row_warns_but_a_stated_end_still_covers() -> None:
    p = card_profile(balance=None, booked_on="Verwendungszweck", header_marker=["Belegdatum", "Eingangstag"])
    p["purpose"] = []
    text = CARD.replace("Zweck;Betrag", "Verwendungszweck;Betrag")
    pf = run(text, profile=p)
    assert pf.rows == ()
    assert any("every row" in w for w in pf.report.warnings)
    assert pf.report.skipped.count == pf.report.rows_read > 0
