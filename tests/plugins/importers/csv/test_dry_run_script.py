from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.csv_dry_run import main
from tests.plugins.importers.csv.fixtures import LONG_PURPOSE, PRIVATE, card_a_bytes, giro_bytes


def run_cli(tmp_path: Path, data: bytes, *args: str) -> tuple[int, str]:
    f = tmp_path / "export.csv"
    f.write_bytes(data)
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["--file", str(f), "--currency", "EUR", "--today", "2026-08-20", *args])
    return code, out.getvalue()


def test_prints_the_privacy_safe_report(tmp_path: Path) -> None:
    code, out = run_cli(tmp_path, giro_bytes(), "--preset", "giro_with_preamble")
    assert code == 0
    assert PRIVATE not in out and "DE00 0000" not in out and LONG_PURPOSE not in out
    for needle in (
        "utf-8-sig",
        "';'",
        "Buchung",
        "coverage",
        "2026-08-20",
        "balance",
        "1244.56",
        "rolled back",
    ):
        assert needle in out
    for line in out.splitlines():
        assert len(line) < 400


def test_card_shows_synthetic_payment(tmp_path: Path) -> None:
    code, out = run_cli(tmp_path, card_a_bytes(), "--preset", "card_footer_balance")
    assert code == 0 and "synthetic payment" in out and "51.10" in out and "2026-08-07" in out


def test_set_overrides_a_setting(tmp_path: Path) -> None:
    code, out = run_cli(
        tmp_path,
        card_a_bytes(),
        "--preset",
        "card_footer_balance",
        "--set",
        "statement_payment.date_offset_days=6",
        "--set",
        "statement_payment.counter_account_ref=X1",
    )
    assert code == 0 and "2026-08-09" in out


def test_failure_is_shown_with_exit_code_1(tmp_path: Path) -> None:
    code, out = run_cli(
        tmp_path, giro_bytes(), "--preset", "giro_with_preamble", "--set", "balance.label=Nirgends"
    )
    assert code == 1
    assert "FAILED" in out and "Nirgends" in out and PRIVATE not in out


def test_unknown_preset_exits_2(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as ei:
        run_cli(tmp_path, giro_bytes(), "--preset", "nope")
    assert ei.value.code == 2
    assert os.path.exists(tmp_path)
