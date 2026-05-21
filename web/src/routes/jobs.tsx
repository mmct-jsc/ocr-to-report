import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Briefcase } from "lucide-react";
import { useClient } from "@/lib/auth";
import { PageHeader } from "@/components/layout";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";

const STATUSES = [
  { value: "", label: "All statuses" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "parked", label: "Parked" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
];

export function JobsRoute() {
  const client = useClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const status = searchParams.get("status") ?? "";

  const jobs = useQuery({
    queryKey: ["jobs", "list", status],
    queryFn: () =>
      client.jobs.list({
        ...(status ? { status } : {}),
        limit: 100,
      }),
    refetchInterval: 10_000,
  });

  const summary = useMemo(() => {
    if (!jobs.data) return null;
    const counts: Record<string, number> = {};
    for (const j of jobs.data) counts[j.status] = (counts[j.status] ?? 0) + 1;
    return counts;
  }, [jobs.data]);

  return (
    <>
      <PageHeader
        title="Jobs"
        description="Every transcript request, with provider, cost, and status. Click into a row for actions."
      />

      <div className="flex items-center gap-3 flex-wrap mb-4">
        <Select
          aria-label="Filter jobs by status"
          options={STATUSES}
          value={status}
          onChange={(e) => {
            const v = e.target.value;
            const next = new URLSearchParams(searchParams);
            if (v) next.set("status", v);
            else next.delete("status");
            setSearchParams(next);
          }}
          className="w-48"
        />
        {summary && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {Object.entries(summary).map(([k, v]) => (
              <span key={k} className="inline-flex items-center gap-1">
                <span className="font-mono">{v}</span> {k}
              </span>
            ))}
          </div>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          {jobs.isLoading ? (
            <div className="p-5 space-y-2">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : jobs.data && jobs.data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="jobs-table">
                <thead className="bg-muted/40">
                  <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-5 py-2.5">Status</th>
                    <th className="px-5 py-2.5">ID</th>
                    <th className="px-5 py-2.5">Profile → Target</th>
                    <th className="px-5 py-2.5">Provider</th>
                    <th className="px-5 py-2.5 text-right">Tokens</th>
                    <th className="px-5 py-2.5 text-right">Cost</th>
                    <th className="px-5 py-2.5">Created</th>
                    <th className="px-5 py-2.5 text-right" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {jobs.data.map((j) => (
                    <tr
                      key={j.id}
                      className={cn("hover:bg-muted/40 transition-colors")}
                    >
                      <td className="px-5 py-3">
                        <StatusBadge status={j.status} />
                      </td>
                      <td className="px-5 py-3 font-mono text-xs">
                        {j.id.slice(0, 8)}…
                      </td>
                      <td className="px-5 py-3">
                        <span className="text-sm">
                          {j.profile_id ?? "—"}
                        </span>
                        <span className="text-muted-foreground"> → </span>
                        <span className="text-sm">{j.target_id ?? "—"}</span>
                      </td>
                      <td className="px-5 py-3 text-xs text-muted-foreground">
                        {j.provider_used ?? "—"}
                        {j.model_id_used && (
                          <>
                            {" "}
                            <span className="font-mono">{j.model_id_used}</span>
                          </>
                        )}
                      </td>
                      <td className="px-5 py-3 text-right tabular-nums text-xs">
                        {j.tokens_input.toLocaleString()} /{" "}
                        {j.tokens_output.toLocaleString()}
                      </td>
                      <td className="px-5 py-3 text-right tabular-nums">
                        ${j.usd_cost.toFixed(4)}
                      </td>
                      <td className="px-5 py-3 text-xs text-muted-foreground">
                        {formatTime(j.created_at)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <Link
                          to={`/jobs/${j.id}`}
                          className="text-primary hover:underline inline-flex items-center gap-1 text-xs font-medium"
                        >
                          Open <ArrowRight size={12} aria-hidden />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={Briefcase}
              title="No jobs yet"
              description={
                status
                  ? `No jobs in status "${status}".`
                  : "Submit a transcript via the Process page to populate the job log."
              }
              action={
                <Link
                  to="/upload"
                  className="text-primary hover:underline text-sm font-medium"
                >
                  Process a transcript →
                </Link>
              }
            />
          )}
        </CardContent>
      </Card>
    </>
  );
}

function formatTime(isoLike: string): string {
  try {
    return new Date(isoLike).toLocaleString();
  } catch {
    return isoLike;
  }
}
