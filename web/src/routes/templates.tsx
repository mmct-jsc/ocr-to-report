import { useQuery } from "@tanstack/react-query";
import { BookTemplate, FileSpreadsheet } from "lucide-react";
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
import { EmptyState } from "@/components/ui/empty";

export function TemplatesRoute() {
  const client = useClient();
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: () => client.templates.list(),
  });

  return (
    <>
      <PageHeader
        title="Templates"
        description="Target systems and the templates each ships. Add a target = drop a YAML bundle, no code changes."
      />

      {templates.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      ) : templates.data && templates.data.targets.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2">
          {templates.data.targets.map((t) => (
            <Card key={t.target_id}>
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle>{t.name}</CardTitle>
                  <Badge tone="info">v{t.version}</Badge>
                </div>
                <CardDescription>
                  <span className="font-mono">{t.target_id}</span> · output{" "}
                  {t.output_language.toUpperCase()} ·{" "}
                  {t.output_formats.map((f) => f.toUpperCase()).join(", ")}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
                  Templates ({t.templates.length})
                </p>
                <ul className="space-y-1.5">
                  {t.templates.map((tpl) => (
                    <li
                      key={tpl.key}
                      className="flex items-center gap-3 text-sm rounded-md border border-border px-3 py-2 surface-hover"
                    >
                      <FileSpreadsheet
                        size={14}
                        className="text-muted-foreground shrink-0"
                      />
                      <span className="font-medium">{tpl.key}</span>
                      <span className="text-xs text-muted-foreground">
                        target year {tpl.target_year_index}
                      </span>
                      <span className="ml-auto font-mono text-xs">
                        .{tpl.output_format}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={BookTemplate}
          title="No targets registered"
          description="Drop a target bundle into ./targets/<target-id>/ and restart the API."
        />
      )}
    </>
  );
}
