"""utils/clock.py is the only caller of the system clock (architecture §5.1, §5.6)."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
CLOCK = APP / "utils" / "clock.py"
FORBIDDEN_ATTRS = {"now", "today", "utcnow", "utcfromtimestamp", "fromtimestamp"}
FORBIDDEN_TIME_FUNCS = {"time", "time_ns", "monotonic", "localtime", "gmtime", "ctime"}


def _is_our_clock(value: ast.expr) -> bool:
    """`clock.now()` / `app.utils.clock.today(tz)` are the sanctioned API, not a clock read."""
    return (isinstance(value, ast.Name) and value.id == "clock") or (
        isinstance(value, ast.Attribute) and value.attr == "clock"
    )


def violations(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if a.name == "time"]
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            found.append("from time import ...")
        elif isinstance(node, ast.Attribute):
            if _is_our_clock(node.value):
                continue
            if node.attr in FORBIDDEN_ATTRS or (
                isinstance(node.value, ast.Name)
                and node.value.id == "time"
                and node.attr in FORBIDDEN_TIME_FUNCS
            ):
                found.append(f".{node.attr} (line {node.lineno})")
    return found


def test_only_clock_module_reads_the_system_clock():
    offenders = {
        str(p.relative_to(APP)): v
        for p in APP.rglob("*.py")
        if p != CLOCK and (v := violations(p.read_text()))
    }
    assert offenders == {}


def test_the_check_catches_violations():
    assert violations("from datetime import datetime\nx = datetime.now()")
    assert violations("import time\nt = time.time()")
    assert violations("from time import time")
    assert violations("import datetime\nd = datetime.date.today()")
    assert not violations("from datetime import UTC\nx = 1")
    assert not violations("from app.utils import clock\nx = clock.now()")
