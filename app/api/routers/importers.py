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
from email.message import Message
from email.parser import BytesHeaderParser
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import ApiError, map_error
from app.api.session import CurrentUser, EngineDep
from app.core.accounts import AccountMissing
from app.core.domain.errors import ContractViolation
from app.core.importers import instances as inst
from app.core.importers import upload as up
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
from app.utils import clock

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
map_error(up.NotAFileSource, 409, "not_a_file_source")
map_error(up.AccountClosed, 409, "account_closed")
map_error(up.AccountNotLinked, 409, "account_not_linked")
map_error(ContractViolation, 422, "contract_violation", details=lambda exc: {"rule": exc.rule})
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


# ---- upload --------------------------------------------------------------------------------

MAX_FILE_BYTES = 10 * 1024 * 1024
_FORM_SLACK = 64 * 1024  # what the other form fields and the multipart framing may add
_FIELDS = frozenset({"file", "account_id", "dry_run"})


def _too_large() -> ApiError:
    return ApiError(
        413, "file_too_large", f"the file is larger than the limit of {MAX_FILE_BYTES} bytes (10 MiB)"
    )


async def _read_body(request: Request) -> bytes:
    """The request body, read with a cap: an oversized upload is refused as it streams in."""
    cap = MAX_FILE_BYTES + _FORM_SLACK
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise _too_large()
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _invalid(field: str, message: str, kind: str = "value_error") -> ApiError:
    detail = [{"location": ["body", field], "message": message, "type": kind}]
    return ApiError(422, "validation_error", "The request is not valid.", detail)


def _form_parts(content_type: str, body: bytes) -> dict[str, tuple[bytes, str | None]]:
    """The parts of a multipart/form-data body: field name -> (bytes, filename).

    The standard library only: no form-parsing dependency is needed for three fields.
    """
    head = Message()
    head["content-type"] = content_type
    boundary = head.get_param("boundary")
    if head.get_content_type() != "multipart/form-data" or not isinstance(boundary, str) or not boundary:
        raise _invalid("body", "send the upload as multipart/form-data", "type_error")
    parts: dict[str, tuple[bytes, str | None]] = {}
    delimiter = b"--" + boundary.encode()
    for piece in body.split(delimiter)[1:]:
        if piece.startswith(b"--"):  # the closing delimiter
            break
        piece = piece.removeprefix(b"\r\n").removesuffix(b"\r\n")
        raw_head, sep, content = piece.partition(b"\r\n\r\n")
        if not sep:
            raise _invalid("body", "malformed multipart body", "type_error")
        headers = BytesHeaderParser().parsebytes(raw_head)
        name = headers.get_param("name", header="content-disposition")
        if not isinstance(name, str) or not name:
            raise _invalid("body", "a form part has no name", "type_error")
        if name in parts:
            raise _invalid(name, "given twice", "value_error")
        filename = headers.get_filename()
        parts[name] = (content, filename)
    return parts


def _flag(value: str) -> bool:
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0", ""):
        return False
    raise _invalid("dry_run", "must be true or false", "bool_parsing")


@router.post("/instances/{instance_id}/upload")
def upload_file(
    instance_id: int,
    request: Request,
    user: CurrentUser,
    engine: EngineDep,
    raw: Annotated[bytes, Depends(_read_body)],
) -> Any:
    """Upload one export for one linked account. `dry_run` parses and previews, writes nothing."""
    parts = _form_parts(request.headers.get("content-type", ""), raw)
    for name in parts:
        if name not in _FIELDS:
            raise _invalid(name, "unknown field", "extra_forbidden")
    if "file" not in parts:
        raise _invalid("file", "the export file is required", "missing")
    if "account_id" not in parts:
        raise _invalid("account_id", "required", "missing")
    data = parts["file"][0]
    if len(data) > MAX_FILE_BYTES:
        raise _too_large()
    try:
        account_id = int(parts["account_id"][0].decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise _invalid("account_id", "must be an integer", "int_parsing") from None
    dry_run = _flag(parts["dry_run"][0].decode("ascii", "replace")) if "dry_run" in parts else False

    importer = importer_for(request, _view(engine, instance_id).importer)
    result = up.upload(
        engine,
        instance_id=instance_id,
        account_id=account_id,
        data=data,
        importer=importer,
        user_id=user.id,
        today=clock.today(request.app.state.config.timezone),
        dry_run=dry_run,
    )
    return to_json(result)
