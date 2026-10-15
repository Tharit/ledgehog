"""A write that names a category, payee or account that no longer exists (architecture §4.1, D200).

A merge repoints entries without bumping their versions, so a client still holding the merged-away
id (an open panel's draft, a stale picker) must be refused rather than write a dangling reference.
The refusal is one named conflict, `StaleReference`, whose `field` names the request field at fault;
the API answers 409 with the code `stale_reference`. Writes check the reference themselves where
they can name the field; `stale_from_integrity` is the net under every other write: a foreign key
that rejects an insert or update because its target is gone.
"""

from __future__ import annotations

import re

import psycopg.errors
from sqlalchemy.exc import DBAPIError

from app.utils.db.errors import constraint_name


class StaleReference(Exception):
    """The write names a row that no longer exists. `field` is the request field, `entity` the kind."""

    def __init__(self, field: str, entity: str, entity_id: int | None = None) -> None:
        self.field = field
        self.entity = entity
        self.entity_id = entity_id
        what = f"{entity} {entity_id}" if entity_id is not None else f"the {entity} named by `{field}`"
        super().__init__(f"{what} no longer exists: reload the {entity} list")


# FK column -> the kind of row it names; only the dimensions a merge or delete can remove
_ENTITY_OF = {
    "category_id": "category",
    "parent_id": "category",
    "payee_id": "payee",
    "account_id": "account",
    "counter_account_id": "account",
    "tag_id": "tag",
}
_FK_COLUMN = re.compile(r"_(" + "|".join(_ENTITY_OF) + r")_fkey$")
_KEY_ID = re.compile(r"\)=\((\d+)\)")


def stale_from_integrity(exc: DBAPIError) -> StaleReference | None:
    """The `StaleReference` a foreign-key violation on insert or update amounts to, else None.

    A delete refused because something still references the row is a different violation
    (RESTRICT) and is not stale.
    """
    orig = exc.orig
    if not isinstance(orig, psycopg.errors.ForeignKeyViolation):
        return None
    diag = orig.diag
    if not (diag.message_primary or "").startswith("insert or update"):
        return None
    name = constraint_name(exc) or ""
    if name == "fk_category_parent_same_kind":
        field = "parent_id"
    else:
        found = _FK_COLUMN.search(name)
        if found is None:
            return None
        field = found.group(1)
    key = _KEY_ID.search(diag.message_detail or "")
    return StaleReference(field, _ENTITY_OF[field], int(key.group(1)) if key else None)
