from __future__ import annotations

import base64
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class ProtocolCryptoError(ValueError):
    """Raised when protocol-level cryptographic inputs are malformed."""


def canonical_json(obj: object) -> bytes:
    """Serialize an object to canonical JSON bytes (UTF-8, deterministic key order)."""
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return canonical.encode("utf-8")


def sha256_hex_from_canonical_json(obj: object) -> str:
    """Hash canonical JSON using SHA-256 and return lowercase hex digest."""
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def decode_base64url(value: str, *, expected_len: int | None = None, label: str = "value") -> bytes:
    if not value or _BASE64URL_RE.fullmatch(value) is None:
        raise ProtocolCryptoError(f"Invalid {label} encoding")

    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{value}{padding}")
    except (ValueError, TypeError) as exc:
        raise ProtocolCryptoError(f"Invalid {label} encoding") from exc

    if expected_len is not None and len(decoded) != expected_len:
        raise ProtocolCryptoError(f"Invalid {label} length")

    return decoded


def verify_ed25519_signature(
    *,
    public_key_b64url: str,
    signature_b64url: str,
    message: bytes,
) -> bool:
    """Verify an Ed25519 signature encoded in base64url (no padding required)."""
    public_key_bytes = decode_base64url(public_key_b64url, expected_len=32, label="public key")
    signature_bytes = decode_base64url(signature_b64url, expected_len=64, label="signature")

    verifier = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        verifier.verify(signature_bytes, message)
    except InvalidSignature:
        return False

    return True
