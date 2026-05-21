/**
 * Runtime detection of the deployment mode.
 *
 * The Pages build sets ``VITE_STATIC_DEMO=true`` in the GitHub Actions
 * workflow (.github/workflows/pages.yml). At build time Vite inlines
 * that into ``import.meta.env`` so the SPA can branch UI on it without
 * runtime config:
 *
 *   * ``isStaticDemo === true``  — no backend will ever be reachable.
 *     The /login route, all "Sign in" CTAs, and the "API unreachable"
 *     red indicator should be hidden or rewritten as "Demo mode" /
 *     "Deploy locally" pointers. Visitors land on /demo by default.
 *
 *   * ``isStaticDemo === false`` — normal docker / nginx deployment
 *     with a real API. Auth flow renders normally.
 *
 * Surfaces consuming this:
 *   - App.tsx routing — static demo redirects auth-protected routes
 *     to /demo + replaces /login with a friendly explanation.
 *   - demo.tsx CTAs — primary action becomes "Deploy locally" /
 *     "View source" instead of "Try the live console."
 *   - layout.tsx topbar — health indicator hidden in demo mode.
 */
export const isStaticDemo: boolean = import.meta.env.VITE_STATIC_DEMO === "true";

/** URL of the public repo. Used in static-demo CTAs. */
export const REPO_URL = "https://github.com/mmct-jsc/ocr-to-report";

/** README anchor for the "deploy locally" instructions. */
export const DEPLOY_GUIDE_URL = `${REPO_URL}#quick-start`;
