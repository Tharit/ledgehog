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
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from sqlalchemy import Engine, text

from app.api.errors import ApiError, map_error
from app.api.ids import MAX_ID, EntityId, PathId
from app.api.openapi import ErrorEnvelope
from app.api.session import CurrentUser, EngineDep
from app.core.accounts import AccountMissing
from app.core.domain.errors import ContractViolation
from app.core.importers import catalog as cat
from app.core.importers import instances as inst
from app.core.importers import upload as up
from app.core.importers.instances import InstanceView
from app.core.plugins.errors import (
    AccountUnsupported,
    AuthRejected,
    BankSetupRequired,
    ChallengeAbandoned,
    ChallengeExpired,
    ImporterError,
    InvalidProfile,
    NotRegistered,
    ParseFailed,
    SourceUnavailable,
)
from app.core.plugins.importer import FileImporter
from app.core.tasks import InstanceBusy
from app.utils import clock

router = APIRouter(prefix="/api/importers")

# ---- serialisation -------------------------------------------------------------------------


_AMOUNT_KEYS = frozenset({"amount", "balance", "before", "after"})


def _holds_amount(obj: Mapping[str, Any]) -> bool:
    # a before/after pair counts even when both are null (no difference), so its shape is stable
    if {"before", "after"} <= obj.keys() and all(
        obj[k] is None or isinstance(obj[k], int) for k in ("before", "after")
    ):
        return True
    return any(
        (k.endswith("_minor") or k in _AMOUNT_KEYS) and isinstance(v, int) and not isinstance(v, bool)
        for k, v in obj.items()
    )


def to_json(value: Any, *, currency: str | None = None, currencies: Mapping[int, str] | None = None) -> Any:
    """A JSON-ready copy of a result tree: dataclasses become objects (field names as keys),
    dates ISO strings, tuples lists, integer-keyed mappings string-keyed.

    Money rule (architecture §4.5, an amount never travels without its currency): amounts keep
    their integer minor units and their names, and every object that holds one (`amount`,
    `balance`, `before`, `after` as an integer, or any `*_minor` field) gets a `currency` field
    next to it. The currency is `currency`, or, below an object with an `account_id`, that
    account's from `currencies`; an object that already has its own `currency` keeps it.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        scope = currency
        owner = getattr(value, "account_id", None)
        if currencies is not None and isinstance(owner, int) and owner in currencies:
            scope = currencies[owner]
        out = {
            f.name: to_json(getattr(value, f.name), currency=scope, currencies=currencies)
            for f in dataclasses.fields(value)
        }
        return _stamped(out, scope)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        out = {str(k): to_json(v, currency=currency, currencies=currencies) for k, v in value.items()}
        return _stamped(out, currency)
    if isinstance(value, list | tuple | set | frozenset):
        return [to_json(v, currency=currency, currencies=currencies) for v in value]
    return value


def _stamped(obj: dict[str, Any], currency: str | None) -> dict[str, Any]:
    if currency is not None and "currency" not in obj and _holds_amount(obj):
        obj["currency"] = currency
    return obj


def account_currencies(engine: Engine) -> dict[int, str]:
    """Every account's currency (household scale: one small query), to stamp amounts with."""
    with engine.connect() as conn:
        return {int(r.id): str(r.currency) for r in conn.execute(text("SELECT id, currency FROM account"))}


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
map_error(inst.InstanceForbidden, 403, "forbidden")
map_error(inst.InvalidInstance, 422, "invalid_instance")
map_error(inst.InstanceHasRuns, 409, "instance_has_runs")
map_error(inst.InstanceDisabled, 409, "instance_disabled")
map_error(inst.NotAnAccountSource, 409, "not_an_account_source")
map_error(inst.AccountClosed, 409, "account_closed")
map_error(inst.ExternalRefTaken, 409, "external_ref_taken")
map_error(inst.AlreadyLinked, 409, "already_linked")
map_error(
    inst.ClearanceAccount,
    409,
    "conflict",
    details=lambda e: {"reason": "clearance_account", "account_id": e.account_id},
)
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
map_error(BankSetupRequired, 422, "bank_setup_required", details=_importer_details)
map_error(AccountUnsupported, 422, "account_unsupported", details=_importer_details)


def importer_for(request: Request, name: str) -> FileImporter:
    """The registered implementation of importer `name`, or 422 `importer_not_available`."""
    found: FileImporter | None = request.app.state.importers.get(name)
    if found is None:
        raise ApiError(
            422, "importer_not_available", f"importer {name!r} is not available in this deployment"
        )
    return found


# ---- the catalog ---------------------------------------------------------------------------


class CatalogEntryOut(BaseModel):
    name: str
    kind: Literal["file", "fetch"]
    emits: list[Literal["transactions", "documents", "rates"]]
    presets: dict[str, dict[str, Any]]  # preset name -> the settings it fills; empty for most importers


@router.get("")
def list_catalog(request: Request, user: CurrentUser) -> list[CatalogEntryOut]:
    """The importers this deployment registers: what a new instance can be made from."""
    entries = cat.catalog(request.app.state.importers)
    return [
        CatalogEntryOut(
            name=e.name,
            kind=e.kind,
            emits=list(e.emits),  # type: ignore[arg-type]
            presets={k: dict(v) for k, v in e.presets.items()},
        )
        for e in entries
    ]


# ---- instances -----------------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateInstance(_Body):
    importer: str = Field(min_length=1)
    label: str
    settings: dict[str, Any]
    # a fetch importer holds a login: owned by the creator, or shared; a file importer takes none
    access: Literal["owner", "shared"] | None = None


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


def _out(view: InstanceView, user_id: int) -> dict[str, Any]:
    """The instance as read: everything of it (the other user reads settings too, spec §5.11), plus
    `manageable`, whether this user may change or run it, so a client need not repeat the rule."""
    out: dict[str, Any] = to_json(view)
    out["manageable"] = inst.may_manage(view, user_id)
    return out


@router.get("/instances")
def list_instances(user: CurrentUser, engine: EngineDep) -> list[Any]:
    with engine.connect() as conn:
        return [_out(v, user.id) for v in inst.list_instances(conn)]


@router.post("/instances", status_code=201)
def create_instance(body: CreateInstance, request: Request, user: CurrentUser, engine: EngineDep) -> Any:
    importer = importer_for(request, body.importer)
    entry = cat.describe(body.importer, importer)  # what it emits is the catalog's to say, not the client's
    if entry.kind == "file":  # no credential: its profile is shared by the household
        if body.access is not None:
            raise _invalid("access", "a file importer holds no login: it is always shared", "extra_forbidden")
        access = "shared"
    else:
        access = body.access or "owner"
    new_id = inst.create_instance(
        engine,
        importer=body.importer,
        label=body.label,
        settings=body.settings,
        emits=list(entry.emits),
        access=access,
        owner_id=user.id if access == "owner" else None,
        validate=importer.validate_settings,
    )
    return _out(_view(engine, new_id), user.id)


@router.put("/instances/{instance_id}")
def update_instance(
    instance_id: PathId, body: UpdateInstance, request: Request, user: CurrentUser, engine: EngineDep
) -> Any:
    inst.require_manager(engine, instance_id, user.id)
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
    return _out(_view(engine, instance_id), user.id)


@router.post("/instances/{instance_id}/reset")
def reset_instance(instance_id: PathId, request: Request, user: CurrentUser, engine: EngineDep) -> Any:
    inst.require_manager(engine, instance_id, user.id)
    if request.app.state.tasks.is_held(instance_id):  # a running job would write its state back over it
        raise InstanceBusy([instance_id])
    inst.reset_instance(engine, instance_id)
    return _out(_view(engine, instance_id), user.id)


@router.delete("/instances/{instance_id}")
def delete_instance(instance_id: PathId, user: CurrentUser, engine: EngineDep) -> Any:
    inst.require_manager(engine, instance_id, user.id)
    return {"settle": to_json(inst.delete_instance(engine, instance_id))}


# ---- links ---------------------------------------------------------------------------------


class LinkAccount(_Body):
    account_id: EntityId
    external_ref: str | None = None
    dry_run: bool = False


@router.post("/instances/{instance_id}/links")
def link_account(
    instance_id: PathId, body: LinkAccount, request: Request, user: CurrentUser, engine: EngineDep
) -> Any:
    # A file importer has no login: the reference is `acct-<account id>`, read by nothing, so a
    # client does not give one. A fetch importer's reference is its account at the login: required.
    inst.require_manager(engine, instance_id, user.id)
    importer = request.app.state.importers.get(_view(engine, instance_id).importer)
    if isinstance(importer, FileImporter):
        if body.external_ref is not None:
            raise _invalid("external_ref", "a file importer takes no reference")
        ref = f"acct-{body.account_id}"
    elif body.external_ref is None:
        raise _invalid("external_ref", "required", "missing")
    else:
        ref = body.external_ref
    return to_json(inst.link_account(engine, instance_id, body.account_id, ref, dry_run=body.dry_run))


@router.delete("/instances/{instance_id}/links/{account_id}")
def unlink_account(instance_id: PathId, account_id: PathId, user: CurrentUser, engine: EngineDep) -> Any:
    inst.require_manager(engine, instance_id, user.id)
    return {"settle": to_json(inst.unlink_account(engine, instance_id, account_id))}


# ---- upload --------------------------------------------------------------------------------

MAX_FILE_BYTES = 10 * 1024 * 1024
_FORM_SLACK = 64 * 1024  # what the other form fields and the multipart framing may add
_FIELDS = frozenset({"file", "account_id", "dry_run"})


def _too_large() -> ApiError:
    return ApiError(
        413, "file_too_large", f"the file is larger than the limit of {MAX_FILE_BYTES} bytes (10 MiB)"
    )


def _invalid(field: str, message: str, kind: str = "value_error") -> ApiError:
    detail = [{"location": ["body", field], "message": message, "type": kind}]
    return ApiError(422, "validation_error", "The request is not valid.", detail)


class _Form:
    """Collects the parts of a multipart/form-data body as the library's parser streams them."""

    def __init__(self) -> None:
        self.parts: dict[str, tuple[bytearray, str | None]] = {}
        self.closed = False
        self._head = bytearray()
        self._field = bytearray()
        self._value = bytearray()
        self._data: bytearray | None = None

    # the parser's callbacks, in the order it calls them for each part
    def on_part_begin(self) -> None:
        self._head.clear()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._value += data[start:end]

    def on_header_end(self) -> None:
        self._head += bytes(self._field) + b": " + bytes(self._value) + b"\r\n"
        self._field.clear()
        self._value.clear()

    def on_headers_finished(self) -> None:
        headers = BytesHeaderParser().parsebytes(bytes(self._head))
        name = headers.get_param("name", header="content-disposition")
        if not isinstance(name, str) or not name:
            raise _invalid("body", "a form part has no name", "type_error")
        if name in self.parts:
            raise _invalid(name, "given twice", "value_error")
        self._data = bytearray()
        self.parts[name] = (self._data, headers.get_filename())

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        assert self._data is not None
        self._data += data[start:end]
        if len(self._data) > MAX_FILE_BYTES:  # no field is larger than the file may be
            raise _too_large()

    def on_end(self) -> None:
        self.closed = True


def _boundary(content_type: str) -> str:
    head = Message()
    head["content-type"] = content_type
    boundary = head.get_param("boundary")
    if head.get_content_type() != "multipart/form-data" or not isinstance(boundary, str) or not boundary:
        raise _invalid("body", "send the upload as multipart/form-data", "type_error")
    return boundary


async def _read_form(request: Request) -> dict[str, tuple[bytes, str | None]]:
    """The parts of the upload, parsed as the body streams in (RFC 2046, `python-multipart`).

    An oversized upload is refused as it streams in: by its Content-Length at once, otherwise
    when the bytes received pass the cap. Nothing is spooled past it.
    """
    try:
        boundary = _boundary(request.headers.get("content-type", ""))
    except ApiError:
        return {}  # the route answers it, after the path was validated
    cap = MAX_FILE_BYTES + _FORM_SLACK
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise _too_large()
    form = _Form()
    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": form.on_part_begin,
            "on_header_field": form.on_header_field,
            "on_header_value": form.on_header_value,
            "on_header_end": form.on_header_end,
            "on_headers_finished": form.on_headers_finished,
            "on_part_data": form.on_part_data,
            "on_end": form.on_end,
        },
    )
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > cap:
                raise _too_large()
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError:
        raise _invalid("body", "malformed multipart body", "type_error") from None
    if not form.closed:  # a body cut off before its closing delimiter never completed
        raise _invalid("body", "malformed multipart body", "type_error")
    return {name: (bytes(data), filename) for name, (data, filename) in form.parts.items()}


def _flag(value: str) -> bool:
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0", ""):
        return False
    raise _invalid("dry_run", "must be true or false", "bool_parsing")


# The body is parsed by hand (`_read_form`), so FastAPI sees none: the schema is declared here.
_UPLOAD_BODY: dict[str, Any] = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "account_id": {"type": "integer"},
                    "dry_run": {"type": "boolean", "default": False},
                },
                "required": ["file", "account_id"],
                "additionalProperties": False,
            }
        }
    },
}
_UPLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    # the result tree is serialised dynamically (`to_json`), so it is described as an object
    200: {
        "description": "The upload result (a dry run previews, a real upload also reports the run).",
        "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}},
    },
    401: {"model": ErrorEnvelope, "description": "Not signed in."},
    404: {"model": ErrorEnvelope, "description": "No such instance or account."},
    409: {"model": ErrorEnvelope, "description": "Not a file source, account closed or not linked."},
    413: {"model": ErrorEnvelope, "description": "The file is larger than 10 MiB (`file_too_large`)."},
    422: {"model": ErrorEnvelope, "description": "The request or the file is not valid."},
    502: {"model": ErrorEnvelope, "description": "The source is unavailable."},
}


@router.post(
    "/instances/{instance_id}/upload",
    openapi_extra={"requestBody": _UPLOAD_BODY},
    responses=_UPLOAD_RESPONSES,
)
def upload_file(
    instance_id: PathId,
    request: Request,
    user: CurrentUser,
    engine: EngineDep,
    parts: Annotated[dict[str, tuple[bytes, str | None]], Depends(_read_form)],
) -> Any:
    """Upload one export for one linked account. `dry_run` parses and previews, writes nothing."""
    _boundary(request.headers.get("content-type", ""))  # not multipart: refused (`parts` is empty)
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
    if not 0 < account_id <= MAX_ID:
        raise _invalid("account_id", f"must be between 1 and {MAX_ID}", "value_error")
    dry_run = _flag(parts["dry_run"][0].decode("ascii", "replace")) if "dry_run" in parts else False

    importer = importer_for(request, _view(engine, instance_id).importer)
    currency = account_currencies(engine).get(account_id)
    try:
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
    except ParseFailed as exc:  # its report holds amounts: they leave with the account's currency
        details = {"retryable": exc.retryable, "report": to_json(exc.report, currency=currency)}
        raise ApiError(422, "parse_failed", str(exc), details) from exc
    return to_json(result, currency=currency)
