from argon2 import PasswordHasher
from argon2.low_level import Type

from app.utils.auth import hash_password, needs_rehash, verify_password


def test_hash_is_argon2id_and_salted():
    a, b = hash_password("correct horse"), hash_password("correct horse")
    assert a.startswith("$argon2id$")
    assert a != b


def test_verify_accepts_right_and_rejects_wrong_password():
    h = hash_password("correct horse")
    assert verify_password(h, "correct horse")
    assert not verify_password(h, "wrong horse")


def test_verify_on_malformed_hash_is_a_mismatch_not_an_error():
    assert not verify_password("not-a-hash", "x")


def test_fresh_hash_does_not_need_rehash_but_weaker_parameters_do():
    assert not needs_rehash(hash_password("pw"))
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID).hash("pw")
    assert needs_rehash(weak)
    assert verify_password(weak, "pw")
