"""`get_erasure_scope`: where a subject type is registered, for an erasure to start from (#3)."""

from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from mcp import Client

from catalog_mcp.catalog import Catalog
from catalog_mcp.server import build_server

FRAUD = "catalog:read catalog:fraud:read"
FRAUD_AND_POLICY = "catalog:read catalog:fraud:read catalog:policy:read"


@pytest.fixture
async def client():
    async with Client(build_server()) as c:
        yield c


async def scope(client, subject_type: str = "customer") -> dict:
    result = await client.call_tool("get_erasure_scope", {"subject_type": subject_type})
    assert not result.is_error, result.content[0].text
    return result.structured_content


def over_http(rpc, token: str, subject_type: str = "customer") -> dict:
    params = {"name": "get_erasure_scope", "arguments": {"subject_type": subject_type}}
    response = rpc("tools/call", params, token=token)
    assert response.status_code == 200
    return response.json()["result"]["structuredContent"]


@pytest.mark.anyio
async def test_the_iban_case_finds_both_datasets_with_owner_columns_and_readers(client):
    """The README's walkthrough: customer data, and the IBAN columns inside it."""
    found = await scope(client)
    by_table = {d["table"]: d for d in found["datasets"]}
    assert sorted(by_table) == ["claims_deduped", "transactions_scored"]

    scored = by_table["transactions_scored"]
    assert scored["domain"] == "fraud" and scored["owner"] == "fraud-data@example.com"
    assert "iban" in scored["columns"]
    assert "claimant_iban" in by_table["claims_deduped"]["columns"]
    assert scored["consumers"] == [], "nothing reads the scored table"
    assert found["complete"] is True


@pytest.mark.anyio
async def test_the_table_the_ibans_came_from_is_named_but_not_called_customer_data(client):
    scored = next(
        d for d in (await scope(client))["datasets"] if d["table"] == "transactions_scored"
    )
    upstream = scored["reads_from"]
    assert upstream["lineage"] == {"namespace": "cordata://fraud", "name": "fraud_raw.transactions"}
    assert upstream["classified"] is False
    assert upstream["columns"] == [], "unclassified, so no column is tagged customer"
    assert {c["pipeline"] for c in upstream["consumers"]} == {
        "transactions-scored-daily",
        "merchant-settlement-daily",
    }


@pytest.mark.anyio
async def test_no_example_dataset_records_retention(client):
    """`null` is "not recorded"; nothing fills it with a default."""
    assert {d["retention"] for d in (await scope(client))["datasets"]} == {None}


@pytest.mark.anyio
async def test_a_retention_tag_is_reported_as_tagged(tmp_path):
    example = tmp_path / "example"
    shutil.copytree(
        Path(files("pipeline_runtime.example").joinpath("domains")), example / "domains"
    )
    path = example / "domains/fraud/pipelines/transactions_scored.yml"
    raw = yaml.safe_load(path.read_text())
    raw["contract"]["lf_tags"]["retention"] = "10y"
    path.write_text(yaml.safe_dump(raw))

    async with Client(build_server(Catalog(example=example))) as c:
        found = await scope(c)
    retention = {d["table"]: d["retention"] for d in found["datasets"]}
    assert retention == {"transactions_scored": "10y", "claims_deduped": None}


@pytest.mark.anyio
async def test_a_subject_type_outside_the_ontology_is_an_error(client):
    result = await client.call_tool("get_erasure_scope", {"subject_type": "customers"})
    assert result.is_error
    assert "'customer'" in result.content[0].text


@pytest.mark.anyio
async def test_the_description_says_what_it_does_not_answer(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    description = tools["get_erasure_scope"].description
    assert "never rows" in description
    assert "not interpreted" in description


@pytest.mark.anyio
async def test_the_output_schema_comes_from_models(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    schema = tools["get_erasure_scope"].output_schema
    assert set(schema["properties"]) == {"subject_type", "datasets", "complete"}
    assert {"ScopeEntry", "Upstream", "Consumer", "Lineage"} <= set(schema["$defs"])


def test_a_domain_the_caller_may_not_read_is_left_out_and_the_result_says_so(rpc, mint):
    found = over_http(rpc, mint(FRAUD))
    assert [(d["domain"], d["table"]) for d in found["datasets"]] == [
        ("fraud", "transactions_scored")
    ]
    assert found["complete"] is False


def test_with_every_matching_domain_granted_the_result_is_complete(rpc, mint):
    found = over_http(rpc, mint(FRAUD_AND_POLICY))
    assert len(found["datasets"]) == 2 and found["complete"] is True


def test_readers_in_domains_the_caller_may_not_read_are_listed(rpc, mint):
    """A fraud-only token still sees finance's read of the table the IBANs came from."""
    [scored] = over_http(rpc, mint(FRAUD))["datasets"]
    assert {c["domain"] for c in scored["reads_from"]["consumers"]} == {"fraud", "finance"}
