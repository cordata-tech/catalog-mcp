from __future__ import annotations

import json
from importlib.resources import files

import pytest
from pipeline_runtime import descriptor as v1
from pipeline_runtime.errors import UnknownTagValue
from pydantic import ValidationError

from catalog_mcp.catalog import Catalog, reaches


@pytest.fixture(scope="module")
def catalog():
    return Catalog()


def test_every_published_dataset_is_loaded(catalog):
    assert sorted(catalog.datasets) == [
        ("finance", "merchant_settlement_daily"),
        ("fraud", "transactions_scored"),
        ("policy", "claims_deduped"),
    ]


def test_ownership_and_contract_are_the_runtimes_own_models(catalog):
    dataset = catalog.get("fraud", "transactions_scored")
    assert type(dataset.metadata) is v1.Metadata
    assert type(dataset.contract) is v1.Contract


def test_columns_inherit_the_table_tags_and_the_domain(catalog):
    columns = {c.name: c.lf_tags for c in catalog.get("fraud", "transactions_scored").columns}
    assert columns["iban"] == {
        "domain": "fraud",
        "sensitivity": "high",
        "residency": "eu",
        "subject_type": "customer",
    }
    assert columns["amount_eur"] == columns["iban"]


def test_a_column_tag_overrides_the_table_tag_for_that_key(tmp_path):
    def tag(data):
        data["finance/merchant_settlement_daily"][0]["lf_tags"] = {"sensitivity": "high"}

    dataset = Catalog(columns=_stand_in(tmp_path, tag)).get("finance", "merchant_settlement_daily")
    tags = {c.name: c.lf_tags for c in dataset.columns}
    assert tags["merchant_id"]["sensitivity"] == "high"
    assert tags["merchant_id"]["residency"] == "eu"
    assert tags["amount_eur"]["sensitivity"] == "confidential"


def test_reaches_needs_every_key_with_a_listed_value():
    tags = {"sensitivity": "high", "residency": "eu"}
    assert reaches({"sensitivity": ["high"]}, tags)
    assert reaches({"sensitivity": ["high", "confidential"], "residency": ["eu"]}, tags)
    assert not reaches({"sensitivity": ["confidential"]}, tags)
    assert not reaches({"retention": ["7y"]}, tags)


def test_an_unknown_tag_value_fails_the_way_the_executor_fails(catalog):
    with pytest.raises(UnknownTagValue, match="allowed"):
        catalog.resolve({"sensitivity": "hgh"})


def test_the_catalog_and_its_objects_cannot_be_changed(catalog):
    dataset = catalog.get("fraud", "transactions_scored")
    with pytest.raises(ValidationError):
        dataset.columns[0].name = "renamed"
    with pytest.raises(TypeError):
        catalog.datasets[("fraud", "new")] = dataset


def test_the_ontology_handed_out_is_a_copy(catalog):
    catalog.ontology()["sensitivity"].append("anything")
    assert "anything" not in catalog.ontology()["sensitivity"]


def _stand_in(tmp_path, edit):
    data = json.loads((files("catalog_mcp") / "columns.json").read_text(encoding="utf-8"))
    edit(data)
    path = tmp_path / "columns.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_published_dataset_without_columns_fails_to_load(tmp_path):
    path = _stand_in(tmp_path, lambda d: d.pop("finance/merchant_settlement_daily"))
    with pytest.raises(ValueError, match="finance/merchant_settlement_daily has no columns"):
        Catalog(columns=path)


def test_columns_for_a_dataset_nobody_publishes_fail_to_load(tmp_path):
    path = _stand_in(tmp_path, lambda d: d.update({"hr/salaries": []}))
    with pytest.raises(ValueError, match="hr/salaries"):
        Catalog(columns=path)


def test_a_column_tag_outside_the_ontology_fails_to_load(tmp_path):
    def mistag(data):
        data["fraud/transactions_scored"][0]["lf_tags"] = {"sensitivity": "secret"}

    with pytest.raises(UnknownTagValue):
        Catalog(columns=_stand_in(tmp_path, mistag))


def test_every_table_a_pipeline_reads_is_a_source(catalog):
    assert sorted(catalog.sources) == [("fraud", "transactions"), ("policy", "claims")]


def test_a_source_carries_only_its_domain_and_is_unclassified(catalog):
    source = catalog.sources[("policy", "claims")]
    assert source.classified is False
    assert {k for c in source.columns for k in c.lf_tags} == {"domain"}


def test_a_source_tagged_in_columns_json_is_classified(tmp_path):
    def tag(data):
        data["sources"]["policy_raw.claims"]["columns"][2]["lf_tags"] = {"sensitivity": "high"}

    source = Catalog(columns=_stand_in(tmp_path, tag)).sources[("policy", "claims")]
    assert source.classified is True


def test_a_table_a_pipeline_reads_without_a_source_entry_fails_to_load(tmp_path):
    path = _stand_in(tmp_path, lambda d: d["sources"].pop("policy_raw.claims"))
    with pytest.raises(ValueError, match="policy_raw.claims"):
        Catalog(columns=path)


def test_a_source_no_pipeline_reads_fails_to_load(tmp_path):
    def add(data):
        data["sources"]["fraud_raw.chargebacks"] = {
            "domain": "fraud",
            "schema_version": 1,
            "columns": [],
        }

    with pytest.raises(ValueError, match="fraud_raw.chargebacks"):
        Catalog(columns=_stand_in(tmp_path, add))


def test_a_source_owned_by_a_domain_outside_the_ontology_fails_to_load(tmp_path):
    def mistag(data):
        data["sources"]["policy_raw.claims"]["domain"] = "insurance"

    with pytest.raises(UnknownTagValue):
        Catalog(columns=_stand_in(tmp_path, mistag))
