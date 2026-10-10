"""Per-context development database `dev_<worktree>` (architecture §9).

    . ./test.env && uv run python scripts/dev_db.py name     # prints dev_<worktree>
    . ./test.env && uv run python scripts/dev_db.py create   # creates it and runs migrations
    . ./test.env && uv run python scripts/dev_db.py drop

Then point the app at it: POSTGRES_DB=$(uv run python scripts/dev_db.py name).
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from app.utils.config import Config
from app.utils.db import admin, migrate

ROOT = Path(__file__).resolve().parent.parent


def dev_name(worktree: Path = ROOT) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", worktree.name.lower()).strip("_")[:40] or "default"
    return f"dev_{slug}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["name", "create", "drop"])
    args = parser.parse_args(argv)
    name = dev_name()
    if args.command == "name":
        print(name)
        return 0
    env = dict(os.environ)
    env.setdefault("BASE_CURRENCY", "EUR")
    env.setdefault("TIMEZONE", "UTC")
    env["POSTGRES_DB"] = env.get("POSTGRES_ADMIN_DB", "postgres")
    admin_cfg = Config.from_env(env)
    if args.command == "drop":
        admin.drop_database(admin_cfg, name)
        print(f"dropped {name}")
        return 0
    if not admin.database_exists(admin_cfg, name):
        admin.create_database(admin_cfg, name)
    migrate.upgrade(admin_cfg.with_database(name))
    print(f"ready: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
