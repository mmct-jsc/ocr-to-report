/**
 * OCR-to-Report TypeScript SDK.
 *
 * One default-exported class — `Client` — wraps the v1 REST API. Built
 * on the global `fetch`, so it runs unchanged in Node 20+, the
 * browser, Cloudflare Workers, and Deno.
 *
 * Usage:
 *
 *     import { Client } from "@ocr-to-report/sdk";
 *     const client = new Client({
 *         baseUrl: "https://api.example.com",
 *         apiKey: "sk_live_..."
 *     });
 *     const resp = await client.transcripts.create({
 *         file: new Blob([bytes], { type: "image/png" }),
 *         filename: "transcript.png",
 *         profileId: "pl.lo.swiadectwo_szkolne.v1",
 *         targetId: "us-hs.v1",
 *     });
 */

import { fromResponse, type ProblemDetail, SDKError } from "./errors.js";
import type {
  BatchAcceptedResponse,
  AdminApiKeySummary,
  ApiKeyIssueRequest,
  ApiKeyIssueResponse,
  AuditEntrySummary,
  JobSummary,
  SystemOverview,
  TemplatesResponse,
  TenantCreateRequest,
  TenantSummary,
  TenantUpdateRequest,
  TranscriptExtractionResponse,
  UsageResponse,
  WebhookCreateResponse,
  WebhookSummary,
} from "./models.js";

export interface ClientOptions {
  baseUrl: string;
  apiKey: string;
  timeoutMs?: number;
  /**
   * If set, sends `X-Acting-Tenant-Id` on every request. Requires the
   * key to have the `admin:*` scope. The server swaps the tenant
   * context for tenant-scoped endpoints (jobs, transcripts, webhooks,
   * dsr, usage) and audits the impersonation on the target tenant.
   * Set to `null` to clear; not sent when undefined.
   */
  actingTenantId?: string | null;
  /** Optional fetch implementation — useful for tests + non-global-fetch runtimes. */
  fetchImpl?: typeof fetch;
}

const DEFAULT_TIMEOUT_MS = 60_000;

interface CallOptions {
  method: string;
  path: string;
  body?: BodyInit | null;
  headers?: Record<string, string>;
  query?: Record<string, string | number | undefined>;
}

/**
 * Synchronous-feeling typed client for the REST API.
 *
 * Every method maps 1:1 to a v1 endpoint. Errors throw a typed
 * `SDKError` subclass; callers narrow with `instanceof`.
 */
export class Client {
  public readonly transcripts: TranscriptsResource;
  public readonly jobs: JobsResource;
  public readonly webhooks: WebhooksResource;
  public readonly usage: UsageResource;
  public readonly templates: TemplatesResource;
  public readonly admin: AdminResource;

  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;
  private actingTenantId: string | null;

  constructor(options: ClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.actingTenantId = options.actingTenantId ?? null;
    // Bind ``fetch`` to its host (``window`` / ``globalThis``) so the
    // browser's "Illegal invocation" check doesn't trip when we later
    // invoke it as a free function via ``this.fetchImpl(...)``.
    this.fetchImpl =
      options.fetchImpl ?? ((input, init) => fetch(input, init));
    this.transcripts = new TranscriptsResource(this);
    this.jobs = new JobsResource(this);
    this.webhooks = new WebhooksResource(this);
    this.usage = new UsageResource(this);
    this.admin = new AdminResource(this);
    this.templates = new TemplatesResource(this);
  }

  /**
   * Update the impersonation header without rebuilding the Client. Pass
   * `null` to clear. Useful when an admin UI swaps tenant context.
   */
  public setActingTenantId(id: string | null): void {
    this.actingTenantId = id;
  }

  /** @internal */
  public async _call(options: CallOptions): Promise<Response> {
    // Support both absolute baseUrls ("https://api.example.com") and
    // relative ones ("/api") used by browsers behind a same-origin
    // proxy. `URL` requires an absolute base, so when ours is relative
    // we anchor it to `window.location.origin` (or a sentinel host
    // server-side, where the relative case shouldn't happen anyway).
    const fullPath = this.baseUrl + options.path;
    const isAbsolute = /^https?:\/\//i.test(fullPath);
    const baseAnchor =
      typeof window !== "undefined" && window.location ? window.location.origin : "http://0.0.0.0";
    const url = new URL(fullPath, isAbsolute ? undefined : baseAnchor);
    if (options.query) {
      for (const [k, v] of Object.entries(options.query)) {
        if (v !== undefined) url.searchParams.set(k, String(v));
      }
    }
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      "User-Agent": "ocr-to-report-ts/0.1",
      ...(this.actingTenantId ? { "X-Acting-Tenant-Id": this.actingTenantId } : {}),
      ...options.headers,
    };
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(url.toString(), {
        method: options.method,
        headers,
        body: options.body ?? null,
        signal: ctrl.signal,
      });
    } finally {
      clearTimeout(timeout);
    }
    if (!response.ok) {
      let body: ProblemDetail | null = null;
      try {
        const ct = response.headers.get("content-type") ?? "";
        if (ct.includes("application/")) {
          body = (await response.json()) as ProblemDetail;
        }
      } catch {
        body = null;
      }
      throw fromResponse({
        status: response.status,
        body,
        requestId: response.headers.get("x-request-id"),
      });
    }
    return response;
  }
}

// ─── Resources ───────────────────────────────────────────────
class TranscriptsResource {
  constructor(private readonly client: Client) {}

  async create(args: {
    file: Blob;
    filename: string;
    profileId: string;
    targetId: string;
    targetTemplateKey?: string;
    idempotencyKey?: string;
  }): Promise<TranscriptExtractionResponse> {
    const fd = new FormData();
    fd.append("file", args.file, args.filename);
    fd.append("profile_id", args.profileId);
    fd.append("target_id", args.targetId);
    if (args.targetTemplateKey !== undefined) {
      fd.append("target_template_key", args.targetTemplateKey);
    }
    const headers: Record<string, string> = {};
    if (args.idempotencyKey !== undefined) headers["Idempotency-Key"] = args.idempotencyKey;
    const response = await this.client._call({
      method: "POST",
      path: "/v1/transcripts",
      body: fd,
      headers,
    });
    return (await response.json()) as TranscriptExtractionResponse;
  }

  async createBatch(args: {
    files: Array<{ blob: Blob; filename: string }>;
    profileId: string;
    targetId: string;
    targetTemplateKey?: string;
  }): Promise<BatchAcceptedResponse> {
    if (args.files.length === 0) {
      throw new SDKError("at least one file is required");
    }
    const fd = new FormData();
    for (const f of args.files) fd.append("files", f.blob, f.filename);
    fd.append("profile_id", args.profileId);
    fd.append("target_id", args.targetId);
    if (args.targetTemplateKey !== undefined) {
      fd.append("target_template_key", args.targetTemplateKey);
    }
    const response = await this.client._call({
      method: "POST",
      path: "/v1/transcripts:batch",
      body: fd,
    });
    return (await response.json()) as BatchAcceptedResponse;
  }
}

class JobsResource {
  constructor(private readonly client: Client) {}

  async get(jobId: string): Promise<JobSummary> {
    const response = await this.client._call({
      method: "GET",
      path: `/v1/jobs/${jobId}`,
    });
    return (await response.json()) as JobSummary;
  }

  async list(args: { status?: string; limit?: number } = {}): Promise<JobSummary[]> {
    const response = await this.client._call({
      method: "GET",
      path: "/v1/jobs",
      query: { status: args.status, limit: args.limit ?? 100 },
    });
    return (await response.json()) as JobSummary[];
  }

  async getResult(jobId: string): Promise<ArrayBuffer> {
    const response = await this.client._call({
      method: "GET",
      path: `/v1/jobs/${jobId}/result`,
    });
    return await response.arrayBuffer();
  }

  async approve(jobId: string): Promise<JobSummary> {
    const response = await this.client._call({
      method: "POST",
      path: `/v1/jobs/${jobId}/approve`,
    });
    return (await response.json()) as JobSummary;
  }

  async reject(jobId: string, args: { reason?: string } = {}): Promise<JobSummary> {
    const body = args.reason !== undefined ? JSON.stringify({ reason: args.reason }) : "{}";
    const response = await this.client._call({
      method: "POST",
      path: `/v1/jobs/${jobId}/reject`,
      body,
      headers: { "Content-Type": "application/json" },
    });
    return (await response.json()) as JobSummary;
  }
}

class WebhooksResource {
  constructor(private readonly client: Client) {}

  async create(args: { url: string; events: string[] }): Promise<WebhookCreateResponse> {
    const response = await this.client._call({
      method: "POST",
      path: "/v1/webhooks",
      body: JSON.stringify({ url: args.url, events: args.events }),
      headers: { "Content-Type": "application/json" },
    });
    return (await response.json()) as WebhookCreateResponse;
  }

  async list(): Promise<WebhookSummary[]> {
    const response = await this.client._call({
      method: "GET",
      path: "/v1/webhooks",
    });
    return (await response.json()) as WebhookSummary[];
  }
}

class UsageResource {
  constructor(private readonly client: Client) {}

  async get(): Promise<UsageResponse> {
    const response = await this.client._call({
      method: "GET",
      path: "/v1/usage",
    });
    return (await response.json()) as UsageResponse;
  }
}

class TemplatesResource {
  constructor(private readonly client: Client) {}

  async list(): Promise<TemplatesResponse> {
    const response = await this.client._call({
      method: "GET",
      path: "/v1/templates",
    });
    return (await response.json()) as TemplatesResponse;
  }
}

/**
 * Cross-tenant admin endpoints. The Client instance must be holding a
 * key with the `admin:*` scope; otherwise every call here returns 403.
 */
class AdminResource {
  constructor(private readonly client: Client) {}

  async system(): Promise<SystemOverview> {
    const r = await this.client._call({ method: "GET", path: "/v1/admin/system" });
    return (await r.json()) as SystemOverview;
  }

  async listTenants(args: { includeArchived?: boolean } = {}): Promise<TenantSummary[]> {
    const r = await this.client._call({
      method: "GET",
      path: "/v1/admin/tenants",
      query: { include_archived: args.includeArchived ? "true" : undefined },
    });
    return (await r.json()) as TenantSummary[];
  }

  async createTenant(body: TenantCreateRequest): Promise<TenantSummary> {
    const r = await this.client._call({
      method: "POST",
      path: "/v1/admin/tenants",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    });
    return (await r.json()) as TenantSummary;
  }

  async updateTenant(tenantId: string, body: TenantUpdateRequest): Promise<TenantSummary> {
    const r = await this.client._call({
      method: "PATCH",
      path: `/v1/admin/tenants/${tenantId}`,
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    });
    return (await r.json()) as TenantSummary;
  }

  async archiveTenant(tenantId: string): Promise<void> {
    await this.client._call({
      method: "DELETE",
      path: `/v1/admin/tenants/${tenantId}`,
    });
  }

  async listApiKeys(tenantId: string): Promise<AdminApiKeySummary[]> {
    const r = await this.client._call({
      method: "GET",
      path: `/v1/admin/tenants/${tenantId}/api-keys`,
    });
    return (await r.json()) as AdminApiKeySummary[];
  }

  async issueApiKey(
    tenantId: string,
    body: ApiKeyIssueRequest = {},
  ): Promise<ApiKeyIssueResponse> {
    const r = await this.client._call({
      method: "POST",
      path: `/v1/admin/tenants/${tenantId}/api-keys`,
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    });
    return (await r.json()) as ApiKeyIssueResponse;
  }

  async revokeApiKey(apiKeyId: string): Promise<void> {
    await this.client._call({
      method: "DELETE",
      path: `/v1/admin/api-keys/${apiKeyId}`,
    });
  }

  async tenantAudit(
    tenantId: string,
    args: { limit?: number } = {},
  ): Promise<AuditEntrySummary[]> {
    const r = await this.client._call({
      method: "GET",
      path: `/v1/admin/tenants/${tenantId}/audit`,
      query: { limit: args.limit ?? 100 },
    });
    return (await r.json()) as AuditEntrySummary[];
  }
}
