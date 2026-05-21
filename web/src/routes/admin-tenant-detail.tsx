import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Plus,
  KeyRound,
  Eye,
  EyeOff,
  Copy,
  Trash2,
  History,
} from "lucide-react";
import type { ApiKeyIssueRequest, TenantUpdateRequest } from "@ocr-to-report/sdk";
import { useClient } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { PageHeader } from "@/components/layout";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

const TIERS = [
  { value: "economy", label: "economy" },
  { value: "standard", label: "standard" },
  { value: "premium", label: "premium" },
  { value: "enterprise", label: "enterprise" },
];

export function AdminTenantDetailRoute() {
  const { tenantId = "" } = useParams();
  const client = useClient();
  const qc = useQueryClient();
  const toast = useToast();

  const tenants = useQuery({
    queryKey: ["admin", "tenants"],
    queryFn: () => client.admin.listTenants({ includeArchived: true }),
  });
  const tenant = tenants.data?.find((t) => t.id === tenantId);

  const apiKeys = useQuery({
    queryKey: ["admin", "tenant-keys", tenantId],
    queryFn: () => client.admin.listApiKeys(tenantId),
    enabled: !!tenantId,
  });

  const audit = useQuery({
    queryKey: ["admin", "audit", tenantId],
    queryFn: () => client.admin.tenantAudit(tenantId, { limit: 50 }),
    enabled: !!tenantId,
  });

  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState<TenantUpdateRequest>({});
  const update = useMutation({
    mutationFn: () => client.admin.updateTenant(tenantId, edit),
    onSuccess: () => {
      toast.success("Tenant updated");
      qc.invalidateQueries({ queryKey: ["admin", "tenants"] });
      setEditing(false);
      setEdit({});
    },
    onError: (e) => toast.error("Update failed", e instanceof Error ? e.message : "unknown"),
  });

  const [keyForm, setKeyForm] = useState<ApiKeyIssueRequest>({
    label: "",
    scopes: ["transcripts:write"],
    live: false,
  });
  const [createdKey, setCreatedKey] = useState<{ id: string; secret: string } | null>(null);
  const [secretShown, setSecretShown] = useState(false);

  const issueKey = useMutation({
    mutationFn: () => client.admin.issueApiKey(tenantId, keyForm),
    onSuccess: (resp) => {
      toast.success("API key issued", "Save the secret — it isn't returned again.");
      setCreatedKey({ id: resp.api_key.id, secret: resp.secret });
      setSecretShown(true);
      setKeyForm({ label: "", scopes: ["transcripts:write"], live: false });
      qc.invalidateQueries({ queryKey: ["admin", "tenant-keys", tenantId] });
    },
    onError: (e) => toast.error("Issue failed", e instanceof Error ? e.message : "unknown"),
  });

  const revokeKey = useMutation({
    mutationFn: (keyId: string) => client.admin.revokeApiKey(keyId),
    onSuccess: () => {
      toast.success("API key revoked");
      qc.invalidateQueries({ queryKey: ["admin", "tenant-keys", tenantId] });
    },
    onError: (e) => toast.error("Revoke failed", e instanceof Error ? e.message : "unknown"),
  });

  if (tenants.isLoading) {
    return (
      <>
        <PageHeader title="Tenant" description="Loading…" />
        <Skeleton className="h-40" />
      </>
    );
  }
  if (!tenant) {
    return (
      <>
        <PageHeader title="Tenant not found" />
        <Link to="/admin/tenants" className="text-primary hover:underline text-sm">
          ← back to tenants
        </Link>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={tenant.name}
        description={`${tenant.slug} · sla ${tenant.sla_tier} · pipeline ${tenant.pipeline_id}`}
        actions={
          <Link to="/admin/tenants">
            <Button variant="ghost" size="sm">
              <ArrowLeft size={14} aria-hidden /> All tenants
            </Button>
          </Link>
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
            <CardDescription>Edit SLA, region pin, default target.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Field label="ID">
              <code className="font-mono text-xs break-all">{tenant.id}</code>
            </Field>
            <Field label="SLA tier">
              {editing ? (
                <Select
                  options={TIERS}
                  value={(edit.sla_tier as string) ?? tenant.sla_tier}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      sla_tier: e.target.value as TenantUpdateRequest["sla_tier"],
                    })
                  }
                />
              ) : (
                <Badge tone="info">{tenant.sla_tier}</Badge>
              )}
            </Field>
            <Field label="Region pin">
              {editing ? (
                <Input
                  value={(edit.region_pin as string) ?? tenant.region_pin ?? ""}
                  onChange={(e) => setEdit({ ...edit, region_pin: e.target.value || null })}
                  placeholder="(none)"
                />
              ) : (
                <span>{tenant.region_pin ?? "—"}</span>
              )}
            </Field>
            <Field label="Default target">
              {editing ? (
                <Input
                  value={
                    (edit.default_target_system as string) ??
                    tenant.default_target_system ??
                    ""
                  }
                  onChange={(e) =>
                    setEdit({ ...edit, default_target_system: e.target.value || null })
                  }
                  placeholder="us-hs.v1"
                />
              ) : (
                <span>{tenant.default_target_system ?? "—"}</span>
              )}
            </Field>
            <Field label="Created">
              <span className="text-muted-foreground">
                {new Date(tenant.created_at).toLocaleString()}
              </span>
            </Field>
            {tenant.archived_at && (
              <Field label="Archived">
                <span className="text-warning">
                  {new Date(tenant.archived_at).toLocaleString()}
                </span>
              </Field>
            )}
          </CardContent>
          <CardFooter>
            {editing ? (
              <>
                <Button
                  variant="outline"
                  onClick={() => {
                    setEditing(false);
                    setEdit({});
                  }}
                >
                  Cancel
                </Button>
                <Button onClick={() => update.mutate()} loading={update.isPending}>
                  Save
                </Button>
              </>
            ) : (
              <Button variant="outline" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
          </CardFooter>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between flex">
            <div>
              <CardTitle>API keys</CardTitle>
              <CardDescription>
                {apiKeys.data?.length ?? 0} key
                {apiKeys.data && apiKeys.data.length === 1 ? "" : "s"} for this tenant.
              </CardDescription>
            </div>
          </CardHeader>
          {createdKey && (
            <CardContent className="border-t border-border bg-success/5">
              <p className="text-sm font-semibold text-success mb-1.5">
                New key — copy it now, it isn't returned again.
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <code className="font-mono text-xs bg-card border border-border rounded px-3 py-2 break-all flex-1 min-w-0">
                  {secretShown ? createdKey.secret : "•".repeat(28)}
                </code>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSecretShown((v) => !v)}
                >
                  {secretShown ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
                  {secretShown ? "Hide" : "Reveal"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    await navigator.clipboard.writeText(createdKey.secret);
                    toast.info("Copied");
                  }}
                >
                  <Copy size={14} aria-hidden /> Copy
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setCreatedKey(null)}>
                  Dismiss
                </Button>
              </div>
            </CardContent>
          )}
          <CardContent className="px-0 pb-0">
            {apiKeys.isLoading ? (
              <div className="p-5 space-y-2">
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
              </div>
            ) : apiKeys.data && apiKeys.data.length > 0 ? (
              <ul className="divide-y divide-border">
                {apiKeys.data.map((k) => (
                  <li key={k.id} className="px-5 py-3 flex items-center gap-3">
                    <KeyRound size={16} aria-hidden className="text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {k.label || "(unlabeled)"}
                      </p>
                      <p className="text-xs text-muted-foreground font-mono">
                        {k.prefix}…
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {k.scopes.map((s) => (
                          <Badge key={s} tone={s === "admin:*" ? "warning" : "info"}>
                            {s}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    {k.last_used_at && (
                      <span className="text-xs text-muted-foreground">
                        last used {new Date(k.last_used_at).toLocaleDateString()}
                      </span>
                    )}
                    {k.revoked_at ? (
                      <Badge tone="danger">revoked</Badge>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (confirm(`Revoke key ${k.prefix}…?`)) revokeKey.mutate(k.id);
                        }}
                      >
                        <Trash2 size={12} aria-hidden /> Revoke
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="p-5 text-sm text-muted-foreground">No API keys yet.</p>
            )}
          </CardContent>
          <CardFooter>
            <div className="flex flex-wrap gap-2 items-end">
              <div>
                <Label htmlFor="key-label">Label</Label>
                <Input
                  id="key-label"
                  className="w-40"
                  placeholder="ci-runner"
                  value={keyForm.label ?? ""}
                  onChange={(e) => setKeyForm({ ...keyForm, label: e.target.value })}
                />
              </div>
              <label className="inline-flex items-center gap-2 text-sm cursor-pointer mb-2">
                <input
                  type="checkbox"
                  checked={(keyForm.scopes ?? []).includes("admin:*")}
                  onChange={(e) =>
                    setKeyForm({
                      ...keyForm,
                      scopes: e.target.checked
                        ? ["admin:*", "transcripts:write"]
                        : ["transcripts:write"],
                    })
                  }
                  className="accent-primary"
                />
                <span>admin:*</span>
              </label>
              <label className="inline-flex items-center gap-2 text-sm cursor-pointer mb-2">
                <input
                  type="checkbox"
                  checked={!!keyForm.live}
                  onChange={(e) => setKeyForm({ ...keyForm, live: e.target.checked })}
                  className="accent-primary"
                />
                <span>live (sk_live_)</span>
              </label>
              <Button onClick={() => issueKey.mutate()} loading={issueKey.isPending}>
                <Plus size={14} aria-hidden /> Issue key
              </Button>
            </div>
          </CardFooter>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader className="flex-row items-center gap-2 flex">
            <History size={16} aria-hidden className="text-muted-foreground" />
            <CardTitle>Audit log (latest 50)</CardTitle>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            {audit.isLoading ? (
              <div className="p-5 space-y-2">
                <Skeleton className="h-8" />
                <Skeleton className="h-8" />
                <Skeleton className="h-8" />
              </div>
            ) : audit.data && audit.data.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40">
                    <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="px-5 py-2.5">Timestamp</th>
                      <th className="px-5 py-2.5">Actor</th>
                      <th className="px-5 py-2.5">Action</th>
                      <th className="px-5 py-2.5">Resource</th>
                      <th className="px-5 py-2.5">Metadata</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {audit.data.map((a) => (
                      <tr key={a.id} className="hover:bg-muted/40">
                        <td className="px-5 py-2 font-mono text-xs">
                          {new Date(a.ts).toLocaleString()}
                        </td>
                        <td className="px-5 py-2 text-xs">{a.actor_type}</td>
                        <td className="px-5 py-2 font-medium">{a.action}</td>
                        <td className="px-5 py-2 font-mono text-xs">
                          {a.resource_type}
                          {a.resource_id ? `/${a.resource_id.slice(0, 8)}…` : ""}
                        </td>
                        <td className="px-5 py-2 text-xs text-muted-foreground">
                          {Object.keys(a.metadata).length > 0
                            ? Object.entries(a.metadata)
                                .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                                .join(" ")
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="p-5 text-sm text-muted-foreground">No audit entries yet.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] items-center gap-3">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div>{children}</div>
    </div>
  );
}
