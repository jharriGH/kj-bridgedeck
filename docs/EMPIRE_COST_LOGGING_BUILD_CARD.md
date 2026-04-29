# Empire Cost Logging Build Card

**Version:** 1.0 — empire-wide self-reporting standard
**Authored:** 2026-04-29
**Source commits:** see git log for `feat(cost): empire-wide /cost/ingest`
**Applies to:** every KJE product that calls Anthropic, OpenAI, or any LLM API

---

## Why this exists

Anthropic Admin API ingestion is gated behind Build Tier 2+ / Enterprise
which Jim's account isn't on yet. Without admin-level access we can't pull
billed truth directly from the provider. So instead, every KJE product
self-reports cost into BridgeDeck via a single client module
(`kje-cost-logger`) and BridgeDeck becomes the empire-wide single source
of truth.

The contract is simple: after every billable model call, POST one row to
`/cost/ingest` with model, tokens, and computed USD cost. Failure modes
are all soft — cost logging never breaks the hot path.

---

## Cost calculation pricing reference

Pricing table lives in `kje_cost_logger/pricing.py` and is shared across
every KJE product. Update that file when Anthropic / OpenAI publish new
rates and every product picks it up on next deploy.

Per-1M-token rates (USD, 2026):

| Model | Input | Output | Cache write (1.25×) | Cache read (0.10×) |
|-------|-------|--------|---------------------|--------------------|
| `claude-haiku-4-5-20251001`   | 0.80  | 4.00  | 1.00  | 0.08 |
| `claude-sonnet-4-5-20250514`  | 3.00  | 15.00 | 3.75  | 0.30 |
| `claude-opus-4-7-20260101`    | 15.00 | 75.00 | 18.75 | 1.50 |
| `whisper-1`                    | per-minute: 0.006 |
| `gpt-4o-mini`                  | 0.15  | 0.60  |
| `gpt-4o`                       | 2.50  | 10.00 |
| `text-embedding-3-small`       | 0.02  | — |
| `text-embedding-3-large`       | 0.13  | — |

Helpers: `calc_anthropic_cost(model, tokens_in, tokens_out, cache_read=0,
cache_write=0)` and `calc_openai_cost(model, tokens_in=0, tokens_out=0,
audio_minutes=0)`.

---

## Implementation patterns

### Pattern 1 — Direct (most common)

```python
from kje_cost_logger import CostLogger
import os

logger = CostLogger(
    bridgedeck_url=os.environ["BRIDGEDECK_URL"],
    api_key=os.environ["BRIDGEDECK_INGEST_KEY"],
    source_system="agentenginez",        # your product slug
    project_slug="agentenginez",          # Brain project slug
)

response = await anthropic.messages.create(model="claude-sonnet-4-5", ...)
await logger.log_anthropic_call(
    response,
    model="claude-sonnet-4-5",
    intent="lead_qualification",
    session_id=session.id,                # optional, for traceability
)
```

### Pattern 2 — Decorator

For functions that wrap a single Anthropic call:

```python
from kje_cost_logger import CostLogger, track_cost

logger = CostLogger(...)

@track_cost(logger, intent="lead_qualification")
async def qualify_lead(lead):
    return await anthropic.messages.create(model="claude-sonnet-4-5", ...)

# `qualify_lead(lead)` now auto-logs cost on every call. The wrapped
# function's return value is unchanged.
```

### Pattern 3 — Manual

For non-Anthropic / non-OpenAI providers (Vapi, ElevenLabs, Plivo, etc):

```python
await logger.log_manual(
    model="vapi-call",
    cost_usd=0.072,
    intent="outbound_call",
    duration_ms=145_000,
    metadata={"call_id": "abc-123", "phone": "+1..."},
)
```

---

## Configuration (env vars)

Each KJE product reads these at startup:

```
BRIDGEDECK_URL=https://kj-bridgedeck-api.onrender.com
BRIDGEDECK_INGEST_KEY=<BRIDGEDECK_ADMIN_KEY value>
```

Pick a stable `source_system` slug that matches the product's identity in
Brain (e.g. `kjwidgetz`, `agentenginez`). Don't make it ad-hoc — the
Coverage Report panel in BridgeDeck checks against a fixed list of
expected products.

The `BRIDGEDECK_INGEST_KEY` is the same as `BRIDGEDECK_ADMIN_KEY` for
now — there's no separate ingest scope yet. Future enhancement: dedicate
a scoped ingest-only key.

---

## Verification protocol

### Step 1 — Test the POST manually

```bash
curl -X POST https://kj-bridgedeck-api.onrender.com/cost/ingest \
  -H "Authorization: Bearer $BRIDGEDECK_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_system": "<your_product>",
    "project_slug": "<your_product>",
    "model": "claude-haiku-4-5-20251001",
    "tokens_in": 1000,
    "tokens_out": 200,
    "cost_usd": 0.0016,
    "intent": "test"
  }'
# expect: {"logged": true, "logged_at": "...", "cap_status": "ok"}
```

### Step 2 — Confirm it lands in cost_log

```bash
curl https://kj-bridgedeck-api.onrender.com/cost/by-source?days=1 \
  -H "Authorization: Bearer $BRIDGEDECK_ADMIN_KEY"
# expect: {"sources": {"<your_product>": 0.0016, ...}, "days": 1}
```

### Step 3 — Confirm Coverage Report shows your product as instrumented

```bash
curl https://kj-bridgedeck-api.onrender.com/cost/coverage \
  -H "Authorization: Bearer $BRIDGEDECK_ADMIN_KEY"
# expect: coverage[<your_product>].instrumented = true,
#         calls_24h >= 1, last_seen ≈ now
```

If your product slug isn't in the `EXPECTED_PRODUCTS` list, it lands in
`unexpected_sources` instead. Either pick a slug from the list or add
yours to `api/routes/cost.py::EXPECTED_PRODUCTS`.

### Step 4 — Wire the real call

Replace the test POST with a real Anthropic / OpenAI call wrapped in
`logger.log_anthropic_call(...)` or `logger.log_openai_call(...)`. Run
the product through one happy-path scenario and confirm cost appears in
the BridgeDeck Cost tab within 60 seconds.

---

## Recommended priority order

Instrument in order of expected daily spend:

1. **`kj_autonomous`** — 8-agent system, highest volume
2. **`kjle`** — 5-stage enrichment pipeline, batch traffic
3. **`agentenginez`** — agent factory, drives many sub-product calls
4. **`reviewbombz`** — review platform, per-customer LLM usage
5. **`daycaremarketerz`** — vertical SaaS, per-customer usage
6. **`kj_salesagentz`** — sales agents, per-conversation
7. **`kjwidgetz`** — widget builder, support queries
8. **`demoboosterz`** + **`demoenginez`** — demo platforms
9. **`voicedropz`** — RVM, mostly Plivo costs (use log_manual)
10. Everything else as it goes to production

Anything calling Anthropic without instrumentation shows up in the
**Coverage Report** as `instrumented: false` — so the empire view of
"who's logging" is auditable from the BridgeDeck UI.

---

## Empire-wide rule (per KJ_RULEZ)

> Any KJE product that calls Anthropic, OpenAI, or any LLM API MUST
> instrument cost reporting via the kje-cost-logger module. Without
> instrumentation, a product is not considered production-ready.

See KJ_RULEZ.md for the canonical rule statement. Anthropic Admin API
ingestion is a future addition for reconciliation — currently blocked
behind Build Tier 2+ / Enterprise gating. Self-reporting via
`/cost/ingest` is the baseline standard.

---

## Common pitfalls

1. **Wrong source_system slug.** If you invent a new slug instead of
   picking from `EXPECTED_PRODUCTS`, you land in `unexpected_sources` —
   the Coverage Report flags this so it's visible, but pick a real slug
   for clean reporting.
2. **`cost_usd: 0` from unknown model.** `calc_anthropic_cost()` returns
   0.0 when the model name isn't in the pricing table. If you're seeing
   zero cost on real calls, check the model id you passed — it must
   match the pricing-table key exactly.
3. **Cache tokens not landing.** The Anthropic SDK exposes
   `usage.cache_read_input_tokens` and `usage.cache_creation_input_tokens`
   only when prompt caching actually fires. Zero values mean no caching
   happened that turn — see PROMPT_CACHING_BUILD_CARD.md for the floor.
4. **Logging in sync code.** `kje_cost_logger.CostLogger` is async-only.
   For sync codebases, wrap the call with `asyncio.run` or use a
   background thread; do NOT block the hot path waiting for cost log.
5. **Ingest endpoint failing silently.** `fail_silently=True` (default)
   is right for production but masks issues during instrumentation. Set
   `fail_silently=False` while wiring a new product so you see auth /
   payload problems immediately.

---

## Revision log

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-04-29 | Initial empire-wide self-reporting standard. Replaces blocked Phase 3.1 Anthropic Admin API ingestion path. |
