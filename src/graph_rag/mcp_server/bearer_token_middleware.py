from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerTokenMiddleware:
    """Rejects HTTP requests without a matching `Authorization: Bearer <token>` header.

    Cheap defense in depth for the loopback-only MCP server; becomes
    mandatory if the bind address is ever widened beyond 127.0.0.1.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self._is_authorized(scope):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)

    def _is_authorized(self, scope: Scope) -> bool:
        headers = dict(scope["headers"])
        value = headers.get(b"authorization", b"").decode("latin-1")
        return value == f"Bearer {self._token}"
