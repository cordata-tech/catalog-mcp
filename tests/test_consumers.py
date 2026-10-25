"""`get_consumers`: who declares a read of a table, and the source tables it needs (#2)."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest
from mcp import Client
from pipeline_runtime.descriptor import TableRef
from pipeline_runtime.pins import readers

from catalog_mcp.catalog import Catalog
from catalog_mcp.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    async with Client(build_server()) as c:
        yield c


async def consumers(client, domain: str, table: str) -> dict:
    result = await client.call_tool("get_consumers", {"domain": domain, "table": table})
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_a_table_two_domains_read_lists_both_with_their_pins_and_owners(client):
    found = await consumers(client, "fraud", "transactions")
    assert found["consumers"] == [
        {
            "pipeline": "merchant-settlement-daily",
            "domain": "finance",
            "owner": "finance-data@example.com",
            "pins": 7,
            "descriptor": "domains/finance/pipelines/merchant_settlement.yml",
        },
        {
            "pipeline": "transactions-scored-daily",
            "domain": "fraud",
            "owner": "fraud-data@example.com",
            "pins": 7,
            "descriptor": "domains/fraud/pipelines/transactions_scored.yml",
        },
    ]
    assert found["lineage"] == {"namespace": "cordata://fraud", "name": "fraud_raw.transactions"}


async def test_the_list_is_the_runtimes_own():
    """Not a second derivation: the same descriptors `pins.readers()` returns."""
    catalog = Catalog()
    ref = TableRef(database="fraud_raw", table="transactions")
    domains = Path(files("pipeline_runtime.example").joinpath("domains"))
    expected = [r.pipeline.metadata.name for r in readers(ref, [domains])]
    assert [c.pipeline for c in catalog.consumers("fraud", "transactions").consumers] == expected


async def test_a_source_table_comes_back_unclassified_with_only_its_domain(client):
    found = await consumers(client, "fraud", "transactions")
    source = found["source"]
    assert source["classified"] is False
    assert source["schema_version"] == 7
    assert source["table"] == {"database": "fraud_raw", "table": "transactions"}
    # Its IBAN is not given the `high` of the pipeline that reads it.
    iban = next(c for c in source["columns"] if c["name"] == "iban")
    assert iban["lf_tags"] == {"domain": "fraud"}


async def test_a_dataset_nobody_reads_has_no_consumers_and_no_source(client):
    found = await consumers(client, "fraud", "transactions_scored")
    assert found["consumers"] == [] and found["source"] is None


async def test_an_unknown_table_is_an_error(client):
    result = await client.call_tool("get_consumers", {"domain": "fraud", "table": "nope"})
    assert result.is_error


async def test_the_docstring_says_who_is_missing_from_the_list(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    description = tools["get_consumers"].description
    assert "notebooks, BI tools, ad-hoc" in description


async def test_the_output_schema_comes_from_the_catalogs_models(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    schema = tools["get_consumers"].output_schema
    assert set(schema["properties"]) == {"lineage", "source", "consumers"}
    assert {"Source", "Consumer", "TableRef"} <= set(schema["$defs"])


async def test_list_domains_names_the_source_tables_each_domain_owns(client):
    result = await client.call_tool("list_domains", {})
    sources = {d["name"]: d["sources"] for d in result.structured_content["domains"]}
    assert sources == {"finance": [], "fraud": ["transactions"], "policy": ["claims"]}


async def test_an_unclassified_source_is_not_found_by_a_classification(client):
    """`find_datasets` covers published datasets; a source holds no `subject_type` to match."""
    result = await client.call_tool("find_datasets", {"tags": {"subject_type": "customer"}})
    tables = {d["table"] for d in result.structured_content["datasets"]}
    assert "transactions" not in tables and "claims" not in tables
