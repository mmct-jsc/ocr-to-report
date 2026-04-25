# Source profile bundles

Each subdirectory is a self-contained source profile (e.g.,
`pl.lo.swiadectwo_szkolne.v1/`). Profiles are loaded by `core/profiles/` at
startup; tenants enable subsets per their config.

Bundle structure (introduced in Phase 2):

```
<profile_id>/
├── manifest.yaml          # id, version, language, education_system, fingerprint
├── extraction_schema.yaml # declarative field list → dynamic Pydantic model
├── vocabulary.yaml        # subject/grade word translations
├── grade_scale.yaml       # source-side grade scale
├── year_system.yaml       # class/year naming + promotion rules
├── prompts/extraction.md  # vision prompt template
└── samples/               # sample images (gitignored)
```

Phase 0 ships scaffolds only. Phase 2 populates `pl.lo.swiadectwo_szkolne.v1`
fully and stubs the others.

To add a new language: see `CONTRIBUTING_PROFILE.md` (Phase 2).
