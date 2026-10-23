"""What the governance plane holds about each dataset — loaded once, read-only.

Three stores stand in for the reference topology's (fabric-mesh-on-aws § 1):

- **Ownership and the policy contract** come from the pipeline descriptors,
  parsed with `pipeline_runtime`'s own models. Nothing here restates them; the
  post's claim is one model with several consumers, and this is one of them.
- **The permitted vocabulary** is the runtime's ontology, through
  `policy.resolve()` — the same function the executor runs.
- **Columns and their tags** come from `columns.json`, the stand-in for each
  domain's Glue catalog: the one part of a dataset the descriptor does not carry.

Everything returned is frozen. The server has no write path to remove because
it never had one, and the objects it hands out cannot be changed either.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from types import MappingProxyType

import yaml
from pipeline_runtime import descriptor as v1
from pipeline_runtime import descriptor_v2 as v2
from pipeline_runtime import policy
from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Column(_Frozen):
    name: str
    type: str
    # Effective tags: the table's, with the column's own overriding per key, as
    # LakeFormation column tags do.
    lf_tags: dict[str, str]


class Lineage(_Frozen):
    """How the runtime's OpenLineage events name this dataset.

    OpenLineage identifies a dataset by namespace and name, so a lineage reader
    beside this server — `qedro`, a Marquez instance — can match what it holds
    against these two strings and nothing else.
    """

    namespace: str
    name: str


class Dataset(_Frozen):
    # The governance-owned halves are the runtime's models, not copies of them.
    metadata: v1.Metadata
    contract: v1.Contract
    columns: list[Column]
    lineage: Lineage


def lineage_of(domain: str, target: v1.TableRef) -> Lineage:
    """The identity the runtime emits for a table that `domain` owns.

    The runtime's rule, from `emit.dataset()`: the namespace is the owning
    domain and the name is `database.table`. Restated here because importing
    `emit` would pull in the `run` extra; `tools/check_lineage.py` and the tests
    hold it to events the runtime actually wrote.
    """
    return Lineage(namespace=f"cordata://{domain}", name=target.fqn)


def _descriptor(raw: dict) -> tuple[v1.Metadata, v1.TableRef, v1.Contract]:
    """(metadata, target, contract) from a v1 or v2 descriptor.

    Dispatches on `apiVersion` as the executor does, without importing the
    executor, which would pull in the `run` extra this package does not need.
    """
    api = raw.get("apiVersion")
    if api == "cordata.tech/v1":
        d1 = v1.Descriptor.model_validate(raw)
        return d1.metadata, d1.target, d1.contract
    if api == "cordata.tech/v2":
        d2 = v2.Descriptor.model_validate(raw)
        contract = v1.Contract.model_validate(d2.target.contract.model_dump())
        return d2.metadata, d2.target, contract
    raise ValueError(f"unknown apiVersion {api!r}")


def _resolve(tags: Mapping[str, str]) -> dict[str, str]:
    # The executor's own check; an unknown key or value raises the same errors.
    return policy.resolve(dict(tags))


class Catalog:
    """The example catalog, or any directory laid out like it."""

    def __init__(self, example=None, columns=None):
        example = example if example is not None else files("pipeline_runtime.example")
        columns = columns if columns is not None else files("catalog_mcp") / "columns.json"
        stand_in = {
            k: v
            for k, v in json.loads(columns.read_text(encoding="utf-8")).items()
            if not k.startswith("_")
        }

        datasets: dict[tuple[str, str], Dataset] = {}
        for domain_dir in sorted(example.joinpath("domains").iterdir(), key=lambda p: p.name):
            pipelines = domain_dir.joinpath("pipelines")
            if not pipelines.is_dir():
                continue
            for path in sorted(pipelines.iterdir(), key=lambda p: p.name):
                if not path.name.endswith((".yml", ".yaml")):
                    continue
                metadata, target, contract = _descriptor(
                    yaml.safe_load(path.read_text(encoding="utf-8"))
                )
                table = target.table
                key = f"{metadata.domain}/{table}"
                if key not in stand_in:
                    raise ValueError(f"{key} has no columns in columns.json")
                # `domain` is an ontology key; the database carries it in a
                # deployment, so every column inherits it here.
                table_tags = _resolve({"domain": metadata.domain, **contract.lf_tags})
                cols = [
                    Column(
                        name=c["name"],
                        type=c["type"],
                        lf_tags={**table_tags, **_resolve(c.get("lf_tags", {}))},
                    )
                    for c in stand_in.pop(key)
                ]
                datasets[(metadata.domain, table)] = Dataset(
                    metadata=metadata,
                    contract=contract,
                    columns=cols,
                    lineage=lineage_of(metadata.domain, target),
                )
        if stand_in:
            raise ValueError(
                f"columns.json describes datasets no descriptor publishes: {sorted(stand_in)}"
            )
        self._datasets: Mapping[tuple[str, str], Dataset] = MappingProxyType(datasets)

    @property
    def datasets(self) -> Mapping[tuple[str, str], Dataset]:
        return self._datasets

    def domains(self) -> list[str]:
        return sorted({domain for domain, _ in self._datasets})

    def get(self, domain: str, table: str) -> Dataset | None:
        return self._datasets.get((domain, table))

    @staticmethod
    def ontology() -> dict[str, list[str]]:
        # A copy: the runtime caches its parsed ontology, and a caller must not
        # be able to change what the next caller sees.
        return {key: list(values) for key, values in policy.ontology().items()}

    @staticmethod
    def resolve(tags: Mapping[str, str]) -> dict[str, str]:
        return _resolve(tags)

    @staticmethod
    def validate_expression(expression: Mapping[str, list[str]]) -> None:
        for key, values in expression.items():
            for value in values:
                _resolve({key: value})


def reaches(expression: Mapping[str, list[str]], tags: Mapping[str, str]) -> bool:
    """Whether a tag-based grant expression matches a set of tags.

    LakeFormation semantics: every key in the expression must be present, with
    one of the listed values.
    """
    return all(tags.get(key) in values for key, values in expression.items())
