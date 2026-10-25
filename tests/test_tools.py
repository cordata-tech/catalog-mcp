"""The tools and resources over stdio's model: no token, so every domain is visible."""

from __future__ import annotations

import json

import pytest
from mcp import Client

from catalog_mcp.server import build_server

pytestmark = pytest.mark.anyio

TOOLS = {
    "list_domains",
    "get_dataset",
    "resolve_lf_tag",
    "check_grant_expression",
    "find_datasets",
    "get_consumers",
}


@pytest.fixture
async def client():
    async with Client(build_server()) as c:
        yield c


async def test_the_six_tools_and_nothing_else(client):
    assert {t.name for t in (await client.list_tools()).tools} == TOOLS


async def test_output_schemas_come_from_the_runtimes_models(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    schema = tools["get_dataset"].output_schema
    assert set(schema["properties"]) == {"metadata", "contract", "columns", "lineage"}
    # Derived from pipeline_runtime.descriptor, not restated: the field names
    # and the "forbid extras" posture are the runtime's.
    assert {"Metadata", "Contract"} <= set(schema["$defs"])
    assert set(schema["$defs"]["Contract"]["properties"]) >= {"lf_tags"}


async def test_get_dataset_returns_effective_column_tags(client):
    result = await client.call_tool(
        "get_dataset", {"domain": "fraud", "table": "transactions_scored"}
    )
    columns = {c["name"]: c["lf_tags"] for c in result.structured_content["columns"]}
    assert columns["iban"]["sensitivity"] == "high"


async def test_an_unknown_dataset_is_an_error(client):
    result = await client.call_tool("get_dataset", {"domain": "fraud", "table": "nope"})
    assert result.is_error


async def test_a_misspelt_tag_is_an_error_listing_the_allowed_values(client):
    result = await client.call_tool("resolve_lf_tag", {"tags": {"sensitivity": "hgh"}})
    assert result.is_error
    assert "allowed" in result.content[0].text and "'high'" in result.content[0].text


async def check(client, expression: dict) -> dict:
    result = await client.call_tool(
        "check_grant_expression",
        {"domain": "fraud", "table": "transactions_scored", "expression": expression},
    )
    return result.structured_content


async def test_the_reference_analyst_grant_reaches_nothing_in_a_high_table(client):
    # The analyst role from fabric-mesh-on-aws § 3: every sensitivity but high.
    analyst = {
        "domain": ["fraud"],
        "sensitivity": ["public", "internal", "confidential"],
        "residency": ["eu"],
    }
    assert await check(client, analyst) == {"reaches": False, "columns": []}


async def test_a_grant_that_includes_high_reaches_every_column(client):
    found = await check(client, {"domain": ["fraud"], "sensitivity": ["high"]})
    assert found["reaches"] is True
    assert len(found["columns"]) == 10


async def test_a_grant_with_a_misspelt_value_is_an_error(client):
    result = await client.call_tool(
        "check_grant_expression",
        {
            "domain": "fraud",
            "table": "transactions_scored",
            "expression": {"residency": ["europe"]},
        },
    )
    assert result.is_error


async def test_find_datasets_answers_which_datasets_hold_customer_data(client):
    result = await client.call_tool("find_datasets", {"tags": {"subject_type": "customer"}})
    found = {(d["domain"], d["table"]) for d in result.structured_content["datasets"]}
    assert ("fraud", "transactions_scored") in found


async def test_the_ontology_is_one_resource_and_the_dataset_a_template(client):
    resources = [str(r.uri) for r in (await client.list_resources()).resources]
    templates = [
        t.uri_template for t in (await client.list_resource_templates()).resource_templates
    ]
    assert resources == ["cordata://ontology/lf-tags"]
    assert templates == ["cordata://domain/{domain}/dataset/{table}"]


async def test_the_dataset_template_reads(client):
    read = await client.read_resource("cordata://domain/finance/dataset/merchant_settlement_daily")
    assert json.loads(read.contents[0].text)["metadata"]["domain"] == "finance"


async def test_the_ontology_resource_is_the_runtimes(client):
    from pipeline_runtime import policy

    read = await client.read_resource("cordata://ontology/lf-tags")
    assert json.loads(read.contents[0].text) == {k: list(v) for k, v in policy.ontology().items()}


# Read-only, enforced: § 4 of the post says the hints enforce nothing, so these
# test what happens when a client ignores them.


async def test_every_tool_is_annotated_read_only(client):
    for tool in (await client.list_tools()).tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


async def test_a_write_returns_an_error_not_a_hint(client):
    result = await client.call_tool(
        "set_lf_tag",
        {"domain": "fraud", "table": "transactions_scored", "tags": {"sensitivity": "public"}},
    )
    assert result.is_error
    # And nothing changed for the next caller.
    after = await client.call_tool(
        "get_dataset", {"domain": "fraud", "table": "transactions_scored"}
    )
    iban = next(c for c in after.structured_content["columns"] if c["name"] == "iban")
    assert iban["lf_tags"]["sensitivity"] == "high"


async def test_changing_a_returned_answer_does_not_change_the_next_one(client):
    first = await client.call_tool(
        "get_dataset", {"domain": "fraud", "table": "transactions_scored"}
    )
    first.structured_content["columns"].clear()
    second = await client.call_tool(
        "get_dataset", {"domain": "fraud", "table": "transactions_scored"}
    )
    assert len(second.structured_content["columns"]) == 10
