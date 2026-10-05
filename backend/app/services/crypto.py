"""Password-based key derivation and AES-GCM encryption for the vault."""

from __future__ import annotations

import os
from hashlib import sha256
import hmac
import unicodedata

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from mnemonic import Mnemonic

# Tuned for interactive unlock on a local machine
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 64 * 1024  # KiB
ARGON2_PARALLELISM = 2
ARGON2_HASH_LEN = 32
SALT_LEN = 16
NONCE_LEN = 12
DEK_LEN = 32
RECOVERY_ENTROPY_BITS = 128
RECOVERY_AAD = b"finsight:v1:vault-recovery"

_mnemonic = Mnemonic("english")


def new_salt() -> bytes:
    return os.urandom(SALT_LEN)


def new_dek() -> bytes:
    return os.urandom(DEK_LEN)


def derive_key(password: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,
    )


def encrypt(key: bytes, plaintext: bytes, associated_data: bytes | None = None) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    aes = AESGCM(key)
    return nonce + aes.encrypt(nonce, plaintext, associated_data)


def decrypt(key: bytes, blob: bytes, associated_data: bytes | None = None) -> bytes:
    if len(blob) < NONCE_LEN + 16:
        raise ValueError("Ciphertext too short")
    nonce, ct = blob[:NONCE_LEN], blob[NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ct, associated_data)


def derive_subkey(dek: bytes, purpose: str) -> bytes:
    """Derive a domain-separated key without storing additional key material."""
    if not purpose:
        raise ValueError("Key purpose must not be empty")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=DEK_LEN,
        salt=None,
        info=f"finsight:v1:{purpose}".encode("utf-8"),
    ).derive(dek)


def blind_index(dek: bytes, namespace: str, value: str) -> bytes:
    """Create a keyed equality index; the normalized value is never persisted."""
    key = derive_subkey(dek, f"blind-index:{namespace}")
    return hmac.new(key, value.encode("utf-8"), sha256).digest()


def wrap_dek(password: str, salt: bytes, dek: bytes) -> bytes:
    return encrypt(derive_key(password, salt), dek)


def unwrap_dek(password: str, salt: bytes, wrapped: bytes) -> bytes:
    return decrypt(derive_key(password, salt), wrapped)


def normalize_recovery_phrase(phrase: str) -> str:
    """Normalize a BIP-39 phrase without weakening its checksum validation."""
    return " ".join(unicodedata.normalize("NFKD", phrase).lower().split())


def generate_recovery_phrase() -> str:
    """Generate a 12-word BIP-39 phrase backed by 128 bits of entropy."""
    return _mnemonic.generate(strength=RECOVERY_ENTROPY_BITS)


def recovery_entropy(phrase: str) -> bytes:
    normalized = normalize_recovery_phrase(phrase)
    if len(normalized.split()) != 12 or not _mnemonic.check(normalized):
        raise ValueError("Invalid recovery phrase")
    entropy = bytes(_mnemonic.to_entropy(normalized))
    if len(entropy) * 8 != RECOVERY_ENTROPY_BITS:
        raise ValueError("Invalid recovery phrase")
    return entropy


def derive_recovery_key(phrase: str, salt: bytes) -> bytes:
    """Derive a domain-separated KEK from a high-entropy recovery phrase."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=DEK_LEN,
        salt=salt,
        info=RECOVERY_AAD,
    ).derive(recovery_entropy(phrase))


def wrap_dek_with_recovery_phrase(phrase: str, salt: bytes, dek: bytes) -> bytes:
    return encrypt(derive_recovery_key(phrase, salt), dek, RECOVERY_AAD)


def unwrap_dek_with_recovery_phrase(phrase: str, salt: bytes, wrapped: bytes) -> bytes:
    return decrypt(derive_recovery_key(phrase, salt), wrapped, RECOVERY_AAD)
