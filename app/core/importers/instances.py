"""Importer instances and account links (spec §5.4, architecture §4.1).

Every write is ONE transaction: settle lock shared, then the account's lock where an account
is written; it commits, and only then settles where it changed what the synced status reads
(settling takes the settle lock exclusively in its own transaction). A settling failure is
reported on the result, never raised into the committed write.

Settings are validated by the plugin, not here: callers inject `validate`, which runs before
anything is written and may raise whatever the plugin raises.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.accounts import AccountMissing
from app.core.settle.settle import SettleResult, settle
from app.utils.db.errors import constraint_name
from app.utils.db.locks import lock_accounts, lock_settle_shared, retry_on_deadlock

Validate = Callable[[Mapping[str, Any]], None]

_KINDS = frozenset({"transactions", "documents", "rates"})
_ACCESS = frozenset({"owner", "shared"})


class InstanceError(Exception):
    """An instance or link operation was refused; the message states the rule. Nothing was written."""


class InstanceMissing(InstanceError):
    def __init__(self, instance_id: int) -> None:
        super().__init__(f"importer instance {instance_id} does not exist")


class InstanceForbidden(InstanceError):
    """The instance belongs to the other user (spec §5.11): 403 `forbidden`."""

    def __init__(self, instance_id: int) -> None:
        super().__init__(f"importer instance {instance_id} belongs to another user")


def may_manage(instance: Any, user_id: int) -> bool:
    """Spec §5.11: the owner, or anyone for a shared instance, may run and manage it."""
    return bool(instance.access == "shared" or instance.owner_id == user_id)


def require_manager(engine: Engine, instance_id: int, user_id: int) -> None:
    """The one owner check of every managing operation: `InstanceMissing`, else `InstanceForbidden`."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT access, owner_id FROM importer_instance WHERE id = :i"), {"i": instance_id}
        ).one_or_none()
    if row is None:
        raise InstanceMissing(instance_id)
    if not may_manage(row, user_id):
        raise InstanceForbidden(instance_id)


class InvalidInstance(InstanceError):
    """The request is malformed (emits, access and owner, blank label or reference)."""


class InstanceHasRuns(InstanceError):
    """Delete refused: runs are provenance and outlive the instance's row only as orphans."""

    def __init__(self, instance_id: int, runs: int) -> None:
        super().__init__(
            f"importer instance {instance_id} has {runs} run(s) and cannot be deleted: disable it instead"
        )


class InstanceDisabled(InstanceError):
    def __init__(self, instance_id: int) -> None:
        super().__init__(f"importer instance {instance_id} is disabled: enable it before linking an account")


class NotAnAccountSource(InstanceError):
    def __init__(self, instance_id: int) -> None:
        super().__init__(
            f"importer instance {instance_id} does not emit transactions: it has no accounts to link"
        )


class AccountClosed(InstanceError):
    def __init__(self, account_id: int) -> None:
        super().__init__(f"account {account_id} is closed: reopen it before linking it")


class ExternalRefTaken(InstanceError):
    def __init__(self, instance_id: int, external_ref: str) -> None:
        super().__init__(f"importer instance {instance_id} already links an account as {external_ref!r}")


class AlreadyLinked(InstanceError):
    def __init__(self, instance_id: int, account_id: int) -> None:
        super().__init__(f"account {account_id} is already linked to importer instance {instance_id}")


class LinkMissing(InstanceError):
    def __init__(self, instance_id: int, account_id: int) -> None:
        super().__init__(f"account {account_id} is not linked to importer instance {instance_id}")


@dataclass(frozen=True)
class LinkedAccount:
    account_id: int
    external_ref: str


@dataclass(frozen=True)
class InstanceView:
    id: int
    importer: str
    label: str
    emits: tuple[str, ...]
    access: str
    owner_id: int | None
    owner_name: str | None  # the owner's display name; None for a shared instance
    settings: dict[str, Any]
    disabled: bool
    last_run_at: datetime | None
    accounts: tuple[LinkedAccount, ...]


@dataclass(frozen=True)
class LinkResult:
    """The preview of a link, and what a real link did (same shape either way).

    `user_authored_count` counts the user-authored source rows the account holds, counter-legs
    included: imports overlapping them are not deduplicated against them (spec §5.2, §5.3).
    """

    instance_id: int
    account_id: int
    external_ref: str
    dry_run: bool
    user_authored_count: int
    first_booked_on: date | None
    last_booked_on: date | None
    account_becomes_synced: bool
    warnings: tuple[str, ...]
    changes: tuple[str, ...]
    settle: SettleResult | None = None


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value))


def _need_instance(conn: Connection, instance_id: int) -> Any:
    row = conn.execute(
        text("SELECT id, emits, disabled FROM importer_instance WHERE id = :i FOR SHARE"), {"i": instance_id}
    ).one_or_none()
    if row is None:
        raise InstanceMissing(instance_id)
    return row


def _check_label(label: str) -> None:
    if not label.strip():
        raise InvalidInstance("an importer instance needs a label")


def create_instance(
    engine: Engine,
    *,
    importer: str,
    label: str,
    settings: Mapping[str, Any],
    emits: Sequence[str],
    access: str,
    owner_id: int | None = None,
    validate: Validate | None = None,
) -> int:
    """Create an instance. `validate` (the plugin's settings check) runs before anything is written."""
    _check_label(label)
    if not emits or not set(emits) <= _KINDS:
        raise InvalidInstance(f"emits must be a non-empty subset of {sorted(_KINDS)}")
    if access not in _ACCESS:
        raise InvalidInstance(f"access must be one of {sorted(_ACCESS)}")
    if (access == "owner") != (owner_id is not None):
        raise InvalidInstance("an instance has an owner exactly when its access is 'owner'")
    if validate is not None:
        validate(settings)

    def run() -> int:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            if (
                owner_id is not None
                and conn.execute(text("SELECT 1 FROM app_user WHERE id = :i"), {"i": owner_id}).first()
                is None
            ):
                raise InvalidInstance(f"user {owner_id} does not exist")
            return int(
                conn.execute(
                    text(
                        "INSERT INTO importer_instance (importer, label, emits, access, owner_id, settings)"
                        " VALUES (:importer, :label, :emits, :access, :owner, CAST(:settings AS jsonb))"
                        " RETURNING id"
                    ),
                    {
                        "importer": importer,
                        "label": label,
                        "emits": list(emits),
                        "access": access,
                        "owner": owner_id,
                        "settings": _json(settings),
                    },
                ).scalar_one()
            )

    return retry_on_deadlock(run)


def update_instance(
    engine: Engine,
    instance_id: int,
    *,
    label: str | None = None,
    settings: Mapping[str, Any] | None = None,
    disabled: bool | None = None,
    validate: Validate | None = None,
) -> None:
    """Change what is given. Nothing the synced status reads changes, so nothing settles."""
    if label is not None:
        _check_label(label)
    if settings is not None and validate is not None:
        validate(settings)

    def run() -> None:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            _need_instance(conn, instance_id)
            if label is not None:
                conn.execute(
                    text("UPDATE importer_instance SET label = :v WHERE id = :i"),
                    {"v": label, "i": instance_id},
                )
            if settings is not None:
                conn.execute(
                    text("UPDATE importer_instance SET settings = CAST(:v AS jsonb) WHERE id = :i"),
                    {"v": _json(settings), "i": instance_id},
                )
            if disabled is not None:
                conn.execute(
                    text("UPDATE importer_instance SET disabled = :v WHERE id = :i"),
                    {"v": disabled, "i": instance_id},
                )

    retry_on_deadlock(run)


def reset_instance(engine: Engine, instance_id: int) -> None:
    """Forget what the importer wrote back (`state`); the settings stay."""

    def run() -> None:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            _need_instance(conn, instance_id)
            conn.execute(
                text("UPDATE importer_instance SET state = '{}'::jsonb WHERE id = :i"), {"i": instance_id}
            )

    retry_on_deadlock(run)


def save_state(engine: Engine, instance_id: int, state: Mapping[str, Any]) -> bool:
    """Write back the importer's working copy of `state` (architecture §5.5), only if it differs.

    One short transaction, after a job ended and whatever its outcome. Returns whether a row
    changed; an instance deleted meanwhile is no error. Nothing settles: state is read by no
    derived value. The importer keeps secrets out of it (spec §7); this does not look.
    """
    payload = _json(state)

    def run() -> bool:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            return bool(
                conn.execute(
                    text(
                        "UPDATE importer_instance SET state = CAST(:v AS jsonb)"
                        " WHERE id = :i AND state IS DISTINCT FROM CAST(:v AS jsonb)"
                    ),
                    {"v": payload, "i": instance_id},
                ).rowcount
            )

    return retry_on_deadlock(run)


def delete_instance(engine: Engine, instance_id: int) -> SettleResult:
    """Delete an instance that has no runs (the runs' foreign key would only null them out).

    Its links go with it, so the accounts it made synced are re-judged: it settles.
    """

    def run() -> None:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            _need_instance(conn, instance_id)
            runs = int(
                conn.execute(
                    text("SELECT count(*) FROM import_run WHERE importer_instance_id = :i"),
                    {"i": instance_id},
                ).scalar_one()
            )
            if runs:
                raise InstanceHasRuns(instance_id, runs)
            conn.execute(text("DELETE FROM importer_instance WHERE id = :i"), {"i": instance_id})

    retry_on_deadlock(run)
    return settle(engine)


def list_instances(conn: Connection) -> list[InstanceView]:
    """Every instance with its linked accounts and when it last ran. Credential state is not listed."""
    links: dict[int, list[LinkedAccount]] = {}
    for r in conn.execute(
        text("SELECT importer_instance_id, account_id, external_ref FROM account_source ORDER BY account_id")
    ):
        links.setdefault(r.importer_instance_id, []).append(LinkedAccount(r.account_id, r.external_ref))
    return [
        InstanceView(
            id=r.id,
            importer=r.importer,
            label=r.label,
            emits=tuple(r.emits),
            access=r.access,
            owner_id=r.owner_id,
            owner_name=r.owner_name,
            settings=r.settings,
            disabled=r.disabled,
            last_run_at=r.last_run_at,
            accounts=tuple(links.get(r.id, ())),
        )
        for r in conn.execute(
            text(
                "SELECT i.id, i.importer, i.label, i.emits, i.access, i.owner_id,"
                " u.display_name AS owner_name, i.settings, i.disabled, l.last_run_at"
                " FROM importer_instance i"
                " LEFT JOIN app_user u ON u.id = i.owner_id"
                " LEFT JOIN v_importer_last_run l ON l.importer_instance_id = i.id ORDER BY i.id"
            )
        )
    ]


def _link(
    conn: Connection, instance_id: int, account_id: int, external_ref: str, dry_run: bool
) -> LinkResult:
    lock_settle_shared(conn)
    lock_accounts(conn, [account_id])
    instance = _need_instance(conn, instance_id)
    account = conn.execute(
        text(
            "SELECT a.closed_on, (SELECT count(*) FROM account_source s WHERE s.account_id = a.id) AS links"
            " FROM account a WHERE a.id = :i"
        ),
        {"i": account_id},
    ).one_or_none()
    if account is None:
        raise AccountMissing(account_id)
    if "transactions" not in instance.emits:
        raise NotAnAccountSource(instance_id)
    if instance.disabled:
        raise InstanceDisabled(instance_id)
    if account.closed_on is not None:
        raise AccountClosed(account_id)
    held = conn.execute(
        text(
            "SELECT count(*) AS n, min(booked_on) AS first, max(booked_on) AS last"
            " FROM source_transaction WHERE account_id = :a AND importer IS NULL"
        ),
        {"a": account_id},
    ).one()
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO account_source (account_id, importer_instance_id, external_ref)"
                    " VALUES (:a, :i, :r)"
                ),
                {"a": account_id, "i": instance_id, "r": external_ref},
            )
    except DBAPIError as exc:
        if constraint_name(exc) == "ux_account_source_ref":
            raise ExternalRefTaken(instance_id, external_ref) from exc
        if constraint_name(exc) == "account_source_pkey":
            raise AlreadyLinked(instance_id, account_id) from exc
        raise
    becomes_synced = account.links == 0
    warnings: tuple[str, ...] = ()
    if held.n:
        warnings = (
            f"the account holds {held.n} user-authored row(s) (counter-legs included) dated "
            f"{held.first} to {held.last}: later imports overlapping them are not deduplicated "
            "against them",
        )
    changes: list[str] = []
    if becomes_synced:
        changes.append(
            "the account becomes synced: new user-authored rows and counter-legs will be refused on it "
            "(those it holds stay)"
        )
    changes.append("units not yet confirmed are settled again")
    return LinkResult(
        instance_id=instance_id,
        account_id=account_id,
        external_ref=external_ref,
        dry_run=dry_run,
        user_authored_count=int(held.n),
        first_booked_on=held.first,
        last_booked_on=held.last,
        account_becomes_synced=becomes_synced,
        warnings=warnings,
        changes=tuple(changes),
    )


def link_account(
    engine: Engine, instance_id: int, account_id: int, external_ref: str, *, dry_run: bool = False
) -> LinkResult:
    """Link an account to an instance, as `external_ref` at that login (spec §5.4).

    The previewed operation: `dry_run=True` runs the same code and rolls it back (no settle),
    returning the same shape. The account must be open, the instance enabled and emitting
    transactions, and `external_ref` unused within the instance.
    """
    if not external_ref.strip():
        raise InvalidInstance("a link needs the account's reference at the login")

    def run() -> LinkResult:
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                result = _link(conn, instance_id, account_id, external_ref, dry_run)
            except BaseException:
                tx.rollback()
                raise
            if dry_run:
                tx.rollback()
            else:
                tx.commit()
            return result

    result = retry_on_deadlock(run)
    if dry_run:
        return result
    return replace(result, settle=settle(engine))


def unlink_account(engine: Engine, instance_id: int, account_id: int) -> SettleResult:
    """Remove the link; the coverage of past runs stays. Settles."""

    def run() -> None:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            lock_accounts(conn, [account_id])
            deleted = conn.execute(
                text("DELETE FROM account_source WHERE importer_instance_id = :i AND account_id = :a"),
                {"i": instance_id, "a": account_id},
            ).rowcount
            if not deleted:
                raise LinkMissing(instance_id, account_id)

    retry_on_deadlock(run)
    return settle(engine)
