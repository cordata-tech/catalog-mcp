# Contributing

Issues and pull requests are welcome. Most of this page is about scope and about the
commitments the server keeps, because the quickest way to waste an afternoon here is to
send something good that cannot be merged. [AGENTS.md](AGENTS.md) is the short form of
this page, for a coding agent or for a quick reference.

## What this repo is for

Answering questions *about* datasets from what a governance plane already records —
ownership, schema, LF-tag classification, which grants reach what, who declares a read
of a table, where a kind of personal data is registered — and never answering a
question that needs the data itself. The server is the runnable version of [The catalog
is the API](https://cordata.tech/en/blog/governed-mesh-over-mcp), and its inclusion rule
comes from there: a question gets a tool when its answer already exists as a record.

## Especially welcome

**A way to see what a token should not.** A request that reaches a domain its token has
no scope for, a list that shows one, or a response that differs between an authorised
and an unauthorised caller in a way that leaks something. Report it privately, as
[SECURITY.md](SECURITY.md) describes; a failing test is worth more than a fix.

**A wrong answer about classification.** A column whose effective tags are not what Lake
Formation would compute, a grant expression the server says reaches a column it would
not, or the reverse.

**Running it against a client we have not tried.** The tests use the SDK's own client
and a throwaway token issuer. What a real MCP client does with the output schemas, the
`Mcp-Param-Domain` header or the `403` challenge is the part they cannot show.

## Out of scope

- **Returning rows, or anything computed from them.** Not a missing feature; finding one
  person's rows is a query against the data, and this server never reads data.
- **A write path of any kind**, including tagging or granting. The governance plane's
  writes belong to the governance plane.
- **Reading OpenLineage events in the server.** Observed lineage is run history and
  belongs to a lineage reader such as [`qedro`](https://github.com/cordata-tech/qedro);
  this server answers about current state.
- **Calling AWS.** v1 serves the example only. README § *Deploying it against AWS*
  records how a deployment would read Lake Formation, Glue and DataZone, and the identity
  rules it would have to keep.

## The commitments

Each of these has been argued out, and each will look like an unnecessary constraint at
some point.

**Read-only by construction.** No handler writes, the catalog loads once into an
immutable mapping, and every object a tool returns is a frozen model.
[§ 4 of the post](https://cordata.tech/en/blog/governed-mesh-over-mcp#s4) argues that
`readOnlyHint` is display metadata a client may ignore, so the guarantee has to be what
the code can do.

**Authorization refuses rather than hides.** A request for a domain the token cannot
read gets a `403` naming the scope it lacks, never an empty answer a client could not
tell from a dataset with nothing in it, and the handler re-checks the scope on every
call. A token is accepted only from one issuer and only for this server's own audience,
and it is never passed on. See [§ 5](https://cordata.tech/en/blog/governed-mesh-over-mcp#s5).

**One model, several consumers.** Ownership and the policy contract are
`pipeline_runtime.descriptor`'s own models, tags are validated by the executor's own
`policy.resolve()`, and a table's readers come from `pins.readers()`. When the server
needs something the runtime keeps in its execution stack, the fix is to move it to the
runtime's base install, not to write it again here. The one restatement, the lineage
naming in `lineage_of()`, is checked against events a runtime release emitted.

**The server does not classify on an owner's behalf.** A source table carrying no tag
but `domain` is `classified: false` and never inherits the tags of the pipelines that
read it, and a missing `retention` tag is reported as `null` rather than a default
period. A catalog that filled those gaps would be answering a question nobody recorded
an answer to.

## Ground rules

**Every output has a model.** Each tool returns a Pydantic model, so the SDK derives the
`outputSchema` clients validate against. A union return type is wrapped by the SDK in
`{"result": …}`, which changes the shape every client sees; check `list_tools()` after
touching a return type.

**`columns.json` is checked, not trusted.** It stands in for each domain's Glue catalog
and is written by hand, so CI's columns job runs the runtime's example pipelines and
fails if a dataset's columns differ from the Parquet they write, or if a source table's
domain, version, columns or tags differ from the catalog the runtime seeds.

**The base install stays without an execution stack.** The server depends on
`cordata-pipeline-runtime` without its `run` extra, so a plain install brings no DuckDB,
pandas, pyarrow, great_expectations or OpenLineage client. CI's test job runs that way.

## Running things

```bash
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check . && codespell
```

Python 3.12 is the floor; CI runs 3.12 and 3.13. `pre-commit install` (or
`prek install`) runs ruff and codespell before each commit, at the versions CI uses.

The columns job needs the runtime's execution stack and a warehouse its example
pipelines wrote. `.github/workflows/ci.yml` shows the steps; in short, clone
`cordata-tech/pipeline-runtime` at the installed version into `runtime/`, seed it, run
the three example pipelines, then:

```bash
CORDATA_WAREHOUSE=runtime/example/warehouse \
CORDATA_CATALOG=runtime/example/catalog.duckdb python -m tools.check_columns
python -m tools.check_lineage runtime/out/lineage.ndjson
```

## Commits and pull requests

**Explain the reasoning, not the diff.** A commit message here is for the person who
finds this code in a year and wants to know why it is shaped this way.

**Sign your commits.** `git config commit.gpgsign true` with an SSH or GPG key.

**Sign off every commit, too** — `git commit -s`, which adds `Signed-off-by: Your Name
<you@example.com>`. It certifies, under the [Developer Certificate of
Origin](https://developercertificate.org), that you wrote the change or otherwise have the
right to submit it under the MIT licence. It is the lightweight alternative to a
contributor licence agreement that the Linux kernel and the Linux Foundation's projects
use. The DCO check fails a pull request with a commit whose sign-off does not match its
author; `git rebase --signoff main` adds the missing ones. Signing and signing off are
different things: the signature proves who made the commit, the sign-off is what they
certify about it.

**Coding agents are welcome.** Saying that one helped is welcome too, though not
required: a line in the pull request on what it did and what you checked yourself tells
a reviewer where to look harder, and a commit trailer such as `Assisted-by: <tool>`, or
the `Co-Authored-By:` line many tools add on their own, is fine. Whoever opens the pull
request is responsible for every line in it, whatever wrote it, and has read every one.

**Tests that read as sentences.** Test names here describe the behaviour being
protected, not the function being called. Follow that; it is why the suite is readable.

**How a change gets in.** Fork, branch, open a pull request against `main`. A merge
needs CI to pass and an approving review from a code owner, given after the last push,
and `main` takes no force pushes and cannot be deleted. `.github/CODEOWNERS` requests that
review automatically, and lists separately the paths where a change is easy to make and
expensive to get wrong — authorization, the output models, `columns.json`, the checks
that hold this repository to the runtime, the dependencies and the release workflow. A
pull request touching one of those is worth a sentence in its description about which
commitment it keeps. Release tags are created by maintainers only.

## Releases

`0.x` versions may change interfaces between releases, and the changelog says which.
The minor moves for anything a client would want to know about before upgrading — a new
tool, a new or changed field in an output, a change to what a scope grants; the patch is
for a defect fixed without changing those, or for documentation.

Pushing a `v*` tag is what publishes. The workflow refuses to ship if the tag disagrees
with the version in `pyproject.toml` or `catalog_mcp.__version__`, or if the changelog
entry for that version is missing or still marked unreleased.
