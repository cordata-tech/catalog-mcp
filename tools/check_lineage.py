"""Fail if a dataset's `lineage` names something the runtime never emitted.

`Dataset.lineage` restates the runtime's naming rule rather than importing it,
so this holds the restatement to events the runtime actually wrote: every
dataset this server serves must appear, under exactly that namespace and name,
as the output of a completed run, and every source table as an input of one.

    python -m tools.check_lineage runtime/out/lineage.ndjson

The server itself reads no OpenLineage events; only this check and the tests do.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from catalog_mcp.catalog import Catalog


def produced(events: Path, side: str = "outputs") -> set[tuple[str, str]]:
    """(namespace, name) of every dataset a completed run wrote, or with `inputs`, read."""
    found = set()
    for line in events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("eventType") != "COMPLETE":
            continue
        found |= {(d["namespace"], d["name"]) for d in event.get(side, [])}
    return found


def unmatched(catalog: Catalog, events: Path) -> list[str]:
    written, read = produced(events), produced(events, "inputs")
    served = [
        (key, ds.lineage, written, "wrote") for key, ds in sorted(catalog.datasets.items())
    ] + [(key, catalog.consumers(*key).lineage, read, "read") for key in sorted(catalog.sources)]
    return [
        f"{domain}/{table}: lineage says {lineage.namespace} {lineage.name}, "
        f"which no completed run {verb}"
        for (domain, table), lineage, emitted, verb in served
        if (lineage.namespace, lineage.name) not in emitted
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
        print(
            f"lineage matches the emitted events for {len(catalog.datasets)} datasets "
            f"and {len(catalog.sources)} source tables"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
