import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Webhook as WebhookIcon, Copy, EyeOff, Eye } from "lucide-react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";

const ALL_EVENTS = ["job.completed", "job.failed", "job.parked"];

export function WebhooksRoute() {
  const client = useClient();
  const qc = useQueryClient();
  const toast = useToast();

  const [url, setUrl] = useState("");
  const [selected, setSelected] = useState<string[]>(["job.completed"]);
  const [createdSecret, setCreatedSecret] = useState<{ id: string; secret: string } | null>(
    null,
  );
  const [secretShown, setSecretShown] = useState(false);

  const list = useQuery({
    queryKey: ["webhooks"],
    queryFn: () => client.webhooks.list(),
  });

  const create = useMutation({
    mutationFn: () => client.webhooks.create({ url, events: selected }),
    onSuccess: (resp) => {
      toast.success("Webhook created", "Save the signing secret — it isn't returned again.");
      setCreatedSecret({ id: resp.id, secret: resp.signing_secret });
      setSecretShown(true);
      setUrl("");
      setSelected(["job.completed"]);
      qc.invalidateQueries({ queryKey: ["webhooks"] });
    },
    onError: (e) => toast.error("Create failed", e instanceof Error ? e.message : "unknown"),
  });

  const toggleEvent = (ev: string) =>
    setSelected((cur) => (cur.includes(ev) ? cur.filter((e) => e !== ev) : [...cur, ev]));

  return (
    <>
      <PageHeader
        title="Webhooks"
        description="Subscribe to job lifecycle events; payloads are HMAC-signed with the per-webhook secret."
      />

      {createdSecret && (
        <Card className="mb-4 border-success/30 bg-success/5">
          <CardHeader>
            <CardTitle className="text-success">Signing secret</CardTitle>
            <CardDescription>
              Copy this now — it is only returned once.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-2 flex-wrap">
            <code className="font-mono text-xs bg-card border border-border rounded px-3 py-2 break-all flex-1 min-w-0">
              {secretShown ? createdSecret.secret : "•".repeat(64)}
            </code>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSecretShown((v) => !v)}
            >
              {secretShown ? <EyeOff size={14} /> : <Eye size={14} />}
              {secretShown ? "Hide" : "Reveal"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                await navigator.clipboard.writeText(createdSecret.secret);
                toast.info("Copied secret");
              }}
            >
              <Copy size={14} /> Copy
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCreatedSecret(null)}
            >
              Dismiss
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Active subscriptions</CardTitle>
            <CardDescription>
              {list.data?.length ?? 0} subscription
              {list.data && list.data.length === 1 ? "" : "s"} for this tenant.
            </CardDescription>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            {list.isLoading ? (
              <div className="px-5 pb-5 space-y-2">
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
              </div>
            ) : list.data && list.data.length > 0 ? (
              <ul className="divide-y divide-border">
                {list.data.map((w) => (
                  <li key={w.id} className="px-5 py-4 flex items-start gap-3">
                    <div className="rounded-md bg-muted p-2">
                      <WebhookIcon size={16} className="text-muted-foreground" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{w.url}</p>
                      <div className="mt-1 flex gap-1.5 flex-wrap">
                        {w.events.map((ev) => (
                          <Badge key={ev} tone="info">
                            {ev}
                          </Badge>
                        ))}
                      </div>
                      {w.last_delivered_at && (
                        <p className="text-xs text-muted-foreground mt-1">
                          Last delivery: {new Date(w.last_delivered_at).toLocaleString()} (
                          {w.last_delivery_status ?? "—"})
                        </p>
                      )}
                    </div>
                    <Badge tone={w.active ? "success" : "neutral"}>
                      {w.active ? "active" : "paused"}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={WebhookIcon}
                title="No webhooks yet"
                description="Add a receiver URL on the right to subscribe to job events."
                className="m-5"
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Add subscription</CardTitle>
            <CardDescription>HMAC-SHA256 signed POST per event.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="hook-url">Receiver URL</Label>
              <Input
                id="hook-url"
                type="url"
                placeholder="https://hooks.example.com/ocr"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Events</Label>
              <div className="space-y-1">
                {ALL_EVENTS.map((ev) => (
                  <label
                    key={ev}
                    className="flex items-center gap-2 text-sm cursor-pointer rounded-md px-2 py-1 hover:bg-muted"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(ev)}
                      onChange={() => toggleEvent(ev)}
                      className="rounded border-border accent-primary"
                    />
                    <span className="font-mono">{ev}</span>
                  </label>
                ))}
              </div>
            </div>
          </CardContent>
          <CardFooter>
            <Button
              onClick={() => create.mutate()}
              loading={create.isPending}
              disabled={!url || selected.length === 0}
            >
              <Plus size={14} /> Create
            </Button>
          </CardFooter>
        </Card>
      </div>
    </>
  );
}
