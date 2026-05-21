/**
 * Settings → SLA tab.
 *
 * Per-field overrides on top of the tenant's SLA tier preset. Each row
 * pairs a "Override" toggle with a value input; when the toggle is on,
 * a single ``set`` patch is included in the saved ``sla_patches`` array.
 * When the toggle is off, that field falls back to the tier baseline.
 *
 * The fields covered in v0.2.0 Task 9:
 *
 * * ``confidence_threshold`` — number (0.0–1.0).
 * * ``park_low_confidence`` — boolean.
 * * ``retention_days`` — integer (1–3650).
 * * ``provider_policy`` — enum.
 *
 * The page reads the resolved view + the raw ``sla_patches`` list from
 * ``GET /v1/tenant/config``, surfaces the baseline alongside each
 * override toggle for context, and writes back the full replacement
 * patch list via ``PUT``. The server's strict Pydantic re-validation
 * catches out-of-range values (e.g., threshold > 1.0) and surfaces them
 * as a toast.
 */

import { useEffect, useMemo, useState } from "react";
import { Save } from "lucide-react";
import type { OverridePatch } from "@ocr-to-report/sdk";
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
import { FormField, type FormFieldAriaProps } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";

type ProviderPolicy = "single" | "fallback" | "ensemble";
const PROVIDER_POLICIES: ProviderPolicy[] = ["single", "fallback", "ensemble"];

interface OverrideFieldState {
  enabled: boolean;
  value: unknown;
}

interface SlaFormState {
  confidence_threshold: OverrideFieldState;
  park_low_confidence: OverrideFieldState;
  retention_days: OverrideFieldState;
  provider_policy: OverrideFieldState;
}

const OVERRIDABLE_FIELDS = [
  "confidence_threshold",
  "park_low_confidence",
  "retention_days",
  "provider_policy",
] as const;
type OverridableField = (typeof OVERRIDABLE_FIELDS)[number];

function emptyState(): SlaFormState {
  return {
    confidence_threshold: { enabled: false, value: 0 },
    park_low_confidence: { enabled: false, value: false },
    retention_days: { enabled: false, value: 30 },
    provider_policy: { enabled: false, value: "single" },
  };
}

function patchesToState(
  resolved: Record<string, unknown>,
  patches: OverridePatch[],
): SlaFormState {
  // Start from the resolved (baseline+patches) view so the inputs show
  // the current effective values; flip ``enabled=true`` only on fields
  // that actually have a patch.
  const state = emptyState();
  for (const field of OVERRIDABLE_FIELDS) {
    const resolvedValue = resolved[field];
    if (resolvedValue !== undefined) {
      state[field].value = resolvedValue;
    }
  }
  for (const p of patches) {
    if (p.op !== "set") continue;
    if (!OVERRIDABLE_FIELDS.includes(p.path as OverridableField)) continue;
    const field = p.path as OverridableField;
    state[field].enabled = true;
    state[field].value = p.value;
  }
  return state;
}

function stateToPatches(state: SlaFormState): OverridePatch[] {
  const out: OverridePatch[] = [];
  for (const field of OVERRIDABLE_FIELDS) {
    if (state[field].enabled) {
      out.push({ op: "set", path: field, value: state[field].value });
    }
  }
  return out;
}

/**
 * Stable string representation of a patch list, ignoring key insertion
 * order in each patch object. ``JSON.stringify`` is order-sensitive —
 * if the server returns ``{path, op, value}`` and the client emits
 * ``{op, path, value}``, naive stringify reports them as different
 * even though they're semantically identical, which would falsely
 * mark the form as dirty on page load.
 *
 * Sorting the patch list itself would lose meaning (patches apply in
 * order); we only sort keys WITHIN each patch object.
 */
function canonicalize(patches: OverridePatch[]): string {
  return JSON.stringify(
    patches.map((p) => {
      const entries = Object.entries(p).sort(([a], [b]) => a.localeCompare(b));
      return Object.fromEntries(entries);
    }),
  );
}

export function SlaTab() {
  const { client } = useAuth();
  const toast = useToast();

  const [tier, setTier] = useState<string>("standard");
  const [baseline, setBaseline] = useState<Record<string, unknown> | null>(null);
  const [savedPatches, setSavedPatches] = useState<OverridePatch[]>([]);
  const [state, setState] = useState<SlaFormState>(emptyState);
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
    client.tenantConfig
      .get()
      .then((cfg) => {
        if (cancelled) return;
        const tierValue = typeof cfg.sla.tier === "string" ? cfg.sla.tier : "standard";
        setTier(tierValue);
        setBaseline(cfg.sla);
        setSavedPatches(cfg.sla_patches);
        setState(patchesToState(cfg.sla, cfg.sla_patches));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(e instanceof Error ? e.message : "Failed to load SLA config");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const proposedPatches = useMemo(() => stateToPatches(state), [state]);
  // Key-order canonical stringify — the server may serialize patch
  // objects with different key insertion order than ``stateToPatches``
  // emits, which would otherwise produce a spurious ``dirty=true`` on
  // load (and an always-enabled Save button before the user touched
  // anything). Sorting keys before stringify gives us semantic
  // equality without pulling in a deep-equal dep.
  const dirty = useMemo(
    () => canonicalize(proposedPatches) !== canonicalize(savedPatches),
    [proposedPatches, savedPatches],
  );

  function update<F extends OverridableField>(
    field: F,
    next: Partial<OverrideFieldState>,
  ): void {
    setState((prev) => ({ ...prev, [field]: { ...prev[field], ...next } }));
  }

  async function save() {
    if (!client || !dirty) return;
    setSaving(true);
    try {
      const cfg = await client.tenantConfig.replace({ sla_patches: proposedPatches });
      setSavedPatches(cfg.sla_patches);
      setBaseline(cfg.sla);
      toast.success(
        "SLA overrides saved",
        proposedPatches.length === 0
          ? "All overrides cleared; reverting to tier baseline."
          : `${proposedPatches.length} field${proposedPatches.length === 1 ? "" : "s"} overridden.`,
      );
    } catch (e: unknown) {
      toast.error(
        "Could not save",
        e instanceof Error ? e.message : "Server rejected the patch — check field bounds.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (!client) {
    return (
      <p className="text-sm text-muted-foreground">
        Sign in to manage this tenant's SLA overrides.
      </p>
    );
  }
  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading SLA config…</p>;
  }
  if (loadError !== null) {
    return (
      <p className="text-sm text-danger-foreground bg-danger/10 rounded-md px-3 py-2">
        {loadError}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Base SLA tier</CardTitle>
          <CardDescription>
            Set by the admin via <code className="font-mono">PATCH /v1/admin/tenants/…</code>.
            Per-field overrides below stack on top of this preset.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm">
            Current tier:{" "}
            <span className="font-mono uppercase tracking-wide">{tier}</span>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Per-field overrides</CardTitle>
          <CardDescription>
            Toggle a field on to pin its value above the tier baseline. The
            shown baseline reflects the tier preset before your overrides.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <OverrideRow
            label="Confidence threshold"
            description="Minimum vision confidence to auto-render; below this the job parks."
            baseline={baseline?.confidence_threshold}
            enabled={state.confidence_threshold.enabled}
            onToggle={(enabled) => update("confidence_threshold", { enabled })}
            controlId="sla-conf-threshold"
            renderControl={(controlProps) => (
              <Input
                {...controlProps}
                type="number"
                step={0.01}
                min={0}
                max={1}
                value={String(state.confidence_threshold.value)}
                disabled={!state.confidence_threshold.enabled}
                onChange={(e) =>
                  update("confidence_threshold", { value: Number(e.target.value) })
                }
              />
            )}
          />

          <OverrideRow
            label="Park low-confidence jobs"
            description="When off, low-confidence extractions still render (best-effort)."
            baseline={baseline?.park_low_confidence}
            enabled={state.park_low_confidence.enabled}
            onToggle={(enabled) => update("park_low_confidence", { enabled })}
            controlId="sla-park"
            renderControl={(controlProps) => (
              <select
                {...controlProps}
                value={String(state.park_low_confidence.value)}
                disabled={!state.park_low_confidence.enabled}
                onChange={(e) =>
                  update("park_low_confidence", { value: e.target.value === "true" })
                }
                className="border border-border rounded-md px-2 py-1 text-sm bg-background disabled:opacity-50"
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            )}
          />

          <OverrideRow
            label="Retention (days)"
            description="How long completed job blobs stay in storage before the sweep deletes them."
            baseline={baseline?.retention_days}
            enabled={state.retention_days.enabled}
            onToggle={(enabled) => update("retention_days", { enabled })}
            controlId="sla-retention"
            renderControl={(controlProps) => (
              <Input
                {...controlProps}
                type="number"
                min={1}
                max={3650}
                value={String(state.retention_days.value)}
                disabled={!state.retention_days.enabled}
                onChange={(e) =>
                  update("retention_days", { value: Number(e.target.value) })
                }
              />
            )}
          />

          <OverrideRow
            label="Provider policy"
            description="single = one provider; fallback = retry on a stronger model; ensemble = consensus."
            baseline={baseline?.provider_policy}
            enabled={state.provider_policy.enabled}
            onToggle={(enabled) => update("provider_policy", { enabled })}
            controlId="sla-policy"
            renderControl={(controlProps) => (
              <select
                {...controlProps}
                value={String(state.provider_policy.value)}
                disabled={!state.provider_policy.enabled}
                onChange={(e) => update("provider_policy", { value: e.target.value })}
                className="border border-border rounded-md px-2 py-1 text-sm bg-background disabled:opacity-50"
              >
                {PROVIDER_POLICIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            )}
          />
        </CardContent>
        <CardFooter>
          <Button onClick={save} disabled={!dirty || saving}>
            <Save size={14} aria-hidden /> {saving ? "Saving…" : "Save"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

// ─── Internal row primitive ──────────────────────────────────────────

function OverrideRow({
  label,
  description,
  baseline,
  enabled,
  onToggle,
  controlId,
  renderControl,
}: {
  label: string;
  description: string;
  baseline: unknown;
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  controlId: string;
  renderControl: (controlProps: FormFieldAriaProps) => React.ReactNode;
}) {
  const baselineDisplay =
    baseline === undefined
      ? "—"
      : typeof baseline === "boolean"
        ? String(baseline)
        : typeof baseline === "number"
          ? String(baseline)
          : String(baseline);

  return (
    <div className="grid gap-2 md:grid-cols-[1fr_auto] items-start">
      <div>
        <FormField label={label} htmlFor={controlId} helper={description}>
          {(aria) => renderControl(aria)}
        </FormField>
        <p className="text-xs text-muted-foreground mt-1">
          Tier baseline: <span className="font-mono">{baselineDisplay}</span>
        </p>
      </div>
      {/*
        Visible "Override" text doubles as the checkbox's accessible
        label by virtue of the wrapping ``<label>`` — no separate
        ``aria-label`` is needed (and adding one would have screen
        readers announce "Override Confidence threshold Override",
        repeating the same word). The ``id={toggleId}`` + ``htmlFor``
        association lets ``<label>`` claim the click target while the
        visible text drives the AT name. The field-name context comes
        from the row's overall structure ‒ the FormField above already
        provides the field label.
      */}
      <label
        htmlFor={`${controlId}-toggle`}
        className="inline-flex items-center gap-2 self-end pb-2 cursor-pointer"
      >
        <input
          id={`${controlId}-toggle`}
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
        />
        <span className="text-xs text-muted-foreground">Override</span>
      </label>
    </div>
  );
}
