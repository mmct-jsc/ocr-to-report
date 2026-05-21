# Retroactive UX / A11y / Microcopy audit — 2026-05-20

> **Context:** v0.1.0+resilience and earlier shipped before the
> 9-stage pipeline elevated responsiveness + UX to first-class gates.
> This audit retroactively applies the new stages 5b / 6 / 7 (web)
> to every existing route. Three agents reviewed the source in
> parallel: design-critique, accessibility-review, ux-copy.

## Findings count

| Dimension | Blocker | Serious | Polish | Total |
|---|---:|---:|---:|---:|
| Design | 3 | 12 | 7 | 22 |
| A11y (WCAG 2.1 AA) | 13 | 13 | 7 | 33 |
| Microcopy | 6 | 17 | 15 | 38 |
| **Total raw** | **22** | **42** | **29** | **93** |

Many findings share a single root cause. The **leverage map** below
collapses them into 10 fixes that close >90% of the blockers.

---

## Leverage map — 10 fixes, 22 blockers + 27 serious closed

### LV1 — Darken `--warning` / `--success` / `--danger` light-theme tokens

**Closes:** A11y BLOCKERs #1, #2, #3 (12+ surface points across StatusBadge, Parked-for-review heading, success toasts, danger callouts).

**Fix:** In `web/src/index.css` (or wherever the light-theme CSS vars live), bump light-theme tokens to 700-shade variants:
- `--warning: 161 98 7` (amber-700, was yellow-500)
- `--success: 5 122 85` (emerald-700, was emerald-500)
- `--danger: 185 28 28` (red-700, was red-500)

Dark theme already passes; leave untouched.

**Files:** `web/src/index.css`, no JSX changes.

---

### LV2 — `aria-hidden="true"` on every decorative lucide icon inside text buttons

**Closes:** A11y BLOCKER #7 (icon name duplication across 30+ buttons site-wide).

**Fix:** Site-wide grep/replace inside `web/src/`: every `<IconName size={N} />` rendered next to a text label inside a `<button>`, `<Link>`, `<NavLink>`, or `<a>` gets `aria-hidden="true"`. Standalone icon-only buttons keep their `aria-label` (no `aria-hidden`).

**Files:** every route + `components/layout.tsx`, `components/tenant-switcher.tsx`.

---

### LV3 — Add accessible name to the jobs filter `<Select>`

**Closes:** A11y BLOCKER #11.

**Fix:** `web/src/routes/jobs.tsx:53-64` — add `aria-label="Filter by status"` to the `<Select>` (or wrap with a visible `<Label>` if there's space).

---

### LV4 — Replace `window.confirm()` with an in-app `AlertDialog`

**Closes:** A11y BLOCKER #6, Microcopy BLOCKERs #1 (archive confirm) + #2 (revoke confirm). Eliminates the design SERIOUS #15 (sign-out silent) concern too.

**Fix:** New `web/src/components/ui/alert-dialog.tsx` (Radix-style: focus-trap, `role="alertdialog"`, `aria-labelledby` + `aria-describedby`). Replace `window.confirm` callers in:
- `routes/admin-tenants.tsx:123` (archive)
- `routes/admin-tenant-detail.tsx:310` (revoke)

Copy templates:
- Archive: *"Archive tenant **`{name}`**? Archived tenants stop accepting new requests but keys, jobs, and audit history are preserved. You can restore from the tenant detail page."*
- Revoke: *"Revoke key **`{label || prefix}`**? Active sessions using it fail with 401 immediately. This can't be undone — issue a new key to replace it."*

---

### LV5 — Inline form errors with `aria-invalid` + `aria-describedby`

**Closes:** A11y BLOCKER #8, Microcopy BLOCKERs #3 + #4 (login error specificity).

**Fix:** New `<FormField>` wrapper around `<Input>` that:
- Renders `aria-invalid={!!error}` on the input.
- Renders `aria-describedby={`${id}-error`}` linking an inline error `<p id="${id}-error" role="alert">`.
- The toast still fires for cross-cutting failures (network), but field-specific errors inline.

Update messages:
- Login auth-fail: *"The API rejected this key. Check the value, or run `ocr-to-report bootstrap` to issue a new one."*
- Login non-200: *"Server error {status}. The API answered but couldn't validate the key. Verify the base URL and try again."*

---

### LV6 — `CardTitle` renders `<h2>` by default with a `level` prop escape hatch

**Closes:** A11y BLOCKER #10 (heading-level skip h1 → h3 across 11 routes).

**Fix:** `web/src/components/ui/card.tsx:17` — `CardTitle` currently renders `<h3>`. Change default to `<h2>`; accept `level?: 2|3|4` prop for the rare cases where a section needs nested headings.

---

### LV7 — Tenant-switcher: real menu semantics + visible warning state

**Closes:** A11y BLOCKERs #5 + #22 (focus trap + invalid ARIA mix), Design SERIOUS #7 (impersonation under-emphasized).

**Fix:** Rewrite `web/src/components/tenant-switcher.tsx`:
- `role="menu"` on panel, `role="menuitem"` on each row, `aria-activedescendant` on trigger.
- Focus moves into the panel on open; Tab cycles inside; Escape returns focus to trigger.
- When `actingTenantId !== null`: trigger renders as a **filled** warning chip (not thin border) with `Eye` icon + bold tenant name; full-width sticky banner across `<main>` reads *"You are acting as `{name}` — every action is audited on the target tenant."*
- Add `aria-controls` from trigger to panel id.

---

### LV8 — `<main>` layout: drop `max-w-7xl mx-auto` from the global wrapper

**Closes:** Design BLOCKER #2.

**Fix:** `web/src/components/layout.tsx:211` — remove `max-w-7xl mx-auto` from the global `<main>`. Routes that genuinely need a narrow column (e.g., `/upload`, single-record forms) opt in with their own `max-w-3xl`. List views (jobs, audit, tenants) get the full viewport minus sidebar.

Also: add `<main>` landmark to `demo.tsx` (currently a `<div>` — A11y SERIOUS #17).

---

### LV9 — Standardize empty states via the existing `EmptyState` component

**Closes:** Design SERIOUS #8 (sparkle emoji drift), Microcopy SERIOUS x4 (dashboard parked, jobs filtered, admin-tenants list, templates list).

**Fix:** Replace ad-hoc empty paragraphs with `<EmptyState icon=... title=... description=... action=... />`. Specific copy:
- Dashboard parked-queue: *"Nothing to review. Low-confidence extractions appear here when the SLA gate parks them."*
- Jobs filtered: *"No jobs are currently `{status}`."* + Clear-filter button.
- Admin tenants: *"No tenants yet. Use **Create tenant** above to provision the first."*
- Templates: *"No target bundles loaded. Drop a YAML bundle into `./targets/<id>/` and restart the API. See `docs/TARGETS.md`."*

---

### LV10 — Toasts: error-toast stickiness + upload status tone

**Closes:** Microcopy BLOCKER #5 (upload toast wrong tone on failed), polish item on auto-dismiss.

**Fix:**
- `components/toast.tsx`: errors stay until dismissed (or 15s minimum), info/success at 5s.
- `routes/upload.tsx:79`: branch tone by `resp.job.status`:
  - `succeeded` → `toast.success("Extraction complete", ...)`
  - `parked` → `toast.warn("Parked for review", "...")`
  - `failed` → `toast.error("Extraction failed", resp.job.error_detail ?? "...")`

---

## Other items not in the 10 fixes

### A11y SERIOUS (do after blockers)

- Sidebar mobile overlay: add `Esc` keyboard close (#16).
- Tables: `<th scope="col">` + accessible empty `<th>` for actions column (#20, #21).
- `aria-live="polite"` on `<StatusBadge>` containers in detail views so auto-refetch flips announce (#25).
- Secret reveal: `aria-live` on `<code>` (#24).
- Reduced-motion media query for `animate-pulse`, `animate-spin`, `smooth-scroll`, `animate-fade-in` (#27, #30).
- Touch targets: pad `remove` (upload.tsx:152) and eye-toggle (login.tsx:143) to ≥ 44px (#19).

### Design SERIOUS (do after blockers)

- Table-row density consistency: pick `py-2.5`, apply across jobs / admin-tenants / admin-tenant-detail (#4).
- `job-detail.tsx` "Idempotency key: —" hardcoded dead field (#5).
- `webhooks.tsx` double-badge collapse (#9).
- `jobs.tsx` filter summary uses raw text instead of badges (#10).
- `admin-tenant-detail.tsx` metadata column overflow (#11).
- `demo.tsx` hero needs a screenshot above the fold (#12).
- `tierTone` for enterprise should not be `warning` (#15).

### Microcopy SERIOUS (do after blockers)

(17 items — buttons, toasts, helper text. Batch into a single "microcopy sweep" commit.)

### POLISH (29 items)

Deferred to a follow-up task. Filed as `docs/audits/2026-05-20-polish-todo.md`.

---

## Plan

**Batch A (LV1, LV2, LV3, LV6) — token + label fixes.** ~150 lines of edits, no behaviour change. Mechanical.

**Batch B (LV4) — AlertDialog component + two callers.** New file + two replacements. ~200 lines.

**Batch C (LV5) — FormField wrapper + login + webhooks rewires.** ~120 lines.

**Batch D (LV7) — Tenant-switcher rebuild + warning banner.** Substantial. ~250 lines.

**Batch E (LV8 + LV9 + LV10) — Layout + empty states + toast tone.** ~150 lines.

**Batch F — Remaining SERIOUS items.** Spread across 2-3 commits.

Each batch goes through the full pipeline: TDD where possible (toast tone, FormField), Playwright axe-core scan after each, screenshots at 3 breakpoints, design agent re-review on the diff.

---

## Verification gates

After all batches:
- `axe-core` clean (0 violations) on every route at light + dark theme.
- Lighthouse a11y score ≥ 95 on every authenticated + public route.
- Color contrast ≥ 4.5:1 on every text/background pair (verified via axe).
- Keyboard nav: every interactive element reachable, focus visible, Esc closes overlays.
- Mobile breakpoint screenshots at 360 / 768 / 1280px clean on every route.
- Re-spawn the three design agents on the diff; all blockers resolved.
