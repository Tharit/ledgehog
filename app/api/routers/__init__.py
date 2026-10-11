"""The API routers (architecture §4.1).

Every module in this package that defines `router` (a `fastapi.APIRouter`) is included
automatically, in name order, so adding an operation group is adding a module: no
registration line to edit. A module maps its domain exceptions to envelope codes at
import time with `app.api.errors.map_error`.
"""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import FastAPI


def include_routers(app: FastAPI) -> None:
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router)
