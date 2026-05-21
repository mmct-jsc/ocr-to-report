/**
 * Response models for the SDK.
 *
 * These mirror the API's Pydantic schemas. Dates arrive as ISO 8601
 * strings; we leave the parsing to callers (Date construction is a
 * personal preference and the raw string is more cache-friendly).
 */

export interface JobSummary {
  id: string;
  status: string;
  profile_id: string | null;
  target_id: string | null;
  target_template_key: string | null;
  pipeline_id: string;
  provider_used: string | null;
  model_id_used: string | null;
  tokens_input: number;
  tokens_output: number;
  usd_cost: number;
  error_detail: string | null;
  park_reason: string | null;
  output_blob_key: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  expires_at: string | null;
}

export interface TranscriptExtractionResponse {
  job: JobSummary;
  extraction: Record<string, unknown>;
  overall_confidence: number;
  warnings: string[];
}

export interface BatchAcceptedResponse {
  jobs: JobSummary[];
  accepted_count: number;
  rejected: string[];
}

export interface WebhookCreateResponse {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  signing_secret: string;
}

export interface WebhookSummary {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  last_delivery_status: string | null;
  last_delivered_at: string | null;
}

export interface UsageResponse {
  period_start: string;
  period_end: string;
  transcripts_processed: number;
  tokens_input: number;
  tokens_output: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  usd_cost: number;
}

export interface TemplateInfo {
  key: string;
  output_format: string;
  target_year_index: number;
}

export interface TargetInfo {
  target_id: string;
  name: string;
  version: string;
  output_language: string;
  output_formats: string[];
  templates: TemplateInfo[];
}

export interface TemplatesResponse {
  targets: TargetInfo[];
}

/**
 * Server response for ``POST /v1/templates/{target_id}/{template_key}``.
 *
 * The ``blob_key`` is the storage key the server picked — it embeds the
 * upload's sha256, so re-uploading the same bytes is idempotent at the
 * blob layer. The web UI doesn't need to interpret it; it's surfaced
 * for support diagnostics.
 */
export interface CustomTemplateResponse {
  target_id: string;
  template_key: string;
  blob_key: string;
  sha256: string;
  size_bytes: number;
}

// ─── Tenant config (override patches) ────────────────────────
/**
 * One DB-wire-format patch. The server's resolver validates ``op`` is
 * one of the known operations and ``path`` is a non-empty string;
 * deeper validation happens lazily at apply time.
 */
export interface OverridePatch {
  op: "set" | "delete" | "append" | "merge";
  path: string;
  value?: unknown;
}

/**
 * Replacement body for ``PUT /v1/tenant/config`` and ``POST
 * /v1/tenant/config:preview``.
 *
 * Every field is optional — sending ``{ sla_patches: [...] }`` replaces
 * JUST the SLA patches and leaves profile/target rows alone. To clear a
 * scope, send an explicit empty list.
 */
export interface TenantConfigUpdate {
  /**
   * Replacement pipeline id (e.g., ``default_v1``,
   * ``with_manual_review_v1``, ``batch_economy_v1``). Direct write to the
   * tenant column — not a patch list. Omit to leave unchanged.
   */
  pipeline_id?: string | null;
  sla_patches?: OverridePatch[] | null;
  profile_overrides?: Record<string, OverridePatch[]> | null;
  target_overrides?: Record<string, OverridePatch[]> | null;
}

/**
 * Resolved view returned by ``GET /v1/tenant/config`` and
 * ``POST /v1/tenant/config:preview``.
 *
 * ``sla`` is the tier preset with any ``sla_patches`` applied. The
 * raw patch lists are surfaced alongside so the UI can render its
 * diff editor without re-deriving from the resolved view.
 */
export interface TenantConfigResponse {
  sla: Record<string, unknown>;
  pipeline_id: string;
  sla_patches: OverridePatch[];
  profile_overrides: Record<string, OverridePatch[]>;
  target_overrides: Record<string, OverridePatch[]>;
}

// ─── Tenant providers (BYOK, v0.3.0) ─────────────────────────
/**
 * Stable provider identifier. v0.3.0 only routes "anthropic"; the
 * other three are accepted-but-deferred to v0.7.0 (PUT returns 501).
 */
export type ProviderId = "anthropic" | "openai" | "google_vertex" | "tesseract";

/**
 * One redacted credential row.
 *
 * ``api_key_redacted`` is never the plaintext: the PUT response carries
 * the last-4 form ("sk-ant-…XYZ1") for confirmation; the GET list uses
 * a fixed placeholder ("sk-ant-…••••") so a poll doesn't have to
 * unwrap the DEK on every read.
 */
export interface ProviderStatus {
  provider: ProviderId;
  active: boolean;
  api_key_redacted: string | null;
  region: string | null;
  rotated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Response body for ``GET /v1/tenant/providers``. */
export interface ProvidersListResponse {
  providers: ProviderStatus[];
}

/** Request body for ``PUT /v1/tenant/providers/{provider}``. */
export interface ProviderUpsertRequest {
  api_key: string;
  model_overrides?: Record<string, string> | null;
  region?: string | null;
}

// ─── Admin ───────────────────────────────────────────────────
export interface TenantSummary {
  id: string;
  name: string;
  slug: string;
  sla_tier: string;
  region_pin: string | null;
  default_target_system: string | null;
  pipeline_id: string;
  created_at: string;
  archived_at: string | null;
}

export interface TenantCreateRequest {
  name: string;
  slug: string;
  sla_tier?: "economy" | "standard" | "premium" | "enterprise";
  region_pin?: string | null;
  default_target_system?: string | null;
  pipeline_id?: string;
}

export interface TenantUpdateRequest {
  name?: string;
  sla_tier?: "economy" | "standard" | "premium" | "enterprise";
  region_pin?: string | null;
  default_target_system?: string | null;
  pipeline_id?: string;
}

export interface AdminApiKeySummary {
  id: string;
  tenant_id: string;
  prefix: string;
  label: string | null;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  expires_at: string | null;
}

export interface ApiKeyIssueRequest {
  label?: string | null;
  scopes?: string[];
  live?: boolean;
}

export interface ApiKeyIssueResponse {
  api_key: AdminApiKeySummary;
  secret: string;
}

export interface AuditEntrySummary {
  id: string;
  ts: string;
  actor_type: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  metadata: Record<string, unknown>;
}

export interface SystemOverview {
  tenants_total: number;
  tenants_active: number;
  api_keys_active: number;
  profiles_loaded: string[];
  targets_loaded: string[];
  sla_presets: string[];
  queue_depth: number;
  api_version: string;
}
