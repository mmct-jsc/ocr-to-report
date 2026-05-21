import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Building2, ArrowRight, Archive } from "lucide-react";
import type { TenantCreateRequest } from "@ocr-to-report/sdk";
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
import { EmptyState } from "@/components/ui/empty";
import { AlertDialog } from "@/components/ui/alert-dialog";

const TIERS = [
  { value: "economy", label: "Economy (batch only, ~$0.005)" },
  { value: "standard", label: "Standard (Haiku→Sonnet, ~$0.012)" },
  { value: "premium", label: "Premium (Sonnet→Opus, ~$0.04)" },
  { value: "enterprise", label: "Enterprise (dedicated, ~$0.04)" },
];

export function AdminTenantsRoute() {
  const client = useClient();
  const qc = useQueryClient();
  const toast = useToast();

  const [showCreate, setShowCreate] = useState(false);
  const [includeArchived, setIncludeArchived] = useState(false);
  // Archive confirmation. We hold the *tenant* in state (not just the id)
  // so the dialog can show the name + slug rather than a UUID. null when
  // closed.
  const [pendingArchive, setPendingArchive] = useState<
    { id: string; name: string } | null
  >(null);

  const tenants = useQuery({
    queryKey: ["admin", "tenants", includeArchived],
    queryFn: () => client.admin.listTenants({ includeArchived }),
  });

  const archive = useMutation({
    mutationFn: (id: string) => client.admin.archiveTenant(id),
    onSuccess: () => {
      toast.success("Tenant archived");
      qc.invalidateQueries({ queryKey: ["admin", "tenants"] });
      setPendingArchive(null);
    },
    onError: (e) => {
      toast.error("Archive failed", e instanceof Error ? e.message : "unknown");
      setPendingArchive(null);
    },
  });

  return (
    <>
      <PageHeader
        title="Tenants"
        description="Cross-tenant management. Each row links to its keys + audit log."
        actions={
          <>
            <label className="inline-flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
                className="accent-primary"
              />
              Include archived
            </label>
            <Button onClick={() => setShowCreate((v) => !v)}>
              <Plus size={14} aria-hidden /> {showCreate ? "Close" : "Create tenant"}
            </Button>
          </>
        }
      />

      {showCreate && (
        <CreateTenantPanel onCreated={() => setShowCreate(false)} />
      )}

      <Card>
        <CardContent className="px-0 pb-0">
          {tenants.isLoading ? (
            <div className="p-5 space-y-2">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : tenants.data && tenants.data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="tenants-table">
                <thead className="bg-muted/40">
                  <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-5 py-2.5">Name</th>
                    <th className="px-5 py-2.5">Slug</th>
                    <th className="px-5 py-2.5">SLA</th>
                    <th className="px-5 py-2.5">Pipeline</th>
                    <th className="px-5 py-2.5">Region</th>
                    <th className="px-5 py-2.5">Created</th>
                    <th className="px-5 py-2.5 text-right" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {tenants.data.map((t) => (
                    <tr key={t.id} className="hover:bg-muted/40 transition-colors">
                      <td className="px-5 py-3 font-medium">{t.name}</td>
                      <td className="px-5 py-3 font-mono text-xs">{t.slug}</td>
                      <td className="px-5 py-3">
                        <Badge tone={tierTone(t.sla_tier)}>{t.sla_tier}</Badge>
                      </td>
                      <td className="px-5 py-3 text-xs text-muted-foreground">
                        {t.pipeline_id}
                      </td>
                      <td className="px-5 py-3 text-xs text-muted-foreground">
                        {t.region_pin ?? "—"}
                      </td>
                      <td className="px-5 py-3 text-xs text-muted-foreground">
                        {new Date(t.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-5 py-3 text-right space-x-2">
                        {!t.archived_at && (
                          <button
                            type="button"
                            onClick={() =>
                              setPendingArchive({ id: t.id, name: t.name })
                            }
                            className="text-xs text-muted-foreground hover:text-danger inline-flex items-center gap-1"
                          >
                            <Archive size={12} aria-hidden /> Archive
                          </button>
                        )}
                        <Link
                          to={`/admin/tenants/${t.id}`}
                          className="text-primary hover:underline inline-flex items-center gap-1 text-xs font-medium"
                        >
                          Manage <ArrowRight size={12} aria-hidden />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={Building2}
              level={3}
              title="No tenants yet"
              description="Use Create tenant above to provision the first one, or run ocr-to-report bootstrap on the host."
              action={
                <button
                  type="button"
                  onClick={() => setShowCreate(true)}
                  className="inline-flex items-center gap-2 h-9 px-4 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:opacity-90 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  Create first tenant
                </button>
              }
            />
          )}
        </CardContent>
      </Card>

      <AlertDialog
        open={pendingArchive !== null}
        onClose={() => setPendingArchive(null)}
        onConfirm={() => {
          if (pendingArchive) archive.mutate(pendingArchive.id);
        }}
        title={`Archive ${pendingArchive?.name ?? "tenant"}?`}
        description={
          <>
            Archived tenants stop accepting new requests, but keys, jobs, and audit
            history are preserved. You can restore from the tenant detail page.
          </>
        }
        confirmLabel="Archive"
        cancelLabel="Keep tenant"
        tone="danger"
        pending={archive.isPending}
      />
    </>
  );
}

function CreateTenantPanel({ onCreated }: { onCreated: () => void }) {
  const client = useClient();
  const qc = useQueryClient();
  const toast = useToast();

  const [form, setForm] = useState<TenantCreateRequest>({
    name: "",
    slug: "",
    sla_tier: "standard",
    pipeline_id: "default_v1",
  });

  const create = useMutation({
    mutationFn: () => client.admin.createTenant(form),
    onSuccess: (t) => {
      toast.success("Tenant created", `${t.name} (${t.slug}) — sla=${t.sla_tier}`);
      qc.invalidateQueries({ queryKey: ["admin", "tenants"] });
      setForm({ name: "", slug: "", sla_tier: "standard", pipeline_id: "default_v1" });
      onCreated();
    },
    onError: (e) => toast.error("Create failed", e instanceof Error ? e.message : "unknown"),
  });

  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle>Create tenant</CardTitle>
        <CardDescription>
          Mints a tenant + an envelope-encryption DEK. Issue API keys from the tenant detail
          page.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="name">Display name</Label>
            <Input
              id="name"
              value={form.name}
              placeholder="Acme Inc."
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="slug">Slug (URL-safe)</Label>
            <Input
              id="slug"
              value={form.slug}
              placeholder="acme"
              onChange={(e) => setForm({ ...form, slug: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sla">SLA tier</Label>
            <Select
              id="sla"
              options={TIERS}
              value={form.sla_tier ?? "standard"}
              onChange={(e) =>
                setForm({
                  ...form,
                  sla_tier: e.target.value as TenantCreateRequest["sla_tier"],
                })
              }
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pipeline">Pipeline</Label>
            <Select
              id="pipeline"
              options={[
                { value: "default_v1", label: "default_v1" },
                { value: "with_manual_review_v1", label: "with_manual_review_v1" },
                { value: "batch_economy_v1", label: "batch_economy_v1" },
              ]}
              value={form.pipeline_id ?? "default_v1"}
              onChange={(e) => setForm({ ...form, pipeline_id: e.target.value })}
            />
          </div>
        </div>
      </CardContent>
      <CardFooter>
        <Button variant="outline" onClick={onCreated}>
          Cancel
        </Button>
        <Button
          onClick={() => create.mutate()}
          loading={create.isPending}
          disabled={!form.name || !form.slug}
        >
          <Plus size={14} aria-hidden /> Create
        </Button>
      </CardFooter>
    </Card>
  );
}

function tierTone(tier: string): "info" | "success" | "warning" | "neutral" {
  switch (tier) {
    case "economy":
      return "neutral";
    case "standard":
      return "info";
    case "premium":
      return "success";
    case "enterprise":
      return "warning";
    default:
      return "neutral";
  }
}
