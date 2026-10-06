"""Encrypted document vault on a single SQLite file.

See docs/ARCHITECTURE.md §4 for the key hierarchy. Summary:

* PIN -> Argon2id -> KEK, which wraps a random data key (DK). Changing the PIN re-wraps DK only.
* Documents are JSON, encrypted with AES-256-GCM under a key derived from DK.
* Collection and day are stored only as HMAC tags, so they are not readable at rest.
* While locked, writes are sealed to an X25519 public key into `inbox` and migrated on unlock.

All public methods are thread-safe (the collector thread writes while the UI thread reads).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..crypto import primitives as cp

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
MIN_PIN_LENGTH = 6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS records (
    ctag BLOB NOT NULL,
    id   TEXT NOT NULL,
    dtag BLOB,
    blob BLOB NOT NULL,
    PRIMARY KEY (ctag, id)
);
CREATE INDEX IF NOT EXISTS records_by_day ON records (ctag, dtag);
CREATE TABLE IF NOT EXISTS inbox (
    seq  INTEGER PRIMARY KEY AUTOINCREMENT,
    epk  BLOB NOT NULL,
    blob BLOB NOT NULL
);
"""

_AAD_DK = b"wa1|dk|"
_AAD_SK = b"wa1|sk|"
_AAD_REC = b"wa1|rec|"
_AAD_INBOX = b"wa1|inbox|"


class VaultState(Enum):
    UNINITIALIZED = "uninitialized"
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class VaultError(Exception):
    pass


class VaultLockedError(VaultError):
    """Raised when reading while locked."""


class WrongPinError(VaultError):
    pass


class VaultTamperedError(VaultError):
    pass


class WeakPinError(VaultError):
    pass


@dataclass
class _Keys:
    record: bytes
    index: bytes
    private: bytes


def validate_pin(pin: str) -> None:
    if len(pin) < MIN_PIN_LENGTH:
        raise WeakPinError(f"PIN must be at least {MIN_PIN_LENGTH} characters")


class Vault:
    def __init__(self, path: Path | str, kdf_defaults: dict[str, int] | None = None):
        self._path = Path(path)
        self._kdf_defaults = kdf_defaults or {}
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._keys: _Keys | None = None
        self._public_key: bytes | None = None

    # --- lifecycle --------------------------------------------------------------------------

    def open(self) -> "Vault":
        with self._lock:
            if self._db is not None:
                return self
            self._path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript(_SCHEMA)
            self._db = db
            version = self._meta("format_version")
            if version is not None and int(version) != FORMAT_VERSION:
                raise VaultError(f"unsupported vault format {int(version)}")
            pk = self._meta("public_key")
            self._public_key = bytes(pk) if pk is not None else None
            return self

    def close(self) -> None:
        with self._lock:
            self._keys = None
            if self._db is not None:
                self._db.close()
                self._db = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def state(self) -> VaultState:
        with self._lock:
            if self._public_key is None:
                return VaultState.UNINITIALIZED
            return VaultState.UNLOCKED if self._keys else VaultState.LOCKED

    @property
    def is_unlocked(self) -> bool:
        return self.state is VaultState.UNLOCKED

    # --- key management ---------------------------------------------------------------------

    def initialize(self, pin: str) -> None:
        validate_pin(pin)
        with self._lock:
            if self._public_key is not None:
                raise VaultError("vault already initialized")
            params = cp.KdfParams.new(**self._kdf_defaults)
            dk = cp.random_key()
            sk, pk = cp.generate_keypair()
            kdf_json = params.to_json()
            wrapped_dk = cp.aead_encrypt(cp.derive_kek(pin, params), dk, _AAD_DK + kdf_json)
            wrapped_sk = cp.aead_encrypt(cp.hkdf(dk, b"wa1/sealing"), sk, _AAD_SK + pk)
            with self._tx() as db:
                for k, v in (
                    ("format_version", str(FORMAT_VERSION).encode()),
                    ("kdf", kdf_json),
                    ("wrapped_dk", wrapped_dk),
                    ("public_key", pk),
                    ("wrapped_sk", wrapped_sk),
                ):
                    db.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (k, v))
            self._public_key = pk
            self._keys = self._derive_keys(dk)
            log.info("vault initialized")

    def unlock(self, pin: str) -> int:
        """Unlock and migrate locked-time writes. Returns number of migrated writes."""
        with self._lock:
            if self._public_key is None:
                raise VaultError("vault not initialized")
            dk = self._unwrap_dk(pin)
            keys = self._derive_keys(dk)
            if cp.public_from_private(keys.private) != self._public_key:
                raise VaultTamperedError("vault public key does not match private key")
            self._keys = keys
            migrated = self._migrate_inbox()
            log.info("vault unlocked (migrated %d locked writes)", migrated)
            return migrated

    def lock(self) -> None:
        with self._lock:
            if self._keys is not None:
                self._keys = None
                log.info("vault locked")

    def verify_pin(self, pin: str) -> bool:
        with self._lock:
            try:
                self._unwrap_dk(pin)
                return True
            except WrongPinError:
                return False

    def change_pin(self, old_pin: str, new_pin: str) -> None:
        validate_pin(new_pin)
        with self._lock:
            dk = self._unwrap_dk(old_pin)
            params = cp.KdfParams.from_json(self._require_meta("kdf")).renewed()
            kdf_json = params.to_json()
            wrapped = cp.aead_encrypt(cp.derive_kek(new_pin, params), dk, _AAD_DK + kdf_json)
            with self._tx() as db:
                db.execute("UPDATE meta SET value=? WHERE key='kdf'", (kdf_json,))
                db.execute("UPDATE meta SET value=? WHERE key='wrapped_dk'", (wrapped,))
            log.info("vault PIN changed")

    def _unwrap_dk(self, pin: str) -> bytes:
        kdf_json = self._require_meta("kdf")
        params = cp.KdfParams.from_json(kdf_json)
        try:
            return cp.aead_decrypt(cp.derive_kek(pin, params), self._require_meta("wrapped_dk"),
                                   _AAD_DK + kdf_json)
        except cp.DecryptionError as exc:
            raise WrongPinError("wrong PIN") from exc

    def _derive_keys(self, dk: bytes) -> _Keys:
        try:
            sk = cp.aead_decrypt(cp.hkdf(dk, b"wa1/sealing"), self._require_meta("wrapped_sk"),
                                 _AAD_SK + self._public_key)
        except cp.DecryptionError as exc:
            raise VaultTamperedError("private key failed authentication") from exc
        return _Keys(record=cp.hkdf(dk, b"wa1/records"), index=cp.hkdf(dk, b"wa1/index"), private=sk)

    # --- documents --------------------------------------------------------------------------

    def put(self, collection: str, doc_id: str, doc: dict[str, Any], day: str | None = None) -> None:
        """Insert or replace a document. Works while locked (write-only)."""
        payload = json.dumps({"c": collection, "i": doc_id, "d": day, "v": doc},
                             separators=(",", ":"), ensure_ascii=False).encode()
        with self._lock:
            if self._public_key is None:
                raise VaultError("vault not initialized")
            if self._keys is None:
                epk, blob = cp.seal(self._public_key, payload, _AAD_INBOX)
                with self._tx() as db:
                    db.execute("INSERT INTO inbox(epk, blob) VALUES (?, ?)", (epk, blob))
                return
            with self._tx() as db:
                self._put_record(db, collection, doc_id, day, payload)

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            keys = self._require_keys()
            ctag = self._ctag(keys, collection)
            row = self._conn().execute(
                "SELECT blob FROM records WHERE ctag=? AND id=?", (ctag, doc_id)).fetchone()
            return self._open_record(keys, ctag, doc_id, collection, row[0]) if row else None

    def list(self, collection: str, day: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            keys = self._require_keys()
            ctag = self._ctag(keys, collection)
            if day is None:
                rows = self._conn().execute("SELECT id, blob FROM records WHERE ctag=?", (ctag,))
            else:
                rows = self._conn().execute(
                    "SELECT id, blob FROM records WHERE ctag=? AND dtag=?",
                    (ctag, self._dtag(keys, collection, day)))
            return [self._open_record(keys, ctag, i, collection, b) for i, b in rows.fetchall()]

    def delete(self, collection: str, doc_id: str) -> None:
        with self._lock:
            keys = self._require_keys()
            with self._tx() as db:
                db.execute("DELETE FROM records WHERE ctag=? AND id=?",
                           (self._ctag(keys, collection), doc_id))

    def delete_day(self, collection: str, day: str) -> int:
        with self._lock:
            keys = self._require_keys()
            with self._tx() as db:
                cur = db.execute("DELETE FROM records WHERE ctag=? AND dtag=?",
                                 (self._ctag(keys, collection), self._dtag(keys, collection, day)))
                return cur.rowcount

    def pending_writes(self) -> int:
        """Number of sealed writes awaiting unlock (readable while locked; reveals no content)."""
        with self._lock:
            return self._conn().execute("SELECT COUNT(*) FROM inbox").fetchone()[0]

    # --- internals --------------------------------------------------------------------------

    def _migrate_inbox(self) -> int:
        keys = self._require_keys()
        rows = self._conn().execute("SELECT seq, epk, blob FROM inbox ORDER BY seq").fetchall()
        if not rows:
            return 0
        with self._tx() as db:
            for seq, epk, blob in rows:
                try:
                    payload = cp.unseal(keys.private, epk, blob, _AAD_INBOX)
                    item = json.loads(payload)
                    self._put_record(db, item["c"], item["i"], item["d"], payload)
                except (cp.DecryptionError, ValueError, KeyError):
                    # Corrupt or forged rows are dropped rather than blocking every unlock.
                    log.warning("dropped unreadable locked write seq=%d", seq)
            db.execute("DELETE FROM inbox WHERE seq <= ?", (rows[-1][0],))
        return len(rows)

    def _put_record(self, db: sqlite3.Connection, collection: str, doc_id: str,
                    day: str | None, payload: bytes) -> None:
        keys = self._require_keys()
        ctag = self._ctag(keys, collection)
        dtag = self._dtag(keys, collection, day) if day else None
        blob = cp.aead_encrypt(keys.record, payload, _AAD_REC + ctag + b"|" + doc_id.encode())
        db.execute("INSERT OR REPLACE INTO records(ctag, id, dtag, blob) VALUES (?, ?, ?, ?)",
                   (ctag, doc_id, dtag, blob))

    def _open_record(self, keys: _Keys, ctag: bytes, doc_id: str, collection: str,
                     blob: bytes) -> dict[str, Any]:
        try:
            payload = cp.aead_decrypt(keys.record, blob, _AAD_REC + ctag + b"|" + doc_id.encode())
        except cp.DecryptionError as exc:
            raise VaultTamperedError("record failed authentication") from exc
        item = json.loads(payload)
        if item.get("c") != collection or item.get("i") != doc_id:
            raise VaultTamperedError("record collection mismatch")
        return item["v"]

    @staticmethod
    def _ctag(keys: _Keys, collection: str) -> bytes:
        return cp.hmac_tag(keys.index, b"c|" + collection.encode())[:16]

    @staticmethod
    def _dtag(keys: _Keys, collection: str, day: str) -> bytes:
        return cp.hmac_tag(keys.index, b"d|" + collection.encode() + b"|" + day.encode())[:16]

    def _require_keys(self) -> _Keys:
        if self._keys is None:
            raise VaultLockedError("vault is locked")
        return self._keys

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            raise VaultError("vault not open")
        return self._db

    def _meta(self, key: str) -> bytes | None:
        row = self._conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return bytes(row[0]) if row else None

    def _require_meta(self, key: str) -> bytes:
        value = self._meta(key)
        if value is None:
            raise VaultTamperedError(f"missing vault header field {key}")
        return value

    def _tx(self) -> "_Transaction":
        return _Transaction(self._conn())


class _Transaction:
    def __init__(self, db: sqlite3.Connection):
        self._db = db

    def __enter__(self) -> sqlite3.Connection:
        self._db.execute("BEGIN IMMEDIATE")
        return self._db

    def __exit__(self, exc_type, exc, tb) -> None:
        self._db.execute("ROLLBACK" if exc_type else "COMMIT")
