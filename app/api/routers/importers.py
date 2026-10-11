"""Importer instances, account links and file upload (architecture §4.1, §4.4, §5.5).

Thin over `app.core.importers`: parse the request, call one operation, serialise what it
returns. The importer implementations come from `request.app.state.importers` (the composition
root fills it); this module never imports a plugin. Domain errors are answered through the
envelope by the mappings registered below.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import ApiError, map_error
from app.api.session import CurrentUser, EngineDep
from app.core.accounts import AccountMissing
from app.core.importers import instances as inst
from app.core.importers.instances import InstanceView
from app.core.plugins.errors import (
    AuthRejected,
    ChallengeAbandoned,
    ChallengeExpired,
    ImporterError,
    InvalidProfile,
    NotRegistered,
    ParseFailed,
    SourceUnavailable,
)
from app.core.plugins.importer import FileImporter

router = APIRouter(prefix="/api/importers")

# ---- serialisation -------------------------------------------------------------------------


def to_json(value: Any) -> Any:
    """A JSON-ready copy of a result tree: dataclasses become objects (field names as keys),
    dates ISO strings, tuples lists, integer-keyed mappings string-keyed. Amounts stay the
    integer minor units the core holds (their currency is a field next to them)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_json(v) for v in value]
    return value


# ---- error mapping -------------------------------------------------------------------------


def _setting_of(exc: InvalidProfile) -> dict[str, str | None]:
    # the plugin's message is "<setting>: <what is wrong>" (architecture §5.5)
    head, sep, _ = str(exc).partition(":")
    return {"setting": head.strip() if sep else None}


def _importer_details(exc: ImporterError) -> dict[str, Any]:
    details: dict[str, Any] = {"retryable": exc.retryable}
    if isinstance(exc, ParseFailed):
        details["report"] = to_json(exc.report)
    return details


map_error(AccountMissing, 404, "not_found")
map_error(inst.InstanceMissing, 404, "not_found")
map_error(inst.LinkMissing, 404, "not_found")
map_error(inst.InvalidInstance, 422, "invalid_instance")
map_error(inst.InstanceHasRuns, 409, "instance_has_runs")
map_error(inst.InstanceDisabled, 409, "instance_disabled")
map_error(inst.NotAnAccountSource, 409, "not_an_account_source")
map_error(inst.AccountClosed, 409, "account_closed")
map_error(inst.ExternalRefTaken, 409, "external_ref_taken")
map_error(inst.AlreadyLinked, 409, "already_linked")
map_error(InvalidProfile, 422, "invalid_profile", details=_setting_of)
# the importer taxonomy (§5.5): the code names the class, `details.retryable` drives the UI
map_error(ImporterError, 422, "importer_error", details=_importer_details)
map_error(ParseFailed, 422, "parse_failed", details=_importer_details)
map_error(AuthRejected, 422, "auth_rejected", details=_importer_details)
map_error(ChallengeExpired, 422, "challenge_expired", details=_importer_details)
map_error(ChallengeAbandoned, 422, "challenge_abandoned", details=_importer_details)
map_error(SourceUnavailable, 502, "source_unavailable", details=_importer_details)
map_error(NotRegistered, 422, "not_registered", details=_importer_details)


def importer_for(request: Request, name: str) -> FileImporter:
    """The registered implementation of importer `name`, or 422 `importer_not_available`."""
    found: FileImporter | None = request.app.state.importers.get(name)
    if found is None:
        raise ApiError(
            422, "importer_not_available", f"importer {name!r} is not available in this deployment"
        )
    return found


# ---- instances -----------------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateInstance(_Body):
    importer: str = Field(min_length=1)
    label: str
    settings: dict[str, Any]


class UpdateInstance(_Body):
    label: str | None = None
    settings: dict[str, Any] | None = None
    disabled: bool | None = None


def _view(engine: Any, instance_id: int) -> InstanceView:
    with engine.connect() as conn:
        for v in inst.list_instances(conn):
            if v.id == instance_id:
                return v
    raise inst.InstanceMissing(instance_id)


@router.get("/instances")
def list_instances(user: CurrentUser, engine: EngineDep) -> list[Any]:
    with engine.connect() as conn:
        return to_json(inst.list_instances(conn))  # type: ignore[no-any-return]


@router.post("/instances", status_code=201)
def create_instance(body: CreateInstance, request: Request, user: CurrentUser, engine: EngineDep) -> Any:
    importer = importer_for(request, body.importer)
    # a file importer: it emits transactions, and its profile is shared by the household
    new_id = inst.create_instance(
        engine,
        importer=body.importer,
        label=body.label,
        settings=body.settings,
        emits=["transactions"],
        access="shared",
        owner_id=None,
        validate=importer.validate_settings,
    )
    return to_json(_view(engine, new_id))


@router.put("/instances/{instance_id}")
def update_instance(
    instance_id: int, body: UpdateInstance, request: Request, user: CurrentUser, engine: EngineDep
) -> Any:
    validate = None
    if body.settings is not None:
        name = _view(engine, instance_id).importer
        validate = importer_for(request, name).validate_settings
    inst.update_instance(
        engine,
        instance_id,
        label=body.label,
        settings=body.settings,
        disabled=body.disabled,
        validate=validate,
    )
    return to_json(_view(engine, instance_id))


@router.post("/instances/{instance_id}/reset")
def reset_instance(instance_id: int, user: CurrentUser, engine: EngineDep) -> Any:
    inst.reset_instance(engine, instance_id)
    return to_json(_view(engine, instance_id))


@router.delete("/instances/{instance_id}")
def delete_instance(instance_id: int, user: CurrentUser, engine: EngineDep) -> Any:
    return {"settle": to_json(inst.delete_instance(engine, instance_id))}


# ---- links ---------------------------------------------------------------------------------


class LinkAccount(_Body):
    account_id: int
    external_ref: str | None = None
    dry_run: bool = False


@router.post("/instances/{instance_id}/links")
def link_account(instance_id: int, body: LinkAccount, user: CurrentUser, engine: EngineDep) -> Any:
    ref = body.external_ref if body.external_ref is not None else f"acct-{body.account_id}"
    return to_json(inst.link_account(engine, instance_id, body.account_id, ref, dry_run=body.dry_run))


@router.delete("/instances/{instance_id}/links/{account_id}")
def unlink_account(instance_id: int, account_id: int, user: CurrentUser, engine: EngineDep) -> Any:
    return {"settle": to_json(inst.unlink_account(engine, instance_id, account_id))}
