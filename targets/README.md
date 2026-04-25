# Target system bundles

Each subdirectory is a self-contained target system (e.g., `us-hs.v1/` for US
high school). Loaded by `core/targets/` at startup.

Bundle structure (introduced in Phase 2):

```
<target_id>/
├── manifest.yaml          # id, version, system_name, year_range
├── grade_scale.yaml       # target grade scale (A+/A/B/C/D-E/F or 0.0–4.0 GPA)
├── year_system.yaml       # year/grade names
├── subject_taxonomy.yaml  # canonical_id → display name + base hours per year
└── templates/             # output template files (xlsx/pdf/csv)
    ├── grade_9.xlsx
    ├── grade_10.xlsx
    └── ...
```

Phase 0 ships scaffolds only. Phase 2 populates `us-hs.v1/` Grade 9 fully and
stubs Grades 10/11/12 and other targets.

To add a new target: see `CONTRIBUTING_TARGET.md` (Phase 2).
