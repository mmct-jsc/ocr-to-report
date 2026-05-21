import { useState } from "react";
import { useNavigate, useLocation, type Location } from "react-router-dom";
import { Eye, EyeOff, KeyRound, Server } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";

interface LocationState {
  from?: { pathname?: string };
}

export function LoginRoute() {
  const navigate = useNavigate();
  const location = useLocation() as Location & { state?: LocationState };
  const { signIn, baseUrl } = useAuth();
  const toast = useToast();

  const [apiKey, setApiKey] = useState("");
  const [url, setUrl] = useState(baseUrl);
  const [show, setShow] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // Inline, field-scoped errors. Cleared on next submit attempt so the
  // user sees fresh feedback rather than stale red. Cross-cutting
  // problems (DNS, offline) still fall through to a toast.
  const [keyError, setKeyError] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setKeyError(null);
    setUrlError(null);

    if (!apiKey.trim()) {
      setKeyError("Paste a key issued by `ocr-to-report bootstrap`.");
      return;
    }
    setSubmitting(true);
    try {
      // Validate by hitting /v1/usage; if it 401s the key is bad,
      // anything else (5xx, 404) suggests the URL is wrong.
      const probe = await fetch(`${url.replace(/\/+$/, "")}/v1/usage`, {
        headers: { Authorization: `Bearer ${apiKey.trim()}` },
      });
      if (probe.status === 401) {
        setKeyError(
          "The API rejected this key. Check the value, or run `ocr-to-report bootstrap` to issue a new one.",
        );
        return;
      }
      if (!probe.ok) {
        setUrlError(
          `Server error ${probe.status}. The API answered but couldn't validate the key — verify the base URL is correct.`,
        );
        return;
      }
      signIn(apiKey.trim(), url.trim() || "/api");
      const next = location.state?.from?.pathname ?? "/dashboard";
      navigate(next, { replace: true });
    } catch (error) {
      // True network-level failure (DNS, offline, CORS preflight
      // killed before the response). Stays as a toast because it isn't
      // specifically about either field.
      toast.error(
        "Couldn't reach the API",
        error instanceof Error
          ? `${error.message}. Check your network and the base URL.`
          : "Check your network and the base URL.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-background">
      <section className="hidden lg:flex flex-col justify-between p-12 bg-gradient-to-br from-primary to-accent text-primary-foreground">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-white/15 grid place-items-center font-bold">
            OR
          </div>
          <p className="font-semibold tracking-tight">OCR-to-Report</p>
        </div>
        <div className="space-y-5 max-w-md">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight">
            Schema-driven transcript intelligence.
          </h1>
          <p className="text-primary-foreground/80 leading-relaxed">
            Convert transcripts in any source language into target-system reports — Polish
            ŚWIADECTWO into US-HS Grade-9 Excel today, anything else tomorrow without code
            changes. Multi-tenant, encrypted at rest, compliance-aligned.
          </p>
          <ul className="space-y-2 text-sm text-primary-foreground/80">
            <li>· FERPA + GDPR ready (DSR access / portability / erasure)</li>
            <li>· Tiered Claude vision with batch lane (~50% cheaper)</li>
            <li>· Manual-review queue with approve / reject workflow</li>
          </ul>
        </div>
        <p className="text-xs text-primary-foreground/60">
          v0.1.0 · Need a key? Run{" "}
          <code className="font-mono bg-white/10 px-1.5 py-0.5 rounded">
            ocr-to-report bootstrap
          </code>{" "}
          on the host. ·{" "}
          <a
            href="/demo"
            className="underline decoration-primary-foreground/30 hover:decoration-primary-foreground"
          >
            See the feature tour
          </a>
        </p>
      </section>

      <section className="flex items-center justify-center p-6 lg:p-12">
        <Card className="w-full max-w-md shadow-md">
          <CardContent className="p-8">
            <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Authenticate with the bearer token issued for your tenant.
            </p>

            <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-5">
              <FormField
                label="API base URL"
                htmlFor="base-url"
                error={urlError}
                helper={
                  <>
                    Leave as <code className="font-mono">/api</code> when running behind the
                    Vite proxy; switch to a fully qualified URL in production.
                  </>
                }
              >
                {(aria) => (
                  <div className="relative">
                    <Server
                      size={14}
                      aria-hidden
                      className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
                    />
                    <Input
                      {...aria}
                      name="base-url"
                      placeholder="/api"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      autoComplete="url"
                      className="pl-9"
                    />
                  </div>
                )}
              </FormField>

              <FormField label="API key" htmlFor="api-key" error={keyError}>
                {(aria) => (
                  <div className="relative">
                    <KeyRound
                      size={14}
                      aria-hidden
                      className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
                    />
                    <Input
                      {...aria}
                      name="api-key"
                      type={show ? "text" : "password"}
                      placeholder="sk_test_…"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      autoComplete="off"
                      className="pl-9 pr-10 font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => setShow((s) => !s)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-2.5 text-muted-foreground hover:text-foreground"
                      aria-label={show ? "Hide API key" : "Show API key"}
                    >
                      {show ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
                    </button>
                  </div>
                )}
              </FormField>

              <Button type="submit" className="w-full" loading={submitting} size="lg">
                {submitting ? "Signing in…" : "Sign in"}
              </Button>
            </form>

            <p className="text-[11px] text-muted-foreground mt-6 text-center">
              Your token is stored in this browser's <code>localStorage</code>.
            </p>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
