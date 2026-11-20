# Security

## Reporting

Email **privacy@cordata.tech**, or open a private advisory through GitHub's *Report a
vulnerability* on this repository. Please do not open a public issue for anything
exploitable.

Expect an acknowledgement within three working days. If a fix is warranted it ships as a
patch release with an entry in the changelog naming what was wrong; credit is given
unless you would rather it were not.

Supported: the most recent `0.x` release. There is no long-term support branch before
`1.0`.

## What this server can reach, by construction

Most of the security posture is a property of the code rather than a policy applied to
it, so it is worth stating plainly.

**No write path exists.** No tool or resource handler modifies anything. The catalog is
loaded once at start into an immutable mapping, and every object a tool returns is a
frozen model, so a caller cannot change what the next caller sees.
`tests/test_tools.py` calls a write tool that does not exist and checks that the next
read is unchanged.

**No data is read.** The server answers from descriptors, the ontology and `columns.json`,
the stand-in for each domain's Glue catalog. It has no code that opens a table or a file
of rows.

**No outbound network traffic.** The server makes no AWS call and no HTTP request: over
HTTP it verifies tokens locally against the public key given with `--public-key`, and it
fetches no key set. It reads no OpenLineage events.

**Over stdio there is no token.** The client that started the process is the only party
that can talk to it, and the process boundary is the authorization, so every domain is
visible.

**Over HTTP every request needs a token**, a JWT signed ES256 by the one issuer named
with `--issuer`, whose audience is this server's own URL. A token minted for any other
resource is refused, and a token is never passed on to anything else. Access is per
domain: `catalog:read` reaches the server, and `catalog:{domain}:read` each domain. A
request for a domain the token lacks gets a `403` naming the scope, and each handler
checks the scope again on every call. List results are marked `cacheScope: private`.

## What a response discloses

Metadata about datasets, never their contents: dataset and column names, column types,
owner email addresses, LF-tags, and pipeline names with the schema versions they pin.

Two answers cross domain lines on purpose, and are recorded here so that they are not
reported as leaks:

- **`get_consumers` and `get_erasure_scope` list readers in every domain.** A caller who
  may read a table sees every pipeline that declares a read of it, including pipelines
  in domains the caller has no scope for, because a producer, or an erasure, working from
  part of that list would miss what it could not see.
- **`get_erasure_scope` reports `complete: false`** when it left out a dataset in a domain
  the caller may not read. That reveals one fact, that some unreadable domain holds the
  subject type, and not which domain or which dataset.

## Dependencies

Three at runtime: `cordata-pipeline-runtime` without its `run` extra, which brings
pydantic and PyYAML but no execution stack, the MCP Python SDK, and `pyjwt[crypto]`.
The weekly security workflow audits what a plain install brings with `pip-audit`.

## Scope

In scope: anything that lets a request see a domain its token has no scope for, accept a
token from another issuer or for another audience, change what a later request sees, make
the server send a request anywhere, or return something a tool's description says it
never returns — a row, or a classification nobody recorded.

Out of scope: the contents of the catalog you point it at, and anything requiring an
attacker who can already run code as the server's user.
