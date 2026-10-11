"""A template that is in use is never old enough to be swept.

The sweeper drops `tpl_` databases older than a day, and the template is built once per
migration chain and reused across runs. Without a refresh, the first session started a
day after the template was built would find it swept by the sweeper's own test (or by a
concurrent sweep) and fail with "template database not found". Each session therefore
re-stamps the template it is about to use.
"""

from __future__ import annotations

from datetime import timedelta

from app.utils import clock
from app.utils.config import Config
from app.utils.db import admin
from tests.conftest import ensure_template


def _created(cfg: Config, name: str):
    return {d.name: d for d in admin.list_databases(cfg)}[name].created_at


def test_a_session_refreshes_an_old_templates_stamp(admin_cfg: Config, template_db: str) -> None:
    admin.stamp(admin_cfg, template_db, clock.now() - timedelta(days=3))
    assert template_db in admin.sweep(admin_cfg, older_than=timedelta(days=1), dry_run=True)

    assert ensure_template(admin_cfg) == template_db  # what a session does at start

    assert clock.now() - _created(admin_cfg, template_db) < timedelta(minutes=5)
    assert template_db not in admin.sweep(admin_cfg, older_than=timedelta(days=1), dry_run=True)
