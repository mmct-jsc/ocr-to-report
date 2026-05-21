import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  TrendingUp,
  Coins,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  ArrowRight,
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
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";

export function DashboardRoute() {
  const client = useClient();

  const usage = useQuery({
    queryKey: ["usage"],
    queryFn: () => client.usage.get(),
    refetchInterval: 30_000,
  });
  const jobs = useQuery({
    queryKey: ["jobs", "recent"],
    queryFn: () => client.jobs.list({ limit: 5 }),
    refetchInterval: 15_000,
  });
  const parked = useQuery({
    queryKey: ["jobs", "parked"],
    queryFn: () => client.jobs.list({ status: "parked", limit: 100 }),
    refetchInterval: 30_000,
  });

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Live tenant operations: spend, throughput, manual-review queue."
        actions={
          <Link to="/upload">
            <Button>
              <Sparkles size={14} aria-hidden /> Process transcript
            </Button>
          </Link>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KPI
          icon={CheckCircle2}
          tone="success"
          label="Transcripts (this period)"
          value={usage.data?.transcripts_processed}
          loading={usage.isLoading}
        />
        <KPI
          icon={Coins}
          tone="info"
          label="Spend (USD, this period)"
          value={usage.data ? `$${usage.data.usd_cost.toFixed(4)}` : undefined}
          loading={usage.isLoading}
        />
        <KPI
          icon={TrendingUp}
          tone="info"
          label="Tokens in / out"
          value={
            usage.data
              ? `${formatThousands(usage.data.tokens_input)} / ${formatThousands(usage.data.tokens_output)}`
              : undefined
          }
          loading={usage.isLoading}
        />
        <KPI
          icon={AlertTriangle}
          tone={parked.data && parked.data.length > 0 ? "warning" : "success"}
          label="Parked for review"
          value={parked.data?.length ?? 0}
          loading={parked.isLoading}
        />
      </div>

      <div className="grid gap-4 mt-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent jobs</CardTitle>
            <CardDescription>Last 5 transcripts processed for this tenant.</CardDescription>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            {jobs.isLoading ? (
              <div className="px-5 pb-5 space-y-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
              </div>
            ) : jobs.data && jobs.data.length > 0 ? (
              <ul className="divide-y divide-border">
                {jobs.data.map((j) => (
                  <li key={j.id} className="px-5 py-3 flex items-center gap-3">
                    <StatusBadge status={j.status} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">
                        {j.profile_id ?? "—"} → {j.target_id ?? "—"}
                      </p>
                      <p className="text-xs text-muted-foreground font-mono truncate">
                        {j.id}
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground hidden md:inline">
                      ${j.usd_cost.toFixed(4)}
                    </span>
                    <Link
                      to={`/jobs/${j.id}`}
                      className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                    >
                      Detail <ArrowRight size={12} aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="px-5 pb-5">
                <EmptyState
                  icon={TrendingUp}
                  level={3}
                  title="No jobs yet"
                  description="Process your first transcript to populate this list. Recent jobs include status, model used, cost, and a direct link to the result."
                  action={
                    <Link
                      to="/upload"
                      className="inline-flex items-center gap-2 h-9 px-4 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:opacity-90 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    >
                      Process first transcript
                    </Link>
                  }
                />
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Manual-review queue</CardTitle>
            <CardDescription>
              Low-confidence extractions parked by the SLA gate.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {parked.isLoading ? (
              <Skeleton className="h-20" />
            ) : parked.data && parked.data.length > 0 ? (
              <ul className="space-y-2">
                {parked.data.slice(0, 5).map((j) => (
                  <li key={j.id} className="rounded-md border border-border p-3 surface-hover">
                    <Link to={`/jobs/${j.id}`} className="block">
                      <p className="text-sm font-medium truncate">
                        {j.profile_id ?? "—"}
                      </p>
                      <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
                        {j.park_reason ?? "—"}
                      </p>
                    </Link>
                  </li>
                ))}
                {parked.data.length > 5 && (
                  <Link
                    to="/jobs?status=parked"
                    className="text-xs text-primary hover:underline"
                  >
                    View all {parked.data.length} parked jobs →
                  </Link>
                )}
              </ul>
            ) : (
              <EmptyState
                icon={Sparkles}
                level={3}
                title="Nothing to review"
                description="Low-confidence extractions appear here when the SLA gate parks them. Reviewers approve or reject; rejected jobs are discarded."
              />
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

interface KPIProps {
  icon: typeof CheckCircle2;
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

function formatThousands(n: number): string {
  return n.toLocaleString("en-US");
}
