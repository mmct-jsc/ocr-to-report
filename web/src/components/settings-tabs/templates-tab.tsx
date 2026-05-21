/**
 * Settings → Templates tab.
 *
 * Lists every (target_id, template_key) slot from
 * ``GET /v1/templates`` and overlays the tenant's per-slot override
 * status (read from ``tenant_config.target_overrides[targetId]``).
 *
 * Each row supports:
 *
 * * Inline file picker (``<input type="file" accept=".xlsx">``) — the
 *   browser's native dialog handles MIME, filename, size. Selecting a
 *   file triggers an immediate upload via ``client.templates.upload``.
 * * Drag-and-drop onto the row — same upload path; just a fancier UX.
 * * Revert button — only enabled when an override exists; calls
 *   ``client.templates.delete`` and refreshes the override list.
 *
 * The component re-loads ``tenant_config`` after every successful
 * upload/delete so the override badges and Revert buttons stay in sync.
 * Per-slot loading/error state lives in component state so multiple
 * slots can be operated on independently.
 */

import { type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle, Upload, Trash2 } from "lucide-react";
import type { OverridePatch, TargetInfo } from "@ocr-to-report/sdk";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface SlotState {
  loading: boolean;
}

function slotKey(targetId: string, templateKey: string): string {
  return `${targetId}::${templateKey}`;
}

/** Walk the resolved target_overrides looking for a ``set`` patch on
 * ``templates[<key>].blob_key``. Matches the server's storage shape. */
function hasOverride(
  overrides: Record<string, OverridePatch[]> | undefined,
  targetId: string,
  templateKey: string,
): boolean {
  const patches = overrides?.[targetId];
  if (!patches) return false;
  return patches.some(
    (p) => p.op === "set" && p.path === `templates[${templateKey}].blob_key`,
  );
}

export function TemplatesTab() {
  const { client } = useAuth();
  const toast = useToast();

  const [catalogue, setCatalogue] = useState<TargetInfo[]>([]);
  const [targetOverrides, setTargetOverrides] = useState<
    Record<string, OverridePatch[]>
  >({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [slotState, setSlotState] = useState<Record<string, SlotState>>({});

  async function refresh(): Promise<void> {
    if (!client) return;
    try {
      const [tpls, cfg] = await Promise.all([
        client.templates.list(),
        client.tenantConfig.get(),
      ]);
      // Stable display order: by target.target_id then template.key.
      const sortedTargets = [...tpls.targets].sort((a, b) =>
        a.target_id.localeCompare(b.target_id),
      );
      for (const t of sortedTargets) {
        t.templates.sort((a, b) => a.key.localeCompare(b.key));
      }
      setCatalogue(sortedTargets);
      setTargetOverrides(cfg.target_overrides);
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : "Failed to load template catalogue");
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
    setLoadError(null);
    void refresh();
    // refresh closes over client; eslint exhaustive-deps would want it
    // in the array, but client is stable for the page's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function upload(targetId: string, templateKey: string, file: File): Promise<void> {
    if (!client) return;
    const key = slotKey(targetId, templateKey);
    setSlotState((s) => ({ ...s, [key]: { loading: true } }));
    try {
      const resp = await client.templates.upload({
        targetId,
        templateKey,
        file,
        filename: file.name,
      });
      toast.success(
        "Template uploaded",
        `${resp.size_bytes.toLocaleString()} bytes · sha ${resp.sha256.slice(0, 8)}…`,
      );
      await refresh();
    } catch (e: unknown) {
      toast.error(
        "Upload failed",
        e instanceof Error ? e.message : "Server rejected the upload.",
      );
    } finally {
      setSlotState((s) => ({ ...s, [key]: { loading: false } }));
    }
  }

  async function revert(targetId: string, templateKey: string): Promise<void> {
    if (!client) return;
    const key = slotKey(targetId, templateKey);
    setSlotState((s) => ({ ...s, [key]: { loading: true } }));
    try {
      await client.templates.delete({ targetId, templateKey });
      toast.success("Reverted to shipped template");
      await refresh();
    } catch (e: unknown) {
      toast.error(
        "Revert failed",
        e instanceof Error ? e.message : "Could not remove override.",
      );
    } finally {
      setSlotState((s) => ({ ...s, [key]: { loading: false } }));
    }
  }

  if (!client) {
    return (
      <p className="text-sm text-muted-foreground">
        Sign in to manage this tenant's templates.
      </p>
    );
  }
  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading template catalogue…</p>;
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
          <CardTitle>Per-tenant template uploads</CardTitle>
          <CardDescription>
            Replace the shipped xlsx template with your own for any
            <code className="font-mono mx-1">(target_id, template_key)</code>
            slot. Cell bindings stay the same — your file changes the
            carrier (sheet layout, headers, frozen panes, styling). Only
            xlsx is supported today; max 2&nbsp;MB.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {catalogue.map((target) => (
            <section key={target.target_id} className="space-y-2">
              <header className="flex items-baseline gap-2">
                <h3 className="text-sm font-semibold">{target.name}</h3>
                <code className="font-mono text-xs text-muted-foreground">
                  {target.target_id} · v{target.version}
                </code>
              </header>
              <ul className="space-y-2">
                {target.templates
                  .filter((t) => t.output_format === "xlsx")
                  .map((t) => {
                    const overridden = hasOverride(
                      targetOverrides,
                      target.target_id,
                      t.key,
                    );
                    const sk = slotKey(target.target_id, t.key);
                    const busy = slotState[sk]?.loading === true;
                    return (
                      <li key={t.key}>
                        <TemplateSlotRow
                          targetId={target.target_id}
                          templateKey={t.key}
                          overridden={overridden}
                          busy={busy}
                          onUpload={(f) => upload(target.target_id, t.key, f)}
                          onRevert={() => revert(target.target_id, t.key)}
                        />
                      </li>
                    );
                  })}
              </ul>
            </section>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ─── slot row ────────────────────────────────────────────────────────


function TemplateSlotRow({
  targetId,
  templateKey,
  overridden,
  busy,
  onUpload,
  onRevert,
}: {
  targetId: string;
  templateKey: string;
  overridden: boolean;
  busy: boolean;
  onUpload: (file: File) => void;
  onRevert: () => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputId = useMemo(() => `tpl-${targetId}-${templateKey}`, [targetId, templateKey]);

  function handleFiles(files: FileList | null): void {
    if (!files || files.length === 0) return;
    const file = files[0];
    if (!file) return;
    onUpload(file);
  }

  function handleDrop(e: DragEvent<HTMLDivElement>): void {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>): void {
    e.preventDefault();
    setDragOver(true);
  }

  function handleDragLeave(e: DragEvent<HTMLDivElement>): void {
    e.preventDefault();
    setDragOver(false);
  }

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      className={[
        "flex items-center gap-3 rounded-md border px-3 py-2.5 transition-colors",
        dragOver ? "border-primary bg-primary/5" : "border-border",
      ].join(" ")}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <code className="font-mono text-sm">{templateKey}</code>
          {overridden ? (
            <span className="inline-flex items-center gap-1 text-xs rounded-full bg-success/10 text-success-foreground px-2 py-0.5">
              <CheckCircle size={11} aria-hidden /> overridden
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">shipped</span>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          {dragOver
            ? "Drop xlsx to upload"
            : "Drag & drop an .xlsx file or click Upload to replace."}
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <input
          id={inputId}
          ref={fileInputRef}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          className="sr-only"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <Button
          variant="outline"
          size="sm"
          onClick={() => fileInputRef.current?.click()}
          disabled={busy}
          aria-label={`Upload custom template for ${templateKey}`}
        >
          <Upload size={13} aria-hidden /> {busy ? "Working…" : "Upload"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onRevert}
          disabled={!overridden || busy}
          aria-label={`Revert ${templateKey} to the shipped template`}
        >
          <Trash2 size={13} aria-hidden /> Revert
        </Button>
      </div>
    </div>
  );
}
