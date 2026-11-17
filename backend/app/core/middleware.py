"""Request context middleware: request ID + one access-log line per request.

Written as plain ASGI middleware (not BaseHTTPMiddleware) so it adds no overhead and
the request ID stays visible to the error handlers, even for crashes.
"""

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.logging import request_id_ctx

logger = logging.getLogger("app.access")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        # Accept a caller-provided ID (e.g. from Nginx) only if it looks sane.
        request_id = incoming if 0 < len(incoming) <= 64 else uuid.uuid4().hex
        request_id_ctx.set(request_id)

        status_code = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "%s %s %s",
                scope["method"],
                scope["path"],
                status_code,
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": (scope.get("client") or ("-",))[0],
                },
            )
            # No request_id_ctx.reset() here on purpose: the 500 handler runs *outside*
            # this middleware (in Starlette's ServerErrorMiddleware) and still needs the ID.
            # Each request runs in its own asyncio task, so the value cannot leak.


SECURITY_HEADERS = [
    # Browsers must not guess content types (stops some XSS via uploaded files).
    (b"x-content-type-options", b"nosniff"),
    # The API is never meant to be framed (clickjacking protection).
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    # JSON responses need no scripts/styles; Swagger UI (/docs) is exempt below.
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    """Adds standard security headers to every API response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = scope["path"] in ("/docs", "/redoc", "/docs/oauth2-redirect")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                for name, value in SECURITY_HEADERS:
                    if is_docs and name == b"content-security-policy":
                        continue  # Swagger UI loads its JS/CSS from a CDN
                    headers.append((name, value))
                if settings.is_production:  # HSTS only makes sense over HTTPS
                    headers.append(HSTS)
            await send(message)

        await self.app(scope, receive, send_wrapper)
