"""HTTP plumbing shared by model, speech and voice providers.

Auth is a small object that returns headers for the exact bytes being sent,
so header keys and AWS SigV4 (which signs the body) share one code path.
Every error leaving this module has had the credentials scrubbed from it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

import httpx

from ira.models.base import ErrorKind, ProviderError


class Auth(Protocol):
    def headers(self, method: str, url: str, body: bytes, content_type: str) -> dict[str, str]: ...

    def secrets(self) -> list[str]: ...


class NoAuth:
    def headers(self, method: str, url: str, body: bytes, content_type: str) -> dict[str, str]:
        return {}

    def secrets(self) -> list[str]:
        return []


class BearerAuth:
    def __init__(self, token: str) -> None:
        self._token = token

    def headers(self, method: str, url: str, body: bytes, content_type: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def secrets(self) -> list[str]:
        return [self._token]


class HeaderKeyAuth:
    """A key sent in a named header, e.g. ``x-api-key``."""

    def __init__(self, key: str, header: str = "x-api-key") -> None:
        self._key = key
        self._header = header

    def headers(self, method: str, url: str, body: bytes, content_type: str) -> dict[str, str]:
        return {self._header: self._key}

    def secrets(self) -> list[str]:
        return [self._key]


def scrub(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    return text


def classify_status(status: int, body: str) -> ErrorKind:
    lowered = body.lower()
    if status in (429, 503, 529) or any(
        word in lowered for word in ("overloaded", "throttl", "capacity", "rate limit")
    ):
        return "capacity"
    if status in (401, 403):
        return "auth"
    if status in (408, 504):
        return "timeout"
    if status >= 500:
        return "server"
    return "bad_request"


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value else None
    except ValueError:
        return None


class HttpClient:
    """POST JSON (or prepared bodies) to one base URL with one auth scheme."""

    def __init__(
        self,
        base_url: str,
        auth: Auth | None = None,
        *,
        headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        label: str = "provider",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth: Auth = auth or NoAuth()
        self.extra_headers = headers or {}
        self.label = label
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    def _error(self, message: str, **kwargs: Any) -> ProviderError:
        return ProviderError(scrub(f"{self.label}: {message}", self.auth.secrets()), **kwargs)

    def _request(
        self, path: str, body: bytes, content_type: str, timeout: float, accept: str
    ) -> httpx.Request:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": content_type, "Accept": accept, **self.extra_headers}
        headers.update(self.auth.headers("POST", url, body, content_type))
        return self.client.build_request(
            "POST", url, content=body, headers=headers, timeout=timeout
        )

    def _raise_for(self, response: httpx.Response, body: str) -> None:
        if response.status_code < 400:
            return
        snippet = " ".join(body.split())[:300]
        raise self._error(
            f"HTTP {response.status_code}: {snippet}",
            kind=classify_status(response.status_code, body),
            status=response.status_code,
            retry_after=_retry_after(response),
        )

    async def post(
        self,
        path: str,
        body: bytes,
        *,
        content_type: str = "application/json",
        accept: str = "application/json",
        timeout: float = 60.0,
    ) -> bytes:
        request = self._request(path, body, content_type, timeout, accept)
        try:
            response = await self.client.send(request)
        except httpx.TimeoutException as exc:
            raise self._error(f"timed out ({type(exc).__name__})", kind="timeout") from None
        except httpx.HTTPError as exc:
            raise self._error(f"network error ({type(exc).__name__})", kind="network") from None
        self._raise_for(response, response.text if response.status_code >= 400 else "")
        return response.content

    async def post_json(
        self, path: str, payload: dict[str, Any], *, timeout: float = 60.0
    ) -> dict[str, Any]:
        raw = await self.post(path, json.dumps(payload).encode(), timeout=timeout)
        try:
            data = json.loads(raw)
        except ValueError:
            raise self._error("response was not JSON", kind="server") from None
        if not isinstance(data, dict):
            raise self._error("response was not a JSON object", kind="server")
        return data

    async def post_multipart(
        self,
        path: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        # Build the body first so any auth scheme can see the exact bytes.
        prepared = httpx.Request("POST", "http://x", data=data, files=files)
        body = prepared.read()
        raw = await self.post(
            path, body, content_type=prepared.headers["Content-Type"], timeout=timeout
        )
        return json.loads(raw)

    @asynccontextmanager
    async def stream_lines(
        self, path: str, payload: dict[str, Any], *, timeout: float = 60.0
    ) -> AsyncIterator[AsyncIterator[str]]:
        """POST JSON and yield the response body line by line (for SSE)."""
        body = json.dumps(payload).encode()
        request = self._request(path, body, "application/json", timeout, "text/event-stream")
        try:
            response = await self.client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise self._error(f"timed out ({type(exc).__name__})", kind="timeout") from None
        except httpx.HTTPError as exc:
            raise self._error(f"network error ({type(exc).__name__})", kind="network") from None
        try:
            if response.status_code >= 400:
                await response.aread()
                self._raise_for(response, response.text)
            yield self._lines(response)
        finally:
            await response.aclose()

    async def _lines(self, response: httpx.Response) -> AsyncIterator[str]:
        try:
            async for line in response.aiter_lines():
                yield line
        except httpx.TimeoutException as exc:
            raise self._error(f"stream timed out ({type(exc).__name__})", kind="timeout") from None
        except httpx.HTTPError as exc:
            raise self._error(f"stream broke ({type(exc).__name__})", kind="network") from None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


async def sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Yield the ``data:`` payloads of a server-sent-event stream."""
    async for line in lines:
        if line.startswith("data:"):
            yield line[5:].strip()
