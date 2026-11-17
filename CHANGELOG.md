# Changelog

## 0.4.1 — unreleased

**The example's customer datasets now report a retention period** (#4).
`cordata-pipeline-runtime` 0.2.11 tags `fraud/transactions_scored` with
`retention: 7y` and `policy/claims_deduped` with `retention: 10y`
(pipeline-runtime#16), so `get_erasure_scope` returns those values where 0.4.0 on the
older runtime returned `null`. The README's IBAN walkthrough shows them, and the
tests that assumed no retention tag now assert the two values, with a separate test
that a dataset whose tag is removed still comes back as `null`.

The minimum runtime is 0.2.11. The server's code is unchanged: 0.4.0 already
reported the tag as written, and with 0.2.11 installed it returns the same values.

## 0.4.0 — 2026-11-17

**A seventh tool, `get_erasure_scope`**, returns every dataset tagged with a subject
type in one call, which took a `find_datasets` followed by a `get_dataset` and a
`get_consumers` per result before (#3). Each dataset comes with its owning domain and
owner, the columns tagged with the subject type, its `retention` tag, its declared
readers, and the table its pipeline reads together with that table's own readers.

`retention` is `null` when the dataset has no `retention` tag, which is the case for
every example dataset, and a tag that is set is reported as written without a ruling
on whether a deletion meets a retention duty. The table a dataset is derived from is
listed with its `classified` flag, so `fraud_raw.transactions`, which holds the same
IBANs as `transactions_scored` but carries only its `domain` tag, appears as feeding
that dataset rather than as customer data.

Datasets in domains the caller may not read are left out, and the result's `complete`
field is `false` when any were, without naming which. Readers are listed in every
domain, as `get_consumers` lists them. The tool lists where data is registered and,
like `find_datasets`, cannot say where one person's rows are.

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
