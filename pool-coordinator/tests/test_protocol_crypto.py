from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.protocol_crypto import (
    ProtocolCryptoError,
    canonical_json,
    sha256_hex_from_canonical_json,
    verify_ed25519_signature,
)


def test_canonical_json_is_deterministic_and_utf8() -> None:
    payload_a = {"b": 2, "a": "á"}
    payload_b = {"a": "á", "b": 2}

    assert canonical_json(payload_a) == canonical_json(payload_b)
    assert canonical_json(payload_a) == b'{"a":"\xc3\xa1","b":2}'


def test_sha256_hex_from_canonical_json() -> None:
    digest = sha256_hex_from_canonical_json({"z": 1, "a": 2})
    assert digest == "c2985c5ba6f7d2a55e768f92490ca09388e95bc4cccb9fdf11b15f4d42f93e73"


def test_verify_ed25519_signature_base64url() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key_b64 = base64.urlsafe_b64encode(public_key_bytes).decode().rstrip("=")

    message = canonical_json({"assignment_id": 1, "nonce": "abc", "output_hash": "deadbeef"})
    signature_b64 = base64.urlsafe_b64encode(private_key.sign(message)).decode().rstrip("=")

    assert verify_ed25519_signature(
        public_key_b64url=public_key_b64,
        signature_b64url=signature_b64,
        message=message,
    )


def test_verify_ed25519_signature_rejects_bad_format() -> None:
    message = b"msg"
    with pytest.raises(ProtocolCryptoError):
        verify_ed25519_signature(public_key_b64url="@@@", signature_b64url="abc", message=message)
