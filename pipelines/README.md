# Workflow pipelines

Pipelines are ordered Steps declared in YAML. Each tenant assigns a pipeline
(or uploads a custom one); the worker executes it for every job.

Pipelines shipped in MVP (introduced in Phase 4 / Phase 8):

- `default_v1.yaml` — sync extract → translate → render → notify (no review)
- `with_manual_review_v1.yaml` — parks low-confidence jobs for human approval
- `batch_economy_v1.yaml` — async-only via Anthropic Batch API (50% cheaper)

Step protocol and built-in step inventory live in `core/steps/`. Phase 0 is
scaffold only.
