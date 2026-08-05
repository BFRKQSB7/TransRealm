"""Stdlib HTTP transport implementing the Transport protocol.

The project ships with zero runtime dependencies (green build first). This
transport uses :mod:`urllib.request` for the actual HTTP exchange and runs the
synchronous call in a worker thread via :func:`asyncio.to_thread` so it honors
the async :class:`~transrealm.adapters.protocol.Transport` contract.

Redirects are handled by this transport rather than by urllib so the
credential boundary can be enforced: same-origin hops keep every header,
while a hop that changes scheme/host/port drops sensitive headers
(Authorization, Cookie, Proxy-Authorization). A redirect that downgrades from
HTTPS to HTTP therefore never carries credentials. A local, explicitly
configured HTTP endpoint is still usable directly.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message

from transrealm.adapters.errors import (
    AdapterConnectionError,
    AdapterResponseError,
    AdapterTimeoutError,
)
from transrealm.adapters.protocol import TransportResponse

_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never auto-follow redirects so the transport owns the redirect loop."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class StdlibHttpTransport:
    """Transport protocol backed by ``urllib.request``.

    Args:
        base_url: Origin the adapter posts to (the ProviderConnection
            endpoint). ``path`` arguments are joined onto this URL. When the
            endpoint ends with ``/v1`` and the request path also starts with
            ``/v1/`` -- the common OpenAI-compatible layout -- the prefix is
            used once rather than doubled.
        max_redirects: Upper bound on redirects followed per request. When
            exceeded, the last 3xx response is returned unchanged.
    """

    def __init__(
        self,
        *,
        base_url: str,
        max_redirects: int = 5,
        max_response_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("base_url must be an HTTP/HTTPS URL without userinfo.")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("base_url port is invalid.") from exc
        if max_redirects < 0:
            raise ValueError(f"max_redirects must be non-negative: {max_redirects}")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive.")
        self._base_url = base_url.rstrip("/")
        self._max_redirects = max_redirects
        self._max_response_bytes = max_response_bytes
        # ProxyHandler({}) disables environment proxy capture so requests to
        # the configured endpoint go directly; proxy configuration is a
        # non-goal for Phase 0.
        self._opener = urllib.request.build_opener(
            _NoRedirect(),
            urllib.request.ProxyHandler({}),
        )

    async def post(
        self,
        path: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> TransportResponse:
        """POST ``body`` as JSON to ``path`` and return the raw response."""
        return await asyncio.to_thread(self._post_sync, path, headers, body, timeout)

    def _post_sync(
        self,
        path: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> TransportResponse:
        started = time.monotonic()
        deadline = started + timeout
        url = self._join_url(path)
        data = json.dumps(body).encode("utf-8")
        current_headers = dict(headers)

        for hop in range(self._max_redirects + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AdapterTimeoutError("Request timed out.")
            request = urllib.request.Request(
                url,
                data=data,
                headers=current_headers,
                method="POST",
            )
            try:
                with self._opener.open(request, timeout=remaining) as response:
                    return TransportResponse(
                        status_code=response.status,
                        headers=self._normalize_headers(response.headers),
                        body=self._read_limited(response, deadline),
                        elapsed_seconds=time.monotonic() - started,
                    )
            except urllib.error.HTTPError as exc:
                status = exc.code
                resp_headers = self._normalize_headers(exc.headers)
                location = resp_headers.get("location")
                if status in _REDIRECT_STATUSES and location:
                    if hop >= self._max_redirects:
                        return self._error_response(exc, status, resp_headers, deadline, started)
                    next_url = urllib.parse.urljoin(url, location)
                    if urllib.parse.urlparse(next_url).scheme.lower() not in {"http", "https"}:
                        return self._error_response(exc, status, resp_headers, deadline, started)
                    if not self._same_origin_pair(url, next_url):
                        current_headers = self._without_sensitive(current_headers)
                    url = next_url
                    continue
                return self._error_response(exc, status, resp_headers, deadline, started)
            except urllib.error.URLError as exc:
                if self._is_timeout(exc.reason):
                    raise AdapterTimeoutError("Request timed out.", cause=exc) from exc
                raise AdapterConnectionError(
                    f"HTTP request failed: {type(exc.reason).__name__}",
                    cause=exc,
                ) from exc
            except TimeoutError as exc:
                raise AdapterTimeoutError("Request timed out.", cause=exc) from exc
            except http.client.HTTPException as exc:
                raise AdapterConnectionError(
                    f"HTTP request failed: {type(exc).__name__}",
                    cause=exc,
                ) from exc
            except OSError as exc:
                raise AdapterConnectionError(
                    f"HTTP request failed: {type(exc).__name__}",
                    cause=exc,
                ) from exc

        raise AdapterConnectionError("Exhausted redirects without a response.")

    def _error_response(
        self,
        exc: urllib.error.HTTPError,
        status: int,
        headers: dict[str, str],
        deadline: float,
        started: float,
    ) -> TransportResponse:
        """Turn an HTTPError into a bounded TransportResponse."""
        return TransportResponse(
            status_code=status,
            headers=headers,
            body=self._read_limited(exc, deadline),
            elapsed_seconds=time.monotonic() - started,
        )

    def _read_limited(self, response: object, deadline: float) -> bytes:
        headers = getattr(response, "headers")
        content_length = headers.get("Content-Length")
        expected_length: int | None = None
        if content_length is not None:
            try:
                expected_length = int(content_length)
                if expected_length > self._max_response_bytes:
                    raise AdapterResponseError("Provider response exceeds configured size limit.")
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        reader = getattr(response, "read")
        while True:
            if time.monotonic() >= deadline:
                raise AdapterTimeoutError("Request timed out.")
            chunk = reader(min(64 * 1024, self._max_response_bytes - total + 1))
            if not chunk:
                if expected_length is not None and total != expected_length:
                    raise AdapterConnectionError("Provider response was truncated.")
                return b"".join(chunks)
            total += len(chunk)
            if total > self._max_response_bytes:
                raise AdapterResponseError("Provider response exceeds configured size limit.")
            chunks.append(chunk)

    def _join_url(self, path: str) -> str:
        base = self._base_url
        if base.endswith("/v1") and path.startswith("/v1"):
            base = base[: -len("/v1")]
        return base + "/" + path.lstrip("/")

    def _same_origin(self, url: str) -> bool:
        """True when ``url`` shares scheme, host and port with the base URL."""
        base = urllib.parse.urlparse(self._base_url)
        target = urllib.parse.urlparse(url)
        if base.scheme.lower() != target.scheme.lower():
            return False
        if (base.hostname or "") != (target.hostname or ""):
            return False
        return self._port(base) == self._port(target)

    @classmethod
    def _same_origin_pair(cls, current_url: str, next_url: str) -> bool:
        current = urllib.parse.urlparse(current_url)
        target = urllib.parse.urlparse(next_url)
        if current.scheme.lower() != target.scheme.lower():
            return False
        if (current.hostname or "") != (target.hostname or ""):
            return False
        return cls._port(current) == cls._port(target)

    @staticmethod
    def _port(parsed: urllib.parse.ParseResult) -> int:
        if parsed.port is not None:
            return parsed.port
        return 443 if parsed.scheme.lower() == "https" else 80

    def _without_sensitive(self, headers: dict[str, str]) -> dict[str, str]:
        return {
            name: value
            for name, value in headers.items()
            if name.lower() not in _SENSITIVE_HEADERS
        }

    @staticmethod
    def _normalize_headers(headers: Message[str, str]) -> dict[str, str]:
        return {name.lower(): value for name, value in headers.items()}

    @staticmethod
    def _is_timeout(reason: object) -> bool:
        if isinstance(reason, TimeoutError):
            return True
        if isinstance(reason, str):
            return "timed out" in reason.lower()
        return False
