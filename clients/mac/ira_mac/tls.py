"""Certificates for https and wss, whichever Python runs the companion.

python.org's Python for macOS has no certificates until its "Install
Certificates" step runs, and then pairing fails with "certificate verify
failed". The companion does not depend on that step. It uses, in order:

* macOS's own trust store, through ``truststore`` (Python 3.10 and newer);
* Python's default, when it holds certificates (Apple's and Homebrew's do);
* ``certifi``'s bundle;
* macOS's ``/etc/ssl/cert.pem``.

``install.sh`` installs ``truststore`` and ``certifi`` next to ``websockets``.
"""

from __future__ import annotations

import ssl
from pathlib import Path

MAC_BUNDLE = Path("/etc/ssl/cert.pem")
# The same list where Linux keeps it (Debian and Ubuntu, then Fedora), for tests and CI.
OTHER_BUNDLES = (
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/etc/pki/tls/certs/ca-bundle.crt"),
)


def _has_certificates(context: ssl.SSLContext) -> bool:
    return bool(context.cert_store_stats().get("x509_ca"))


def context() -> ssl.SSLContext:
    """A client context that checks certificates against a real list of authorities."""
    try:
        import truststore  # type: ignore[import-not-found]

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except (ImportError, OSError, ssl.SSLError):
        pass
    default = ssl.create_default_context()
    if _has_certificates(default):
        return default
    bundles = []
    try:
        import certifi  # type: ignore[import-not-found]

        bundles.append(certifi.where())
    except ImportError:
        pass
    bundles += [str(path) for path in (MAC_BUNDLE, *OTHER_BUNDLES) if path.is_file()]
    for bundle in bundles:
        try:
            return ssl.create_default_context(cafile=bundle)
        except (OSError, ssl.SSLError):
            continue
    return default


def reason(exc: BaseException) -> str:
    """Why a connection failed, in words, with what to do about a certificate problem."""
    cause = getattr(exc, "reason", exc)
    if isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(cause):
        return (
            "certificate verify failed: this Python has no list of certificate authorities. "
            "Run ./install.sh again; it installs one for the companion"
        )
    text = str(getattr(cause, "strerror", None) or cause or type(exc).__name__)
    return " ".join(text.split())[:160]
