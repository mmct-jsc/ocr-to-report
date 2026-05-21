# Development Pipeline

> **Effective:** 2026-05-20. All work on `feat/*` branches from this point
> forward follows this pipeline. Hotfix branches may skip stages 1–3 if
> the bug is well-understood; everything else does the full loop.

Every change goes through nine stages. Stages 1–3 are *thinking* work
that lands in commit bodies and PR descriptions; stages 4–9 are *doing*
work that lands in code, tests, CI, and the release pipeline.

---

## 1. Requirements / spec gathering

**Goal:** Know *what* and *why* before touching code.

**Where the requirements come from:**

| Source | Use it when |
|---|---|
| `docs/plans/<YYYY-MM-DD>-*.md` | Multi-task implementation work (v0.2, v0.3, …). |
| `docs/ROADMAP.md` | A new release-sized milestone. |
| GitHub Issue / written spec | Discrete bug or feature request. |
| Brainstorming session (`superpowers:brainstorming` skill) | New idea with no written spec yet. |

**Output:** A bullet list of acceptance criteria in the task or commit body. If the answer to "how will I know I'm done?" isn't crisp, stop and go back to stage 1.

---

## 2. Investigation & research

**Goal:** Don't reinvent. Don't pick the second-best tool by accident.

**Always check (in this order):**

1. **Existing code in this repo.** `Grep` / `Glob` for prior art. Especially: similar repos, related steps in the pipeline engine, sibling SDK methods. New code that doesn't match the existing patterns is a tax on every future reader.
2. **Library docs via `context7`.** The `mcp__plugin_context7_context7__*` tool is mandatory for any library use, even ones you "know" (training data may be stale). Don't guess SDK signatures.
3. **Cross-cutting concerns.** Does this affect multi-tenant isolation, encryption, audit, retention, idempotency, rate-limit? If yes, list them. If no, prove it.

**Output:** Notes in the design section of the commit. References to specific files and library doc URLs.

---

## 3. Approach proposal

**Goal:** Pick the best approach knowing what was rejected.

For every non-trivial change, in the commit body or design doc:

* **Chosen approach.** One paragraph: what you're doing, what data structures, what API shape.
* **Rejected alternatives.** At least one — usually two. One sentence each + why rejected (performance, complexity, future flexibility, dependency surface).
* **Risks accepted.** Things you've deliberately not handled (with rationale).

**Hard rule:** If the only "alternative" is "do nothing," you haven't thought enough. Make it concrete.

---

## 4. Code — TDD

**Skill:** `superpowers:test-driven-development`.

**Order:**

1. Write the failing test. Run it. **See it fail with the expected message.** If it errors for the wrong reason (import error, fixture missing), fix the test first.
2. Write the minimal implementation. Run the test. See it pass.
3. Refactor if needed; tests must stay green.
4. Run the broader suite for the touched package: `pytest packages/<pkg>/tests/ -q`.
5. Commit (one logical change per commit).

**No bundling.** "While I'm here" improvements get their own commit. The diff a reviewer reads should map 1:1 to the commit message.

---

## 5. Test — code + real interaction

**Goal:** Cover the contract from inside (unit) and from outside (the path a user actually takes).

| Layer | Tool | When |
|---|---|---|
| Pure logic | `pytest` unit tests | Every change in `core/` or stateless helpers. |
| Property | `hypothesis` | Every parser, mapper, validator. |
| Integration | `pytest -m integration` + `testcontainers` | Every change that touches DB, blob, queue. |
| HTTP contract | `schemathesis` | Every new or modified endpoint. |
| **Real browser** | `mcp__plugin_playwright_playwright__*` | Every change that adds or modifies a route in `web/`. |

For Playwright e2e: load the page, exercise the user's actual click path, screenshot the result, assert state. A unit test claiming the React component renders is not a substitute.

### 5b. UX behaviour coverage (web changes only)

Every new or modified web route ships with explicit coverage of:

| Behaviour | What "covered" means |
|---|---|
| **Loading state** | While the request is in flight, the user sees a skeleton, spinner, or progress indicator within 100ms — never a frozen UI. Verify with a Playwright screenshot taken between request-issued and response-received (or by stubbing the fetch to be slow). |
| **Success state** | The success path shows what changed (a toast, a row appearing, navigation). The user is not left wondering whether the action took effect. |
| **Error state** | Every API call has an `onError` branch with a human-readable toast or inline message. "Something went wrong" is not an acceptable error message — it says *what* failed AND *what to do next*. |
| **Empty state** | If the data set is empty, show an explainer + a primary CTA, not a blank panel. (See the existing Dashboard "No jobs yet — start with /upload" pattern.) |
| **Optimistic update** | For low-risk writes (toggle a flag, rename a thing), update the UI before the request returns, with rollback on error. High-risk writes (delete, publish) stay confirmation-first. |
| **Keyboard navigation** | Tab order is sensible. `Enter` submits forms. `Esc` dismisses modals/dropdowns. Focus rings visible. |
| **Mobile breakpoint** | The route works at 360px, 768px, and 1280px+. Screenshot all three with Playwright. No horizontal scroll. Touch targets ≥ 44 × 44px. |
| **Accessibility** | WCAG 2.1 AA: color contrast ≥ 4.5:1 (≥ 3:1 for large text), every icon-only button has `aria-label`, form errors associated with their fields via `aria-describedby`, screen-reader nav order matches visual. |
| **Microcopy** | Buttons say what they do (`Save changes`, not `Submit`). Errors are actionable. Confirmations are specific (`Delete tenant Acme?`, not `Are you sure?`). |

**Tools:**

- `mcp__plugin_playwright_playwright__browser_resize` + screenshot at each breakpoint.
- `mcp__plugin_playwright_playwright__browser_evaluate` for `axe-core` (`window.axe.run()`) to catch a11y violations automatically.
- The `design:accessibility-review` agent for a structured a11y audit when the change is non-trivial.
- The `design:ux-copy` agent for microcopy review on new strings.

**Output:** Test counts before/after in the commit body. For web changes, also: list of breakpoints verified + a11y violations found (must be 0).

---

## 6. Performance — does it pass the specs bar?

**Goal:** Don't ship slow code by accident.

**Specs bars** (default — override per task when warranted):

| Layer | Bar | Measurement |
|---|---|---|
| API handler (P95) | < 100ms cold, < 30ms warm (excl. provider call) | `pytest-benchmark` or in-test `time.process_time` (CPU, not wall) + median of 5 runs. |
| DB query (single) | < 10ms on the local Postgres | `EXPLAIN ANALYZE` for any new query touching > 1 row. |
| Bundle size delta | < +20kb gzipped per route | `vite build` output. |

### Core Web Vitals (web routes)

These map onto Google's published thresholds for *Good* (which we aim for; Needs Improvement = a fail in this pipeline):

| Metric | Bar | Measurement |
|---|---|---|
| **LCP** (Largest Contentful Paint) | < 2.5s | `browser_evaluate(() => performance.getEntriesByType('largest-contentful-paint')[0].startTime)`. |
| **CLS** (Cumulative Layout Shift) | < 0.1 | `browser_evaluate` with `PerformanceObserver('layout-shift')`. |
| **INP** (Interaction to Next Paint) | < 200ms | Triggered click in Playwright + measure to paint via `requestAnimationFrame` round-trip. |
| **TTFB** (Time to First Byte) | < 600ms | Network panel via `browser_network_request`. |

### Responsiveness (perceived performance — UX bars)

| Behaviour | Bar | How |
|---|---|---|
| Click → visible feedback | < 100ms | The button visually responds (state change, ripple, focus) before the request completes. |
| Skeleton/spinner shown | If wait > 200ms | If a request takes longer than 200ms, the UI shows progress; otherwise it's better to not flash a spinner. |
| First meaningful paint (route) | < 1.5s on local stack | Playwright `domcontentloaded` + content assertion. |
| Touch target | ≥ 44 × 44 px on touch viewport | Inspect via `browser_evaluate` on `getBoundingClientRect()`. |

**If the bar isn't hit:** Stop, profile, fix. Do not ship-and-fix later. For web bars, profile with React DevTools, Chrome Performance panel, or `browser_run_code` to add timing markers.

**Output:** Numbers in the commit body. For web changes, all four CWV metrics + responsiveness bars listed explicitly. If the change is performance-neutral by design (docs, comments, internal logic), say so explicitly.

---

## 7. Code review

**Goal:** A fresh pair of eyes confirms correctness, security, and convention adherence.

**Who reviews:**

* **Automated first:** spawn `superpowers:code-reviewer` agent with the diff. The agent has full repo context but no conversation context, so it catches assumptions baked into the conversation.
* **For web changes — add design agents:**
  * `design:design-critique` — layout, hierarchy, consistency.
  * `design:accessibility-review` — WCAG 2.1 AA audit.
  * `design:ux-copy` — microcopy review on every new visible string.
  Run all three in parallel after `code-reviewer` returns.
* **Self-review second:** read the diff one more time before commit, looking for the specific issues every agent flagged.
* **Human review (for shared work):** open a PR; one human approval before merge to `main`.

**Reject reasons:**

* Confidently flagged bug.
* Convention violation (`mypy --strict`, `ruff`, file naming, import order).
* Missing test for a non-trivial path.
* Security concern (see stage 8).
* Documentation drift (README / CHANGELOG / ROADMAP not updated).
* **Web routes:** a11y violation found by axe-core or the accessibility-review agent, microcopy regression flagged by ux-copy agent, breakpoint break (horizontal scroll, broken layout) at any of the three reference widths.

**Output:** Reviewer's findings addressed inline; the agent's report linked or pasted into the PR description.

---

## 8. Security scan

**Goal:** No new attack surface, no leaked secrets, no vulnerable dependencies.

**Automated, every commit:**

* `ruff check --select S` — bandit-equivalent rules baked into ruff.
* `bandit -c pyproject.toml -r packages` — full bandit pass.
* `pip-audit --strict` — CVE check on transitive deps.
* `trivy` — container image scan (post-build).

**Manual when relevant:**

* New auth path → trace bearer / scope / tenant_id all the way through.
* New encryption → verify DEK / KEK envelope, no plaintext in logs.
* New PII column → annotate with `PIIClass`, regenerate the redaction map.
* New egress (HTTP / DB / blob) → confirm the egress allowlist still passes.

**Output:** Any new `# noqa: S<n>` lines must include a justification comment. `bandit` and `pip-audit` clean before merge.

---

## 9. Publish

**Goal:** A green tag pushes signed images and creates a release. No manual steps.

1. `git push` the feature branch.
2. CI must be green (`gh pr checks --watch`).
3. Squash-merge to `main`.
4. If the work warrants a release: bump `CHANGELOG.md`, then `git tag v<x.y.z>+<qualifier> && git push --tags`.
5. The `.github/workflows/release.yml` workflow handles the rest: GHCR multi-arch images, SBOM, cosign signatures, GitHub Release auto-extracted from the CHANGELOG.

---

## Scaling — when stages collapse

Not every change needs all nine stages. Common collapses:

| Change shape | Stages that collapse |
|---|---|
| Typo / comment fix | 1–3 trivial; 6 N/A; rest standard. |
| Internal core wiring (no UI) | Stage 5 has no Playwright + no 5b (UX behaviours). Stage 6 has no Core Web Vitals or responsiveness bars. Stage 7 skips design agents. |
| Doc-only change | 5–6 N/A. Stage 7 still runs (the agent checks for staleness). |
| Hotfix on call | 1–3 may be one sentence; everything else still runs. |
| New endpoint | All nine stages; stage 5 includes contract test, stage 5b N/A. |
| **New web route or modified route** | All nine stages **in full**, including stage 5b (loading / success / error / empty / optimistic / keyboard / mobile / a11y / microcopy), all Core Web Vitals + responsiveness bars in stage 6, all three design agents in stage 7. The scaling rule that lets web change skip any of these is: there is no such rule. |
| **Modified existing web component** | Same as new route, scoped to the affected screens. If the change touches only internal logic (no rendered output difference), 5b + design agents can be skipped — but `axe-core` still runs because non-visual changes can still regress focus management or aria attrs. |

The bar for collapsing a stage is: **can you defend skipping it in the commit body?** If yes, skip and document. If you'd be embarrassed for someone to ask, do the stage.

---

## Enforcement

* `.github/workflows/ci.yml` runs stages 4–8 mechanically on every PR.
* `release.yml` runs the full gate before publishing.
* Pre-commit hooks run a fast subset (ruff, mypy, secrets scan).
* This document is the contract; PRs that skip stages without justification get rejected.

If a stage feels expensive, fix the tooling, not the process.
