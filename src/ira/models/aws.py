"""AWS SigV4 request signing for Amazon Bedrock's Mantle endpoint.

Mantle serves an OpenAI-compatible ``/v1/chat/completions`` at
``https://bedrock-mantle.<region>.api.aws``. Requests are signed with
botocore's default credential chain (environment, shared config, SSO, or an
instance/task role), so no key is ever written to Ira's config.

Needs the optional extra: ``pip install "ira-assistant[aws]"``.
"""

from __future__ import annotations

from typing import Any

from ira.models.base import ProviderError

MANTLE_SERVICE = "bedrock-mantle"


def mantle_base_url(region: str) -> str:
    return f"https://bedrock-mantle.{region}.api.aws/v1"


def _botocore() -> Any:
    try:
        import botocore.session
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError('AWS signing needs botocore: pip install "ira-assistant[aws]"') from exc
    return botocore


class SigV4Auth:
    """Signs each request body with SigV4. Credentials refresh on every call."""

    def __init__(self, region: str, service: str = MANTLE_SERVICE, session: Any = None) -> None:
        botocore = _botocore()
        self.region = region
        self.service = service
        self._session = session or botocore.session.get_session()

    def headers(self, method: str, url: str, body: bytes, content_type: str) -> dict[str, str]:
        from botocore.auth import SigV4Auth as BotoSigV4
        from botocore.awsrequest import AWSRequest

        credentials = self._session.get_credentials()
        if credentials is None:
            raise ProviderError(
                "no AWS credentials found (environment, profile or instance role)", kind="auth"
            )
        request = AWSRequest(
            method=method, url=url, data=body, headers={"Content-Type": content_type}
        )
        BotoSigV4(credentials.get_frozen_credentials(), self.service, self.region).add_auth(request)
        return {k: v for k, v in request.headers.items() if k.lower() != "content-type"}

    def secrets(self) -> list[str]:
        # Signatures are per request and the secret key never enters a header.
        return []
