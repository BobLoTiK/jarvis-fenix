"""Пароль: PBKDF2 со солью, чтение legacy-форматов и миграция при входе."""

import hashlib

from jarvis.intents.password import (
    KDF_ITERATIONS,
    hash_password,
    is_hashed,
    migrate_password_if_needed,
    needs_rehash,
    verify_password,
)


class FakeConfig(dict):
    def set(self, key, value):
        self[key] = value
        return True


def test_new_hash_has_prefix_iterations_and_salt():
    stored = hash_password("AbC-42!")
    assert stored.startswith("pbkdf2_sha256:")
    iterations, salt, digest = stored.split(":")[1:]
    assert int(iterations) == KDF_ITERATIONS
    assert len(bytes.fromhex(salt)) == 16
    assert len(digest) == 64
    assert "AbC-42!" not in stored


def test_salt_makes_equal_passwords_differ():
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)


def test_verify_accepts_current_and_rejects_wrong():
    stored = hash_password("correct horse")
    assert verify_password("correct horse", stored)
    assert not verify_password("correct hors", stored)
    assert not verify_password("", stored)


def test_legacy_sha256_still_verifies():
    legacy = "sha256:" + hashlib.sha256(b"old-pass").hexdigest()
    assert is_hashed(legacy)
    assert verify_password("old-pass", legacy)
    assert not verify_password("new-pass", legacy)


def test_legacy_plaintext_still_verifies():
    assert not is_hashed("plain-pass")
    assert verify_password("plain-pass", "plain-pass")
    assert not verify_password("other", "plain-pass")


def test_verify_upgrades_legacy_hash_when_config_given():
    config = FakeConfig(danger_password="sha256:" + hashlib.sha256(b"old-pass").hexdigest())
    assert verify_password("old-pass", config["danger_password"], config=config)
    upgraded = config["danger_password"]
    assert upgraded.startswith("pbkdf2_sha256:")
    assert verify_password("old-pass", upgraded)


def test_verify_upgrades_plaintext_when_config_given():
    config = FakeConfig(danger_password="plain-pass")
    assert verify_password("plain-pass", "plain-pass", config=config)
    assert config["danger_password"].startswith("pbkdf2_sha256:")


def test_verify_does_not_upgrade_on_wrong_password():
    config = FakeConfig(danger_password="sha256:" + hashlib.sha256(b"right").hexdigest())
    assert not verify_password("wrong", config["danger_password"], config=config)
    assert config["danger_password"].startswith("sha256:")


def test_verify_without_config_never_touches_legacy():
    stored = "sha256:" + hashlib.sha256(b"pass").hexdigest()
    assert verify_password("pass", stored)
    assert stored.startswith("sha256:")


def test_broken_entries_do_not_raise():
    for stored in ("pbkdf2_sha256:", "pbkdf2_sha256:abc:zz:zz", "pbkdf2_sha256:1:zz:zz"):
        assert verify_password("any", stored) is False


def test_needs_rehash_matrix():
    assert not needs_rehash("")
    assert needs_rehash("plain")
    assert needs_rehash("sha256:" + "0" * 64)
    assert needs_rehash(hash_password("x", iterations=1000))
    assert not needs_rehash(hash_password("x"))


def test_migration_hashes_plaintext_and_keeps_current():
    config = FakeConfig(danger_password="plain")
    migrate_password_if_needed(config)
    assert config["danger_password"].startswith("pbkdf2_sha256:")
    assert verify_password("plain", config["danger_password"])

    current = config["danger_password"]
    migrate_password_if_needed(config)
    assert config["danger_password"] == current


def test_migration_leaves_legacy_sha256_for_next_login():
    stored = "sha256:" + hashlib.sha256(b"pass").hexdigest()
    config = FakeConfig(danger_password=stored)
    migrate_password_if_needed(config)
    assert config["danger_password"] == stored


def test_kdf_iterations_meet_floor():
    assert KDF_ITERATIONS >= 600_000
