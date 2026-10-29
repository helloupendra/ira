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


# Digits said as words, as speech-to-text writes them: English, Hindi in Latin letters and
# in Devanagari. ("no" and "do" are left out of the Latin ones only when ambiguous: "do"
# counts as two only among other digits.)
NUMBER_WORDS = {
    **dict.fromkeys(("zero", "oh", "shunya", "sunya", "शून्य", "जीरो"), "0"),
    **dict.fromkeys(("one", "ek", "एक", "वन"), "1"),
    **dict.fromkeys(("two", "do", "दो", "टू"), "2"),
    **dict.fromkeys(("three", "teen", "tin", "तीन", "थ्री"), "3"),
    **dict.fromkeys(("four", "char", "chaar", "चार", "फोर"), "4"),
    **dict.fromkeys(("five", "paanch", "panch", "पांच", "पाँच", "फाइव"), "5"),
    **dict.fromkeys(("six", "chhe", "chhah", "che", "छह", "छः", "छे", "सिक्स"), "6"),
    **dict.fromkeys(("seven", "saat", "sat", "सात", "सेवन"), "7"),
    **dict.fromkeys(("eight", "aath", "आठ", "एट"), "8"),
    **dict.fromkeys(("nine", "nau", "नौ", "नाइन"), "9"),
}
PIN_WORDS = {"pin", "पिन", "mera", "meri", "my", "is", "hai", "है", "मेरा", "मेरी"}
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_SEPARATORS = re.compile(r"[\s.,;:!?'\"()\[\]{}\-–—_/।]+")


def spoken_digits(text: str) -> str | None:
    """The digits of a message made only of digits and digit words ("4321.", "1 2 3 4",
    "ek do teen char", "मेरा पिन चार तीन दो एक है"), else None."""
    tokens = [t for t in _SEPARATORS.split(text.translate(_DEVANAGARI_DIGITS).lower()) if t]
    digits = []
    for token in tokens:
        if token.isdigit():
            digits.append(token)
        elif token in NUMBER_WORDS:
            digits.append(NUMBER_WORDS[token])
        elif token not in PIN_WORDS:
            return None
    return "".join(digits) or None


def looks_like_pin(text: str) -> bool:
    """A message that is a PIN, typed or spoken (digits, or digit words in English or
    Hindi, with nothing else but "my PIN is"): never sent to a model, never stored."""
    digits = spoken_digits(text)
    return digits is not None and valid_pin(digits)


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
