"""Start sequence: the model is wired only when configured (architecture §5.4, §5.7)."""

from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.model.queue import ModelQueue, configure_model_queue, current_model_queue
from app.startup import attach_model, configure_model
from app.utils.config import Config, ModelConfig, Secret


def test_without_a_model_nothing_is_listed_and_no_worker_exists(isolated_db: Config, isolated_engine: Engine):
    configure_model_queue(ModelQueue(lambda entry: None))  # a leftover of an earlier start
    assert configure_model(replace(isolated_db, model=None), isolated_engine) is None
    assert current_model_queue() is None


def test_with_a_model_the_queue_the_worker_and_the_lifespan_are_wired(
    isolated_db: Config, isolated_engine: Engine
):
    config = replace(isolated_db, model=ModelConfig("http://model.test/v1", "m-1", Secret("k")))
    try:
        worker = configure_model(config, isolated_engine)
        assert worker is not None and current_model_queue() is worker.queue
        app = FastAPI()
        attach_model(app, worker)
        assert app.state.model is worker.queue
        with TestClient(app):  # the lifespan starts the worker and stops it
            assert worker._task is not None and not worker._task.done()
        assert worker._task is None
    finally:
        configure_model_queue(None)
