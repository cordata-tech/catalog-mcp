"""Fail if a dataset's `lineage` names something the runtime never emitted.

`Dataset.lineage` restates the runtime's naming rule rather than importing it,
so this holds the restatement to events the runtime actually wrote: every
dataset this server serves must appear, under exactly that namespace and name,
as the output of a completed run.

    python -m tools.check_lineage runtime/out/lineage.ndjson

The server itself reads no OpenLineage events; only this check and the tests do.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from catalog_mcp.catalog import Catalog


def produced(events: Path) -> set[tuple[str, str]]:
    """(namespace, name) of every dataset a completed run wrote."""
    found = set()
    for line in events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("eventType") != "COMPLETE":
            continue
        found |= {(d["namespace"], d["name"]) for d in event.get("outputs", [])}
    return found


def unmatched(catalog: Catalog, events: Path) -> list[str]:
    written = produced(events)
    return [
        f"{domain}/{table}: lineage says {ds.lineage.namespace} {ds.lineage.name}, "
        "which no completed run wrote"
        for (domain, table), ds in sorted(catalog.datasets.items())
        if (ds.lineage.namespace, ds.lineage.name) not in written
    ]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m tools.check_lineage EVENTS.ndjson", file=sys.stderr)
        return 2
    catalog = Catalog()
    problems = unmatched(catalog, Path(args[0]))
    for line in problems:
        print(line, file=sys.stderr)
    if not problems:
        print(f"lineage matches the emitted events for {len(catalog.datasets)} datasets")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
