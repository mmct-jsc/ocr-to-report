import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ShieldCheck,
  Layers,
  Building2,
  Eye,
  KeyRound,
  Workflow,
  Activity,
  Github,
  Zap,
  Globe,
  FileSpreadsheet,
  CheckCircle2,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useTheme } from "@/lib/theme";

/**
 * Public-facing demo / feature tour page.
 *
 * Unauthenticated: a visitor can land here without an API key and see
 * what the platform does end-to-end. Every screenshot below is from the
 * real running stack (captured in docs/ui/, mirrored to /demo-assets/ for the
 * SPA build to ship statically).
 *
 * Designed as one long scrollable page — no in-page nav, just a hero,
 * three "what it does" axes, a feature gallery, and CTAs. The layout
 * intentionally does NOT use the AppLayout (no sidebar) so it works as
 * a marketing landing target.
 */

/**
 * Prefix a public-asset path with Vite's resolved ``base`` so the
 * built URL works on both ``/`` (docker / nginx) and ``/ocr-to-report/``
 * (GitHub Pages subpath deploy). Without this, ``/demo-assets/foo.png``
 * 404s on Pages because it resolves to the host root instead of the
 * project subdirectory.
 */
function withBase(path: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  return base + (path.startsWith("/") ? path : `/${path}`);
}

export function DemoRoute() {
  const { theme, toggle } = useTheme();
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);
  const [apiVersion, setApiVersion] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch("/api/v1/version");
        if (!r.ok) throw new Error("api unreachable");
        const v = (await r.json()) as { api?: string };
        if (alive) {
          setApiReachable(true);
          setApiVersion(v.api ?? "unknown");
        }
      } catch {
        if (alive) setApiReachable(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ──────────── Top bar ──────────── */}
      <header className="sticky top-0 z-30 h-14 bg-background/80 backdrop-blur border-b border-border">
        <div className="max-w-6xl mx-auto h-full px-4 flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-primary text-primary-foreground grid place-items-center text-xs font-bold">
              OR
            </div>
            <span className="text-sm font-semibold tracking-tight">OCR-to-Report</span>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground rounded-full px-2 py-0.5 border border-border ml-2">
              Demo
            </span>
          </div>
          <div className="flex-1" />
          <div className="hidden sm:flex items-center gap-2 text-[11px] text-muted-foreground">
            <span className={cn("h-2 w-2 rounded-full", apiReachable ? "bg-success" : apiReachable === false ? "bg-danger" : "bg-muted-foreground")} />
            {apiReachable === null
              ? "checking…"
              : apiReachable
                ? `API healthy${apiVersion ? ` · v${apiVersion}` : ""}`
                : "API unreachable"}
          </div>
          <button
            type="button"
            onClick={toggle}
            className="text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded-md"
            aria-label="toggle theme"
          >
            {theme === "dark" ? "Light" : "Dark"}
          </button>
          <Link
            to="/login"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:opacity-90"
          >
            Sign in
            <ArrowRight size={14} />
          </Link>
        </div>
      </header>

      {/* ──────────── Hero ──────────── */}
      <section className="max-w-6xl mx-auto px-4 pt-16 pb-12">
        <p className="text-xs uppercase tracking-wider text-muted-foreground mb-3">
          Schema-driven · multi-tenant · multi-provider
        </p>
        <h1 className="text-4xl md:text-5xl font-semibold tracking-tight max-w-3xl">
          Turn any school transcript into any target report —{" "}
          <span className="text-primary">without writing code per language</span>.
        </h1>
        <p className="text-base md:text-lg text-muted-foreground mt-6 max-w-2xl">
          Add a new source language by dropping a YAML bundle. Add a new target system the
          same way. Everything else — tiered vision, encryption, audit, manual review,
          webhooks — is universal core. This page tours what's shipped today.
        </p>

        <div className="flex flex-wrap gap-3 mt-8">
          <Link
            to="/login"
            className="inline-flex items-center gap-2 h-10 px-5 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:opacity-90"
          >
            <Sparkles size={16} /> Try the live console
          </Link>
          <a
            href="https://github.com/QuocTran/OCR_to_Report_QT"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 h-10 px-5 rounded-md text-sm font-medium border border-border hover:bg-muted"
          >
            <Github size={16} /> View on GitHub
          </a>
        </div>

        <ul className="mt-10 flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground">
          <Bullet icon={ShieldCheck} text="FERPA + GDPR aligned" />
          <Bullet icon={Layers} text="Pluggable vision providers" />
          <Bullet icon={Workflow} text="YAML-defined pipelines" />
          <Bullet icon={KeyRound} text="Per-tenant DEKs" />
          <Bullet icon={Activity} text="OTel + Prometheus" />
        </ul>
      </section>

      {/* ──────────── Three axes ──────────── */}
      <section className="max-w-6xl mx-auto px-4 py-12 border-t border-border">
        <h2 className="text-2xl font-semibold tracking-tight">What it does</h2>
        <p className="text-sm text-muted-foreground mt-2 max-w-2xl">
          Every transcript flows through the same five-axis universal pipeline. The bundle
          you drop in determines what the model looks for; the target bundle determines
          what comes out.
        </p>
        <div className="grid gap-4 md:grid-cols-3 mt-8">
          <AxisCard
            icon={Globe}
            title="Source profile"
            sub="YAML bundle"
            body="Polish ŚWIADECTWO SZKOLNE shipped. Scaffolds for Vietnamese, Spanish, German, French, English — adding one is YAML, no Python."
            tag="profiles/"
          />
          <AxisCard
            icon={Workflow}
            title="Universal core"
            sub="language-neutral IR"
            body="Canonical transcript model with normalized grades, ISCED subject IDs, year math, conduct, achievements. Round-trips losslessly with raw_source_value."
            tag="packages/core"
          />
          <AxisCard
            icon={FileSpreadsheet}
            title="Target system"
            sub="YAML bundle + template"
            body="US-HS Grade 9 xlsx shipped. Per-tenant template overrides land in v0.2.0; DOCX + PDF renderers in v0.9.0."
            tag="targets/"
          />
        </div>
      </section>

      {/* ──────────── Feature gallery ──────────── */}
      <section className="max-w-6xl mx-auto px-4 py-12 border-t border-border">
        <h2 className="text-2xl font-semibold tracking-tight">Shipped features</h2>
        <p className="text-sm text-muted-foreground mt-2 max-w-2xl">
          Every screenshot below is from the running stack on this same deployment.
          Sign in with any API key to see them populated with your tenant's data.
        </p>

        <div className="grid gap-6 mt-8">
          <Feature
            number="01"
            icon={Activity}
            title="Dashboard — live tenant KPIs"
            body="Transcripts processed, spend in USD, token in/out, manual-review queue depth. Recent jobs list links straight to job detail with download/approve/reject actions."
            shot="/demo-assets/dashboard-light.png"
            shotDark="/demo-assets/dashboard-dark.png"
          />
          <Feature
            number="02"
            icon={Zap}
            title="Process — drag-and-drop upload"
            body="One screen, multipart up to 25 MiB. Multi-page PDFs are rendered in parallel (150 DPI, thread_count=2). Pipeline + target are explicit; idempotency key supported."
            shot="/demo-assets/upload.png"
          />
          <Feature
            number="03"
            icon={CheckCircle2}
            title="Jobs + manual review"
            body="Every job has status, model used, confidence, USD cost, tokens. Low-confidence extractions park in the manual-review queue; reviewers approve or reject and the result renders."
            shot="/demo-assets/jobs.png"
            secondaryShot="/demo-assets/job-detail.png"
          />
          <Feature
            number="04"
            icon={ShieldCheck}
            title="Compliance — GDPR DSRs + hash-chained audit"
            body="Type-to-confirm DSR endpoints: access (export), portability (machine-readable JSON), erasure (crypto-shred). Audit log is hash-chained per tenant; tampering breaks the chain."
            shot="/demo-assets/compliance.png"
          />
          <Feature
            number="05"
            icon={Layers}
            title="Templates catalog"
            body="Lists every target bundle and the template keys inside it. v0.2.0 lets tenants upload their own; v0.9.0 adds a visual mapping editor for non-xlsx outputs."
            shot="/demo-assets/templates.png"
          />
          <Feature
            number="06"
            icon={Workflow}
            title="Webhooks with HMAC delivery"
            body="Per-tenant webhook subscriptions, signing secret generated server-side, never persisted in plaintext. Failed deliveries retry with exponential backoff."
            shot="/demo-assets/webhooks.png"
          />
          <Feature
            number="07"
            icon={KeyRound}
            title="Admin — system overview"
            body="Plane-wide counts (tenants active/total, API keys, queue depth), build version, registered profile + target + SLA bundles. Gated on the admin:* scope."
            shot="/demo-assets/admin-system.png"
            badge="Admin"
          />
          <Feature
            number="08"
            icon={Building2}
            title="Admin — tenants CRUD"
            body="Issue tenants, set SLA tier, archive without deletion. Per-tenant API-key lifecycle (issue, label, expire, revoke). Paged audit per tenant."
            shot="/demo-assets/admin-tenants.png"
            secondaryShot="/demo-assets/admin-tenant-detail.png"
            badge="Admin"
          />
          <Feature
            number="09"
            icon={Eye}
            title="Tenant impersonation"
            body="An admin can switch the active tenant context from the topbar dropdown. Every endpoint scopes to the target tenant; every request appends a tenant.impersonated_access audit row on the target so the data owner sees who looked."
            body2="X-Acting-Tenant-Id header on every request; React Query invalidates so live pages refetch under the new context."
            badge="Admin"
          />
        </div>
      </section>

      {/* ──────────── Trust & ops ──────────── */}
      <section className="max-w-6xl mx-auto px-4 py-12 border-t border-border">
        <h2 className="text-2xl font-semibold tracking-tight">Built for production</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mt-8">
          <TrustCard
            title="Multi-tenant isolation"
            body="Three layers: app filter, ORM SET LOCAL, Postgres RLS. A SQL-injection bug cannot cross tenants."
          />
          <TrustCard
            title="Envelope encryption"
            body="Per-tenant DEK encrypted by an env / KMS-ready KEK. PII columns AES-GCM at rest. Tenant deletion = crypto-shred."
          />
          <TrustCard
            title="Tiered vision"
            body="Haiku-first with Sonnet fallback on confidence gate. Prompt caching keyed by schema. Batch lane ~50% cheaper for non-urgent loads."
          />
          <TrustCard
            title="Observability"
            body="Prometheus /metrics with golden + pipeline + business signals. OTLP traces with gen_ai.* attributes. SLO alerts as code."
          />
        </div>
      </section>

      {/* ──────────── What's next ──────────── */}
      <section className="max-w-6xl mx-auto px-4 py-12 border-t border-border">
        <h2 className="text-2xl font-semibold tracking-tight">What's next</h2>
        <p className="text-sm text-muted-foreground mt-2 max-w-2xl">
          The current trajectory turns this from a working MVP into a chargeable SaaS.
          Full per-version detail is in <code className="text-xs px-1 py-0.5 rounded bg-muted">docs/ROADMAP.md</code>.
        </p>
        <ol className="mt-6 space-y-3">
          <NextItem ver="v0.2.0" desc="Per-tenant overrides — workflow, template, SLA, vocabulary" status="next" />
          <NextItem ver="v0.3.0" desc="Provider choice + BYOK (Bring Your Own Key)" />
          <NextItem ver="v0.4.0" desc="Subscriptions, plans, quotas, Stripe metering" />
          <NextItem ver="v0.5.0" desc="Localization — UI + API + email in six locales" />
          <NextItem ver="v0.6.0" desc="More profiles + targets (vi, es, de, fr; us-college, uk-ucas, ib-dp)" />
          <NextItem ver="v0.7.0" desc="Full OpenAI / Google / Tesseract adapters" />
          <NextItem ver="v0.8.0" desc="KMS, WORM audit, SIEM, OIDC/SAML, SOC 2 readiness" />
          <NextItem ver="v0.9.0" desc="DOCX + PDF renderers + visual mapping editor" />
          <NextItem ver="v1.0.0" desc="GA — Helm, multi-region, plugin loader, SOC 2 Type 1" status="ga" />
        </ol>
      </section>

      {/* ──────────── Footer CTA ──────────── */}
      <section className="max-w-6xl mx-auto px-4 py-16 border-t border-border">
        <div className="rounded-2xl border border-border bg-card p-8 md:p-10 flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div>
            <h3 className="text-xl md:text-2xl font-semibold tracking-tight">
              Have a key? Sign in and try it on a real transcript.
            </h3>
            <p className="text-sm text-muted-foreground mt-2 max-w-xl">
              The whole upload → extract → render → download loop typically completes in
              under 30 seconds on a clean page; under two minutes for noisy multi-page PDFs.
            </p>
          </div>
          <Link
            to="/login"
            className="inline-flex items-center gap-2 h-11 px-6 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:opacity-90 self-start md:self-center"
          >
            Open console <ArrowRight size={16} />
          </Link>
        </div>
        <p className="text-center text-[11px] text-muted-foreground mt-6 flex items-center justify-center gap-3 flex-wrap">
          <span>OCR-to-Report · MIT licensed · Demo build</span>
          <span aria-hidden>·</span>
          <a
            href="https://ko-fi.com/quoctrantrung"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            ☕ Buy me a coffee
          </a>
          <span aria-hidden>·</span>
          <a
            href="https://github.com/mmct-jsc/ocr-to-report"
            target="_blank"
            rel="noreferrer"
            className="hover:text-foreground"
          >
            Source on GitHub
          </a>
        </p>
      </section>
    </div>
  );
}

/* ────────── small atoms ────────── */

function Bullet({ icon: Icon, text }: { icon: typeof ShieldCheck; text: string }) {
  return (
    <li className="inline-flex items-center gap-1.5">
      <Icon size={14} className="text-primary" /> {text}
    </li>
  );
}

function AxisCard({
  icon: Icon,
  title,
  sub,
  body,
  tag,
}: {
  icon: typeof Globe;
  title: string;
  sub: string;
  body: string;
  tag: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-center gap-2">
        <div className="h-9 w-9 rounded-md bg-primary/10 text-primary grid place-items-center">
          <Icon size={18} />
        </div>
        <div>
          <p className="font-medium tracking-tight">{title}</p>
          <p className="text-[11px] text-muted-foreground uppercase tracking-wider">{sub}</p>
        </div>
      </div>
      <p className="text-sm text-muted-foreground mt-3 leading-relaxed">{body}</p>
      <p className="mt-3 text-[11px] font-mono text-muted-foreground">{tag}</p>
    </div>
  );
}

function Feature({
  number,
  icon: Icon,
  title,
  body,
  body2,
  shot,
  shotDark,
  secondaryShot,
  badge,
}: {
  number: string;
  icon: typeof Activity;
  title: string;
  body: string;
  body2?: string;
  shot?: string;
  shotDark?: string;
  secondaryShot?: string;
  badge?: string;
}) {
  const { theme } = useTheme();
  const primary = theme === "dark" && shotDark ? shotDark : shot;
  return (
    <article className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="grid lg:grid-cols-[1fr,1.4fr] gap-0">
        <div className="p-6 md:p-8 flex flex-col">
          <div className="flex items-center gap-3 text-muted-foreground">
            <span className="text-xs font-mono">{number}</span>
            <Icon size={16} className="text-primary" />
            {badge && (
              <span className="text-[10px] uppercase tracking-wider rounded-full px-2 py-0.5 border border-warning/40 text-warning">
                {badge}
              </span>
            )}
          </div>
          <h3 className="text-lg md:text-xl font-semibold tracking-tight mt-3">{title}</h3>
          <p className="text-sm text-muted-foreground mt-3 leading-relaxed">{body}</p>
          {body2 && (
            <p className="text-sm text-muted-foreground mt-2 leading-relaxed">{body2}</p>
          )}
        </div>
        {primary && (
          <div className="bg-muted/30 p-4 md:p-6 lg:border-l border-border min-h-[200px] flex items-center justify-center">
            <div className="space-y-3">
              <img
                src={withBase(primary)}
                alt={title}
                className="w-full rounded-lg border border-border shadow-sm"
                loading="lazy"
              />
              {secondaryShot && (
                <img
                  src={withBase(secondaryShot)}
                  alt={`${title} (detail)`}
                  className="w-full rounded-lg border border-border shadow-sm"
                  loading="lazy"
                />
              )}
            </div>
          </div>
        )}
      </div>
    </article>
  );
}

function TrustCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-border p-5">
      <p className="font-medium tracking-tight">{title}</p>
      <p className="text-sm text-muted-foreground mt-2 leading-relaxed">{body}</p>
    </div>
  );
}

function NextItem({
  ver,
  desc,
  status,
}: {
  ver: string;
  desc: string;
  status?: "next" | "ga";
}) {
  return (
    <li className="flex items-start gap-3">
      <span
        className={cn(
          "shrink-0 inline-flex items-center justify-center text-[10px] font-mono font-semibold rounded-md px-2 h-6",
          status === "next"
            ? "bg-primary/10 text-primary border border-primary/20"
            : status === "ga"
              ? "bg-success/10 text-success border border-success/20"
              : "bg-muted text-muted-foreground border border-border",
        )}
      >
        {ver}
      </span>
      <p className="text-sm leading-6">
        {desc}
        {status === "next" && (
          <span className="ml-2 text-[10px] uppercase tracking-wider text-primary">
            next up
          </span>
        )}
        {status === "ga" && (
          <span className="ml-2 text-[10px] uppercase tracking-wider text-success">
            GA target
          </span>
        )}
      </p>
    </li>
  );
}
