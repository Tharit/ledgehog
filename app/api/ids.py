"""Id types shared by every route (architecture §4.4).

An id in a path, a query or a body is a positive integer inside the range the database can hold
and the account lock can address; anything else is a 422 `validation_error` at the boundary
(not a 404: the value is not an id at all), so a huge number never reaches a statement.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Path, Query
from pydantic import Field

MAX_ID = 2**53  # JSON-safe, and well below the lock's 2**56 and Postgres bigint
MAX_VERSION = 2**31 - 1  # a `version` column is a Postgres integer

EntityId = Annotated[int, Field(gt=0, le=MAX_ID)]
EntityVersion = Annotated[int, Field(gt=0, le=MAX_VERSION)]
PathId = Annotated[int, Path(gt=0, le=MAX_ID)]
QueryId = Annotated[int, Query(gt=0, le=MAX_ID)]
