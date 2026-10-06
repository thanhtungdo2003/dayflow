import sqlite3

import pytest

from workagent.storage.vault import (
    Vault, VaultLockedError, VaultState, VaultTamperedError, WeakPinError, WrongPinError,
)

from .conftest import FAST_KDF, PIN


def test_initialize_and_basic_crud(vault):
    assert vault.state is VaultState.UNLOCKED
    vault.put("activities", "a1", {"title": "Fix login bug"}, day="2026-10-05")
    vault.put("activities", "a2", {"title": "Code review"}, day="2026-10-06")
    assert vault.get("activities", "a1") == {"title": "Fix login bug"}
    assert [d["title"] for d in vault.list("activities", day="2026-10-05")] == ["Fix login bug"]
    assert len(vault.list("activities")) == 2
    vault.delete("activities", "a1")
    assert vault.get("activities", "a1") is None
    assert vault.delete_day("activities", "2026-10-06") == 1


def test_collections_are_isolated(vault):
    vault.put("tasks", "x", {"v": 1})
    vault.put("reports", "x", {"v": 2})
    assert vault.get("tasks", "x") == {"v": 1}
    assert vault.get("reports", "x") == {"v": 2}


def test_no_plaintext_on_disk(vault):
    vault.put("activities", "a1", {"title": "SUPER-SECRET-PROJECT"}, day="2026-10-05")
    vault.lock()
    vault.put("activities", "a2", {"title": "LOCKED-WRITE-MARKER"}, day="2026-10-05")
    raw = vault.path.read_bytes()
    for needle in (b"SUPER-SECRET-PROJECT", b"LOCKED-WRITE-MARKER", b"2026-10-05", b"activities", PIN.encode()):
        assert needle not in raw


def test_wrong_pin_and_reopen(tmp_path):
    path = tmp_path / "v.db"
    v = Vault(path, kdf_defaults=FAST_KDF).open()
    v.initialize(PIN)
    v.put("tasks", "t", {"title": "x"})
    v.close()

    v2 = Vault(path).open()
    assert v2.state is VaultState.LOCKED
    with pytest.raises(VaultLockedError):
        v2.get("tasks", "t")
    with pytest.raises(WrongPinError):
        v2.unlock("wrong-pin")
    assert not v2.verify_pin("wrong-pin")
    v2.unlock(PIN)
    assert v2.get("tasks", "t") == {"title": "x"}
    v2.close()


def test_weak_pin_rejected(tmp_path):
    v = Vault(tmp_path / "v.db", kdf_defaults=FAST_KDF).open()
    with pytest.raises(WeakPinError):
        v.initialize("123")


def test_locked_writes_are_write_only_then_migrated(vault):
    vault.put("activities", "a1", {"n": 1}, day="2026-10-05")
    vault.lock()
    assert vault.state is VaultState.LOCKED
    vault.put("activities", "a1", {"n": 2}, day="2026-10-05")   # update while locked
    vault.put("activities", "a1", {"n": 3}, day="2026-10-05")   # later write wins
    vault.put("activities", "a3", {"n": 9}, day="2026-10-05")
    assert vault.pending_writes() == 3
    with pytest.raises(VaultLockedError):
        vault.list("activities", day="2026-10-05")
    assert vault.unlock(PIN) == 3
    assert vault.pending_writes() == 0
    assert vault.get("activities", "a1") == {"n": 3}
    assert {d["n"] for d in vault.list("activities", day="2026-10-05")} == {3, 9}


def test_change_pin_keeps_data_without_reencrypting(vault):
    vault.put("tasks", "t", {"title": "keep me"})
    before = vault.path.read_bytes()
    con = sqlite3.connect(vault.path)
    blobs_before = con.execute("SELECT blob FROM records").fetchall()
    con.close()

    vault.change_pin(PIN, "new-pin-456")
    con = sqlite3.connect(vault.path)
    assert con.execute("SELECT blob FROM records").fetchall() == blobs_before  # records untouched
    con.close()
    assert before != vault.path.read_bytes()

    vault.lock()
    with pytest.raises(WrongPinError):
        vault.unlock(PIN)
    vault.unlock("new-pin-456")
    assert vault.get("tasks", "t") == {"title": "keep me"}


def test_change_pin_requires_old_pin(vault):
    with pytest.raises(WrongPinError):
        vault.change_pin("not-the-pin", "another-pin")


def test_tampered_record_detected(vault):
    vault.put("tasks", "t", {"title": "x"})
    con = sqlite3.connect(vault.path)
    blob = bytearray(con.execute("SELECT blob FROM records").fetchone()[0])
    blob[-1] ^= 1
    con.execute("UPDATE records SET blob=?", (bytes(blob),))
    con.commit()
    con.close()
    with pytest.raises(VaultTamperedError):
        vault.get("tasks", "t")


def test_swapped_record_between_ids_detected(vault):
    vault.put("tasks", "a", {"title": "A"})
    vault.put("tasks", "b", {"title": "B"})
    con = sqlite3.connect(vault.path)
    rows = dict(con.execute("SELECT id, blob FROM records").fetchall())
    con.execute("UPDATE records SET blob=? WHERE id='a'", (rows["b"],))
    con.commit()
    con.close()
    with pytest.raises(VaultTamperedError):
        vault.get("tasks", "a")


def test_swapped_public_key_detected(tmp_path):
    path = tmp_path / "v.db"
    v = Vault(path, kdf_defaults=FAST_KDF).open()
    v.initialize(PIN)
    v.close()
    con = sqlite3.connect(path)
    con.execute("UPDATE meta SET value=? WHERE key='public_key'", (b"\x09" * 32,))
    con.commit()
    con.close()
    v2 = Vault(path).open()
    with pytest.raises(VaultTamperedError):
        v2.unlock(PIN)


def test_kdf_param_tampering_fails_unlock(tmp_path):
    path = tmp_path / "v.db"
    v = Vault(path, kdf_defaults=FAST_KDF).open()
    v.initialize(PIN)
    v.close()
    con = sqlite3.connect(path)
    raw = con.execute("SELECT value FROM meta WHERE key='kdf'").fetchone()[0]
    con.execute("UPDATE meta SET value=? WHERE key='kdf'", (raw.replace(b'"t":1', b'"t":2'),))
    con.commit()
    con.close()
    with pytest.raises(WrongPinError):
        Vault(path).open().unlock(PIN)


def test_concurrent_writes_from_threads(vault):
    import threading

    def writer(prefix):
        for i in range(50):
            vault.put("activities", f"{prefix}{i}", {"i": i}, day="2026-10-05")

    threads = [threading.Thread(target=writer, args=(p,)) for p in "abcd"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(vault.list("activities", day="2026-10-05")) == 200
