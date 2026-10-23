# Fixtures

`pipeline-runtime-0.2.2.ndjson` is the OpenLineage file `cordata-pipeline-runtime`
0.2.2, installed from PyPI, wrote on 2026-10-23 when its three example pipelines ran
against a freshly seeded example, from the repository at tag `v0.2.2`:

```sh
python -m tools.seed --clean
python -m pipeline_runtime example/domains/fraud/pipelines/transactions_scored.yml
python -m pipeline_runtime example/domains/policy/pipelines/claims_ingest.yml
python -m pipeline_runtime example/domains/finance/pipelines/merchant_settlement.yml
```

Six events: a `COMPLETE` and a validation `OTHER` per pipeline. It holds no rows,
only dataset names, schemas, tags and provenance. It is copied as written rather
than edited, so the tests check the mapping against what the runtime emits, not
against what somebody expected it to.
