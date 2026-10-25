"""§ 5 of the post, one test per behaviour the #26 acceptance names."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.testclient import TestClient

from catalog_mcp.app import build_http_app
from catalog_mcp.auth import JwtVerifier

from .conftest import ISSUER, RESOURCE, Rpc

METADATA = "http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"
FRAUD = "catalog:read catalog:fraud:read"


def get_dataset(domain: str, table: str) -> dict:
    return {"name": "get_dataset", "arguments": {"domain": domain, "table": table}}


def test_no_token_is_401_pointing_at_the_resource_metadata(rpc):
    response = rpc("tools/list")
    assert response.status_code == 401
    assert f'resource_metadata="{METADATA}"' in response.headers["www-authenticate"]


def test_the_resource_metadata_names_this_server_and_its_one_issuer(rpc):
    metadata = rpc.client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert metadata["resource"] == RESOURCE
    assert metadata["authorization_servers"] == [ISSUER]


def test_a_token_for_another_audience_is_refused(rpc, mint):
    token = mint(FRAUD, aud="https://some-other-service.test/mcp")
    assert rpc("tools/list", token=token).status_code == 401


def test_a_token_from_another_issuer_is_refused(rpc, mint):
    # Signed with the right key, so only the issuer check can catch it.
    assert rpc("tools/list", token=mint(FRAUD, iss="https://elsewhere.test")).status_code == 401


def test_a_token_signed_by_another_key_is_refused(rpc, mint):
    stranger = ec.generate_private_key(ec.SECP256R1())
    assert rpc("tools/list", token=mint(FRAUD, key=stranger)).status_code == 401


def test_an_expired_token_is_refused(rpc, mint):
    assert rpc("tools/list", token=mint(FRAUD, ttl=-60)).status_code == 401


def test_a_token_without_the_base_scope_is_403(rpc, mint):
    response = rpc("tools/list", token=mint("catalog:fraud:read"))
    assert response.status_code == 403
    assert 'error="insufficient_scope"' in response.headers["www-authenticate"]


def test_a_domain_out_of_scope_is_403_naming_the_scope_not_an_empty_answer(rpc, mint):
    response = rpc("tools/call", get_dataset("policy", "claims_deduped"), token=mint(FRAUD))
    assert response.status_code == 403
    challenge = response.headers["www-authenticate"]
    assert 'error="insufficient_scope"' in challenge
    assert 'scope="catalog:policy:read"' in challenge
    assert f'resource_metadata="{METADATA}"' in challenge


def test_a_dataset_resource_out_of_scope_is_403(rpc, mint):
    uri = "cordata://domain/policy/dataset/claims_deduped"
    response = rpc("resources/read", {"uri": uri}, token=mint(FRAUD))
    assert response.status_code == 403
    assert 'scope="catalog:policy:read"' in response.headers["www-authenticate"]


def test_the_same_token_is_checked_again_on_every_call(rpc, mint):
    token = mint(FRAUD)
    allowed = rpc("tools/call", get_dataset("fraud", "transactions_scored"), token=token)
    assert allowed.status_code == 200
    assert allowed.json()["result"]["structuredContent"]["metadata"]["domain"] == "fraud"
    # Having been let in once grants nothing for the next call.
    refused = rpc("tools/call", get_dataset("policy", "claims_deduped"), token=token)
    assert refused.status_code == 403


def test_lists_show_only_the_callers_domains(rpc, mint):
    response = rpc("tools/call", {"name": "list_domains", "arguments": {}}, token=mint(FRAUD))
    domains = response.json()["result"]["structuredContent"]["domains"]
    assert [d["name"] for d in domains] == ["fraud"]


def test_find_datasets_shows_only_the_callers_domains(rpc, mint):
    params = {"name": "find_datasets", "arguments": {"tags": {"subject_type": "customer"}}}
    response = rpc("tools/call", params, token=mint(FRAUD))
    found = response.json()["result"]["structuredContent"]["datasets"]
    assert {d["domain"] for d in found} == {"fraud"}


def test_consumers_in_domains_the_caller_cannot_read_are_still_listed(rpc, mint):
    """A fraud-only token sees that finance reads fraud's table: the pin is
    declared on that table, and a producer cannot act on part of the list."""
    params = {"name": "get_consumers", "arguments": {"domain": "fraud", "table": "transactions"}}
    response = rpc("tools/call", params, token=mint(FRAUD))
    assert response.status_code == 200
    found = response.json()["result"]["structuredContent"]["consumers"]
    assert {c["domain"] for c in found} == {"fraud", "finance"}


def test_the_consumers_of_a_table_out_of_scope_are_403(rpc, mint):
    params = {"name": "get_consumers", "arguments": {"domain": "policy", "table": "claims"}}
    response = rpc("tools/call", params, token=mint(FRAUD))
    assert response.status_code == 403
    assert 'scope="catalog:policy:read"' in response.headers["www-authenticate"]


def test_list_results_are_cached_privately(rpc, mint):
    result = rpc("tools/list", token=mint(FRAUD)).json()["result"]
    assert result["cacheScope"] == "private"
    assert result["ttlMs"] == 60_000


def test_the_handler_refuses_even_without_the_http_layer(issuer_key, mint):
    """The second line: with the 403 middleware stripped off, the tool still refuses."""
    app = build_http_app(issuer_key.public_key(), issuer=ISSUER, resource_url=RESOURCE)
    with TestClient(app.app, base_url="http://127.0.0.1:8000") as client:
        response = Rpc(client)(
            "tools/call", get_dataset("policy", "claims_deduped"), token=mint(FRAUD)
        )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert "catalog:policy:read" in result["content"][0]["text"]


@pytest.mark.anyio
async def test_the_verifier_reports_the_audience_it_checked(issuer_key, mint):
    verifier = JwtVerifier(issuer_key.public_key(), issuer=ISSUER, audience=RESOURCE)
    token = await verifier.verify_token(mint(FRAUD))
    assert token is not None
    assert token.resource == RESOURCE
    assert token.scopes == ["catalog:read", "catalog:fraud:read"]
    assert token.subject == "analyst-1"
