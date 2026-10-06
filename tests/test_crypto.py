import pytest

from workagent.crypto import primitives as cp


def test_aead_roundtrip_and_random_nonce():
    key = cp.random_key()
    a = cp.aead_encrypt(key, b"hello", b"aad")
    b = cp.aead_encrypt(key, b"hello", b"aad")
    assert a != b  # fresh nonce every time
    assert cp.aead_decrypt(key, a, b"aad") == b"hello"


@pytest.mark.parametrize("mutate", ["key", "aad", "ciphertext", "nonce"])
def test_aead_rejects_tampering(mutate):
    key = cp.random_key()
    blob = bytearray(cp.aead_encrypt(key, b"secret data", b"aad"))
    aad = b"aad"
    if mutate == "key":
        key = cp.random_key()
    elif mutate == "aad":
        aad = b"other"
    elif mutate == "ciphertext":
        blob[-1] ^= 1
    else:
        blob[0] ^= 1
    with pytest.raises(cp.DecryptionError):
        cp.aead_decrypt(key, bytes(blob), aad)


def test_kdf_deterministic_per_salt_and_pin():
    params = cp.KdfParams.new(time_cost=1, memory_kib=1024, parallelism=1)
    assert cp.derive_kek("123456", params) == cp.derive_kek("123456", params)
    assert cp.derive_kek("123456", params) != cp.derive_kek("123457", params)
    assert cp.derive_kek("123456", params) != cp.derive_kek("123456", params.renewed())


def test_kdf_normalizes_unicode():
    params = cp.KdfParams.new(time_cost=1, memory_kib=1024, parallelism=1)
    composed, decomposed = "mật khẩu", "mật khẩu"
    assert cp.derive_kek(composed, params) == cp.derive_kek(decomposed, params)


def test_kdf_params_json_roundtrip():
    params = cp.KdfParams.new()
    assert cp.KdfParams.from_json(params.to_json()) == params
    assert params.time_cost >= 3 and params.memory_kib >= 64 * 1024  # production defaults


def test_seal_unseal():
    sk, pk = cp.generate_keypair()
    epk, blob = cp.seal(pk, b"written while locked", b"ctx")
    assert cp.unseal(sk, epk, blob, b"ctx") == b"written while locked"
    other_sk, _ = cp.generate_keypair()
    with pytest.raises(cp.DecryptionError):
        cp.unseal(other_sk, epk, blob, b"ctx")
    with pytest.raises(cp.DecryptionError):
        cp.unseal(sk, epk, blob, b"other")
