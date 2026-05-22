/**
 * Settings → Providers tab (v0.3.0 BYOK).
 *
 * Lists every legal provider id with a status row:
 *
 * * ``anthropic`` — interactive in v0.3.0. PUT a key → server validates
 *   it against ``/v1/models`` before persisting → on success the row
 *   shows the masked key + last-rotated timestamp.
 * * ``openai`` / ``google_vertex`` / ``tesseract`` — render disabled
 *   placeholder rows that read "Coming in v0.7.0". A direct PUT for
 *   these IDs would 501 server-side; we just don't surface the form.
 *
 * Interactions:
 *
 * * Save flow: click "Add" / "Replace" → inline secret-input form
 *   expands → typing → "Save". Calls ``client.providers.upsert``.
 *   On 200 → close form, toast success, refresh list.
 * * Revoke flow: click "Revoke" on an active row → AlertDialog
 *   confirmation → on confirm, ``client.providers.delete`` → toast +
 *   refresh.
 *
 * Security: the plaintext key is never echoed back. The list response
 * uses the placeholder ``sk-ant-…••••``. The PUT response carries the
 * actual last-4 redaction, which we surface as a one-time confirmation
 * toast ("we set the key ending XXXX") so the tenant can verify they
 * pasted what they meant to — but we don't persist that string
 * client-side either.
 */

import { useEffect, useState } from "react";
import { CheckCircle, KeyRound, Plus, RotateCw, Trash2 } from "lucide-react";
import type { ProviderId, ProviderStatus } from "@ocr-to-report/sdk";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { AlertDialog } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";

interface ProviderRowMeta {
  id: ProviderId;
  name: string;
  description: string;
  /** v0.7.0 = scaffolded but disabled in this version. */
  shipped: boolean;
}

const PROVIDERS: ProviderRowMeta[] = [
  {
    id: "anthropic",
    name: "Anthropic",
    description:
      "Routes your vision calls through your own Anthropic key. Usage is billed to your account, not the platform.",
    shipped: true,
  },
  {
    id: "openai",
    name: "OpenAI",
    description:
      "Scaffolded; full BYOK support ships in v0.7.0 (provider expansion).",
    shipped: false,
  },
  {
    id: "google_vertex",
    name: "Google Vertex AI",
    description:
      "Scaffolded; full BYOK support ships in v0.7.0 (provider expansion).",
    shipped: false,
  },
  {
    id: "tesseract",
    name: "Tesseract (on-prem)",
    description:
      "Scaffolded; full BYOK support ships in v0.7.0 (provider expansion).",
    shipped: false,
  },
];

export function ProvidersTab() {
  const { client } = useAuth();
  const toast = useToast();

  const [byProvider, setByProvider] = useState<Record<string, ProviderStatus>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProviderId | null>(null);
  const [pendingRevoke, setPendingRevoke] = useState<ProviderId | null>(null);
  const [revoking, setRevoking] = useState(false);

  async function refresh(): Promise<void> {
    if (!client) return;
    setLoadError(null);
    try {
      const list = await client.providers.list();
      // The server returns one row per provider that has EVER had a
      // credential. Keying by provider keeps the lookup O(1) and the
      // "rotation history" view shows the most recent row per provider.
      const map: Record<string, ProviderStatus> = {};
      for (const p of list.providers) {
        // If we already saw a row for this provider, prefer the active
        // one (or the most recent created_at when both are inactive).
        const prior = map[p.provider];
        if (
          prior === undefined ||
          (p.active && !prior.active) ||
          (p.created_at !== null &&
            prior.created_at !== null &&
            p.created_at > prior.created_at)
        ) {
          map[p.provider] = p;
        }
      }
      setByProvider(map);
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : "Failed to load credentials");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!client) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function save(provider: ProviderId, apiKey: string): Promise<void> {
    if (!client) return;
    try {
      const status = await client.providers.upsert(provider, { api_key: apiKey });
      toast.success(
        "Credential saved",
        status.api_key_redacted
          ? `Key ${status.api_key_redacted} is now active.`
          : "Active.",
      );
      setEditing(null);
      await refresh();
    } catch (e: unknown) {
      const message =
        e instanceof Error ? e.message : "The server rejected the key.";
      toast.error("Save failed", message);
    }
  }

  async function confirmRevoke(): Promise<void> {
    if (!client || pendingRevoke === null) return;
    setRevoking(true);
    try {
      await client.providers.delete(pendingRevoke);
      toast.success(
        "Credential revoked",
        "Future requests will route through the platform key.",
      );
      setPendingRevoke(null);
      await refresh();
    } catch (e: unknown) {
      const message =
        e instanceof Error ? e.message : "Could not revoke credential.";
      toast.error("Revoke failed", message);
    } finally {
      setRevoking(false);
    }
  }

  if (!client) {
    return (
      <p className="text-sm text-muted-foreground">
        Sign in to manage this tenant's BYOK credentials.
      </p>
    );
  }
  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading credentials…</p>;
  }
  if (loadError !== null) {
    return (
      <p className="text-sm text-danger-foreground bg-danger/10 rounded-md px-3 py-2">
        {loadError}
      </p>
    );
  }

  const pendingRevokeRow =
    pendingRevoke !== null ? byProvider[pendingRevoke] : undefined;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound size={16} aria-hidden /> Bring your own key
          </CardTitle>
          <CardDescription>
            Configure tenant-supplied provider API keys. Your vision
            requests route through these instead of the platform's
            default credentials; usage is billed to your account, and
            invoicing skips the corresponding rows. Keys are stored
            envelope-encrypted with your tenant DEK — the platform
            never logs them and they're not echoed back on GET.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {PROVIDERS.map((p) => {
            const row = byProvider[p.id];
            const isEditing = editing === p.id;
            return (
              <ProviderRow
                key={p.id}
                meta={p}
                status={row}
                editing={isEditing}
                onStartEdit={() => setEditing(p.id)}
                onCancelEdit={() => setEditing(null)}
                onSave={(apiKey) => save(p.id, apiKey)}
                onRequestRevoke={() => setPendingRevoke(p.id)}
              />
            );
          })}
        </CardContent>
      </Card>

      <AlertDialog
        open={pendingRevoke !== null}
        onClose={() => setPendingRevoke(null)}
        onConfirm={() => {
          void confirmRevoke();
        }}
        title={`Revoke ${labelFor(pendingRevoke) ?? "credential"}?`}
        description={
          <>
            The platform will fall back to its own key for this tenant
            until you set a new one. The current credential row stays
            in your audit history but is no longer routable.
            {pendingRevokeRow?.api_key_redacted ? (
              <>
                {" "}
                Affected key:{" "}
                <code className="font-mono">{pendingRevokeRow.api_key_redacted}</code>.
              </>
            ) : null}
          </>
        }
        confirmLabel={revoking ? "Revoking…" : "Revoke"}
        cancelLabel="Keep credential"
        tone="danger"
        pending={revoking}
      />
    </div>
  );
}

function labelFor(id: ProviderId | null): string | null {
  if (id === null) return null;
  return PROVIDERS.find((p) => p.id === id)?.name ?? null;
}

// ─── single row ──────────────────────────────────────────────────────


function ProviderRow({
  meta,
  status,
  editing,
  onStartEdit,
  onCancelEdit,
  onSave,
  onRequestRevoke,
}: {
  meta: ProviderRowMeta;
  status: ProviderStatus | undefined;
  editing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: (apiKey: string) => Promise<void>;
  onRequestRevoke: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    // Clear draft state whenever the editor opens or closes.
    setDraft("");
    setFormError(null);
    setSaving(false);
  }, [editing]);

  const active = status?.active === true;

  return (
    <div
      className={[
        "rounded-md border px-3 py-2.5 space-y-2",
        meta.shipped ? "border-border" : "border-border opacity-70",
      ].join(" ")}
    >
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold">{meta.name}</span>
            <code className="font-mono text-xs text-muted-foreground">{meta.id}</code>
            {!meta.shipped ? (
              <span className="text-xs rounded-full bg-muted px-2 py-0.5">
                Coming in v0.7.0
              </span>
            ) : active ? (
              <span className="inline-flex items-center gap-1 text-xs rounded-full bg-success/10 text-success-foreground px-2 py-0.5">
                <CheckCircle size={11} aria-hidden /> BYOK active
              </span>
            ) : status !== undefined ? (
              <span className="text-xs rounded-full bg-muted px-2 py-0.5">
                Platform (previously set)
              </span>
            ) : (
              <span className="text-xs rounded-full bg-muted px-2 py-0.5">Platform</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">{meta.description}</p>
          {active && status ? (
            <p className="text-xs text-muted-foreground mt-1">
              Key:{" "}
              <code className="font-mono">
                {status.api_key_redacted ?? "sk-…"}
              </code>
              {status.rotated_at ? (
                <>
                  {" "}
                  · Rotated{" "}
                  <time dateTime={status.rotated_at}>
                    {new Date(status.rotated_at).toLocaleString()}
                  </time>
                </>
              ) : null}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {meta.shipped ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={onStartEdit}
                disabled={editing}
                aria-label={
                  active
                    ? `Replace ${meta.name} credential`
                    : `Add ${meta.name} credential`
                }
              >
                {active ? (
                  <>
                    <RotateCw size={13} aria-hidden /> Replace
                  </>
                ) : (
                  <>
                    <Plus size={13} aria-hidden /> Add
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={onRequestRevoke}
                disabled={!active || editing}
                aria-label={`Revoke ${meta.name} credential`}
              >
                <Trash2 size={13} aria-hidden /> Revoke
              </Button>
            </>
          ) : (
            <Button variant="outline" size="sm" disabled>
              <Plus size={13} aria-hidden /> Add
            </Button>
          )}
        </div>
      </div>

      {editing && meta.shipped ? (
        <form
          className="border-t pt-3 space-y-2"
          onSubmit={async (e) => {
            e.preventDefault();
            const trimmed = draft.trim();
            if (trimmed.length < 8) {
              setFormError("Paste your full API key (min 8 characters).");
              return;
            }
            setFormError(null);
            setSaving(true);
            try {
              await onSave(trimmed);
            } finally {
              setSaving(false);
            }
          }}
        >
          <Label htmlFor={`provider-key-${meta.id}`}>
            {meta.name} API key
          </Label>
          <Input
            id={`provider-key-${meta.id}`}
            type="password"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={`provider-key-${meta.id}-hint`}
            placeholder="sk-ant-…"
          />
          <p
            id={`provider-key-${meta.id}-hint`}
            className="text-xs text-muted-foreground"
          >
            We validate the key against the provider's API before
            saving. We never log or echo it back.
          </p>
          {formError ? (
            <p className="text-xs text-danger-foreground" role="alert">
              {formError}
            </p>
          ) : null}
          <div className="flex items-center gap-2">
            <Button type="submit" variant="primary" size="sm" disabled={saving}>
              {saving ? "Validating…" : "Save"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onCancelEdit}
              disabled={saving}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
