# Operations Console screenshots

Captured against the live `docker compose up` stack with Playwright MCP.
Tenant: Acme. SLA: Standard. One transcript processed end-to-end (Polish
ŚWIADECTWO → US-HS Grade-9 xlsx, $0.0313, 3,192/419 tokens, ~4s).

| File | What it shows |
|---|---|
| `dashboard-light.png` | Dashboard with live KPIs, recent jobs, manual-review queue |
| `dashboard-dark.png` | Same, dark theme |
| `upload-with-file.png` | Drag-and-drop dropzone with a 20.5 MB PNG selected, routing form |
| `job-after-upload.png` | Job detail after a successful sync extract — Sonnet 4.6, $0.0313, Download ready |
| `jobs.png` | Jobs list with filterable status (1 succeeded, 4 failed, 2 pending) |
| `job-detail.png` | Job detail layout (status grid + actions panel) |
| `webhooks.png` | Webhook subscriptions list + add form |
| `compliance.png` | DSR Article 15 result for "Antoni Judek" (1 record returned) |
| `templates.png` | Target catalog (us-hs.v1 with grade_9 template) |
