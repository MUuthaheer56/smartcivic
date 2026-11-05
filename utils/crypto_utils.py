"""
SmartCivic — Cryptographic Utilities
Provides Fernet symmetric encryption at rest for sensitive verification documents (Plan 3.2).
"""
import os
import base64
import hashlib
from cryptography.fernet import Fernet


def get_fernet_key() -> bytes:
    """
    Retrieves or deterministically derives a 32-byte URL-safe base64 Fernet key.
    Uses VERIFICATION_ENCRYPTION_KEY env var if set, otherwise derives from SECRET_KEY.
    """
    env_key = os.getenv("VERIFICATION_ENCRYPTION_KEY", "").strip()
    if env_key and len(env_key) == 44:
        try:
            # Validate valid base64
            base64.urlsafe_b64decode(env_key.encode("ascii"))
            return env_key.encode("ascii")
        except Exception:
            pass

    secret = os.getenv("SECRET_KEY", "smartcivic-default-dev-secret-key-32b")
    # Derive 32 bytes from SECRET_KEY using SHA-256
    derived_32 = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(derived_32)


def encrypt_bytes(data: bytes) -> bytes:
    """Encrypts bytes at rest using Fernet."""
    f = Fernet(get_fernet_key())
    return f.encrypt(data)


def decrypt_bytes(encrypted_data: bytes) -> bytes:
    """Decrypts Fernet-encrypted bytes."""
    f = Fernet(get_fernet_key())
    return f.decrypt(encrypted_data)


def is_fernet_encrypted(data: bytes) -> bool:
    """Fernet tokens start with base64 prefix gAAAAA."""
    return bool(data and data.startswith(b"gAAAAA"))


def decrypt_verification_file(data: bytes) -> bytes:
    """
    Safely decrypts verification files if encrypted, otherwise returns raw bytes for legacy/mock compatibility.
    """
    if is_fernet_encrypted(data):
        try:
            return decrypt_bytes(data)
        except Exception:
            return data
    return data
