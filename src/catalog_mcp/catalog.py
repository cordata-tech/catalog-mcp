"""What the governance plane holds about each dataset — loaded once, read-only.

Three stores stand in for the reference topology's (fabric-mesh-on-aws § 1):

- **Ownership and the policy contract** come from the pipeline descriptors,
  parsed with `pipeline_runtime`'s own models. Nothing here restates them; the
  post's claim is one model with several consumers, and this is one of them.
  So does **who reads a table**: `pins.readers()`, the list the runtime's
  producer-side check works from.
- **The permitted vocabulary** is the runtime's ontology, through
  `policy.resolve()` — the same function the executor runs.
- **Columns and their tags** come from `columns.json`, the stand-in for each
  domain's Glue catalog: the one part of a dataset the descriptor does not carry.
  It also holds the source tables the pipelines read, which no descriptor
  publishes, with the domain that owns each and the version it is at.

Everything returned is frozen. The server has no write path to remove because
it never had one, and the objects it hands out cannot be changed either.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from pipeline_runtime import descriptor as v1
from pipeline_runtime import pins, policy
from pydantic import BaseModel, ConfigDict, Field


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


class Source(_Frozen):
    """A table an application publishes and pipelines read.

    No descriptor publishes it, so it has no pipeline owner and no contract: the
    catalog records the domain that owns it, the version it is at, and its columns.
    """

    domain: str
    table: v1.TableRef
    schema_version: int = Field(description="The version the catalog is at")
    classified: bool = Field(
        description=(
            "False when no column carries an LF-tag besides `domain`. Classifying an "
            "application's table is its owner's decision, so until then a grant written "
            "on sensitivity or subject_type does not reach it, and the tags of the "
            "pipelines that read it are theirs, not its."
        )
    )
    columns: list[Column]


class Consumer(_Frozen):
    pipeline: str
    domain: str
    owner: str
    pins: int = Field(description="The version of the table this pipeline is written against")
    descriptor: str = Field(description="Where the pipeline's descriptor sits in the example")


class Consumers(_Frozen):
    lineage: Lineage
    source: Source | None = Field(
        description="The table, when it is a source table rather than a dataset get_dataset serves"
    )
    consumers: list[Consumer]


def lineage_of(domain: str, target: v1.TableRef) -> Lineage:
    """The identity the runtime emits for a table that `domain` owns.

    The runtime's rule, from `emit.dataset()`: the namespace is the owning
    domain and the name is `database.table`. Restated here because importing
    `emit` would pull in the `run` extra; `tools/check_lineage.py` and the tests
    hold it to events the runtime actually wrote.
    """
    return Lineage(namespace=f"cordata://{domain}", name=target.fqn)


def _resolve(tags: Mapping[str, str]) -> dict[str, str]:
    # The executor's own check; an unknown key or value raises the same errors.
    return policy.resolve(dict(tags))


def _columns(declared: list[dict], table_tags: dict[str, str]) -> list[Column]:
    return [
        Column(
            name=c["name"],
            type=c["type"],
            lf_tags={**table_tags, **_resolve(c.get("lf_tags", {}))},
        )
        for c in declared
    ]


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
        declared_sources = stand_in.pop("sources", {})
        # A real directory, installed or not: `pins` walks it as a Path.
        domains = Path(example.joinpath("domains"))

        datasets: dict[tuple[str, str], Dataset] = {}
        tables: dict[tuple[str, str], v1.TableRef] = {}
        read: set[str] = set()
        for domain_dir in sorted(domains.iterdir(), key=lambda p: p.name):
            pipelines = domain_dir.joinpath("pipelines")
            if not pipelines.is_dir():
                continue
            for path in sorted(pipelines.iterdir(), key=lambda p: p.name):
                if not path.name.endswith((".yml", ".yaml")):
                    continue
                # v1 or v2, in the shape the executor runs, without the executor.
                pipeline = pins.load(path)
                metadata, target = pipeline.metadata, pipeline.target
                read.add(pipeline.source.fqn)
                key = f"{metadata.domain}/{target.table}"
                if key not in stand_in:
                    raise ValueError(f"{key} has no columns in columns.json")
                # `domain` is an ontology key; the database carries it in a
                # deployment, so every column inherits it here.
                table_tags = _resolve({"domain": metadata.domain, **pipeline.contract.lf_tags})
                datasets[(metadata.domain, target.table)] = Dataset(
                    metadata=metadata,
                    contract=pipeline.contract,
                    columns=_columns(stand_in.pop(key), table_tags),
                    lineage=lineage_of(metadata.domain, target),
                )
                tables[(metadata.domain, target.table)] = target
        if stand_in:
            raise ValueError(
                f"columns.json describes datasets no descriptor publishes: {sorted(stand_in)}"
            )

        published = {ref.fqn for ref in tables.values()}
        sources: dict[tuple[str, str], Source] = {}
        for fqn, entry in sorted(declared_sources.items()):
            if fqn in published:
                raise ValueError(
                    f"columns.json describes {fqn} as a source, but a descriptor publishes it"
                )
            if fqn not in read:
                raise ValueError(f"columns.json describes {fqn} as a source no descriptor reads")
            database, table = fqn.split(".")
            ref = v1.TableRef(database=database, table=table)
            key = (entry["domain"], table)
            if key in tables:
                raise ValueError(f"{fqn} and {tables[key].fqn} are both {'/'.join(key)}")
            # Only the domain, unless columns.json says more: the pipelines that
            # read the table promise their own outputs' tags, not its.
            cols = _columns(entry["columns"], _resolve({"domain": entry["domain"]}))
            sources[key] = Source(
                domain=entry["domain"],
                table=ref,
                schema_version=entry["schema_version"],
                classified=any(k != "domain" for c in cols for k in c.lf_tags),
                columns=cols,
            )
            tables[key] = ref
        if unknown := read - published - set(declared_sources):
            raise ValueError(
                f"descriptors read tables columns.json has no source for: {sorted(unknown)}"
            )

        consumers = {
            key: Consumers(
                lineage=lineage_of(key[0], ref),
                source=sources.get(key),
                consumers=[_consumer(r, domains) for r in pins.readers(ref, [domains])],
            )
            for key, ref in tables.items()
        }

        self._datasets: Mapping[tuple[str, str], Dataset] = MappingProxyType(datasets)
        self._sources: Mapping[tuple[str, str], Source] = MappingProxyType(sources)
        self._consumers: Mapping[tuple[str, str], Consumers] = MappingProxyType(consumers)

    @property
    def datasets(self) -> Mapping[tuple[str, str], Dataset]:
        return self._datasets

    @property
    def sources(self) -> Mapping[tuple[str, str], Source]:
        return self._sources

    def domains(self) -> list[str]:
        return sorted({domain for domain, _ in self._datasets} | {d for d, _ in self._sources})

    def get(self, domain: str, table: str) -> Dataset | None:
        return self._datasets.get((domain, table))

    def consumers(self, domain: str, table: str) -> Consumers | None:
        """Who declares a read of this dataset or source table; None if the catalog has neither."""
        return self._consumers.get((domain, table))

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


def _consumer(reader: pins.Reader, domains: Path) -> Consumer:
    where = reader.path.relative_to(domains.parent).as_posix()
    if reader.pipeline is None:
        # Every descriptor under `pipelines/` has parsed by now, so this one sits
        # elsewhere. Its dependency is hidden, and a list without it would not say so.
        raise ValueError(f"{where} reads a catalog table but does not parse: {reader.detail}")
    return Consumer(
        pipeline=reader.pipeline.metadata.name,
        domain=reader.pipeline.metadata.domain,
        owner=reader.pipeline.metadata.owner,
        pins=reader.pipeline.source.schema_version,
        descriptor=where,
    )


def reaches(expression: Mapping[str, list[str]], tags: Mapping[str, str]) -> bool:
    """Whether a tag-based grant expression matches a set of tags.

    LakeFormation semantics: every key in the expression must be present, with
    one of the listed values.
    """
    return all(tags.get(key) in values for key, values in expression.items())
