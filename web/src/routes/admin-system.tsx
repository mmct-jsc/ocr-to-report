import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  KeyRound,
  Layers,
  Server,
  Workflow,
  Activity,
} from "lucide-react";
import { useClient } from "@/lib/auth";
import { PageHeader } from "@/components/layout";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

export function AdminSystemRoute() {
  const client = useClient();
  const overview = useQuery({
    queryKey: ["admin", "system"],
    queryFn: () => client.admin.system(),
    refetchInterval: 30_000,
  });

  return (
    <>
      <PageHeader
        title="System"
        description="Plane-wide stats: tenants, keys, registered bundles, queue depth, build."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KPI
          icon={Building2}
          tone="info"
          label="Tenants (active / total)"
          value={
            overview.data
              ? `${overview.data.tenants_active} / ${overview.data.tenants_total}`
              : undefined
          }
          loading={overview.isLoading}
        />
        <KPI
          icon={KeyRound}
          tone="info"
          label="API keys (active)"
          value={overview.data?.api_keys_active}
          loading={overview.isLoading}
        />
        <KPI
          icon={Workflow}
          tone="info"
          label="Queue depth"
          value={overview.data?.queue_depth}
          loading={overview.isLoading}
        />
        <KPI
          icon={Server}
          tone="success"
          label="API version"
          value={overview.data ? `v${overview.data.api_version}` : undefined}
          loading={overview.isLoading}
        />
      </div>

      <div className="grid gap-4 mt-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers size={16} aria-hidden /> Profiles loaded
            </CardTitle>
            <CardDescription>Source-side bundles auto-discovered at boot.</CardDescription>
          </CardHeader>
          <CardContent>
            {overview.isLoading ? (
              <Skeleton className="h-12" />
            ) : overview.data && overview.data.profiles_loaded.length > 0 ? (
              <ul className="space-y-1.5">
                {overview.data.profiles_loaded.map((id) => (
                  <li
                    key={id}
                    className="text-sm font-mono rounded-md border border-border px-3 py-2"
                  >
                    {id}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No profiles registered.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers size={16} aria-hidden /> Targets loaded
            </CardTitle>
            <CardDescription>Output-side bundles auto-discovered at boot.</CardDescription>
          </CardHeader>
          <CardContent>
            {overview.isLoading ? (
              <Skeleton className="h-12" />
            ) : overview.data && overview.data.targets_loaded.length > 0 ? (
              <ul className="space-y-1.5">
                {overview.data.targets_loaded.map((id) => (
                  <li
                    key={id}
                    className="text-sm font-mono rounded-md border border-border px-3 py-2"
                  >
                    {id}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No targets registered.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity size={16} aria-hidden /> SLA tiers
            </CardTitle>
            <CardDescription>
              Presets shipped at sla-tiers/&lt;tier&gt;.yaml.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {overview.isLoading ? (
              <Skeleton className="h-12" />
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {overview.data?.sla_presets.map((tier) => (
                  <Badge key={tier} tone="info">
                    {tier}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

interface KPIProps {
  icon: typeof Server;
  label: string;
  value: number | string | undefined;
  loading?: boolean;
  tone?: "success" | "warning" | "info";
}

function KPI({ icon: Icon, label, value, loading, tone = "info" }: KPIProps) {
  const toneClass =
    tone === "success"
      ? "text-success bg-success/10"
      : tone === "warning"
        ? "text-warning bg-warning/10"
        : "text-primary bg-primary/10";
  return (
    <Card>
      <CardContent className="p-5 flex items-start gap-4">
        <div className={`rounded-lg p-2 ${toneClass}`}>
          <Icon size={18} aria-hidden />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
          {loading ? (
            <Skeleton className="h-7 w-24 mt-2" />
          ) : (
            <p className="text-2xl font-semibold tracking-tight mt-1 text-foreground">
              {value ?? "—"}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
