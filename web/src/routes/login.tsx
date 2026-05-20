import { useState } from "react";
import { useNavigate, useLocation, type Location } from "react-router-dom";
import { Eye, EyeOff, KeyRound, Server } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";

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

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!apiKey.trim()) {
      toast.warn("Missing API key", "Paste a key issued by `ocr-to-report bootstrap`.");
      return;
    }
    setSubmitting(true);
    try {
      // Validate by hitting /v1/usage; if it 401s the key is bad.
      const probe = await fetch(`${url.replace(/\/+$/, "")}/v1/usage`, {
        headers: { Authorization: `Bearer ${apiKey.trim()}` },
      });
      if (probe.status === 401) {
        toast.error("Authentication failed", "The API key was rejected by the server.");
        return;
      }
      if (!probe.ok) {
        toast.error("API not reachable", `The probe returned ${probe.status}.`);
        return;
      }
      signIn(apiKey.trim(), url.trim() || "/api");
      const next = location.state?.from?.pathname ?? "/dashboard";
      navigate(next, { replace: true });
    } catch (error) {
      toast.error("Network error", error instanceof Error ? error.message : "unknown");
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

            <form onSubmit={handleSubmit} className="mt-6 space-y-5">
              <div className="space-y-1.5">
                <Label htmlFor="base-url">API base URL</Label>
                <div className="relative">
                  <Server
                    size={14}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
                  />
                  <Input
                    id="base-url"
                    name="base-url"
                    placeholder="/api"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    autoComplete="url"
                    className="pl-9"
                  />
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Leave as <code className="font-mono">/api</code> when running behind the
                  Vite proxy; switch to a fully qualified URL in production.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="api-key">API key</Label>
                <div className="relative">
                  <KeyRound
                    size={14}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
                  />
                  <Input
                    id="api-key"
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
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-muted-foreground hover:text-foreground"
                    aria-label={show ? "hide key" : "show key"}
                  >
                    {show ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>

              <Button type="submit" className="w-full" loading={submitting} size="lg">
                {submitting ? "Verifying…" : "Continue"}
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
