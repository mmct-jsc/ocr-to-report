import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FileUp, X, Sparkles, FileCheck, AlertTriangle } from "lucide-react";
import type { TranscriptExtractionResponse } from "@ocr-to-report/sdk";
import { useClient } from "@/lib/auth";
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
import { Select } from "@/components/ui/select";
import { StatusBadge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

const MAX_BYTES = 25 * 1024 * 1024;
const ACCEPT = {
  "application/pdf": [".pdf"],
  "image/png": [".png"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/webp": [".webp"],
  "image/tiff": [".tif", ".tiff"],
};

export function UploadRoute() {
  const client = useClient();
  const navigate = useNavigate();
  const toast = useToast();

  const [file, setFile] = useState<File | null>(null);
  const [profileId, setProfileId] = useState("pl.lo.swiadectwo_szkolne.v1");
  const [targetId, setTargetId] = useState("us-hs.v1");
  const [templateKey, setTemplateKey] = useState<string>("");
  const [idempotencyKey, setIdempotencyKey] = useState("");

  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: () => client.templates.list(),
  });

  const targets = templates.data?.targets ?? [];
  const target = targets.find((t) => t.target_id === targetId);

  const dropzone = useDropzone({
    accept: ACCEPT,
    maxFiles: 1,
    maxSize: MAX_BYTES,
    onDrop: (accepted, rejected) => {
      if (rejected.length > 0) {
        toast.error("Upload rejected", rejected[0]?.errors[0]?.message ?? "unknown reason");
        return;
      }
      const f = accepted[0];
      if (f) setFile(f);
    },
  });

  const submit = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Pick a file first.");
      return client.transcripts.create({
        file,
        filename: file.name,
        profileId,
        targetId,
        ...(templateKey ? { targetTemplateKey: templateKey } : {}),
        ...(idempotencyKey ? { idempotencyKey } : {}),
      });
    },
    onSuccess: (resp) => {
      toast.success("Job " + resp.job.status, summarizeResponse(resp));
      navigate(`/jobs/${resp.job.id}`);
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast.error("Submission failed", msg);
    },
  });

  const profileOptions = useMemo(
    () => [
      { value: "pl.lo.swiadectwo_szkolne.v1", label: "Polish ŚWIADECTWO (LO) v1" },
    ],
    [],
  );

  const targetOptions = targets.map((t) => ({
    value: t.target_id,
    label: `${t.name} (${t.target_id})`,
  }));

  const templateOptions = useMemo(() => {
    if (!target) return [{ value: "", label: "Auto-select by year" }];
    return [
      { value: "", label: "Auto-select by year" },
      ...target.templates.map((t) => ({ value: t.key, label: t.key })),
    ];
  }, [target]);

  return (
    <>
      <PageHeader
        title="Process transcript"
        description="Upload a PDF or image; the pipeline runs synchronously and returns the canonical extraction plus a downloadable Excel."
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Source document</CardTitle>
            <CardDescription>
              Up to 25 MB · PDF, PNG, JPEG, WebP, TIFF.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div
              {...dropzone.getRootProps()}
              data-testid="dropzone"
              className={cn(
                "border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors",
                dropzone.isDragActive
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/40",
                file && "border-success/40 bg-success/5",
              )}
            >
              <input {...dropzone.getInputProps()} aria-label="upload file" />
              {file ? (
                <div className="flex items-center justify-center gap-3">
                  <FileCheck className="text-success" size={24} />
                  <div className="text-left">
                    <p className="text-sm font-medium">{file.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatBytes(file.size)} · {file.type || "unknown"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setFile(null);
                    }}
                    className="ml-2 p-1.5 rounded-full hover:bg-muted"
                    aria-label="remove"
                  >
                    <X size={14} />
                  </button>
                </div>
              ) : (
                <>
                  <FileUp className="mx-auto text-muted-foreground" size={28} aria-hidden />
                  <p className="mt-3 text-sm font-medium">
                    Drag a transcript here or click to choose.
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Single file · max 25 MB. Magic-byte validated server-side.
                  </p>
                </>
              )}
            </div>
          </CardContent>

          <CardFooter className="flex justify-between flex-wrap gap-3">
            <p className="text-xs text-muted-foreground inline-flex items-center gap-1.5">
              <AlertTriangle size={12} className="text-warning" />
              Sync extract — long PDFs may take 5–30s.
            </p>
            <Button
              size="lg"
              loading={submit.isPending}
              onClick={() => submit.mutate()}
              disabled={!file}
            >
              <Sparkles size={14} />
              {submit.isPending ? "Extracting…" : "Extract & render"}
            </Button>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Routing</CardTitle>
            <CardDescription>
              Profile → target template + optional idempotency key.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="profile">Source profile</Label>
              <Select
                id="profile"
                value={profileId}
                onChange={(e) => setProfileId(e.target.value)}
                options={profileOptions}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="target">Target system</Label>
              <Select
                id="target"
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                options={
                  targetOptions.length > 0
                    ? targetOptions
                    : [{ value: targetId, label: targetId }]
                }
                disabled={templates.isLoading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="template-key">Template (optional)</Label>
              <Select
                id="template-key"
                value={templateKey}
                onChange={(e) => setTemplateKey(e.target.value)}
                options={templateOptions}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="idempotency-key">Idempotency key (optional)</Label>
              <Input
                id="idempotency-key"
                placeholder="ux-batch-2026-04-01-001"
                value={idempotencyKey}
                onChange={(e) => setIdempotencyKey(e.target.value)}
              />
              <p className="text-[11px] text-muted-foreground">
                Same key + same body within 24h replays the cached response.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {submit.data && <ExtractionPreview data={submit.data} />}
    </>
  );
}

function ExtractionPreview({ data }: { data: TranscriptExtractionResponse }) {
  return (
    <Card className="mt-6">
      <CardHeader className="flex-row items-center gap-2 flex">
        <CardTitle>Last extraction</CardTitle>
        <StatusBadge status={data.job.status} />
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <Field label="Confidence" value={`${(data.overall_confidence * 100).toFixed(1)}%`} />
          <Field label="Tokens (in)" value={data.job.tokens_input.toLocaleString()} />
          <Field label="Tokens (out)" value={data.job.tokens_output.toLocaleString()} />
          <Field label="Cost" value={`$${data.job.usd_cost.toFixed(4)}`} />
        </div>
        {data.warnings.length > 0 && (
          <div className="mt-5 space-y-1.5">
            <p className="text-xs font-medium text-warning">Warnings</p>
            <ul className="text-sm text-muted-foreground list-disc pl-5 space-y-0.5">
              {data.warnings.map((w, idx) => (
                <li key={idx}>{w}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-base font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function summarizeResponse(r: TranscriptExtractionResponse): string {
  return `Confidence ${(r.overall_confidence * 100).toFixed(1)}% · ${r.job.tokens_input.toLocaleString()} in / ${r.job.tokens_output.toLocaleString()} out · $${r.job.usd_cost.toFixed(4)}`;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}
