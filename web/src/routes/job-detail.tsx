import { useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Download,
  Check,
  X,
  Copy,
  CheckCircle2,
  TerminalSquare,
} from "lucide-react";
import { useAuth, useClient } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { PageHeader } from "@/components/layout";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/input";

export function JobDetailRoute() {
  const { jobId = "" } = useParams();
  const client = useClient();
  const { apiKey, baseUrl } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [rejectReason, setRejectReason] = useState("");

  const job = useQuery({
    queryKey: ["jobs", "detail", jobId],
    queryFn: () => client.jobs.get(jobId),
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return 5_000;
      if (data.status === "pending" || data.status === "running") return 3_000;
      return false;
    },
    enabled: jobId.length > 0,
  });

  const approve = useMutation({
    mutationFn: () => client.jobs.approve(jobId),
    onSuccess: (j) => {
      toast.success("Job approved", `Status is now ${j.status}.`);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => toast.error("Approve failed", e instanceof Error ? e.message : "unknown"),
  });

  const reject = useMutation({
    mutationFn: () =>
      client.jobs.reject(jobId, rejectReason ? { reason: rejectReason } : {}),
    onSuccess: (j) => {
      toast.success("Job rejected", `Marked ${j.status}.`);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => toast.error("Reject failed", e instanceof Error ? e.message : "unknown"),
  });

  if (job.isLoading) {
    return (
      <>
        <PageHeader title="Job" description="Loading…" />
        <Skeleton className="h-40" />
      </>
    );
  }
  if (!job.data) {
    return (
      <>
        <PageHeader title="Job not found" />
        <Link to="/jobs" className="text-primary hover:underline text-sm">
          ← back to jobs
        </Link>
      </>
    );
  }
  const j = job.data;
  const canDownload = j.status === "succeeded" && j.output_blob_key;

  const downloadXlsx = async () => {
    try {
      const buf = await client.jobs.getResult(jobId);
      const blob = new Blob([buf], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `job_${jobId}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Download started");
    } catch (e) {
      toast.error("Download failed", e instanceof Error ? e.message : "unknown");
    }
  };

  const copyCurl = async () => {
    const url = `${baseUrl.replace(/\/+$/, "")}/v1/jobs/${jobId}/result`;
    const cmd = `curl -O -H 'Authorization: Bearer ${apiKey ?? "<API_KEY>"}' ${url}`;
    await navigator.clipboard.writeText(cmd);
    toast.info("Copied curl");
  };

  return (
    <>
      <PageHeader
        title={`Job ${j.id.slice(0, 8)}`}
        description={`${j.profile_id ?? "—"} → ${j.target_id ?? "—"}`}
        actions={
          <Button variant="ghost" size="sm" onClick={() => navigate("/jobs")}>
            <ArrowLeft size={14} aria-hidden /> All jobs
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center gap-3 flex">
            <CardTitle>Status</CardTitle>
            <StatusBadge status={j.status} />
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
              <Field label="Pipeline">{j.pipeline_id}</Field>
              <Field label="Provider">{j.provider_used ?? "—"}</Field>
              <Field label="Model">{j.model_id_used ?? "—"}</Field>
              <Field label="Tokens (in/out)">
                {j.tokens_input.toLocaleString()} / {j.tokens_output.toLocaleString()}
              </Field>
              <Field label="Cost">${j.usd_cost.toFixed(4)}</Field>
              <Field label="Created">{formatTime(j.created_at)}</Field>
              <Field label="Completed">{formatTime(j.completed_at)}</Field>
              <Field label="Expires">{formatTime(j.expires_at)}</Field>
              <Field label="Idempotency key">
                <span className="font-mono text-xs break-all">—</span>
              </Field>
            </dl>

            {j.error_detail && (
              <div className="mt-5 rounded-md border border-danger/30 bg-danger/5 p-3 text-sm">
                <p className="font-semibold text-danger">Error</p>
                <p className="text-foreground/80 mt-0.5 break-words">{j.error_detail}</p>
              </div>
            )}
            {j.park_reason && (
              <div className="mt-5 rounded-md border border-warning/30 bg-warning/5 p-3 text-sm">
                <p className="font-semibold text-warning">Parked for review</p>
                <p className="text-foreground/80 mt-0.5 break-words">{j.park_reason}</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Actions</CardTitle>
            <CardDescription>
              Approve / reject parked jobs, or download the rendered output.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button
              size="lg"
              className="w-full"
              onClick={downloadXlsx}
              disabled={!canDownload}
            >
              <Download size={14} aria-hidden /> Download xlsx
            </Button>
            <Button variant="outline" size="md" className="w-full" onClick={copyCurl}>
              <TerminalSquare size={14} aria-hidden /> Copy curl
            </Button>

            {j.status === "parked" && (
              <div className="pt-3 border-t border-border space-y-2">
                <p className="text-xs font-medium text-muted-foreground">
                  Manual review
                </p>
                <Textarea
                  placeholder="Reject reason (optional)"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  className="text-sm"
                />
                <div className="flex gap-2">
                  <Button
                    className="flex-1"
                    onClick={() => approve.mutate()}
                    loading={approve.isPending}
                  >
                    <Check size={14} aria-hidden /> Approve
                  </Button>
                  <Button
                    variant="danger"
                    className="flex-1"
                    onClick={() => reject.mutate()}
                    loading={reject.isPending}
                  >
                    <X size={14} aria-hidden /> Reject
                  </Button>
                </div>
              </div>
            )}

            {j.status === "succeeded" && (
              <p className="text-[11px] text-muted-foreground inline-flex items-center gap-1">
                <CheckCircle2 size={12} aria-hidden className="text-success" />
                Output ready for download.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-sm mt-0.5 text-foreground">{children}</dd>
    </div>
  );
}

function formatTime(s: string | null): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

// Suppress unused import (Copy reserved for future).
const _ = Copy;
void _;
