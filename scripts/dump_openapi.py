"""Write the OpenAPI schema to a file, with no database and no server.

    uv run python scripts/dump_openapi.py                  # writes frontend/openapi.json
    uv run python scripts/dump_openapi.py --out some.json
    uv run python scripts/dump_openapi.py --check          # exit 1 when the file is stale

The frontend generates its types from the file:

    npx openapi-typescript frontend/openapi.json -o frontend/src/lib/types/api.d.ts

The output is deterministic (sorted keys, fixed indent). The app is built with dummy settings and
a lazy engine, so nothing is read from the environment that matters and no connection is opened.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from app.api import create_app
from app.api.openapi import build_openapi
from app.utils.config import Config
from app.utils.db.engine import make_engine

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "frontend" / "openapi.json"

# placeholders for the variables `Config.from_env` requires: the schema depends on none of them
_DUMMY = {
    "POSTGRES_DB": "openapi_dump",
    "POSTGRES_USER": "openapi_dump",
    "POSTGRES_PASSWORD": "not-a-real-password",
    "BASE_CURRENCY": "EUR",
    "TIMEZONE": "UTC",
}


def generate() -> str:
    env = {**_DUMMY, **{k: v for k, v in os.environ.items() if k in _DUMMY or k.startswith("POSTGRES_")}}
    config = replace(Config.from_env(env), expose_openapi=True)
    engine = make_engine(config)  # lazy: no connection until first use, and none is made here
    try:
        app = create_app(config, engine)
        return json.dumps(build_openapi(app), indent=2, sort_keys=True) + "\n"
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="target file (default: %(default)s)")
    parser.add_argument("--check", action="store_true", help="exit 1 when the file differs; write nothing")
    args = parser.parse_args(argv)
    out: Path = args.out
    fresh = generate()
    if args.check:
        if not out.is_file():
            print(f"{out} is missing; run scripts/dump_openapi.py to create it", file=sys.stderr)
            return 1
        stored = out.read_text(encoding="utf-8")
        if stored == fresh:
            return 0
        diff = difflib.unified_diff(
            stored.splitlines(keepends=True),
            fresh.splitlines(keepends=True),
            fromfile=f"{out} (stored)",
            tofile="generated",
            n=1,
        )
        lines = list(diff)
        sys.stderr.writelines(lines[:60])
        if len(lines) > 60:
            print(f"... {len(lines) - 60} more diff lines", file=sys.stderr)
        print(f"{out} is out of date; run scripts/dump_openapi.py", file=sys.stderr)
        return 1
    if not out.parent.is_dir():
        print(
            f"the directory {out.parent} does not exist; create it first (nothing was written)",
            file=sys.stderr,
        )
        return 2
    out.write_text(fresh, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
