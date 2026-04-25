# Adding a Source Profile

A source profile is a self-contained YAML bundle that describes a specific
document type from a specific education system in a specific language.
Adding a new profile **does not require any Python code changes**.

## Profile id format

`<lang>.<system_or_subsystem>.<doc_type>.v<N>` — lowercase, dot-separated,
trailing `.v<N>` for version. Examples:

- `pl.lo.swiadectwo_szkolne.v1` — Polish liceum (LO) school certificate
- `vi.high_school.report.v1` — Vietnamese high school report
- `es.bachillerato.expediente.v1` — Spanish bachillerato transcript
- `de.gymnasium.zeugnis.v1` — German Gymnasium report
- `fr.lycee.bulletin.v1` — French lycée bulletin

## Steps

1. **Create the bundle directory** under `profiles/<id>/`:

```
profiles/<id>/
├── manifest.yaml
├── extraction_schema.yaml
├── vocabulary.yaml
├── grade_scale.yaml
├── conduct_scale.yaml
├── year_system.yaml
└── prompts/
    └── extraction.md
```

2. **Copy the Polish profile** (`profiles/pl.lo.swiadectwo_szkolne.v1/`)
   as a starting point and edit each file. The structure is identical
   across profiles; only the content changes.

3. **Validate** by running the loader:

```bash
uv run python -c "
from pathlib import Path
from ocr_to_report.core.profiles import load_profile_bundle
load_profile_bundle(Path('profiles/<your-id>'))
print('OK')
"
```

4. **Add an anonymized fixture transcript** under
   `tests/fixtures/anonymized/<your-id>.pdf` (with names + dates redacted
   to fictional values). Real student data must never be committed.

5. **Add a snapshot test** mirroring
   `tests/integration/test_polish_to_us_hs.py` (Phase 4).

## YAML conventions

- Grade scale levels MAY use either `normalized: <0..1 float>` directly
  OR `canonical: <FAIL|PASS|SATISFACTORY|GOOD|VERY_GOOD|EXCELLENT>`.
  The loader maps `canonical` to the enum's lower bound on the 0..1 scale.
- All raw values + aliases are case-folded and trimmed before lookup.
- Subject `canonical_id` must be one of the values in
  `ocr_to_report.core.enums.canonical.CanonicalSubjectId`. To add a new
  canonical id, edit that enum (additive change — non-breaking).
- The `extraction_schema.yaml` field names MUST match the conventional
  names recognized by the mapping engine (see
  `ocr_to_report.core.mapping.extraction.CANONICAL_EXTRACTION_FIELDS`).

## What the prompts/extraction.md contains

The vision-model system prompt template. Three interpolation slots are
supported (at least one must appear):

- `{schema_json}` — JSON Schema derived from `extraction_schema.yaml`
- `{language_hint}` — Two-letter language code + native-language name
- `{document_type}` — Document type slug from the manifest

The Polish profile's `prompts/extraction.md` is a reference example.
