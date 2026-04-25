/**
 * Typed exception hierarchy for SDK callers.
 *
 * Every HTTP error from the API is mapped to one of these classes
 * based on the response's `problem+json` `status`. The raw response
 * body is preserved on the error for callers that want to introspect
 * field-level validation details.
 */

export interface ProblemDetail {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  [key: string]: unknown;
}

export class SDKError extends Error {
  public readonly status: number | null;
  public readonly body: ProblemDetail | null;
  public readonly requestId: string | null;

  constructor(
    message: string,
    options: {
      status?: number | null;
      body?: ProblemDetail | null;
      requestId?: string | null;
    } = {},
  ) {
    super(message);
    this.name = this.constructor.name;
    this.status = options.status ?? null;
    this.body = options.body ?? null;
    this.requestId = options.requestId ?? null;
  }
}

export class BadRequestError extends SDKError {}
export class AuthenticationError extends SDKError {}
export class ForbiddenError extends SDKError {}
export class NotFoundError extends SDKError {}
export class ConflictError extends SDKError {}
export class PayloadTooLargeError extends SDKError {}
export class RateLimitedError extends SDKError {}
export class ServerError extends SDKError {}

const STATUS_MAP: Record<number, typeof SDKError> = {
  400: BadRequestError,
  401: AuthenticationError,
  403: ForbiddenError,
  404: NotFoundError,
  409: ConflictError,
  413: PayloadTooLargeError,
  429: RateLimitedError,
};

export function fromResponse(args: {
  status: number;
  body: ProblemDetail | null;
  requestId: string | null;
}): SDKError {
  const Cls = STATUS_MAP[args.status] ?? (args.status >= 500 ? ServerError : SDKError);
  const detail = args.body?.detail ?? args.body?.title ?? "";
  const message = detail !== "" ? String(detail) : `HTTP ${args.status}`;
  return new Cls(message, {
    status: args.status,
    body: args.body,
    requestId: args.requestId,
  });
}
