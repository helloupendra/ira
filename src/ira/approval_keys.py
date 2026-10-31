"""Approving with a device's own key: a fingerprint or Face ID instead of a typed PIN.

A phone or a Mac makes an EC P-256 key pair that only the person's biometric unlocks
(Android Keystore, Secure Enclave), and a Windows PC an RSA key in Windows Hello (which
makes no EC keys), and enrols its public key once, with the PIN. To confirm a Tier 3
action it signs ``message(pending)``; the server checks the signature with the stored
key. A wrong signature counts as a wrong PIN (docs/security.md).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ira.store import Store

# ES256: ECDSA on P-256 with SHA-256. RS256: RSASSA-PKCS1-v1_5 with SHA-256, as Windows
# Hello signs, with a key of at least 2048 bits.
ALGORITHMS = ("ES256", "RS256")
MIN_RSA_BITS = 2048


class KeyError_(ValueError):  # noqa: N801 - not the builtin KeyError
    pass


def _b64(text: str) -> bytes:
    text = text.strip()
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise KeyError_("not base64") from None


def message(action_id: str, summary: str, expires_at: float) -> bytes:
    """What a device signs to confirm an action: bound to its id, what the person was
    shown, and when it expires (the action's ``expires_at``, whole seconds)."""
    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    return f"ira-approve:1\n{action_id}\n{digest}\n{int(expires_at)}".encode()


def load_public_key(text: str, algorithm: str = "ES256") -> Any:
    """The algorithm's public key from base64 SubjectPublicKeyInfo (DER): EC P-256 for
    ES256, RSA of 2048 bits or more for RS256."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ec, rsa
        from cryptography.hazmat.primitives.serialization import load_der_public_key
    except ImportError:  # pragma: no cover - only without the extra
        raise KeyError_("this server cannot check device keys (cryptography)") from None
    try:
        key = load_der_public_key(_b64(text))
    except ValueError:
        raise KeyError_("not a public key (base64 SubjectPublicKeyInfo, DER)") from None
    if algorithm == "RS256":
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size < MIN_RSA_BITS:
            raise KeyError_(f"the key must be RSA of {MIN_RSA_BITS} bits or more (RS256)")
        return key
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise KeyError_("the key must be EC P-256 (ES256)")
    return key


@dataclass
class ApprovalKey:
    device_id: int
    user_id: int
    algorithm: str
    created_at: float


class ApprovalKeys:
    def __init__(
        self,
        store: Store,
        *,
        active_device: Callable[[int], Any],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.active_device = active_device  # the device if it is still paired, else None
        self.clock = clock

    def enrol(self, user_id: int, device_id: int, public_key: str, algorithm: str) -> ApprovalKey:
        if algorithm not in ALGORITHMS:
            raise KeyError_(f"the algorithm is one of {', '.join(ALGORITHMS)}")
        load_public_key(public_key, algorithm)  # refuses a key that does not match it
        self.store.execute(
            "INSERT INTO approval_keys (device_id, user_id, public_key, algorithm, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET user_id = "
            "excluded.user_id, public_key = excluded.public_key, algorithm = "
            "excluded.algorithm, created_at = excluded.created_at",
            (device_id, user_id, public_key.strip(), algorithm, self.clock()),
        )
        return ApprovalKey(device_id, user_id, algorithm, self.clock())

    def for_user(self, user_id: int) -> list[ApprovalKey]:
        rows = self.store.query(
            "SELECT * FROM approval_keys WHERE user_id = ? ORDER BY device_id", (user_id,)
        )
        return [
            ApprovalKey(r["device_id"], r["user_id"], r["algorithm"], r["created_at"])
            for r in rows
            if self.active_device(r["device_id"]) is not None
        ]

    def remove(self, user_id: int, device_id: int) -> bool:
        cursor = self.store.execute(
            "DELETE FROM approval_keys WHERE user_id = ? AND device_id = ?", (user_id, device_id)
        )
        return cursor.rowcount == 1

    def verify(self, user_id: int, device_id: int, pending: Any, signature: str) -> bool:
        """Whether this person's device signed this very action, with its enrolled key."""
        row = self.store.one(
            "SELECT * FROM approval_keys WHERE device_id = ? AND user_id = ?",
            (device_id, user_id),
        )
        if row is None or self.active_device(device_id) is None:
            return False
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec, padding

            key = load_public_key(row["public_key"], row["algorithm"])
            signed = message(pending.id, pending.summary, pending.expires_at)
            if row["algorithm"] == "RS256":
                key.verify(_b64(signature), signed, padding.PKCS1v15(), hashes.SHA256())
            else:
                key.verify(_b64(signature), signed, ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, KeyError_, ValueError):
            return False
        return True
