"""Fail if `columns.json` disagrees with what the runtime's example actually holds.

`columns.json` stands in for each domain's Glue catalog, which a real
deployment would read rather than declare. Declared by hand, it can drift, so CI
runs the runtime's pipelines and compares it with two things:

- each dataset's column names and types with the Parquet its pipeline wrote;
- each source table's domain, version, columns and tags with the runtime's
  seeded catalog, which is what the pipelines resolved their pins against.

Needs the runtime's `run` extra (DuckDB, pandas), a warehouse the pipelines have
written to and the catalog the seed wrote; `CORDATA_WAREHOUSE` and
`CORDATA_CATALOG` point at them, as they do for the runtime.

    python -m tools.check_columns
"""

from __future__ import annotations

import json
import sys
from importlib.resources import files

import duckdb
import yaml
from pipeline_runtime import catalog
from pipeline_runtime import descriptor as v1
from pipeline_runtime import descriptor_v2 as v2
from pipeline_runtime.backends.local import local_path

MODELS = {"cordata.tech/v1": v1.Descriptor, "cordata.tech/v2": v2.Descriptor}

# pandas writes nanosecond timestamps by default. That precision is a property
# of the writer, not of the schema: a Glue catalog records `timestamp` either way.
SAME_TYPE = {"TIMESTAMP_NS": "TIMESTAMP", "TIMESTAMP_US": "TIMESTAMP", "TIMESTAMP_MS": "TIMESTAMP"}


def written() -> dict[str, dict[str, str]]:
    """`domain/table` → column → DuckDB type, read from the Parquet each pipeline wrote."""
    found = {}
    domains = files("pipeline_runtime.example").joinpath("domains")
    paths = [
        path
        for domain in domains.iterdir()
        if domain.joinpath("pipelines").is_dir()
        for path in domain.joinpath("pipelines").iterdir()
        if path.name.endswith((".yml", ".yaml"))
    ]
    for path in sorted(paths, key=lambda p: str(p)):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        descriptor = MODELS[raw["apiVersion"]].model_validate(raw)
        out = local_path(descriptor.target.location)
        rows = duckdb.sql(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning = true)",
            params=[f"{out}/**/*.parquet"],
        ).fetchall()
        found[f"{descriptor.metadata.domain}/{descriptor.target.table}"] = {
            name: SAME_TYPE.get(kind, kind) for name, kind, *_ in rows
        }
    return found


def _stand_in() -> dict:
    return json.loads((files("catalog_mcp") / "columns.json").read_text(encoding="utf-8"))


def declared() -> dict[str, dict[str, str]]:
    return {
        key: {c["name"]: c["type"] for c in columns}
        for key, columns in _stand_in().items()
        if not key.startswith("_") and key != "sources"
    }


def source_problems() -> list[str]:
    """Each declared source table against the catalog the seed wrote."""
    problems = []
    for fqn, entry in sorted(_stand_in().get("sources", {}).items()):
        database, table = fqn.split(".")
        ref = v1.TableRef(database=database, table=table)
        with catalog.connect(read_only=True) as con:
            version = catalog.current_version(con, ref)
            seeded = {c.name: c.type for c in catalog.columns_at(con, ref, entry["schema_version"])}
        if version != entry["schema_version"]:
            problems.append(
                f"{fqn}: columns.json says v{entry['schema_version']}, the catalog is at v{version}"
            )
        want = {c["name"]: c["type"] for c in entry["columns"]}
        for name in sorted(want.keys() | seeded.keys()):
            if want.get(name) != seeded.get(name):
                problems.append(
                    f"{fqn}.{name}: columns.json says {want.get(name)}, "
                    f"the catalog holds {seeded.get(name)}"
                )
        # The server shows a source table with no tag but `domain` as
        # unclassified, so a classification the catalog gained has to fail here.
        tags = catalog.tags_for(ref)
        if tags != {"domain": entry["domain"]}:
            problems.append(
                f"{fqn}: columns.json says domain={entry['domain']} only, the catalog tags {tags}"
            )
    return problems


def main() -> int:
    expected, actual = declared(), written()
    problems = []
    for key in sorted(expected.keys() | actual.keys()):
        want, got = expected.get(key, {}), actual.get(key, {})
        for name in sorted(want.keys() | got.keys()):
            if want.get(name) != got.get(name):
                problems.append(
                    f"{key}.{name}: columns.json says {want.get(name)}, "
                    f"the pipeline writes {got.get(name)}"
                )
    problems += source_problems()
    for line in problems:
        print(line, file=sys.stderr)
    if not problems:
        print(
            f"columns.json matches the Parquet for {len(actual)} datasets "
            f"and the catalog for {len(_stand_in().get('sources', {}))} source tables"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
