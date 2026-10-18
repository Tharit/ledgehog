"""The wire models of the sync operations (architecture §4.1, §4.2, §4.3): the plan, the start answer,
the task status with a discovery's result, and the payload of each of the nine stream events.

The events are plain mappings inside the task (it knows no web framework); these models describe them
for the schema, so the client's types come from the server and not from a copy. They are not used to
serialise a stream: a frame is the stored payload as JSON.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.api.openapi import register_schema

SinceSource = Literal["coverage", "latest_entry", "importer_default"]
ItemKind = Literal["transactions", "documents"]
TaskKind = Literal["sync", "discovery"]
Outcome = Literal["completed", "aborted", "abandoned", "crashed"]
PromptOutcome = Literal["answered", "confirmed", "cancelled", "expired", "aborted"]


# ---- the plan and the start ----------------------------------------------------------------


class PlanAccountOut(BaseModel):
    account_id: int
    external_ref: str
    since: date  # where the fetch would start now
    since_source: SinceSource
    editable: bool  # exactly where the account has no coverage


class PlanInstanceOut(BaseModel):
    instance_id: int
    importer: str
    label: str
    busy: bool  # another task holds the instance
    accounts: list[PlanAccountOut]
    documents_since: date | None  # null: the instance delivers no documents


class StartedSync(BaseModel):
    task_id: str
    busy: list[int]  # instances left out because another task holds them


class StartedDiscovery(BaseModel):
    task_id: str


# ---- the status and a discovery's result ---------------------------------------------------


class DiscoveredAccountOut(BaseModel):
    external_ref: str
    name: str
    currency: str | None
    kind_hint: str | None
    capabilities: list[Literal["transactions", "balance"]]  # empty: nothing fetchable


class AccountMatchOut(BaseModel):
    id: int
    closed: bool  # a closed account is not offered


class DiscoveryEntryOut(BaseModel):
    account: DiscoveredAccountOut
    linked_account_id: int | None  # already linked to this instance under this reference
    matches_account: AccountMatchOut | None  # not linked, but an account holds this reference


class DiscoveryResultOut(BaseModel):
    instance_id: int
    accounts: list[DiscoveryEntryOut]


class TaskStatusOut(BaseModel):
    task_id: str
    kind: TaskKind
    status: Literal["running", "ended"]
    aborting: bool
    outcome: Outcome | None
    last_event_id: int  # 0 before the first event
    result: DiscoveryResultOut | None  # an ended discovery's accounts; null otherwise


# ---- the events (the payload of each frame's `data`) ---------------------------------------


class TaskStartedItem(BaseModel):
    account_id: int | None
    kind: ItemKind


class TaskStartedInstance(BaseModel):
    instance_id: int
    items: list[TaskStartedItem]  # a discovery's instance has none


class TaskStartedEvent(BaseModel):
    kind: TaskKind
    instances: list[TaskStartedInstance]


class InstanceStartedEvent(BaseModel):
    instance_id: int


class RunStartedEvent(BaseModel):
    run_id: int
    instance_id: int
    account_id: int | None  # null for documents
    kind: ItemKind
    since: date


class PromptResolvedEvent(BaseModel):
    prompt_id: str
    outcome: PromptOutcome


class SecretPromptBody(BaseModel):
    kind: Literal["secret"]
    subject: str  # a key the client maps to its own label


class TanPromptBody(BaseModel):
    kind: Literal["tan"]
    medium: Literal["text", "image", "decoupled"]
    challenge: str
    method: str | None
    image_mime: str | None = None  # an image challenge only
    image_b64: str | None = None


class PromptOption(BaseModel):
    id: str
    label: str


class ChoicePromptBody(BaseModel):
    kind: Literal["choice"]
    subject: str
    options: list[PromptOption]


class TextPromptBody(BaseModel):
    kind: Literal["text"]
    subject: str


PromptBody = Annotated[
    SecretPromptBody | TanPromptBody | ChoicePromptBody | TextPromptBody, Field(discriminator="kind")
]


class PromptEvent(BaseModel):
    prompt_id: str
    instance_id: int
    run_id: int | None  # null while signing in
    expires_at: datetime
    prompt: PromptBody | None = None  # absent from the replay once the prompt is resolved


class RunFinishedEvent(BaseModel):
    run_id: int
    instance_id: int
    account_id: int | None
    kind: ItemKind
    stats: dict[str, Any]  # the run's stored statistics, as GET /api/importers/runs/{id} returns them


class RunFailedEvent(BaseModel):
    run_id: int
    instance_id: int
    account_id: int | None
    kind: ItemKind
    code: str
    message: str
    retryable: bool


class InstanceFailedEvent(BaseModel):
    instance_id: int
    code: str
    message: str
    retryable: bool
    run_ids: list[int]  # the runs it ended failed; none for a discovery


class TaskEndedEvent(BaseModel):
    outcome: Outcome
    ok: int
    failed: int
    not_started: list[int]  # the instances never reached


class SyncEventPayloads(BaseModel):
    """Not a body: the nine events of `GET /api/sync/tasks/{id}/events`, by name. A frame's `event:` is a
    key of this object and its `data:` is the JSON of that key's value."""

    task_started: TaskStartedEvent
    instance_started: InstanceStartedEvent
    run_started: RunStartedEvent
    prompt: PromptEvent
    prompt_resolved: PromptResolvedEvent
    run_finished: RunFinishedEvent
    run_failed: RunFailedEvent
    instance_failed: InstanceFailedEvent
    task_ended: TaskEndedEvent


register_schema(SyncEventPayloads)
