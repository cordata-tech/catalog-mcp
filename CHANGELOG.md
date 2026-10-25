# Changelog

## 0.3.0 — 2026-10-25

**A sixth tool, `get_consumers`**, answers which pipelines declare that they read a
table, with each one's owner, domain and pinned schema version (#2). The list comes
from `pipeline_runtime.pins.readers()`, the function the runtime's producer-side
check builds its report from, so this server does not derive it a second time. That
function moved to the runtime's base install in 0.2.9, which is now the minimum
version. Consumers in domains the caller has no scope for are listed too, because a
producer that sees only part of the list can break the pipelines it does not see.
Readers that declare nothing are absent, and the server still reads no OpenLineage
events.

**Source tables join the catalog.** `fraud_raw.transactions` and `policy_raw.claims`
are what every example pipeline reads, so without them `get_consumers` would have
returned nothing for every table the server knew. `columns.json` now holds their
owning domain, schema version and columns, and the CI columns job checks all three
against the runtime's seeded catalog. A source table carries no LF-tag besides
`domain`, and `get_consumers` shows it as `classified: false` rather than borrowing
the tags of the pipelines that read it. `list_domains` gains a `sources` field naming
the source tables each domain owns. `get_dataset`, `check_grant_expression` and
`find_datasets` still cover published datasets only, and their output is unchanged.

Descriptors are now parsed with `pins.load()` instead of a dispatch on `apiVersion`
written here.

## 0.2.0 — 2026-10-23

**`get_dataset`'s result gains a `lineage` field**, and so does the dataset resource:
the namespace and name the runtime's OpenLineage events use for that dataset, for
example `cordata://fraud` and `fraud_curated.transactions_scored`. A lineage reader
beside this server can match datasets on them; this server's own `cordata://domain/…`
URIs carry no database and could not be matched (#1).

The mapping restates the runtime's naming rule, so the tests check it against events
`cordata-pipeline-runtime` 0.2.2 emitted, and CI checks it against a fresh run of the
installed version. The server still reads no OpenLineage events.

## 0.1.0 — 2026-10-18

The first release: the server [The catalog is the API](https://cordata.tech/en/blog/governed-mesh-over-mcp) describes, running over `cordata-pipeline-runtime`'s example catalog.

- Five read-only tools — `list_domains`, `get_dataset`, `resolve_lf_tag`, `check_grant_expression` and `find_datasets` — with output schemas derived from the runtime's descriptor models, and the ontology and each dataset as resources.
- Stdio by default, started with `uvx cordata-catalog-mcp`.
- Streamable HTTP with `--http`, behind bearer-token authorization: one issuer, the audience bound to this server's URL, per-domain scopes, `401` pointing at the protected-resource metadata, and `403 insufficient_scope` naming the scope a request lacks.
- `columns.json` as the stand-in for each domain's Glue catalog, checked against the ontology at start-up and against the Parquet the example pipelines write in CI.

Verified against MCP revision `2026-07-28` and the Python SDK `mcp` 2.3.
