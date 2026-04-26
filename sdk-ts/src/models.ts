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
