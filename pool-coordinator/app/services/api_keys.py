from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass


API_KEY_PREFIX = "omk"
API_KEY_SECRET_BYTES = 32
API_KEY_DISPLAY_PREFIX_LEN = 12


@dataclass(frozen=True)
class GeneratedApiKey:
    raw_key: str
    key_hash: str
    prefix: str


def _extract_prefix(raw_key: str, prefix_len: int = API_KEY_DISPLAY_PREFIX_LEN) -> str:
    return raw_key[:prefix_len]


def generate_api_key_material() -> GeneratedApiKey:
    raw_key = f"{API_KEY_PREFIX}_{secrets.token_urlsafe(API_KEY_SECRET_BYTES)}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    prefix = _extract_prefix(raw_key)
    return GeneratedApiKey(raw_key=raw_key, key_hash=key_hash, prefix=prefix)
