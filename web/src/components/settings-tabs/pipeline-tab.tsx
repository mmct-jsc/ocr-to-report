/**
 * Settings → Pipeline tab.
 *
 * Lets a tenant pick which pipeline the API runs against their jobs.
 * The choice is a direct write to ``tenant.pipeline_id`` via
 * ``PUT /v1/tenant/config { pipeline_id: ... }``. The "Save" CTA is
 * disabled until a real change has been picked, so we don't issue
 * no-op writes.
 *
 * The available pipelines are baked in (no listing endpoint yet). When
 * Task 12's integration test grows out, expose them via an endpoint
 * and replace the constant.
 */

import { type ReactNode, useEffect, useMemo, useState } from "react";
import { CheckCircle, Save } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface PipelineOption {
  id: string;
  label: string;
  summary: string;
  /** Short bulleted description of what makes this pipeline different. */
  highlights: ReactNode;
}

const PIPELINES: PipelineOption[] = [
  {
    id: "default_v1",
    label: "Default",
    summary:
      "Single high-confidence vision pass; auto-render when above threshold; "
      + "park low-confidence jobs for manual review (when SLA allows).",
    highlights: (
      <ul className="list-disc pl-5 space-y-1">
        <li>One Anthropic vision call per upload</li>
        <li>Fallback to a stronger model when first-pass confidence is below SLA</li>
        <li>Renders the result xlsx directly on success</li>
      </ul>
    ),
  },
  {
    id: "with_manual_review_v1",
    label: "Manual review required",
    summary:
      "Park every job for human review before rendering, regardless of "
      + "confidence. Use for HIPAA/PII surfaces where automated approval "
      + "is policy-blocked.",
    highlights: (
      <ul className="list-disc pl-5 space-y-1">
        <li>No auto-render — every job lands in the review queue</li>
        <li>Reviewer can approve (re-extract + render) or reject</li>
        <li>Audit log entry per decision</li>
      </ul>
    ),
  },
  {
    id: "batch_economy_v1",
    label: "Batch economy",
    summary:
      "Use the Anthropic Batch API for ~50% cost savings. Results land via "
      + "webhook + polling; not appropriate for sync /v1/transcripts callers.",
    highlights: (
      <ul className="list-disc pl-5 space-y-1">
        <li>Bundles uploads into nightly batches</li>
        <li>~50% lower per-token cost</li>
        <li>Best paired with the Economy SLA tier</li>
      </ul>
    ),
  },
];

function findPipeline(id: string): PipelineOption | undefined {
  return PIPELINES.find((p) => p.id === id);
}

export function PipelineTab() {
  const { client } = useAuth();
  const toast = useToast();

  const [currentId, setCurrentId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!client) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    client.tenantConfig
      .get()
      .then((cfg) => {
        if (cancelled) return;
        setCurrentId(cfg.pipeline_id);
        setSelectedId(cfg.pipeline_id);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(e instanceof Error ? e.message : "Failed to load tenant config");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const dirty = useMemo(
    () => selectedId !== null && selectedId !== currentId,
    [selectedId, currentId],
  );

  async function save() {
    if (!client || selectedId === null || !dirty) return;
    setSaving(true);
    try {
      await client.tenantConfig.replace({ pipeline_id: selectedId });
      setCurrentId(selectedId);
      toast.success("Pipeline updated", `Tenant pipeline is now ${selectedId}.`);
    } catch (e: unknown) {
      toast.error(
        "Could not save",
        e instanceof Error ? e.message : "Unknown error updating pipeline.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (!client) {
    return (
      <p className="text-sm text-muted-foreground">
        Sign in to manage this tenant's pipeline.
      </p>
    );
  }
  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading tenant config…</p>;
  }
  if (loadError !== null) {
    return (
      <p className="text-sm text-danger-foreground bg-danger/10 rounded-md px-3 py-2">
        {loadError}
      </p>
    );
  }

  const active = selectedId !== null ? findPipeline(selectedId) : undefined;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Choose pipeline</CardTitle>
          <CardDescription>
            Switch which workflow the API runs against this tenant's jobs.
            The change applies to new jobs immediately; in-flight jobs keep
            their original pipeline.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <fieldset className="space-y-3">
            <legend className="sr-only">Pipeline</legend>
            {PIPELINES.map((p) => {
              const checked = selectedId === p.id;
              const isCurrent = currentId === p.id;
              return (
                <label
                  key={p.id}
                  htmlFor={`pipeline-${p.id}`}
                  className={[
                    "flex items-start gap-3 rounded-md border p-3 cursor-pointer",
                    "hover:bg-muted/50 focus-within:ring-2 focus-within:ring-ring",
                    checked ? "border-primary bg-primary/5" : "border-border",
                  ].join(" ")}
                >
                  <input
                    type="radio"
                    id={`pipeline-${p.id}`}
                    name="pipeline-choice"
                    value={p.id}
                    checked={checked}
                    onChange={() => setSelectedId(p.id)}
                    className="mt-1"
                  />
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{p.label}</span>
                      <code className="font-mono text-xs text-muted-foreground">
                        {p.id}
                      </code>
                      {isCurrent && (
                        <span className="inline-flex items-center gap-1 text-xs text-success-foreground">
                          <CheckCircle size={12} aria-hidden /> active
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">{p.summary}</p>
                  </div>
                </label>
              );
            })}
          </fieldset>
        </CardContent>
        <CardFooter>
          <Button onClick={save} disabled={!dirty || saving}>
            <Save size={14} aria-hidden /> {saving ? "Saving…" : "Save"}
          </Button>
        </CardFooter>
      </Card>

      {active && (
        <Card>
          <CardHeader>
            <CardTitle level={3} className="text-base">
              What "{active.label}" does
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm">{active.highlights}</CardContent>
        </Card>
      )}
    </div>
  );
}
