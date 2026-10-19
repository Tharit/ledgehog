"""Two logins on one account (spouses syncing a joint account in turns), real database, the FinTS
importer over a fake bank per login (spec §5.2: identity is scoped to the account, not the credential)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.accounts import create_account
from app.core.importers.instances import create_instance, link_account
from app.core.importers.plan import ItemRequest, JobPlan, plan_start
from app.core.tasks import JobEnv
from app.plugins.importers.fints import FintsImporter
from app.plugins.importers.fints.bank import Procedure
from tests.core.tasks.rig import Handle, Rig
from tests.plugins.importers.fints.fakebank import Dialog, FakeBank

CORPUS = Path(__file__).parent / "statements"
IBAN = "DE02120300000000202051"
DAY_ONE, DAY_TWO = date(2026, 11, 1), date(2026, 11, 2)


def statements(name: str) -> str:
    return (CORPUS / f"{name}.sta").read_text(encoding="latin-1")


@dataclass
class JointRig(Rig):
    """The task rig with the FinTS importer registered and two users, each with a login of their own."""

    banks: dict[str, FakeBank] = field(default_factory=dict)
    importers: dict[str, object] = field(default_factory=dict)
    ben_id: int = 0
    instances: dict[str, int] = field(default_factory=dict)
    account_id: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        with self.engine.begin() as conn:
            self.ben_id = int(
                conn.execute(
                    text(
                        "INSERT INTO app_user (login, pw_hash, display_name) VALUES ('ben', 'x', 'Ben')"
                        " RETURNING id"
                    )
                ).scalar_one()
            )
        self.importers = {
            "fints": FintsImporter("PID", "0.1.0", connect=lambda login: self.banks[login.user_id])
        }
        self.account_id = create_account(self.engine, name="Joint", kind="checking", currency="EUR")
        for login, owner in (("anna", self.user_id), ("ben", self.ben_id)):
            self.instances[login] = create_instance(
                self.engine,
                importer="fints",
                label=f"{login}'s login",
                settings={"url": "https://bank.invalid/fints", "bank_code": "12030000", "user_id": login},
                emits=["transactions"],
                access="owner",
                owner_id=owner,
            )
            link_account(self.engine, self.instances[login], self.account_id, IBAN)

    def bank(self, login: str, *dialogs: Dialog) -> FakeBank:
        self.banks[login] = FakeBank(*dialogs, procedures=[Procedure("900", "photoTAN")])
        return self.banks[login]

    def user(self, login: str) -> int:
        return self.user_id if login == "anna" else self.ben_id

    def sync(self, login: str, day: date) -> Handle:
        """The login's owner fetches the joint account on `day`, typing the PIN; waits for the end."""
        handle = self.begin(login, day)
        handle.wait()
        return handle

    def begin(self, login: str, day: date) -> Handle:
        user = self.user(login)
        with self.engine.connect() as conn:
            jobs: tuple[JobPlan, ...] = plan_start(
                conn,
                user,
                [ItemRequest(self.instances[login], account_id=self.account_id)],
                self.importers,
                day,
            )
        handle = self.start(jobs, user_id=user, env=JobEnv(self.engine, self.importers, day, user))
        handle.answer("123456")  # the PIN
        return handle

    def source_rows(self) -> list[Any]:
        return self.q(
            "SELECT amount, booked_on, purpose, duplicate_of, import_run_id FROM source_transaction"
            " WHERE account_id = :a ORDER BY id",
            a=self.account_id,
        )

    def balance_records(self) -> list[Any]:
        return self.q(
            "SELECT balance_on, balance FROM balance_record WHERE account_id = :a", a=self.account_id
        )


@pytest.fixture
def rig(isolated_engine: Engine) -> JointRig:
    return JointRig(isolated_engine)


def finished(handle: Handle) -> dict[str, Any]:
    (done,) = handle.of("run_finished")
    return dict(done["stats"])


def reconciled(stats: dict[str, Any]) -> bool:
    return stats["unexplained_difference"]["after"] in (None, 0) and stats["since_zero"] == []


def test_the_second_login_delivering_the_same_statements_skips_every_row_by_identity(rig: JointRig) -> None:
    rig.bank("anna", Dialog(text=statements("dk_basic")))
    rig.bank("ben", Dialog(text=statements("dk_basic")))
    first = finished(rig.sync("anna", DAY_ONE))
    assert first["inserted"] == 2 and first["skipped_by_identity"] == 0
    second = finished(rig.sync("ben", DAY_ONE))
    assert second["inserted"] == 0 and second["skipped_by_identity"] == 2
    assert second["inserted_as_duplicates"] == []
    assert len(rig.source_rows()) == 2 and all(r.duplicate_of is None for r in rig.source_rows())


def test_two_reported_balances_on_one_date_leave_no_difference(rig: JointRig) -> None:
    rig.bank("anna", Dialog(text=statements("dk_basic")))
    rig.bank("ben", Dialog(text=statements("dk_basic")))
    rig.sync("anna", DAY_ONE)
    second = finished(rig.sync("ben", DAY_ONE))
    records = rig.balance_records()
    assert [(r.balance_on, r.balance) for r in records] == [(date(2026, 10, 5), 108766)] * 2
    assert reconciled(second)


def test_overlapping_windows_fetched_on_different_days_insert_only_the_new_booking(rig: JointRig) -> None:
    rig.bank("anna", Dialog(text=statements("dk_basic")))
    rig.bank("ben", Dialog(text=statements("dk_basic_more")))  # the same two, and one booked later
    rig.sync("anna", DAY_ONE)
    second = finished(rig.sync("ben", DAY_TWO))
    assert second["inserted"] == 1 and second["skipped_by_identity"] == 2
    assert second["inserted_as_duplicates"] == [] and reconciled(second)
    assert sorted(r.amount for r in rig.source_rows()) == [-2000, -1234, 10000]
    assert [(r.balance_on, r.balance) for r in rig.balance_records()] == [
        (date(2026, 10, 5), 108766),
        (date(2026, 10, 7), 106766),
    ]


def test_a_booking_rendered_differently_in_field_86_is_inserted_as_a_duplicate_by_the_amount_step(
    rig: JointRig,
) -> None:
    rig.bank("anna", Dialog(text=statements("dk_basic")))
    rig.bank("ben", Dialog(text=statements("dk_basic_alt")))  # "Miete 10/2026" for "Miete Oktober 2026"
    rig.sync("anna", DAY_ONE)
    second = finished(rig.sync("ben", DAY_ONE))
    assert second["inserted"] == 0 and second["skipped_by_identity"] == 1
    (duplicate,) = second["inserted_as_duplicates"]
    rows = rig.source_rows()
    assert len(rows) == 3 and [r.duplicate_of for r in rows] == [None, None, duplicate["duplicate_of"]]
    assert rows[2].purpose == "Miete 10/2026" and rows[0].purpose == "Miete Oktober 2026"
    assert reconciled(second)  # a duplicate moves no money


def test_two_logins_syncing_at_the_same_moment_serialise_on_the_account(rig: JointRig) -> None:
    meet = threading.Barrier(2, timeout=15)  # both have their statements before either ingests
    rig.bank("anna", Dialog(text=statements("dk_basic"), before_text=meet.wait))
    rig.bank("ben", Dialog(text=statements("dk_basic"), before_text=meet.wait))
    anna, ben = rig.begin("anna", DAY_ONE), rig.begin("ben", DAY_ONE)
    anna.wait(), ben.wait()
    assert [finished(h)["inserted"] for h in (anna, ben)] in ([2, 0], [0, 2])
    assert sorted(finished(h)["skipped_by_identity"] for h in (anna, ben)) == [0, 2]
    assert len(rig.source_rows()) == 2 and all(r.duplicate_of is None for r in rig.source_rows())
    assert len(rig.balance_records()) == 2


def test_each_login_keeps_its_own_state(rig: JointRig) -> None:
    rig.bank("anna", Dialog(text=statements("dk_basic"), system_id="SYS-A"))
    rig.bank("ben", Dialog(text=statements("dk_basic"), system_id="SYS-B"))
    rig.sync("anna", DAY_ONE)
    rig.sync("ben", DAY_ONE)
    assert rig.state(rig.instances["anna"]) == {"tan_mechanism": "900", "system_id": "SYS-A"}
    assert rig.state(rig.instances["ben"]) == {"tan_mechanism": "900", "system_id": "SYS-B"}


def test_the_login_is_recorded_on_each_run(rig: JointRig) -> None:
    rig.bank("anna", Dialog(text=statements("dk_basic")))
    rig.bank("ben", Dialog(text=statements("dk_basic")))
    rig.sync("anna", DAY_ONE)
    rig.sync("ben", DAY_ONE)
    runs = rig.runs()
    assert [(r.account_id, r.status, r.importer) for r in runs] == [(rig.account_id, "ok", "fints")] * 2
    assert {r.importer_instance_id for r in runs} == set(rig.instances.values())
