"""The `lineage` field, held to events the runtime really emitted.

The fixture is the lineage file `cordata-pipeline-runtime` 0.2.2 wrote when its
three example pipelines ran (`tests/fixtures/README.md`). CI checks the same
thing against a fresh run of whichever runtime version is installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client

from catalog_mcp.catalog import Catalog
from catalog_mcp.server import build_server
from tools.check_lineage import produced, unmatched

EVENTS = Path(__file__).parent / "fixtures" / "pipeline-runtime-0.2.2.ndjson"


def test_every_served_dataset_is_named_as_the_runtime_names_it():
    assert unmatched(Catalog(), EVENTS) == []


def test_the_table_two_domains_read_has_one_name_in_the_events():
    """The runtime fix this mapping depends on (pipeline-runtime#7): fraud's and
    finance's pipelines both read `fraud_raw.transactions`, and both name it
    under fraud's namespace."""
    reads = set()
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["eventType"] == "COMPLETE":
            reads |= {(d["namespace"], d["name"]) for d in event["inputs"]}
    named = {ns for ns, name in reads if name == "fraud_raw.transactions"}
    assert named == {"cordata://fraud"}


def test_a_wrong_rule_would_be_caught(tmp_path):
    """The check is only worth having if it fails: the same events, with the
    namespace spelled the way the runtime spells job namespaces instead."""
    wrong = tmp_path / "events.ndjson"
    wrong.write_text(
        EVENTS.read_text(encoding="utf-8").replace('"cordata://fraud"', '"cordata.fraud"'),
        encoding="utf-8",
    )
    problems = unmatched(Catalog(), wrong)
    assert any(p.startswith("fraud/transactions_scored") for p in problems)
    # The source table is held to the events' inputs, so it is caught as well.
    assert any(p.startswith("fraud/transactions:") for p in problems)
    assert ("cordata.fraud", "fraud_curated.transactions_scored") in produced(wrong)


@pytest.mark.anyio
async def test_get_dataset_carries_the_lineage_identity():
    async with Client(build_server()) as client:
        result = await client.call_tool(
            "get_dataset", {"domain": "fraud", "table": "transactions_scored"}
        )
    assert result.structured_content["lineage"] == {
        "namespace": "cordata://fraud",
        "name": "fraud_curated.transactions_scored",
    }
