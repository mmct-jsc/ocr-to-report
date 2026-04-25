# Security Policy

## Reporting a Vulnerability

If you discover a security issue, **please do not open a public GitHub
issue**. Instead, email the maintainer directly with:

- A description of the issue and its impact
- Steps to reproduce (or a proof-of-concept)
- The affected version(s)
- Any suggested mitigation

We aim to:

- Acknowledge your report within **3 business days**.
- Provide an initial assessment within **7 business days**.
- Keep you informed throughout remediation.

We are happy to credit reporters in release notes (with permission).

## Scope

In scope:

- The OCR-to-Report core, adapters, API, worker, CLI, MCP server, and SDKs in
  this repository.
- Default profile and target bundles shipped in `profiles/` and `targets/`.
- The default `docker-compose.yml` configuration.
- Documentation that describes a secure default that is in fact insecure.

Out of scope:

- Social engineering, physical access, or denial-of-service via volumetric
  traffic.
- Issues in third-party services (Anthropic, OpenAI, Google, MinIO, etc.) —
  please report those upstream.
- Issues only reproducible with non-default insecure configurations
  explicitly warned against in documentation.

## Security Model

See [`ARCHITECTURE.md`](ARCHITECTURE.md) and the design plan for the full
threat model. Summary:

- Multi-tenant isolation: app filter + ORM `SET LOCAL` + Postgres RLS.
- PII encrypted column-by-column with a per-tenant DEK envelope-encrypted by
  a master KEK.
- API keys hashed with Argon2id; only an 8-character prefix stored in plain.
- Webhook payloads HMAC-SHA256 signed.
- Audit log hash-chained, tamper-evident.
- Egress allowlist enforced at the worker network boundary.
- Container images run as a non-root user with read-only root filesystem and
  minimal capabilities.
- All inbound payloads validated against strict Pydantic schemas before
  reaching application logic.
- Religion/ethics fields (GDPR Article 9) are excluded from extraction by
  default; opt-in only with a documented lawful basis and 30-day hard cap.

## Compliance Posture

- **FERPA-aligned** — student educational records require consent, RBAC,
  and a disclosure log; the platform supports all three by design.
- **GDPR-aligned** — data subject access (export) and erasure
  (crypto-shredding) endpoints are first-class. Region pinning available on
  Premium tier.
- **SOC 2 readiness** — defense-in-depth, audit trail, dependency scanning,
  and SBOM generation are in scope; full audit certification is post-MVP and
  customer-driven.

## Disclosed Issues

None at this time.
