# Observability assets

Production-ready Prometheus + Grafana wiring for OCR-to-Report.

## Files

- `prometheus_alerts.yaml` — SLO + operational alert rules (drop into a Prometheus
  rule_files glob).
- `grafana_dashboard.json` — Importable Grafana dashboard with the standard
  panels: golden signals, latency, vision confidence, tokens, cost, manual-review
  backlog, pipeline step durations, webhook delivery, cache hit rate.

## SLOs

| SLO | Target | Alert |
|---|---|---|
| Availability | 99.9% non-5xx on `/v1/*` | `Ocr2rAvailabilityBudgetBurn` (page) |
| Latency | p95 of POST `/v1/transcripts` ≤ 30s | `Ocr2rTranscriptsP95LatencyHigh` (page) |
| Quality | 95% of extractions ≥ 0.85 confidence | `Ocr2rConfidenceBudgetBurn` (ticket) |

## Operational alerts

| Alert | Severity | What it means |
|---|---|---|
| `Ocr2rVisionProviderCircuitOpen` | page | Provider failover engaged; investigate root cause. |
| `Ocr2rManualReviewBacklog` | ticket | Tenant has > 50 parked jobs awaiting review. |
| `Ocr2rWebhookDeliveryFailureRate` | ticket | Webhook event > 10% failure rate over 10m. |
| `Ocr2rDailyCostBudgetExceeded` | page | Vision spend > $100 in last 24h. |

## Tracing

OpenTelemetry tracing is configured by `OCR2R_OTLP_ENDPOINT` (or the standard
`OTEL_EXPORTER_OTLP_ENDPOINT`). When unset, tracing is a no-op.

- Default sample rate: 5% of root spans (`OCR2R_OTEL_SAMPLE_RATIO` to override).
- Sampler: `ParentBased(TraceIdRatioBased)` so children follow their parent's
  decision (full traces for sampled requests).
- Auto-instrumentation: FastAPI server spans + httpx client spans.

## Running locally

```bash
# Bring up Prometheus + Grafana via Docker:
docker compose up prometheus grafana
# Visit http://localhost:9090 (Prometheus) and http://localhost:3000 (Grafana).
```
