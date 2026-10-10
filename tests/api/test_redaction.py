from __future__ import annotations

import logging

import pytest

from app.api.redaction import REDACTED, RedactionFilter, install_redaction


@pytest.fixture
def logger_and_stream():
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger("test.redaction")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    yield logger, stream
    logger.handlers = []


def test_extra_fields_with_sensitive_keys_are_dropped(logger_and_stream):
    logger, stream = logger_and_stream
    logger.info("sync started", extra={"password": "hunter2", "tan": "123456", "account": 7})
    handler = logger.handlers[0]
    record = logger.makeRecord(
        "test.redaction", logging.INFO, "f", 1, "m", (), None, extra={"pin": "9999", "n": 1}
    )
    handler.handle(record)
    assert record.pin == REDACTED and record.n == 1


def test_dict_arguments_are_scrubbed_recursively(logger_and_stream):
    logger, stream = logger_and_stream
    logger.info(
        "payload %(body)s", {"body": {"login": "a", "password": "hunter2", "nested": {"token": "t0k"}}}
    )
    out = stream.getvalue()
    assert "hunter2" not in out and "t0k" not in out and "login" in out


def test_key_value_pairs_in_message_text_are_scrubbed(logger_and_stream):
    logger, stream = logger_and_stream
    logger.info('got password=hunter2 and {"api_key": "sk-123"} Cookie: ledgehog_session=abc')
    logger.info("fetched %s", "TAN=654321")
    out = stream.getvalue()
    for leaked in ("hunter2", "sk-123", "abc", "654321"):
        assert leaked not in out


def test_innocent_messages_are_untouched(logger_and_stream):
    logger, stream = logger_and_stream
    logger.info("users created: %s", "anna, ben")
    assert "users created: anna, ben" in stream.getvalue()


def test_install_is_idempotent_and_attaches_to_root_handlers():
    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    try:
        install_redaction()
        install_redaction()
        assert sum(isinstance(f, RedactionFilter) for f in handler.filters) == 1
    finally:
        root.removeHandler(handler)
