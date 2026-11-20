# catalog-mcp — working notes

@AGENTS.md

The rules above bind every contributor and agent. What follows is the maintainer's
working context: where the design came from, the reasons behind those rules, the other
repositories, and how this repository is released.

The runnable version of [The catalog is the API — a governed mesh over
MCP](https://cordata.tech/en/blog/governed-mesh-over-mcp), which designs the MCP catalog
tool that [Fabric + Mesh on AWS](https://cordata.tech/en/blog/fabric-mesh-on-aws) § 3
proposes. It was specified as cordata-tech/platform#26. The issues since: #1 gave every
dataset the runtime's lineage identity, #2 added `get_consumers` and brought the source
tables into the catalog, #3 added `get_erasure_scope`, and #4 caught the README up with
the runtime's retention tags.

## Why the commitments are what they are

**One model, several consumers** is the published posts' claim, so this repository is
evidence for it or a counterexample. When the server needs something the runtime
computes, the answer is to import it, and when the runtime keeps it behind the `run`
extra, to move it to the base install upstream rather than write it again here.
`pipeline_runtime.pins` was split out of `consumers` in runtime 0.2.9 for exactly this
(#2), the same route the lineage naming fix took as pipeline-runtime#7. The single
restatement left, `lineage_of()`, stays because it is checked against events a runtime
release emitted.

**Read-only enforced rather than annotated** is § 4 of the post: annotations are hints a
client may ignore, so the guarantee has to be what the code can do.

**A `403`, never an empty answer**, is § 5: a client cannot tell an empty result from a
dataset with nothing in it, and an erasure orchestrator cannot tell a filtered list from
a full one, which is why `get_erasure_scope` carries `complete`. The opposite rule for
readers — `get_consumers` lists pipelines in domains the caller cannot read — was
decided on #2: a pin is a dependency declared against the table, and a producer working
from part of the list breaks what it cannot see.

**Unclassified stays unclassified.** The runtime's catalog records only which domain
owns an application's table, because classifying it is the owner's decision (#2). So
`fraud_raw.transactions` holds IBANs and is still `classified: false`, and
`find_datasets` with `subject_type=customer` does not return it; the README says so
rather than hiding it.

## The other repos

| Repo | Answers | Relationship |
|---|---|---|
| [`pipeline-runtime`](https://github.com/cordata-tech/pipeline-runtime) (`cordata-pipeline-runtime` on PyPI) | *What should this pipeline do, and did it?* | The base install is a dependency: descriptor models, `policy`, `pins` and the example. The `run` extra is installed only in CI's columns job |
| [`qedro`](https://github.com/cordata-tech/qedro) | *What happened, and can I prove it to an auditor?* | Reads the lineage this server does not; the two match on the `lineage` namespace and name, and share no code |
| [`art30-emit`](https://github.com/cordata-tech/art30-emit) | *How does code nobody instruments say why it processes?* | None directly |
| `platform` | The site and the posts | The posts quote this repository, and platform#55 names its version |

## Conventions

- **MIT**, public, and on PyPI as `cordata-catalog-mcp`. Anything pushed is public
  immediately, and **pushing a `v*` tag publishes** through trusted publishing, so a tag
  is a release decision.
- **The version is written twice**, in `pyproject.toml` and `catalog_mcp.__version__`.
  The release workflow fails if the tag disagrees with either, or if `CHANGELOG.md` has
  no dated entry for the version.
- **Releasing:** the change goes in with a `## X.Y.Z — unreleased` changelog entry; a
  separate `Release X.Y.Z` commit dates the entry and bumps both version strings. Push
  `main`, then dry-run the workflow with `gh workflow run release.yml --ref main`, which
  does everything but the upload. Only then tag:
  `git tag -s vX.Y.Z -m "cordata-catalog-mcp X.Y.Z — <what it adds>"`.
- **Tags are pushed with `git push origin vX.Y.Z`**, because `jj git push` does not push
  tags. It is the one `git push` in this workflow, and it needs the maintainer's say-so
  each time. A `v*` tag re-pointed after publishing re-runs the Release workflow, which
  fails at upload with `400 File already exists`; delete those runs rather than letting
  them read as a broken release.
- Commit identity is `Laszlo Hadhazy <laszlo@cordata.tech>`, signed. **No assistant
  commit trailers, and no `Signed-off-by` on the maintainer's own commits**: the DCO
  check runs on pull requests only, and the maintainer pushes to `main` directly through
  the ruleset's admin bypass rather than opening pull requests.
- **`jj` is colocated with git.** Work in `jj` — `jj describe`, `jj new`, `jj bookmark set
  main -r @-` and `jj git push --bookmark main` — and use git to read, plus the tag
  commands above.
- **The runtime is a range, not a pin** (`>=0.2.11,<0.3`), so CI picks up each runtime
  patch without a commit here. After a runtime release, check what it changed in the
  parts this server uses: `pins`, the descriptor models, `policy`, the example data and
  the lineage naming.

## A known gap

The posts quote this repository — the governed-mesh post shows `get_dataset`'s schema,
and platform#55 names the released version — and nothing checks that they still agree.
When an output shape or a version a post names changes, check the post.
