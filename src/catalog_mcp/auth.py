"""Authorization over HTTP — § 5 of the post.

Two pieces, because the SDK covers one half of § 5 and not the other:

- `JwtVerifier` checks a bearer token's signature, issuer, audience and expiry.
  The SDK uses it to answer `401` with the RFC 9728 `resource_metadata` pointer
  when a token is missing or fails.
- `DomainScopeMiddleware` answers `403 insufficient_scope` naming the one scope
  a request lacks, `catalog:{domain}:read`. The SDK only checks a fixed list of
  scopes for every request; which domain a request touches is in its JSON-RPC
  body, so this reads the body before the SDK does.

Over stdio neither runs: there is no token, and the host that started the
process is the authorization.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .server import DATASET_URI, DOMAIN_TOOLS, scope_for


class JwtVerifier:
    """Verifies RFC 9068 access tokens from one issuer, for one audience.

    The audience is this server's own URL (RFC 8707): a token minted for any
    other resource is refused, so a token cannot be replayed here from another
    service, and this server never passes a token on to anything else.
    """

    def __init__(
        self,
        public_key,
        *,
        issuer: str,
        audience: str,
        algorithms: Sequence[str] = ("ES256",),
    ):
        self._key = public_key
        self._issuer = issuer
        self._audience = audience
        self._algorithms = list(algorithms)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=self._algorithms,
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iss", "aud", "sub", "client_id"]},
            )
        except jwt.PyJWTError:
            # Any failure is a 401 from the SDK; which check failed is not the
            # caller's business.
            return None
        return AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=str(claims.get("scope", "")).split(),
            expires_at=claims["exp"],
            resource=self._audience,
            subject=claims["sub"],
            claims={"iss": claims["iss"]},
        )


def requested_domain(message: object) -> str | None:
    """The domain a JSON-RPC request is scoped to, or None if it is not scoped to one.

    `list_domains` and `find_datasets` are not here on purpose: they answer
    with the caller's domains only, which is filtering, not a refusal.
    """
    if not isinstance(message, dict):
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    if message.get("method") == "tools/call" and params.get("name") in DOMAIN_TOOLS:
        arguments = params.get("arguments")
        domain = arguments.get("domain") if isinstance(arguments, dict) else None
        return domain if isinstance(domain, str) else None
    if message.get("method") == "resources/read":
        match = DATASET_URI.match(str(params.get("uri", "")))
        return match["domain"] if match else None
    return None


class DomainScopeMiddleware:
    """`403 insufficient_scope` when a request names a domain the token has no scope for.

    A request without a valid token passes through untouched, so the SDK sends
    its `401`; the same verifier runs in both places, so they cannot disagree
    about what a valid token is. The handlers re-check the scope on every call
    as well — this layer exists so that the refusal is an HTTP status a client
    can act on (ask for the named scope), not an error inside a `200`.
    """

    def __init__(
        self,
        app: ASGIApp,
        verifier: TokenVerifier,
        *,
        resource_metadata_url: str,
        path: str = "/mcp",
    ):
        self.app = app
        self.verifier = verifier
        self.resource_metadata_url = resource_metadata_url
        self.path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.path:
            await self.app(scope, receive, send)
            return

        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > DEFAULT_MAX_REQUEST_BODY_SIZE:
                await _send(send, 413, {"error": "request body too large"})
                return

        try:
            domain = requested_domain(json.loads(body))
        except ValueError:
            domain = None  # not JSON: the SDK answers that with a parse error

        if domain is not None:
            token = await self._token(scope)
            if token is not None and scope_for(domain) not in token.scopes:
                await self._insufficient_scope(send, scope_for(domain))
                return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _token(self, scope: Scope) -> AccessToken | None:
        for name, value in scope["headers"]:
            if name == b"authorization":
                kind, _, credential = value.decode("latin-1").partition(" ")
                if kind.lower() == "bearer" and credential:
                    return await self.verifier.verify_token(credential)
        return None

    async def _insufficient_scope(self, send: Send, needed: str) -> None:
        challenge = (
            f'Bearer error="insufficient_scope", scope="{needed}", '
            f'resource_metadata="{self.resource_metadata_url}"'
        )
        await _send(
            send,
            403,
            {"error": "insufficient_scope", "error_description": f"Required scope: {needed}"},
            [(b"www-authenticate", challenge.encode())],
        )


async def _send(send: Send, status: int, payload: dict, headers: list | None = None) -> None:
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *(headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
