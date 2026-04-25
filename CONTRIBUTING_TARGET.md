# Adding a Target System

A target system bundle describes a specific report destination — the
grade scale, year naming, subject taxonomy, and template files. Adding a
target **does not require any Python code changes**.

## Target id format

`<system>.v<N>` — lowercase, dot-separated, trailing `.v<N>` for version.
Examples:

- `us-hs.v1` — US High School (Grades 9-12)
- `us-college.v1` — US college (4.0 GPA scale)
- `uk-ucas.v1` — UK UCAS Tariff
- `ib-dp.v1` — IB Diploma (1-7 scale)

## Steps

1. **Create the bundle directory** under `targets/<id>/`:

```
targets/<id>/
├── manifest.yaml
├── grade_scale.yaml
├── conduct_scale.yaml
├── year_system.yaml
├── subject_taxonomy.yaml
└── templates/
    ├── <key>.binding.yaml
    └── <key>.<format>          (xlsx/pdf/docx)
```

2. **Copy the US-HS target** (`targets/us-hs.v1/`) as a starting point.

3. **Each template** has a `.binding.yaml` describing which source-side
   fields go into which template cells, plus the actual template file
   alongside it. See `targets/us-hs.v1/templates/grade_9.binding.yaml`
   for a full example.

## Adding a template

Inside `targets/<id>/templates/`, add a `.binding.yaml` per template.
Required fields:

- `key` — slug, used by the renderer to select among templates
- `blob_path` — relative path to the template file (e.g.,
  `grade_10.xlsx`); the loader re-anchors this against the bundle root
- `output_format` — one of `xlsx`, `pdf`, `csv`, `docx`, `json`
- `target_year_index` — the year this template renders (e.g., `9` for
  Grade 9). The renderer uses this to select the correct template.
- `bindings` — list of cell-level bindings. Each binding has:
  - `cell` — A1 reference (`A1`, `D19`, etc.)
  - `kind` — one of the values in `TemplateBindingKind`
  - `subject_id` — required for `subject.grade` / `subject.hours`
  - `literal_value` — required for `literal`

## Hours per year

`subject_taxonomy.yaml` carries per-year hour counts. If a subject has
the same hours every year, set `base_hours_default`. If it varies, set
`base_hours_per_year: { <year>: <hours>, ... }`. Subjects that may be
absent in some years should declare `optional: true`.

## Validation

```bash
uv run python -c "
from pathlib import Path
from ocr_to_report.core.targets import load_target_bundle
load_target_bundle(Path('targets/<your-id>'))
print('OK')
"
```
