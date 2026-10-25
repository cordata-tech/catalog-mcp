# cordata-catalog-mcp

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server that answers questions *about* datasets — who owns them, what columns they have, how those columns are classified, and whether a Lake Formation grant would reach them — and never returns a row of the data itself. It serves the example catalog that ships with [`cordata-pipeline-runtime`](https://pypi.org/project/cordata-pipeline-runtime/).

It is the runnable version of a design written up in two posts on cordata.tech. [Fabric + Mesh on AWS — LakeFormation, DataZone, and one governance plane](https://cordata.tech/en/blog/fabric-mesh-on-aws) lays out the reference topology this server is modelled on, with one AWS account per data domain and a governance account that owns the LF-tag ontology and the grants, and closes its [§ 3](https://cordata.tech/en/blog/fabric-mesh-on-aws#s3) by proposing an MCP catalog tool. [The catalog is the API — a governed mesh over MCP](https://cordata.tech/en/blog/governed-mesh-over-mcp) designs that tool: which questions it answers and where its schemas come from, why read-only has to be enforced rather than annotated, and how authorization works. Where this README says "§ N of the post", it means that second post.

Verified against MCP revision **`2026-07-28`**, the Python SDK **`mcp` 2.3**, and `cordata-pipeline-runtime` **0.2.9**. MCP has changed substantially between revisions, so check those three numbers before trusting a detail below against a newer stack.

## Start it

```sh
uvx cordata-catalog-mcp
```

That starts the server over stdio, which is how a desktop or terminal MCP client launches a local server. To give it to a client, add it to the client's server configuration:

```json
{
  "mcpServers": {
    "cordata-catalog": {
      "command": "uvx",
      "args": ["cordata-catalog-mcp"]
    }
  }
}
```

In Claude Code the same thing is one command: `claude mcp add cordata-catalog -- uvx cordata-catalog-mcp`.

Over stdio there is no token. The client that started the process is the only party that can talk to it, so every domain is visible. Serving it over HTTP needs a token issuer and is described [below](#serving-it-over-http).

## What it answers

Six tools, each a lookup or an evaluation against a record the governance plane already holds:

| Tool | Answers |
|---|---|
| `list_domains` | Which domains exist, who owns their datasets, and which source tables each owns |
| `get_dataset` | One dataset's owner, contract and columns, each column with its effective LF-tags |
| `resolve_lf_tag` | Whether a tag set is valid against the governance-owned ontology |
| `check_grant_expression` | Whether a tag-based grant expression would reach a dataset, and which columns |
| `find_datasets` | Which datasets carry given tag values, for example `subject_type=customer` |
| `get_consumers` | Which pipelines declare that they read a table, and the schema version each pins |

LF-tags are Lake Formation's key–value classification labels; a grant written as a tag expression reaches every table or column whose tags match it, which is how the [reference topology](https://cordata.tech/en/blog/fabric-mesh-on-aws#s3) controls access without per-table grants.

Two resources sit beside the tools: the ontology as `cordata://ontology/lf-tags`, and each dataset as the template `cordata://domain/{domain}/dataset/{table}`.

`get_dataset` returns the runtime's own `Metadata` and `Contract` models from `pipeline_runtime.descriptor`, so the SDK derives the tool's `outputSchema` from the same Pydantic classes the pipeline executor validates descriptors with. Nothing in this repository restates them. `resolve_lf_tag` runs the executor's own `policy.resolve()`, so a tag set fails here exactly as it would fail in a pipeline run.

`find_datasets` can say which datasets hold *customer* data, and in which columns. It cannot say where one *person's* rows are, because finding those is a query against the data, and this server never reads data.

### Where the columns come from

Ownership, contracts and the ontology all come from `cordata-pipeline-runtime`. Column lists do not, because a pipeline descriptor does not carry one: in a deployment they live in each domain's Glue catalog. Here [`columns.json`](src/catalog_mcp/columns.json) stands in for that catalog. Each column's tags are checked against the ontology when the server starts, and CI runs the runtime's three example pipelines and fails if a column name or type in `columns.json` differs from the Parquet they write.

`columns.json` also holds the two source tables the pipelines read, `fraud_raw.transactions` and `policy_raw.claims`, which no descriptor publishes. For each it records the owning domain, the schema version the catalog is at, and that version's columns, and CI fails if any of the three differs from the catalog the runtime seeds, which is the catalog the pipelines resolve their pins against.

### Who reads a table

`get_consumers` answers *"who reads this table, and what breaks if I change a column?"* with the pipelines whose descriptors name the table as their source. For `fraud/transactions` that is fraud's `transactions-scored-daily` and finance's `merchant-settlement-daily`, both pinning v7, each with its owner. A pipeline reads every column of the version it pins, so a removed or retyped column breaks every consumer on the list.

The list is the runtime's own. `pipeline_runtime.pins.readers()` is what the runtime's producer-side check, `python -m pipeline_runtime.consumers`, builds its report from, and since `cordata-pipeline-runtime` 0.2.9 it is on the base install, so this server calls it rather than deriving the list again. Readers that declare nothing — notebooks, BI tools, ad-hoc SQL — are not on it. Observed reads are run history, which belongs to a lineage reader such as `qedro`, and this server still reads no OpenLineage events.

A caller who may read the table sees every consumer, including pipelines in domains it has no scope for. A pin is a dependency declared against this table, and a producer working from part of the list would break the pipelines it could not see.

A source table comes back with its columns and `classified: false`. The runtime's catalog records only which domain owns an application's table, because classifying it is the owner's decision, so the server shows the table as unclassified rather than giving it the tags of the pipelines that read it. That has a consequence worth knowing: `fraud_raw.transactions` holds IBANs, yet `find_datasets` with `{"subject_type": "customer"}` does not return it, and a Lake Formation grant written on `sensitivity` would not reach it either. `get_dataset`, `check_grant_expression` and `find_datasets` cover the published datasets only.

### Matching the runtime's lineage

This server names a dataset by its resource URI, `cordata://domain/fraud/dataset/transactions_scored`. The runtime's OpenLineage events name the same table by a namespace and a name, `cordata://fraud` and `fraud_curated.transactions_scored`, because OpenLineage identifies a dataset by that pair and the name carries the database. The two forms differ, so every dataset `get_dataset` returns also carries the lineage form:

```json
"lineage": {"namespace": "cordata://fraud", "name": "fraud_curated.transactions_scored"}
```

An agent connected to this server and to a lineage reader such as `qedro` or Marquez can match datasets on those two strings, without either server reading the other. The rule behind them is the runtime's: the namespace is the domain that owns the table and the name is `database.table`. Since `cordata-pipeline-runtime` 0.2.2 that holds for a table a pipeline reads as well as for one it writes ([pipeline-runtime#7](https://github.com/cordata-tech/pipeline-runtime/issues/7)), so `fraud_raw.transactions` has one identity whichever domain reads it.

The rule is restated here rather than imported, because the runtime keeps it in its execution stack, which this package does not install. The tests hold the restatement to events a runtime release actually emitted (`tests/fixtures/`), and CI holds it to the events from a fresh run of the installed version. The server itself still reads no OpenLineage events.

## The IBAN question, on this example

[§ 1 of the post](https://cordata.tech/en/blog/governed-mesh-over-mcp#s1) opens with a domain engineer who is tagging a new column and asks which sensitivity level applies to one holding an EU IBAN. The answer should come from how comparable columns are already classified, not from what a model knows about IBANs. Against this example, it goes like this.

**Find the precedent.** `find_datasets` with `{"subject_type": "customer"}` returns two datasets that hold customer data, `fraud/transactions_scored` and `policy/claims_deduped`, each with an IBAN column. `get_dataset` on the first shows how that column is tagged and who to ask about it:

```json
{
  "metadata": {"name": "transactions-scored-daily", "domain": "fraud", "owner": "fraud-data@example.com"},
  "contract": {"freshness_sla": "PT4H",
               "lf_tags": {"sensitivity": "high", "residency": "eu", "subject_type": "customer"}},
  "columns": [
    {"name": "iban", "type": "VARCHAR",
     "lf_tags": {"domain": "fraud", "sensitivity": "high", "residency": "eu", "subject_type": "customer"}}
  ]
}
```

(trimmed to the one column)

**Validate the proposal.** `resolve_lf_tag` with `{"sensitivity": "high", "residency": "eu", "subject_type": "customer"}` returns the tag set unchanged, because every value is in the ontology. A value that is not fails with the permitted ones, which is the executor's own error:

```text
lf_tag residency='eea' is not in the ontology; allowed: ['eu', 'ch', 'us', 'global']
```

Validation catches a value nobody defined; it cannot catch a legal value that is wrong for this column. `residency` records where the *data* is stored, so an IBAN column in an extract replicated across regions should be `global`, and `resolve_lf_tag` accepts `eu` and `global` alike. That is the failure [§ 1](https://cordata.tech/en/blog/governed-mesh-over-mcp#s1) describes, and the reason the precedent lookup comes first.

**Check who could read it.** The analyst role in the [reference topology](https://cordata.tech/en/blog/fabric-mesh-on-aws#s3) may read every sensitivity except `high`. `check_grant_expression` with that role's expression, `{"domain": ["fraud"], "sensitivity": ["public", "internal", "confidential"], "residency": ["eu"]}`, returns `{"reaches": false, "columns": []}` for `transactions_scored`. In this example the whole table is classified `high`, so the role reaches nothing in it. The reference topology's Terraform tags only the `iban` column of its customer table `high`, and there the same role sees the table with the IBAN column left out. The IBAN columns here carry their own `high` tag as well, so that they stay `high` if a table's classification is ever lowered.

## Read-only, and how that is enforced

Every tool carries `readOnlyHint: true`, but [§ 4 of the post](https://cordata.tech/en/blog/governed-mesh-over-mcp#s4) argues that annotation is display metadata and enforces nothing. What enforces it here is that no handler writes: there is no write path to remove, the catalog is loaded once into an immutable mapping, and every object it hands out is a frozen Pydantic model. The tests call a write tool that does not exist and check that it returns an error and that the next read is unchanged.

## Serving it over HTTP

```sh
uvx cordata-catalog-mcp --http --issuer https://idp.example --public-key issuer.pem \
  --resource-url https://catalog.example/mcp
```

Over HTTP every request needs a bearer token: a JWT access token in the [RFC 9068](https://www.rfc-editor.org/rfc/rfc9068) shape, signed ES256 by the one issuer named with `--issuer`, whose audience is this server's own URL (`--resource-url`, by default `http://HOST:PORT/mcp`). A token minted for any other resource is refused, which is the [RFC 8707](https://www.rfc-editor.org/rfc/rfc8707) audience binding the MCP authorization spec requires, and the server never passes a token on to anything else.

Access is per domain. A token needs `catalog:read` to reach the server at all, and `catalog:{domain}:read` for each domain it may see — `catalog:fraud:read`, for example. The responses follow [§ 5 of the post](https://cordata.tech/en/blog/governed-mesh-over-mcp#s5):

- **No token, or an invalid one**: `401`, with a `WWW-Authenticate` header whose `resource_metadata` points at `/.well-known/oauth-protected-resource/mcp`. That document is the [RFC 9728](https://www.rfc-editor.org/rfc/rfc9728) protected-resource metadata, and it names the issuer a client should get a token from.
- **A request for a domain the token has no scope for**: `403`, with `error="insufficient_scope"` and `scope="catalog:{domain}:read"`, so the client knows which scope to ask for. The server does not answer with an empty result, which a client could not tell apart from a dataset with nothing in it.
- **Lists** — `list_domains` and `find_datasets` — show only the domains the token may read. List results are marked `cacheScope: private`, because they differ per caller and a shared cache must not serve one caller's catalog to another.

The scope is checked again inside each handler on every call, so holding a token that read one domain grants nothing for the next request. The tests cover each of these against a throwaway issuer, a key pair generated in the test suite; no real identity provider is involved.

## Deploying it against AWS

v1 makes no AWS calls; it serves the example data only. A deployment would read the ontology from `lakeformation.list_lf_tags()` in the governance account, the columns from each domain's Glue catalog, and ownership from DataZone. Three things about the identity chain were settled while designing it, and are recorded here because they are easy to get wrong:

- **Use `sts:AssumeRole` under the server's own identity, never `assume_role_with_web_identity`.** Federating the caller's token into AWS would forward a token this server accepted as its own audience to a third party, which the MCP authorization spec prohibits. The caller travels as the session name and a session tag instead.
- **Sanitise `RoleSessionName`.** STS accepts only `[\w+=,.@-]`, up to 64 characters, and an OIDC `sub` can contain `|` (Auth0 issues `auth0|abc123`).
- **Allow `sts:TagSession` in the reader role's trust policy.** Without it the session tags are refused, and the caller's identity never reaches CloudTrail.

Because AWS never sees the caller's token, no IAM policy can condition on it, and the scope check stays in application code. That is the reason each reader role should be scoped to a single domain.

## Development

```sh
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```

The column check needs a warehouse the runtime's example pipelines have written, from a clone of `cordata-tech/pipeline-runtime` at the installed version; `.github/workflows/ci.yml` shows the steps.

```sh
CORDATA_WAREHOUSE=../pipeline-runtime/example/warehouse \
CORDATA_CATALOG=../pipeline-runtime/example/catalog.duckdb python -m tools.check_columns
```

## Licence

MIT. See [LICENSE](LICENSE).
