# Contributing

## Development setup

```bash
# Prerequisites: uv >= 0.10, docker >= 24, make
git clone <repo> ocr-to-report && cd ocr-to-report
make install            # syncs uv workspace + installs pre-commit hooks
make dev                # brings up postgres + redis + minio + api
make test               # fast suite (<10s)
make ci                 # everything CI runs
```

## Workflow

1. Branch from `main`. Branch names: `feat/<short>`, `fix/<short>`,
   `chore/<short>`, `docs/<short>`.
2. Make changes; keep commits focused. Pre-commit hooks run automatically.
3. Run `make ci` locally — must pass before PR.
4. Open a PR. CI must be green; coverage may not regress.
5. One reviewer approval + green CI = merge. Squash-merge.

## Coding conventions

- **Type-checked**: `mypy --strict` clean. No `Any` without justification.
- **Pydantic v2** for all data structures crossing module boundaries.
- **No magic strings**: enums + module-level constants.
- **Structured logging only**: `structlog`. Never `print` outside CLI command
  output. PII fields auto-redact via the annotation system in `core/pii/`.
- **Async by default** for all I/O code paths. Pure-domain helpers may be
  sync.
- **No bare `except`**. Catch the narrowest exception that makes sense.
- **Comments explain WHY**, not WHAT. The diff and the function name explain
  what.
- **Public functions documented with one-line docstrings** describing
  contract; longer docstrings only for non-obvious invariants.

## Adding a source profile

See `CONTRIBUTING_PROFILE.md` (Phase 2 will introduce this). Short version:
copy an existing `profiles/<id>/` directory, fill in the YAML, write a
fixture transcript and snapshot test. **No Python code changes required.**

## Adding a target system

See `CONTRIBUTING_TARGET.md` (Phase 2). Short version: copy an existing
`targets/<id>/` directory, fill in the YAML, ship the template file.

## Test conventions

- Unit tests: pure functions, no I/O.
- Property tests: `hypothesis`, marked with `@pytest.mark.property`.
- Integration tests: marked `@pytest.mark.integration`, use `testcontainers`.
- E2E: marked `@pytest.mark.e2e`, gated by `LIVE_TESTS=1` env var.
- Snapshots: `syrupy`. Update only with explicit `--snapshot-update` and a PR
  comment justifying the change.
- **No real student data** in the repo. Use synthetic or anonymized fixtures.

## PR description template

```markdown
## What
One-line description.

## Why
The user-facing or internal need this addresses.

## How
Key implementation choices, especially anything non-obvious.

## Testing
- [ ] Unit
- [ ] Integration (if applicable)
- [ ] Snapshot diffs reviewed

## Checklist
- [ ] CI green locally (`make ci`)
- [ ] Docs updated (README / ARCHITECTURE / ADR)
- [ ] No new PII paths without redaction tests
```
