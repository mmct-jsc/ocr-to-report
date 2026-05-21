import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ShieldCheck, Search, Download, Trash2, AlertTriangle } from "lucide-react";
import { useAuth, useClient } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { PageHeader } from "@/components/layout";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";

interface AccessResp {
  subject_full_name: string;
  tenant_id: string;
  generated_at: string;
  record_count: number;
  transcripts: unknown[];
}

interface ErasureResp {
  subject_full_name: string;
  transcripts_erased: number;
  blobs_erased: number;
  audit_entry_id: string;
  completed_at: string;
}

export function ComplianceRoute() {
  const { apiKey, baseUrl } = useAuth();
  const client = useClient();
  const toast = useToast();

  const [accessName, setAccessName] = useState("");
  const [eraseName, setEraseName] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [accessResult, setAccessResult] = useState<AccessResp | null>(null);

  const fetchAccess = async (kind: "access" | "portability"): Promise<AccessResp> => {
    const url =
      `${baseUrl.replace(/\/+$/, "")}/v1/dsr/${kind}` +
      `?subject_full_name=${encodeURIComponent(accessName)}`;
    const r = await fetch(url, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return (await r.json()) as AccessResp;
  };

  const access = useMutation({
    mutationFn: () => fetchAccess("access"),
    onSuccess: (resp) => {
      setAccessResult(resp);
      toast.success(
        "Access request returned",
        `${resp.record_count} record${resp.record_count === 1 ? "" : "s"}`,
      );
    },
    onError: (e) => toast.error("Access failed", e instanceof Error ? e.message : "unknown"),
  });

  const portability = useMutation({
    mutationFn: () => fetchAccess("portability"),
    onSuccess: (resp) => {
      const blob = new Blob([JSON.stringify(resp, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `dsr-portability-${slugify(accessName)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Export downloaded");
    },
    onError: (e) => toast.error("Export failed", e instanceof Error ? e.message : "unknown"),
  });

  const erasure = useMutation({
    mutationFn: async (): Promise<ErasureResp> => {
      const url = `${baseUrl.replace(/\/+$/, "")}/v1/dsr/erasure`;
      const r = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ subject_full_name: eraseName, confirm: true }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        throw new Error(
          (body as { detail?: string } | null)?.detail ?? `HTTP ${r.status}`,
        );
      }
      return (await r.json()) as ErasureResp;
    },
    onSuccess: (resp) => {
      toast.success(
        "Erasure complete",
        `${resp.transcripts_erased} transcript(s) + ${resp.blobs_erased} blob(s) deleted.`,
      );
      setEraseName("");
      setConfirmText("");
    },
    onError: (e) => toast.error("Erasure failed", e instanceof Error ? e.message : "unknown"),
  });

  // Used to surface that the SDK is wired (so future code can swap to it).
  void client;

  const eraseDisabled = !eraseName || confirmText !== eraseName;

  return (
    <>
      <PageHeader
        title="Compliance"
        description="GDPR Article 15 (access), Article 20 (portability), Article 17 (erasure). Each call appends a FERPA-tagged audit entry."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Access · Portability</CardTitle>
            <CardDescription>
              Look up every transcript matching a data subject's full name. Portability
              wraps the same payload in a stable schema_version envelope.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="access-name">Subject full name</Label>
              <Input
                id="access-name"
                placeholder="Antoni Judek"
                value={accessName}
                onChange={(e) => setAccessName(e.target.value)}
              />
            </div>
          </CardContent>
          <CardFooter>
            <Button
              variant="outline"
              onClick={() => access.mutate()}
              loading={access.isPending}
              disabled={!accessName}
            >
              <Search size={14} aria-hidden /> Article 15 — Access
            </Button>
            <Button
              onClick={() => portability.mutate()}
              loading={portability.isPending}
              disabled={!accessName}
            >
              <Download size={14} aria-hidden /> Article 20 — Portability
            </Button>
          </CardFooter>
          {accessResult && (
            <CardContent className="border-t border-border pt-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Last access result
              </p>
              <p className="text-base font-semibold mt-1">
                {accessResult.record_count} record(s) for{" "}
                <span className="font-mono">{accessResult.subject_full_name}</span>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Generated at {new Date(accessResult.generated_at).toLocaleString()}
              </p>
            </CardContent>
          )}
        </Card>

        <Card className="border-danger/30">
          <CardHeader>
            <CardTitle className="text-danger">Erasure (Article 17)</CardTitle>
            <CardDescription className="text-danger/80">
              Crypto-shreds the encrypted transcript row + deletes input/output blobs.
              Cannot be undone.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="erase-name">Subject full name</Label>
              <Input
                id="erase-name"
                placeholder="Antoni Judek"
                value={eraseName}
                onChange={(e) => setEraseName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="confirm-text">
                Type the name again to confirm
              </Label>
              <Input
                id="confirm-text"
                placeholder="(must match exactly)"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
              />
              <p className="text-[11px] text-warning inline-flex items-center gap-1">
                <AlertTriangle size={11} aria-hidden /> Audit log retains a SHA-256 of the name —
                never the plaintext.
              </p>
            </div>
          </CardContent>
          <CardFooter>
            <Button
              variant="danger"
              onClick={() => erasure.mutate()}
              loading={erasure.isPending}
              disabled={eraseDisabled}
            >
              <Trash2 size={14} aria-hidden /> Permanently erase
            </Button>
          </CardFooter>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>About these endpoints</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-2">
          <p className="inline-flex items-center gap-2 font-medium text-foreground">
            <ShieldCheck size={16} aria-hidden className="text-success" /> FERPA-tagged audit entries
            recorded for every call.
          </p>
          <p>
            Subject matching is exact + case-insensitive on{" "}
            <code className="font-mono">student.full_name</code> within the calling
            tenant's records.
          </p>
        </CardContent>
      </Card>
    </>
  );
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}
