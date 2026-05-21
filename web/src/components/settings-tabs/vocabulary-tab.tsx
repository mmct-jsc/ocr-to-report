/**
 * Settings → Vocabulary tab — raw JSON-patch editor.
 *
 * The structured Pipeline + SLA + Templates tabs cover the common
 * surfaces. This one is the power-user escape hatch: a textarea that
 * accepts the full ``profile_overrides`` map (and, by extension, any
 * future scope-keyed patch list) as raw JSON.
 *
 * Validation strategy:
 *
 * 1. Client-side: ``JSON.parse`` first — if it fails, the Save button
 *    stays disabled and the parse error is shown inline.
 * 2. Server-side: ``patches_from_wire`` (called inside the PUT handler)
 *    rejects malformed wire format (unknown ``op``, empty ``path``)
 *    with a 400. The toast surfaces the server's problem detail.
 *
 * The textarea is monospaced + accepts tab indentation. Pretty-printing
 * is done on load so what the user sees matches what the server stores.
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

function pretty(json: Record<string, OverridePatch[]>): string {
  // Pretty-print but elide empty arrays so the editor opens clean.
  return JSON.stringify(json, null, 2);
}

// Mirror of ``core.overrides.resolver.OverrideOperation``. Keep in sync
// — if the server adds a new operation, append it here too; otherwise
// the client will reject patches the server would have accepted.
const VALID_OPS: readonly string[] = ["set", "delete", "append", "merge"];

function parse(text: string): {
  ok: true;
  value: Record<string, OverridePatch[]>;
} | {
  ok: false;
  error: string;
} {
  if (text.trim() === "") {
    return { ok: true, value: {} };
  }
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { ok: false, error: "Top-level value must be a JSON object." };
    }
    for (const [k, v] of Object.entries(parsed)) {
      if (!Array.isArray(v)) {
        return {
          ok: false,
          error: `Value for "${k}" must be an array of patch objects.`,
        };
      }
      for (const [i, p] of (v as unknown[]).entries()) {
        if (typeof p !== "object" || p === null) {
          return { ok: false, error: `Patch ${k}[${i}] is not an object.` };
        }
        const rec = p as Record<string, unknown>;
        if (typeof rec.op !== "string") {
          return { ok: false, error: `Patch ${k}[${i}] is missing 'op'.` };
        }
        // Validate ``op`` against the known set rather than just
        // checking it's a string — the server's ``patches_from_wire``
        // rejects unknown ops with a 400, so this match keeps the
        // client/server contract aligned and produces an inline error
        // instead of a post-Save toast.
        if (!VALID_OPS.includes(rec.op)) {
          return {
            ok: false,
            error: `Patch ${k}[${i}] has unknown op "${rec.op}". Valid: ${VALID_OPS.join(", ")}.`,
          };
        }
        if (typeof rec.path !== "string" || rec.path.length === 0) {
          return {
            ok: false,
            error: `Patch ${k}[${i}] has invalid 'path'.`,
          };
        }
      }
    }
    return { ok: true, value: parsed as Record<string, OverridePatch[]> };
  } catch (e: unknown) {
    return {
      ok: false,
      error: e instanceof Error ? e.message : "JSON parse error",
    };
  }
}

export function VocabularyTab() {
  const { client } = useAuth();
  const toast = useToast();

  const [savedText, setSavedText] = useState<string>("{}");
  const [text, setText] = useState<string>("{}");
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
        const txt = pretty(cfg.profile_overrides);
        setSavedText(txt);
        setText(txt);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(
          e instanceof Error ? e.message : "Failed to load profile overrides",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const parseResult = useMemo(() => parse(text), [text]);
  const parseError = parseResult.ok ? null : parseResult.error;
  const dirty = text !== savedText;

  async function save(): Promise<void> {
    if (!client || !parseResult.ok || !dirty) return;
    setSaving(true);
    try {
      const cfg = await client.tenantConfig.replace({
        profile_overrides: parseResult.value,
      });
      const txt = pretty(cfg.profile_overrides);
      setSavedText(txt);
      setText(txt);
      toast.success(
        "Profile overrides saved",
        Object.keys(parseResult.value).length === 0
          ? "All profile overrides cleared."
          : `Saved overrides for ${Object.keys(parseResult.value).length} profile(s).`,
      );
    } catch (e: unknown) {
      toast.error(
        "Could not save",
        e instanceof Error ? e.message : "Server rejected the patch list.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (!client) {
    return (
      <p className="text-sm text-muted-foreground">
        Sign in to manage this tenant's vocabulary patches.
      </p>
    );
  }
  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading profile overrides…</p>;
  }
  if (loadError !== null) {
    return (
      <p className="text-sm text-danger-foreground bg-danger/10 rounded-md px-3 py-2">
        {loadError}
      </p>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile overrides (raw JSON)</CardTitle>
        <CardDescription>
          Power-user surface. The structured tabs cover SLA + pipeline +
          templates; this one is for hand-editing profile vocabulary
          patches before a UI surface exists. Format:{" "}
          <code className="font-mono text-[11px]">
            {`{ "<profile_id>": [{"op":"set","path":"...","value":...}] }`}
          </code>
          .
        </CardDescription>
      </CardHeader>
      <CardContent>
        <label htmlFor="vocab-editor" className="sr-only">
          Profile overrides JSON
        </label>
        <textarea
          id="vocab-editor"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          rows={20}
          aria-invalid={parseError !== null}
          aria-describedby={parseError !== null ? "vocab-error" : undefined}
          className={[
            "w-full font-mono text-xs rounded-md border bg-background p-3 resize-y",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            parseError !== null ? "border-danger" : "border-border",
          ].join(" ")}
        />
        {parseError !== null && (
          <p
            id="vocab-error"
            role="alert"
            className="mt-2 text-xs text-danger-foreground bg-danger/10 rounded-md px-2 py-1.5"
          >
            {parseError}
          </p>
        )}
      </CardContent>
      <CardFooter className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Save sends the entire map; missing keys are deleted server-side.
        </p>
        <Button onClick={save} disabled={!dirty || parseError !== null || saving}>
          <Save size={14} aria-hidden /> {saving ? "Saving…" : "Save"}
        </Button>
      </CardFooter>
    </Card>
  );
}
