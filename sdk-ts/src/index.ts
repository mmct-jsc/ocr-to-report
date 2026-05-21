/**
 * Public surface of `@ocr-to-report/sdk`.
 *
 * Single entry point — re-exports the `Client` plus all response models
 * and the typed error hierarchy. Callers narrow errors with `instanceof`.
 */

export { Client, type ClientOptions } from "./client.js";
export {
  AuthenticationError,
  BadRequestError,
  ConflictError,
  ForbiddenError,
  fromResponse,
  NotFoundError,
  PayloadTooLargeError,
  type ProblemDetail,
  RateLimitedError,
  SDKError,
  ServerError,
} from "./errors.js";
export type {
  AdminApiKeySummary,
  ApiKeyIssueRequest,
  ApiKeyIssueResponse,
  AuditEntrySummary,
  BatchAcceptedResponse,
  CustomTemplateResponse,
  JobSummary,
  OverridePatch,
  ProviderId,
  ProviderStatus,
  ProviderUpsertRequest,
  ProvidersListResponse,
  SystemOverview,
  TargetInfo,
  TemplateInfo,
  TemplatesResponse,
  TenantConfigResponse,
  TenantConfigUpdate,
  TenantCreateRequest,
  TenantSummary,
  TenantUpdateRequest,
  TranscriptExtractionResponse,
  UsageResponse,
  WebhookCreateResponse,
  WebhookSummary,
} from "./models.js";
