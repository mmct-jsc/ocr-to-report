/**
 * `@ocr-to-report/sdk` — client tests.
 *
 * These don't talk to a real server. We inject a custom `fetchImpl`
 * that records the request + emits canned responses. The goal is to
 * verify URL composition, header defaults, body shape, and the error
 * mapping table.
 */

import { describe, expect, it } from "vitest";

import { AuthenticationError, ConflictError, NotFoundError, ServerError } from "../src/errors.js";
import { Client } from "../src/client.js";

interface RecordedCall {
  url: string;
  method: string;
  headers: Headers;
  body: BodyInit | null;
}

function makeFakeFetch(
  responder: (call: RecordedCall) => Response | Promise<Response>,
): { fetch: typeof fetch; calls: RecordedCall[] } {
  const calls: RecordedCall[] = [];
  const fakeFetch: typeof fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    const recorded: RecordedCall = {
      url,
      method: init?.method ?? "GET",
      headers: new Headers(init?.headers ?? {}),
      body: init?.body ?? null,
    };
    calls.push(recorded);
    return await responder(recorded);
  };
  return { fetch: fakeFetch, calls };
}

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);

function makeJobSummary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    status: "succeeded",
    profile_id: "pl.lo.swiadectwo_szkolne.v1",
    target_id: "us-hs.v1",
    target_template_key: null,
    pipeline_id: "default_v1",
    provider_used: "anthropic",
    model_id_used: "claude-haiku-4-5",
    tokens_input: 1500,
    tokens_output: 300,
    usd_cost: 0.003,
    error_detail: null,
    park_reason: null,
    output_blob_key: "jobs/x/output.xlsx",
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
    completed_at: "2026-04-01T00:00:00Z",
    expires_at: null,
    ...overrides,
  };
}

describe("Client.transcripts.create", () => {
  it("posts a multipart body with auth + form fields", async () => {
    const job = makeJobSummary();
    const fake = makeFakeFetch(async () =>
      new Response(
        JSON.stringify({
          job,
          extraction: { student: { full_name: "Jan" } },
          overall_confidence: 0.95,
          warnings: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const client = new Client({
      baseUrl: "http://test/",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });

    const blob = new Blob([PNG], { type: "image/png" });
    const resp = await client.transcripts.create({
      file: blob,
      filename: "t.png",
      profileId: "pl.lo.swiadectwo_szkolne.v1",
      targetId: "us-hs.v1",
      idempotencyKey: "abc-123",
    });

    expect(resp.job.status).toBe("succeeded");
    expect(resp.overall_confidence).toBe(0.95);

    expect(fake.calls).toHaveLength(1);
    const call = fake.calls[0]!;
    expect(call.method).toBe("POST");
    expect(call.url).toBe("http://test/v1/transcripts");
    expect(call.headers.get("authorization")).toBe("Bearer sk_test");
    expect(call.headers.get("idempotency-key")).toBe("abc-123");
    expect(call.body).toBeInstanceOf(FormData);
  });
});

describe("Client.transcripts.createBatch", () => {
  it("packs multiple files into a single FormData", async () => {
    const fake = makeFakeFetch(async () =>
      new Response(
        JSON.stringify({
          jobs: [makeJobSummary({ status: "pending" }), makeJobSummary({ status: "pending" })],
          accepted_count: 2,
          rejected: [],
        }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      ),
    );

    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });

    const resp = await client.transcripts.createBatch({
      files: [
        { blob: new Blob([PNG], { type: "image/png" }), filename: "a.png" },
        { blob: new Blob([PNG], { type: "image/png" }), filename: "b.png" },
      ],
      profileId: "pl.lo.swiadectwo_szkolne.v1",
      targetId: "us-hs.v1",
    });
    expect(resp.accepted_count).toBe(2);
    expect(fake.calls[0]!.url).toBe("http://test/v1/transcripts:batch");
  });

  it("rejects an empty batch synchronously", async () => {
    const fake = makeFakeFetch(async () => new Response("", { status: 400 }));
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    await expect(
      client.transcripts.createBatch({
        files: [],
        profileId: "p",
        targetId: "t",
      }),
    ).rejects.toThrow(/at least one file/);
    expect(fake.calls).toHaveLength(0);
  });
});

describe("Client.jobs", () => {
  it("get + list compose URLs and query params correctly", async () => {
    const fake = makeFakeFetch(async (call) => {
      if (call.url.endsWith("/v1/jobs/abc")) {
        return new Response(JSON.stringify(makeJobSummary({ id: "abc" })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify([makeJobSummary({ status: "parked" })]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    await client.jobs.get("abc");
    await client.jobs.list({ status: "parked", limit: 50 });

    expect(fake.calls[0]!.url).toBe("http://test/v1/jobs/abc");
    expect(fake.calls[1]!.url).toBe("http://test/v1/jobs?status=parked&limit=50");
  });

  it("approve + reject hit the right paths and pass reason", async () => {
    const fake = makeFakeFetch(async (call) => {
      if (call.url.endsWith("/approve")) {
        return new Response(JSON.stringify(makeJobSummary({ status: "succeeded" })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(makeJobSummary({ status: "failed" })), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    await client.jobs.approve("abc");
    await client.jobs.reject("abc", { reason: "blurry" });

    expect(fake.calls[0]!.method).toBe("POST");
    expect(fake.calls[0]!.url).toBe("http://test/v1/jobs/abc/approve");
    expect(fake.calls[1]!.url).toBe("http://test/v1/jobs/abc/reject");
    const rejectBody = await new Response(fake.calls[1]!.body as BodyInit).text();
    expect(rejectBody).toBe(JSON.stringify({ reason: "blurry" }));
  });

  it("getResult returns raw bytes", async () => {
    const fake = makeFakeFetch(async () =>
      new Response(new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]), {
        status: 200,
        headers: {
          "Content-Type":
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
      }),
    );
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    const buf = await client.jobs.getResult("abc");
    const view = new Uint8Array(buf);
    expect(view[0]).toBe(0x50);
    expect(view[1]).toBe(0x4b);
  });
});

describe("Client error mapping", () => {
  it("401 → AuthenticationError", async () => {
    const fake = makeFakeFetch(async () =>
      new Response(
        JSON.stringify({
          type: "https://errors.ocr-to-report/unauthorized",
          title: "Authentication required",
          status: 401,
          detail: "missing bearer token",
        }),
        { status: 401, headers: { "Content-Type": "application/problem+json" } },
      ),
    );
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "bad",
      fetchImpl: fake.fetch,
    });
    await expect(client.usage.get()).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("404 → NotFoundError carrying the body", async () => {
    const fake = makeFakeFetch(async () =>
      new Response(
        JSON.stringify({ status: 404, title: "not found", detail: "no such job" }),
        { status: 404, headers: { "Content-Type": "application/problem+json" } },
      ),
    );
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    try {
      await client.jobs.get("xyz");
      expect.fail("expected NotFoundError");
    } catch (err) {
      expect(err).toBeInstanceOf(NotFoundError);
      const e = err as NotFoundError;
      expect(e.status).toBe(404);
      expect(e.body?.detail).toBe("no such job");
    }
  });

  it("409 → ConflictError, 500 → ServerError", async () => {
    let nextStatus = 409;
    const fake = makeFakeFetch(async () =>
      new Response(JSON.stringify({ status: nextStatus, title: "x" }), {
        status: nextStatus,
        headers: { "Content-Type": "application/problem+json" },
      }),
    );
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    await expect(client.jobs.approve("a")).rejects.toBeInstanceOf(ConflictError);

    nextStatus = 500;
    await expect(client.jobs.approve("a")).rejects.toBeInstanceOf(ServerError);
  });
});

describe("Templates / Usage / Webhooks", () => {
  it("templates.list", async () => {
    const fake = makeFakeFetch(async () =>
      new Response(
        JSON.stringify({
          targets: [
            {
              target_id: "us-hs.v1",
              name: "US High School",
              version: "1.0",
              output_language: "en",
              output_formats: ["xlsx"],
              templates: [{ key: "grade_9", output_format: "xlsx", target_year_index: 0 }],
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    const resp = await client.templates.list();
    expect(resp.targets[0]!.target_id).toBe("us-hs.v1");
  });

  it("usage.get", async () => {
    const fake = makeFakeFetch(async () =>
      new Response(
        JSON.stringify({
          period_start: "2026-04-01T00:00:00Z",
          period_end: "2026-05-01T00:00:00Z",
          transcripts_processed: 3,
          tokens_input: 5000,
          tokens_output: 1000,
          cache_read_tokens: 0,
          cache_creation_tokens: 0,
          usd_cost: 0.05,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    const u = await client.usage.get();
    expect(u.transcripts_processed).toBe(3);
  });

  it("webhooks.create + list", async () => {
    let firstCall = true;
    const fake = makeFakeFetch(async () => {
      if (firstCall) {
        firstCall = false;
        return new Response(
          JSON.stringify({
            id: "00000000-0000-0000-0000-000000000002",
            url: "https://example.com/hook",
            events: ["job.completed"],
            active: true,
            signing_secret: "0".repeat(64),
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(
        JSON.stringify([
          {
            id: "00000000-0000-0000-0000-000000000002",
            url: "https://example.com/hook",
            events: ["job.completed"],
            active: true,
            last_delivery_status: null,
            last_delivered_at: null,
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    const client = new Client({
      baseUrl: "http://test",
      apiKey: "sk_test",
      fetchImpl: fake.fetch,
    });
    const created = await client.webhooks.create({
      url: "https://example.com/hook",
      events: ["job.completed"],
    });
    expect(created.signing_secret).toHaveLength(64);

    const list = await client.webhooks.list();
    expect(list).toHaveLength(1);
  });
});
