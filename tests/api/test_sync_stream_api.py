"""The event stream (architecture §4.2): framing, replay and resume against a finished task, the payload
models against real events, and, once, live streaming and the keepalive against the app served on a real
port (the in-process client buffers a response until it ends, so it cannot see a stream live)."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from pydantic import TypeAdapter

from app.api import create_app
from app.api.sync_models import SyncEventPayloads
from app.core.tasks import TaskRegistry
from app.plugins.importers.csv import CsvImporter
from app.plugins.importers.testfetch import TestFetchImporter
from tests.api import sync_helpers as h
from tests.api.conftest import PASSWORDS
from tests.api.sync_helpers import PIN, TUNING, WAIT, Sync, acct, error_of

sync = h.sync  # fixtures shared by the sync API tests
make_sync = h.make_sync


def finished_task(sync: Sync) -> str:
    sync.world(refs=("A1", "A2"))
    task = sync.started()
    sync.wait_ended(task)
    return task


# ---- framing and replay of a finished task ----------------------------------------------------


def test_the_stream_of_a_finished_task_is_framed_replayed_from_one_and_closes(sync: Sync):
    task = finished_task(sync)
    r = sync.client.get(f"/api/sync/tasks/{task}/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.text.startswith("retry: 3000\n\n")  # the first bytes
    blocks = [b for b in r.text.split("\n\n") if b][1:]
    frames = []
    for block in blocks:
        id_line, event_line, data_line = block.split("\n")  # exactly these three, in this order
        assert (
            id_line.startswith("id: ") and event_line.startswith("event: ") and data_line.startswith("data: ")
        )
        frames.append((int(id_line[4:]), event_line[7:], json.loads(data_line[6:])))
    assert [f[0] for f in frames] == list(range(1, len(frames) + 1))  # 1, 2, 3, ...
    names = [f[1] for f in frames]
    assert names[0] == "task_started" and names[-1] == "task_ended"  # closed after task_ended
    assert names.count("task_ended") == 1
    assert names.count("run_started") == names.count("run_finished") == 2
    assert len(frames) == sync.status(task)["last_event_id"]


def test_last_event_id_resumes_after_it(sync: Sync):
    task = finished_task(sync)
    everything = sync.events(task)
    assert len(everything) >= 6
    for cut in (1, 3, len(everything) - 1):
        assert sync.events(task, last_id=cut) == everything[cut:]
    r = sync.client.get(f"/api/sync/tasks/{task}/events", headers={"Last-Event-ID": str(len(everything))})
    assert r.status_code == 200 and r.text == "retry: 3000\n\n"  # nothing more will come: closed at once


def test_a_last_event_id_that_is_not_a_number_replays_everything(sync: Sync):
    task = finished_task(sync)
    everything = sync.events(task)
    for junk in ("abc", "-4", "", "1.5"):
        r = sync.client.get(f"/api/sync/tasks/{task}/events", headers={"Last-Event-ID": junk})
        assert r.status_code == 200 and r.text.count("event: ") == len(everything), junk


def test_a_resolved_prompt_is_replayed_without_its_body(sync: Sync):
    sync.world({"open": [PIN]})
    task = sync.started()
    prompt = sync.open_prompt(task)
    assert "prompt" in prompt
    assert sync.answer(task, prompt["prompt_id"], "1234").status_code == 204
    sync.wait_ended(task)
    (replayed,) = [f for f in sync.events(task) if f.event == "prompt"]
    assert replayed.data["prompt_id"] == prompt["prompt_id"] and "prompt" not in replayed.data
    assert set(replayed.data) == {"prompt_id", "instance_id", "run_id", "expires_at"}


def test_run_finished_carries_the_stored_statistics_with_their_currency(sync: Sync):
    inst, (a1,) = sync.world()
    task = sync.started()
    sync.wait_ended(task)
    (done,) = [f for f in sync.events(task) if f.event == "run_finished"]
    run = sync.client.get(f"/api/importers/runs/{done.data['run_id']}").json()
    assert done.data["stats"] == run["stats"]  # the object the run's own endpoint returns
    assert (
        done.data["stats"]["inserted"] == 11
        and done.data["stats"]["unexplained_difference"]["currency"] == "EUR"
    )
    assert (done.data["instance_id"], done.data["account_id"], done.data["kind"]) == (
        inst,
        a1,
        "transactions",
    )


# ---- the payload models describe the real events -------------------------------------------------


def test_every_event_name_validates_against_its_declared_model(sync: Sync):
    """One task that emits all nine events, each checked against the model the schema publishes."""
    steps = [
        PIN,
        {"ask": "tan", "medium": "text", "expect": "111"},
        {"ask": "tan", "medium": "image", "expect": "222"},
        {"ask": "choice", "subject": "tan_medium", "options": [{"id": "a", "label": "A"}]},
        {"ask": "text", "subject": "tan_medium_name"},
        {"ask": "tan", "medium": "decoupled", "polls": 1},
    ]
    bad = sync.instance(
        {"accounts": [acct("B1", fetch=[{"raise": "parse_failed"}]), acct("B2")]}, label="Item fails"
    )
    for ref in ("B1", "B2"):
        sync.link(bad, sync.account(ref), ref)
    down = sync.instance({"accounts": [acct("C1")], "open": [{"raise": "source_unavailable"}]}, label="Down")
    sync.link(down, sync.account("C1"), "C1")
    full = sync.instance({"accounts": [acct("A1")], "open": steps}, label="Prompts")
    sync.link(full, sync.account("A1"), "A1")
    task = sync.started()
    answers = {"secret": "1234", "choice": "a", "text": "Push"}
    seen_kinds = []
    for _ in range(5):  # the decoupled one is confirmed by the bank, never answered
        event = sync.open_prompt(task)
        body = event["prompt"]
        seen_kinds.append((body["kind"], body.get("medium")))
        value = answers.get(body["kind"], "111" if body.get("medium") == "text" else "222")
        assert sync.answer(task, event["prompt_id"], value).status_code == 204
    sync.wait_ended(task)
    assert seen_kinds == [
        ("secret", None),
        ("tan", "text"),
        ("tan", "image"),
        ("choice", None),
        ("text", None),
    ]
    frames = sync.events(task)
    assert {f.event for f in frames} == set(SyncEventPayloads.model_fields)  # all nine
    for f in frames:
        model = SyncEventPayloads.model_fields[f.event].annotation
        TypeAdapter(model).validate_python(f.data, strict=False)


# ---- live: a real port ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def live(sync: Sync, api_config, api_engine) -> Iterator[tuple[str, TaskRegistry]]:
    """The app served by uvicorn on a free port, with its own task registry (its keepalive is 0.2 s)."""
    registry = TaskRegistry(TUNING)
    app = create_app(
        api_config,
        api_engine,
        importers={"csv": CsvImporter(), "testfetch": TestFetchImporter()},
        tasks=registry,
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + WAIT
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "the server did not start"
    yield f"http://127.0.0.1:{port}", registry
    for task in list(registry._tasks.values()):
        task.abort()
    server.should_exit = True
    thread.join(WAIT)


def test_live_streaming_a_prompt_arrives_mid_stream_and_is_answered_through_input(
    sync: Sync, live: tuple[str, TaskRegistry]
):
    base, registry = live
    sync.world({"open": [PIN]})  # the data is in the shared database; the task runs in the served app
    with httpx.Client(base_url=base, timeout=WAIT) as http:
        r = http.post("/api/login", json={"login": "anna", "password": PASSWORDS["anna"]})
        assert r.status_code == 200
        started = http.post("/api/sync")
        assert started.status_code == 202, started.text
        task = started.json()["task_id"]
        anna = sync.user_id("anna")

        frames: list[tuple[str, dict]] = []
        pending: dict[str, str] = {}
        t0 = time.monotonic()
        with http.stream("GET", f"/api/sync/tasks/{task}/events") as stream:
            assert stream.status_code == 200
            lines = stream.iter_lines()
            assert next(lines) == "retry: 3000"
            answered = False
            keepalive_seen = False
            for line in lines:
                if time.monotonic() - t0 > WAIT * 2:
                    raise AssertionError("the stream did not finish")
                if line.startswith(("id: ", "event: ")):
                    pending[line.split(":")[0]] = line.split(": ", 1)[1]
                elif line.startswith("data: "):
                    frames.append((pending["event"], json.loads(line[6:])))
                    if pending["event"] == "prompt" and not answered:
                        # a stream is attached now, and the task is blocked on this prompt
                        live_task = registry.get(task, anna)
                        assert live_task is not None and live_task.attached == 1
                        # idle: a keepalive comes before anything else does
                        for idle in lines:
                            if idle == ": keepalive":
                                keepalive_seen = True
                                break
                            assert idle == "", idle  # only the blank line ending a frame
                        answer = http.post(
                            f"/api/sync/tasks/{task}/input",
                            json={"prompt_id": frames[-1][1]["prompt_id"], "value": "1234"},
                        )
                        assert answer.status_code == 204, answer.text
                        answered = True
            assert answered and keepalive_seen
        names = [name for name, _ in frames]
        assert names[:3] == ["task_started", "instance_started", "prompt"]
        assert names.index("prompt_resolved") > names.index("prompt")
        assert dict(frames[names.index("prompt_resolved")][1])["outcome"] == "answered"
        assert names[-1] == "task_ended" and "run_finished" in names
        # the stream closed by itself after task_ended, and detached
        deadline = time.monotonic() + WAIT
        finished = registry.get(task, anna)
        assert finished is not None
        while finished.attached and time.monotonic() < deadline:
            time.sleep(0.02)
        assert finished.attached == 0
        # the same task over the stream again: the replay, with the prompt's body gone
        replay = http.get(f"/api/sync/tasks/{task}/events")
        assert replay.status_code == 200 and replay.text.count("event: ") == len(frames)
        error_of(http.get("/api/sync/tasks/unknown/events"), 404, "not_found")
