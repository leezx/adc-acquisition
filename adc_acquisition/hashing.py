"""Content hashing for raw evidence immutability checks."""

import hashlib


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
