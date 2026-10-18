# Changelog

## 0.1.0 — 2026-10-18

The first release: the server [The catalog is the API](https://cordata.tech/en/blog/governed-mesh-over-mcp) describes, running over `cordata-pipeline-runtime`'s example catalog.

- Five read-only tools — `list_domains`, `get_dataset`, `resolve_lf_tag`, `check_grant_expression` and `find_datasets` — with output schemas derived from the runtime's descriptor models, and the ontology and each dataset as resources.
- Stdio by default, started with `uvx cordata-catalog-mcp`.
- Streamable HTTP with `--http`, behind bearer-token authorization: one issuer, the audience bound to this server's URL, per-domain scopes, `401` pointing at the protected-resource metadata, and `403 insufficient_scope` naming the scope a request lacks.
- `columns.json` as the stand-in for each domain's Glue catalog, checked against the ontology at start-up and against the Parquet the example pipelines write in CI.

Verified against MCP revision `2026-07-28` and the Python SDK `mcp` 2.3.
