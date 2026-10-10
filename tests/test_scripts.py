import subprocess
import sys
from pathlib import Path

from app.utils.db import admin

ROOT = Path(__file__).resolve().parent.parent


def run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
    )


def test_sweep_script_dry_run_lists_without_dropping(admin_cfg, isolated_db):
    r = run("sweep_dbs.py", "--hours", "-1", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert f"would drop {isolated_db.db.name}" in r.stdout
    assert isolated_db.db.name in {d.name for d in admin.list_databases(admin_cfg)}


def test_dev_db_name_is_derived_from_the_worktree_and_is_disposable_named():
    from scripts.dev_db import dev_name

    assert dev_name(Path("/work/My Tree-1")) == "dev_my_tree_1"
    admin.check_name(dev_name(Path("/work/" + "x" * 100)))  # long names are truncated, still valid
    r = run("dev_db.py", "name")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == dev_name()
