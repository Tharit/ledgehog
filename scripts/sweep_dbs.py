"""Drop leaked disposable databases (`test_*`, `tpl_*`) older than a day.

    . ./test.env && uv run python scripts/sweep_dbs.py [--hours 24] [--dry-run]

`dev_*` databases are never swept: they are long-lived and may hold real data. Drop one
with `scripts/dev_db.py drop`.

Reads POSTGRES_* from the environment; connects to POSTGRES_ADMIN_DB (default `postgres`).
"""

from __future__ import annotations

import argparse
import os
from datetime import timedelta

from app.utils.config import Config
from app.utils.db import admin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    env.setdefault("BASE_CURRENCY", "EUR")
    env.setdefault("TIMEZONE", "UTC")
    env["POSTGRES_DB"] = env.get("POSTGRES_ADMIN_DB", "postgres")
    cfg = Config.from_env(env)
    names = admin.sweep(cfg, older_than=timedelta(hours=args.hours), dry_run=args.dry_run)
    verb = "would drop" if args.dry_run else "dropped"
    for name in names:
        print(f"{verb} {name}")
    print(f"{verb} {len(names)} database(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
