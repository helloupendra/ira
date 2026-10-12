"""Hashing for the action PIN, API tokens and pairing codes.

* The PIN is short and guessable offline, so it gets a salted, slow PBKDF2
  hash. The iteration count is stored with the hash and can be raised later.
* API tokens and pairing codes are long random strings, so a fast SHA-256 is
  enough: there is nothing to brute-force.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

PIN_ITERATIONS = 600_000
# The one place the PIN length rule lives; the API, the CLI and /v1/me/pin read it here.
PIN_MIN_LENGTH = 4
PIN_MAX_LENGTH = 12
PIN_PATTERN = re.compile(rf"\d{{{PIN_MIN_LENGTH},{PIN_MAX_LENGTH}}}")
PIN_RULE = f"{PIN_MIN_LENGTH} to {PIN_MAX_LENGTH} digits"


def valid_pin(pin: str) -> bool:
    return bool(PIN_PATTERN.fullmatch(pin))


def looks_like_pin(text: str) -> bool:
    """A message that is only a PIN's digits: treated as a PIN, never sent to a model."""
    return valid_pin(text.strip())


def hash_pin(pin: str, *, iterations: int = PIN_ITERATIONS, salt: bytes | None = None) -> str:
    if not valid_pin(pin):
        raise ValueError(f"the PIN must be {PIN_RULE}")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)
    salt_b64 = base64.b64encode(salt).decode()
    digest_b64 = base64.b64encode(digest).decode()
    return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_api_token() -> str:
    return "ira_t_" + secrets.token_urlsafe(32)


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_hex(8)
