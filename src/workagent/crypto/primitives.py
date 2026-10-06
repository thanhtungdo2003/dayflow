"""Cryptographic building blocks.

Thin wrappers over audited libraries (`cryptography`, `argon2-cffi`). Nothing here implements a
primitive itself; the wrappers only fix parameters, encodings and error types.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import unicodedata
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_LEN = 32
NONCE_LEN = 12
SALT_LEN = 16


class DecryptionError(Exception):
    """Ciphertext failed authentication (wrong key, tampering or corruption)."""


@dataclass(frozen=True)
class KdfParams:
    """Argon2id parameters. Stored alongside the salt in the vault header."""

    salt: bytes
    time_cost: int = 3
    memory_kib: int = 64 * 1024
    parallelism: int = 4

    @classmethod
    def new(cls, time_cost: int = 3, memory_kib: int = 64 * 1024, parallelism: int = 4) -> "KdfParams":
        return cls(os.urandom(SALT_LEN), time_cost, memory_kib, parallelism)

    def renewed(self) -> "KdfParams":
        """Same cost parameters, fresh salt."""
        return KdfParams(os.urandom(SALT_LEN), self.time_cost, self.memory_kib, self.parallelism)

    def to_json(self) -> bytes:
        # Canonical encoding: also used as AAD so the parameters cannot be swapped silently.
        return json.dumps(
            {
                "alg": "argon2id",
                "v": 19,
                "salt": self.salt.hex(),
                "t": self.time_cost,
                "m": self.memory_kib,
                "p": self.parallelism,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    @classmethod
    def from_json(cls, raw: bytes) -> "KdfParams":
        d = json.loads(raw)
        if d.get("alg") != "argon2id":
            raise ValueError("unsupported KDF")
        return cls(bytes.fromhex(d["salt"]), int(d["t"]), int(d["m"]), int(d["p"]))


def normalize_pin(pin: str) -> bytes:
    return unicodedata.normalize("NFC", pin).encode("utf-8")


def derive_kek(pin: str, params: KdfParams) -> bytes:
    return hash_secret_raw(
        secret=normalize_pin(pin),
        salt=params.salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_kib,
        parallelism=params.parallelism,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def random_key() -> bytes:
    return os.urandom(KEY_LEN)


def aead_encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """AES-256-GCM with a random 96-bit nonce. Returns nonce || ciphertext+tag."""
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def aead_decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < NONCE_LEN + 16:
        raise DecryptionError("ciphertext too short")
    try:
        return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad)
    except InvalidTag as exc:
        raise DecryptionError("authentication failed") from exc


def hkdf(key: bytes, info: bytes, length: int = KEY_LEN, salt: bytes | None = None) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(key)


def hmac_tag(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


# --- X25519 sealing (write-only while locked) -------------------------------------------------

def generate_keypair() -> tuple[bytes, bytes]:
    sk = X25519PrivateKey.generate()
    return (
        sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                         serialization.NoEncryption()),
        public_bytes(sk),
    )


def public_bytes(sk: X25519PrivateKey) -> bytes:
    return sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_from_private(sk_raw: bytes) -> bytes:
    return public_bytes(X25519PrivateKey.from_private_bytes(sk_raw))


def _seal_key(shared: bytes, epk: bytes, pk: bytes) -> bytes:
    return hkdf(shared, b"wa1/seal", salt=epk + pk)


def seal(public_key: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """Encrypt to a public key (ECIES-style). Returns (ephemeral_public_key, blob)."""
    eph = X25519PrivateKey.generate()
    epk = public_bytes(eph)
    shared = eph.exchange(X25519PublicKey.from_public_bytes(public_key))
    key = _seal_key(shared, epk, public_key)
    return epk, aead_encrypt(key, plaintext, aad + epk)


def unseal(private_key: bytes, epk: bytes, blob: bytes, aad: bytes) -> bytes:
    sk = X25519PrivateKey.from_private_bytes(private_key)
    try:
        shared = sk.exchange(X25519PublicKey.from_public_bytes(epk))
    except ValueError as exc:  # low-order point
        raise DecryptionError("invalid ephemeral key") from exc
    key = _seal_key(shared, epk, public_bytes(sk))
    return aead_decrypt(key, blob, aad + epk)
