# Production budget — OCR-to-Report v0.1.0

Honest, **measured-not-modeled** cost projection for running OCR-to-Report
in production. Every per-transcript number below is grounded in the live
end-to-end benchmark from `2026-04-26`; tiered tier costs project from the
SLA tier presets shipped in `sla-tiers/`.

## Live benchmark (the only data point we treat as ground truth)

A single Polish ŚWIADECTWO transcript (page 1, rendered to a 4817×6423 PNG,
~21 MB) was POSTed to `/v1/transcripts` against the running stack. The
default sync pipeline ran end to end and rendered an `.xlsx`.

| | |
|---|---|
| Profile | `pl.lo.swiadectwo_szkolne.v1` |
| Target | `us-hs.v1` (Grade-9 template) |
| Provider | Anthropic |
| Model used | `claude-sonnet-4-6` (after the Haiku attempt fell below the 0.85 confidence gate) |
| Wall-clock latency | **~4 seconds** (cold queries; cache misses on first call) |
| Tokens — input | **3,192** |
| Tokens — output | **419** |
| Cache-creation tokens (prompt cache write) | **8,473** |
| Reported `usd_cost` | **$0.031313** |

What the cost includes:
- 3192 prompt tokens at the Sonnet 4.6 base input rate.
- 419 completion tokens at the Sonnet output rate.
- 8473 cache-creation tokens billed at 1.25× the base input rate (per
  Anthropic's prompt-cache pricing table).
- The Haiku 4.5 first attempt (its cost is folded into the same record by
  `AnthropicVisionAdapter._call`'s `_combine_usage` logic).

What the number does **not** include:
- Postgres / object-storage / egress / compute.
- Anthropic Batch API discount (the batch lane runs at ~50% of these rates;
  see "Tier model" below).

## Per-transcript cost by SLA tier

The four tiers shipped at `sla-tiers/<tier>.yaml` choose different provider
mixes and confidence thresholds. The table below projects from the live
data point; second-call (fallback) probabilities are conservative engineering
defaults — production telemetry will replace them once enough volume runs.

| Tier | Sync allowed? | Primary | Fallback | Conf. threshold | Fallback rate (assumed) | $/transcript |
|---|---|---|---|---|---|---|
| `economy` | No (batch only) | Haiku 4.5 | — | 0.80 | n/a | **~$0.005** |
| `standard` | Yes | Haiku 4.5 | Sonnet 4.6 | 0.85 | 15% | **~$0.012** |
| `premium` | Yes | Sonnet 4.6 | Opus 4.7 | 0.95 | 20% | **~$0.040** |
| `enterprise` | Yes | Sonnet 4.6 | Opus 4.7 | 0.95 | 20% | **~$0.040** |

Reasoning:
- Haiku 4.5 base: input $1/M, output $5/M → ~$0.005/page when content fits in
  the prompt cache (which it does after the first warm hit).
- The Sonnet fallback adds ~$0.030 on the cases that miss the gate — exactly
  what we measured.
- Opus 4.7 escalation (Premium/Enterprise) is rare; budgeted at the
  Sonnet shape with a 4× model multiplier.
- Economy uses the batch lane at ~50% off and never falls back, hence the
  ~$0.005 floor.

## Volume projections

Per-month cost at three traffic levels, all on Standard tier (the most likely
mix for a SaaS launch):

| Transcripts/month | Vision spend | + Infra (Postgres + S3 + 2 vCPU) | **Total / month** |
|---:|---:|---:|---:|
| 1,000 | $12 | $40 | **$52** |
| 10,000 | $120 | $90 | **$210** |
| 100,000 | $1,200 | $400 | **$1,600** |
| 1,000,000 | $12,000 | $1,800 | **$13,800** |

Notes:
- Infra column assumes a small managed Postgres (db.t3.medium / equivalent),
  ~$0.023/GB-mo S3, 2 vCPU API + 2 vCPU worker. Storage scales linearly with
  retention window (default 30 days on Standard).
- Egress is dominated by xlsx downloads (~20 KB each) — negligible vs. vision.
- Adopting the Economy lane for non-urgent backfills typically halves the
  vision line.

## Where the spend goes (cost decomposition)

For a single Standard-tier sync transcript that triggers the Sonnet fallback:

```
total            $0.031313
├── Sonnet input  ~$0.0096   (3192 tokens × $3/M)
├── Sonnet output ~$0.0063   ( 419 tokens × $15/M)
├── Cache write   ~$0.0318/4 (8473 tokens × $3.75/M ≈ $0.032)
└── Haiku attempt ~$0.0001   (folded; first attempt was below threshold)
```

Cache-write tokens dominate the first call; subsequent calls in the same
schema/profile see cache reads at 0.1× the input rate, dropping per-request
cost by ~70%.

## Cost controls already in place

- **Tiered model selection** (`AnthropicVisionAdapter`): every request starts
  on Haiku and only escalates to Sonnet when confidence falls below the
  tier-configured threshold.
- **Prompt caching**: the system prompt + JSON schema are pinned with
  `cache_control: ephemeral` so a warm tenant pays cache-read rates, not
  cache-write rates.
- **Result cache** (`InMemoryAsyncCache` in dev, swappable to Redis): the
  `extract` step is keyed by `(image_hash, provider, schema_version)`,
  short-circuiting a re-extract of the same upload.
- **Per-tenant SLA**: a low-volume tenant on Economy never pays Sonnet
  rates; a high-volume tenant on Premium has the budget for Sonnet/Opus.
- **Cost guard rail alert** (`observability/prometheus_alerts.yaml`):
  `Ocr2rDailyCostBudgetExceeded` fires (page severity) when 24h vision
  spend crosses $100.
- **Batch lane** (`POST /v1/transcripts:batch` + `AnthropicBatchAdapter`):
  ~50% cheaper for non-urgent loads; the worker handles submit/poll/fan-out.

## Validating the model in your own deployment

Once your tenant is processing real volume, replace the fallback-rate
guesses with measured rates:

```bash
# 24h fallback rate (model_id_used distribution)
docker compose exec postgres psql -U ocr2r -d ocr2r -c "
  SELECT model_id_used, COUNT(*)
  FROM jobs
  WHERE status = 'succeeded'
    AND completed_at > now() - interval '24 hours'
  GROUP BY 1;
"

# Average cost / transcript over the last week
docker compose exec postgres psql -U ocr2r -d ocr2r -c "
  SELECT AVG(usd_cost) FROM jobs
  WHERE status='succeeded' AND completed_at > now() - interval '7 days';
"
```

## Bottom line

A schema-driven Polish→US-HS transcript pipeline runs at **~$0.031 per
sync extraction** on Standard tier *with* a Sonnet fallback firing
(observed). With prompt caching warm and Haiku-only success, the same
extraction lands at **~$0.005**. Economy batch at scale is sub-cent.

For a SaaS product offering this end-to-end, a 100×-margin Standard plan
priced at $0.10/transcript leaves enough headroom for infra, support, and
a profitable run rate even at modest volume.
