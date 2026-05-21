import { useState } from "react";
import {
  Copy,
  FileSpreadsheet,
  Gauge,
  KeyRound,
  RefreshCw,
  Server,
  Settings as SettingsIcon,
  Sparkles,
  Workflow,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/toast";
import { useTheme } from "@/lib/theme";
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
import { Tabs, TabsList, TabsPanel, TabsTrigger } from "@/components/ui/tabs";
import { PipelineTab } from "@/components/settings-tabs/pipeline-tab";
import { SlaTab } from "@/components/settings-tabs/sla-tab";
import { TemplatesTab } from "@/components/settings-tabs/templates-tab";
import { VocabularyTab } from "@/components/settings-tabs/vocabulary-tab";

type SettingsTabId = "general" | "pipeline" | "sla" | "templates" | "vocabulary";

export function SettingsRoute() {
  const [tab, setTab] = useState<SettingsTabId>("general");

  return (
    <>
      <PageHeader
        title="Settings"
        description="Connection details, per-tenant pipeline + SLA overrides, theme."
      />

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as SettingsTabId)}
        idPrefix="settings"
      >
        <TabsList>
          <TabsTrigger value="general">
            <span className="inline-flex items-center gap-1.5">
              <SettingsIcon size={14} aria-hidden /> General
            </span>
          </TabsTrigger>
          <TabsTrigger value="pipeline">
            <span className="inline-flex items-center gap-1.5">
              <Workflow size={14} aria-hidden /> Pipeline
            </span>
          </TabsTrigger>
          <TabsTrigger value="sla">
            <span className="inline-flex items-center gap-1.5">
              <Gauge size={14} aria-hidden /> SLA
            </span>
          </TabsTrigger>
          <TabsTrigger value="templates">
            <span className="inline-flex items-center gap-1.5">
              <FileSpreadsheet size={14} aria-hidden /> Templates
            </span>
          </TabsTrigger>
          <TabsTrigger value="vocabulary">
            <span className="inline-flex items-center gap-1.5">
              <Sparkles size={14} aria-hidden /> Vocabulary
            </span>
          </TabsTrigger>
        </TabsList>

        <TabsPanel value="general">
          <GeneralTab />
        </TabsPanel>
        <TabsPanel value="pipeline">
          <PipelineTab />
        </TabsPanel>
        <TabsPanel value="sla">
          <SlaTab />
        </TabsPanel>
        <TabsPanel value="templates">
          <TemplatesTab />
        </TabsPanel>
        <TabsPanel value="vocabulary">
          <VocabularyTab />
        </TabsPanel>
      </Tabs>
    </>
  );
}

function GeneralTab() {
  const { apiKey, baseUrl, signIn } = useAuth();
  const toast = useToast();
  const { theme, set } = useTheme();
  const [draftUrl, setDraftUrl] = useState(baseUrl);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server size={16} aria-hidden /> API endpoint
          </CardTitle>
          <CardDescription>
            The base URL the SDK posts to. Behind the Vite dev proxy this is{" "}
            <code className="font-mono">/api</code>; in production it's the public REST
            host.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Label htmlFor="base-url-edit">Base URL</Label>
          <Input
            id="base-url-edit"
            value={draftUrl}
            onChange={(e) => setDraftUrl(e.target.value)}
            className="mt-1.5"
          />
        </CardContent>
        <CardFooter>
          <Button
            variant="outline"
            onClick={() => {
              if (apiKey) {
                signIn(apiKey, draftUrl);
                toast.success("Saved", "Base URL updated.");
              } else {
                toast.error("Sign in first");
              }
            }}
          >
            <RefreshCw size={14} aria-hidden /> Save
          </Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound size={16} aria-hidden /> API key
          </CardTitle>
          <CardDescription>
            Signed-in token, hashed on the server with Argon2id. Stored client-side in{" "}
            <code className="font-mono">localStorage</code>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <code className="font-mono text-xs bg-muted rounded px-3 py-2 block break-all">
            {apiKey ? mask(apiKey) : "—"}
          </code>
        </CardContent>
        <CardFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              if (apiKey) {
                await navigator.clipboard.writeText(apiKey);
                toast.info("Copied API key");
              }
            }}
          >
            <Copy size={14} aria-hidden /> Copy
          </Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>Toggle between light and dark.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <Button
              variant={theme === "light" ? "primary" : "outline"}
              onClick={() => set("light")}
            >
              Light
            </Button>
            <Button
              variant={theme === "dark" ? "primary" : "outline"}
              onClick={() => set("dark")}
            >
              Dark
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>About</CardTitle>
          <CardDescription>OCR-to-Report Operations Console</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-1">
          <p>
            Version <span className="font-mono">v0.2.0</span>
          </p>
          <p>
            Vite + React 18 + Tailwind. Driven by{" "}
            <code className="font-mono">@ocr-to-report/sdk</code>.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function mask(s: string): string {
  if (s.length <= 12) return s;
  return `${s.slice(0, 8)}…${s.slice(-4)}`;
}
