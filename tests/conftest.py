"""A throwaway token issuer: a key pair made per test session, no real IdP."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.testclient import TestClient

from catalog_mcp import PROTOCOL_REVISION
from catalog_mcp.app import build_http_app

ISSUER = "https://issuer.test"
RESOURCE = "http://127.0.0.1:8000/mcp"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def issuer_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="session")
def mint(issuer_key):
    def mint(scope: str, *, aud=RESOURCE, iss=ISSUER, key=None, ttl=300) -> str:
        now = int(time.time())
        claims = {
            "iss": iss,
            "aud": aud,
            "sub": "analyst-1",
            "client_id": "test-client",
            "scope": scope,
            "iat": now,
            "exp": now + ttl,
        }
        return jwt.encode(claims, key or issuer_key, algorithm="ES256")

    return mint


class Rpc:
    """Posts one 2026-07-28 request, with its `_meta` envelope and mirrored headers."""

    def __init__(self, client: TestClient):
        self.client = client
        self.next_id = 0

    def __call__(self, method: str, params: dict | None = None, token: str | None = None):
        self.next_id += 1
        params = dict(params or {})
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": PROTOCOL_REVISION,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_REVISION,
            "Mcp-Method": method,
        }
        if method == "tools/call":
            headers["Mcp-Name"] = params["name"]
            # The `x-mcp-header` mirror on `domain`: a client must send it, and
            # the SDK refuses a body whose argument has no matching header.
            if "domain" in params.get("arguments", {}):
                headers["Mcp-Param-Domain"] = params["arguments"]["domain"]
        elif method == "resources/read":
            headers["Mcp-Name"] = params["uri"]
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        return self.client.post("/mcp", json=body, headers=headers)


@pytest.fixture
def rpc(issuer_key):
    app = build_http_app(issuer_key.public_key(), issuer=ISSUER, resource_url=RESOURCE)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield Rpc(client)
