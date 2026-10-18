"""Fail if `columns.json` disagrees with the Parquet the example pipelines write.

`columns.json` stands in for each domain's Glue catalog, which a real
deployment would read rather than declare. Declared by hand, it can drift from
what the pipelines actually produce, so CI runs the runtime's pipelines and
compares column names and types with this.

Needs the runtime's `run` extra (DuckDB, pandas) and a warehouse the pipelines
have written to; `CORDATA_WAREHOUSE` points at it, as it does for the runtime.

    python -m tools.check_columns
"""

from __future__ import annotations

import json
import sys
from importlib.resources import files

import duckdb
import yaml
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


def declared() -> dict[str, dict[str, str]]:
    raw = json.loads((files("catalog_mcp") / "columns.json").read_text(encoding="utf-8"))
    return {
        key: {c["name"]: c["type"] for c in columns}
        for key, columns in raw.items()
        if not key.startswith("_")
    }


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
    for line in problems:
        print(line, file=sys.stderr)
    if not problems:
        print(f"columns.json matches the Parquet for {len(actual)} datasets")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
