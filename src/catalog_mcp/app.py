"""The HTTP application: the server, the SDK's bearer-token checks, and the domain-scope layer."""

from __future__ import annotations

from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.auth.settings import AuthSettings
from starlette.types import ASGIApp

from .auth import DomainScopeMiddleware, JwtVerifier
from .catalog import Catalog
from .server import build_server

# Every token must carry this to reach the server at all; each domain then
# needs its own `catalog:{domain}:read` on top.
BASE_SCOPE = "catalog:read"


def build_http_app(
    public_key,
    *,
    issuer: str,
    resource_url: str,
    catalog: Catalog | None = None,
    algorithms: tuple[str, ...] = ("ES256",),
) -> ASGIApp:
    """`resource_url` is this server's own URL, ending in `/mcp`: the audience tokens must name."""
    verifier = JwtVerifier(public_key, issuer=issuer, audience=resource_url, algorithms=algorithms)
    auth = AuthSettings(
        issuer_url=issuer,
        resource_server_url=resource_url,
        required_scopes=[BASE_SCOPE],
        # The verifier reports the token's audience as its resource only after
        # checking it, so the SDK's comparison is a second check of the same thing.
        validate_token_resource=True,
    )
    server = build_server(catalog, auth=auth, token_verifier=verifier)
    # Stateless and JSON: under 2026-07-28 every request stands alone, which is
    # also what lets the scope check run per request rather than per session.
    app = server.streamable_http_app(stateless_http=True, json_response=True)
    return DomainScopeMiddleware(
        app,
        verifier,
        resource_metadata_url=str(build_resource_metadata_url(auth.resource_server_url)),
    )
