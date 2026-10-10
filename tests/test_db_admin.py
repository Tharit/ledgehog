import uuid
from datetime import timedelta

import pytest

from app.utils import clock
from app.utils.config import Config
from app.utils.db import admin


def _names(cfg: Config) -> set[str]:
    return {d.name for d in admin.list_databases(cfg)}


@pytest.fixture
def scratch(admin_cfg: Config):
    made: list[str] = []

    def make(prefix: str = "test_") -> str:
        name = f"{prefix}{uuid.uuid4().hex}"
        made.append(name)
        admin.create_database(admin_cfg, name)
        return name

    yield make
    for n in made:
        admin.drop_database(admin_cfg, n)


def test_create_and_drop(admin_cfg: Config):
    name = f"test_{uuid.uuid4().hex}"
    admin.create_database(admin_cfg, name)
    assert name in _names(admin_cfg)
    admin.drop_database(admin_cfg, name)
    assert name not in _names(admin_cfg)


def test_drop_is_idempotent_and_forces_open_connections(admin_cfg: Config, scratch):
    name = scratch()
    held = admin.connect(admin_cfg.with_database(name))
    admin.drop_database(admin_cfg, name)
    admin.drop_database(admin_cfg, name)
    assert name not in _names(admin_cfg)
    held.close()


def test_refuses_names_outside_the_disposable_prefixes(admin_cfg: Config):
    for bad in ("ledgehog", "postgres", "test_x; DROP DATABASE postgres", "TEST_x", "prod_1"):
        with pytest.raises(ValueError):
            admin.create_database(admin_cfg, bad)
        with pytest.raises(ValueError):
            admin.drop_database(admin_cfg, bad)


def test_template_clone_carries_template_contents(admin_cfg: Config, scratch):
    src = scratch()
    with admin.connect(admin_cfg.with_database(src)) as c:
        c.execute("CREATE TABLE marker (x int)")
    clone = f"test_{uuid.uuid4().hex}"
    try:
        admin.create_database(admin_cfg, clone, template=src)
        with admin.connect(admin_cfg.with_database(clone)) as c:
            assert c.execute("SELECT to_regclass('marker')").fetchone() == ("marker",)
    finally:
        admin.drop_database(admin_cfg, clone)


def test_created_databases_record_their_age(admin_cfg: Config, scratch):
    name = scratch()
    info = {d.name: d for d in admin.list_databases(admin_cfg)}[name]
    assert info.created_at is not None
    assert abs(clock.now() - info.created_at) < timedelta(minutes=5)


def test_sweep_drops_old_disposable_databases_only(admin_cfg: Config, scratch):
    old, fresh, dev = scratch(), scratch(), scratch("dev_")
    with clock.frozen(clock.now() - timedelta(days=2)):
        stale = scratch()
    # `old` is created now; make it look two days old by re-stamping its comment
    admin.stamp(admin_cfg, old, clock.now() - timedelta(days=2))
    dropped = admin.sweep(admin_cfg, older_than=timedelta(days=1))
    assert {old, stale} <= set(dropped)
    assert fresh not in dropped
    names = _names(admin_cfg)
    assert old not in names and stale not in names
    assert fresh in names and dev in names


def test_sweep_dry_run_drops_nothing_and_skips_unprefixed(admin_cfg: Config, scratch):
    name = scratch()
    would = admin.sweep(admin_cfg, older_than=timedelta(days=-1), dry_run=True)
    assert name in would
    assert "postgres" not in would and admin_cfg.db.name not in would
    assert name in _names(admin_cfg)
