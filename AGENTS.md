# AGENTS.md

Instructions for a coding agent, or a person, changing this repository. They are the
short form of [CONTRIBUTING.md](CONTRIBUTING.md), which gives the reasons; read it before
anything substantial. Where the two ever disagree, CONTRIBUTING.md is right and this file
is the bug.

catalog-mcp is a read-only MCP server that answers questions *about* datasets — who owns
them, how their columns are classified, whether a Lake Formation grant would reach them,
who declares a read of them, where a kind of personal data is registered — and never
returns a row of the data itself. It serves the example catalog that ships with
`cordata-pipeline-runtime`, and it is AWS-native by design: LF-tags are the right names
here.

## How a change gets in

- **Fork, branch, open a pull request against `main`.** Do not push to `main`, and do not
  create, move or delete a `v*` tag: pushing one publishes `cordata-catalog-mcp` to PyPI,
  where a version can never be reused. Releases are the maintainer's.
- **The checks have to pass**, the same ones CI runs on Python 3.12 and 3.13:

  ```bash
  pip install -e ".[dev]"
  pytest -q
  ruff check . && ruff format --check . && codespell
  # or once: pre-commit install, to run ruff and codespell before each commit
  ```

  A change to `columns.json` also has to pass CI's columns job, which runs the runtime's
  example pipelines and compares; `.github/workflows/ci.yml` shows the steps to run it
  locally.
- **Add a test for the behaviour you change**, named for what it protects ("a domain the
  caller may not read is left out and the result says so"), not for the function it
  calls.
- **Add a line under the topmost unreleased heading in `CHANGELOG.md`**, saying what a
  user of the server would notice.
- **Sign off every commit** with `git commit -s`. The `Signed-off-by:` line is your
  statement under the [Developer Certificate of Origin](https://developercertificate.org)
  that you may contribute the change under the MIT licence; the DCO check fails a pull
  request where a commit lacks one matching its author. **Sign the commit** too, with an
  SSH or GPG key, and explain the reasoning in the message rather than the diff.
- **Agents are welcome, and saying so is welcome too, not required.** If one helped, a
  line in the pull request on what it did and what you checked yourself helps a reviewer
  know where to look; a trailer such as `Assisted-by: <tool>` is fine as well. Either way,
  the person opening the pull request is responsible for every line, has read every
  line, and answers review on it.
- **A pull request that touches a path listed separately in `.github/CODEOWNERS`** says in
  its description which commitment below it keeps.

## Ask before changing these

An agent asks the person it works for before modifying any of these, naming the path and
what the change would do to a caller — for example: *"This lets a token with
`catalog:fraud:read` see policy's datasets in `find_datasets`. Do you want that?"* A small
edit here changes who can see what, or what every client receives.

- `src/catalog_mcp/auth.py`, `src/catalog_mcp/app.py`, and `_granted`, `_require` and
  `DOMAIN_TOOLS` in `src/catalog_mcp/server.py` — who may read which domain.
- The output models in `src/catalog_mcp/catalog.py` and `src/catalog_mcp/server.py` —
  every tool's `outputSchema` comes from them, and the README and the published post quote
  `get_dataset`'s shape.
- `src/catalog_mcp/columns.json` — the stand-in for each domain's Glue catalog, including
  how the IBAN columns and the source tables are classified.
- `tools/check_columns.py`, `tools/check_lineage.py` and `tests/fixtures/` — what holds
  this repository's restatements to what the runtime actually does.
- The `dependencies` in `pyproject.toml` — the runtime's version floor, and the base
  install having no execution stack.
- `.github/workflows/` — `release.yml` publishes to PyPI.

## Never

These are the repository's commitments, and the changes that most often break them while
looking reasonable.

- **Never add a write path.** No handler writes, the catalog loads once into an immutable
  mapping, and every object handed out is a frozen model. `readOnlyHint` is display
  metadata; read-only is a property of what the code can do, and
  `tests/test_tools.py` calls a write tool that does not exist to check it.
- **Never return a row, or read the data.** A tool answers from records the governance
  plane holds. "Where are this person's rows?" is a query against the data and stays out
  of scope; the descriptions of `find_datasets` and `get_erasure_scope` say so.
- **Never read OpenLineage events in the server.** Run history belongs to a lineage
  reader such as `qedro`. Only `tools/check_lineage.py` and the tests read events, to
  hold the `lineage` identity to what the runtime emitted.
- **Never forward a caller's token**, and never federate it into AWS with
  `assume_role_with_web_identity`. A token is accepted only from the one issuer, for this
  server's own audience, and goes no further.
- **Never answer an out-of-scope request with an empty result.** A domain the token
  cannot read is a `403` naming the scope it lacks, and the handlers re-check the scope
  on every call. Lists show only granted domains, and `get_erasure_scope` says with
  `complete: false` when it left any out.
- **Never restate what the runtime defines.** `Metadata` and `Contract` are
  `pipeline_runtime.descriptor`'s models, tag validation is `policy.resolve()`, and the
  readers of a table are `pins.readers()`. The one rule restated here, the lineage naming
  in `lineage_of()`, is held to emitted events by a test and by CI.
- **Never classify a table on its owner's behalf.** A source table with no tag but
  `domain` is `classified: false`, never given the tags of the pipelines that read it, and
  a dataset with no `retention` tag reports `null`, never a default period.
- **Never return an unmodelled shape.** Every tool returns a Pydantic model, so the SDK
  derives its `outputSchema`; no tool returns a bare `dict`.

## How to work here

What has caught real defects in this repository, rather than general advice:

- **Check a tool's `outputSchema` after changing its return type**, with
  `client.list_tools()`. The SDK wraps a union return in `{"result": …}`, which silently
  changes the shape every client receives.
- **Run the CI columns job locally when `columns.json` changes**: seed a clone of the
  runtime into `runtime/` (gitignored), run its three example pipelines, then
  `tools/check_columns.py` and `tools/check_lineage.py`. Run it once with
  `tools.seed --drift` as well and watch the check fail; a check that cannot fail
  protects nothing.
- **Install the runtime as a wheel, not editable**, when testing against a local
  checkout of it. An editable install maps no `pipeline_runtime.example`, and every test
  fails for a reason that has nothing to do with the change.
- **Test against the base install too.** The server must run without the runtime's
  `run` extra; CI's test job installs no DuckDB, pandas or OpenLineage client, and a
  change that imports one only fails there.
- **Re-run the tool and paste its real output** when the README quotes it. A walkthrough
  written from memory went stale when the runtime's example gained `retention` tags.
- **A runtime release can break tests without any change here.** CI installs the newest
  runtime within the floor, and the weekly scheduled run exists to notice; tests that
  pin exact tag sets are the ones that break.
- **One concern per pull request**, and no new runtime dependency without an issue
  first: each one is a supply-chain path into a server that holds a catalog's
  classification.
- **Security problems go to [SECURITY.md](SECURITY.md)**, never a public issue.

## Where things are

- `src/catalog_mcp/catalog.py` — loading the catalog: descriptors, `columns.json`, source
  tables, readers and lineage identity.
- `src/catalog_mcp/server.py` — the seven tools, the two resources and their output
  models.
- `src/catalog_mcp/auth.py`, `app.py` — token verification and the per-domain scope
  layer for HTTP; `__main__.py` — the command line.
- `src/catalog_mcp/columns.json` — the stand-in Glue catalog.
- `tools/` — the CI checks that need the runtime's execution stack.
- `tests/fixtures/` — OpenLineage events a runtime release emitted, copied as written.

Python 3.12 is the floor; do not add workarounds for older versions.
