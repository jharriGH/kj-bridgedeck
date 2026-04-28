# Empire Prompt Caching Build Card

**Version:** 1.1 — empirical Haiku 4.5 floor correction
**Verified:** 2026-04-27 against production Anthropic API + KJ BridgeDeck
**Source commits:** `1cdf7ef`, `c04bbbb`
**Applies to:** every KJE product that calls Anthropic with a stable system preamble

---

## TL;DR

Anthropic prompt caching gives you ~90% off cached input tokens after the
first write. To activate it, the `cache_control: {"type":"ephemeral"}`
block must clear the model-specific token floor — and the published
floors are not always accurate. **For Haiku 4.5 in production today, target
≥ 4,300 tokens** for the stable block. Anything smaller silently no-ops
and you lose the savings.

---

## Hard requirements

| Model | Documented floor | EMPIRICAL floor (production-verified) |
|-------|------------------|---------------------------------------|
| Sonnet 4.5 / Opus 4.7 | 1,024 | TBD (verify before relying on docs) |
| Haiku 4.5 | 2,048 | **~4,200 tokens** (verified Apr 27, 2026) |

⚠️ **CRITICAL.** Anthropic's published Haiku 4.5 floor of 2,048 is wrong as
of April 2026. Live binary search on production calls established the real
floor is between **4,081** (no cache) and **4,298** (cached).
Recommendation: target ≥ 4,300 tokens for Haiku 4.5 stable blocks. Do NOT
rely on the published 2,048 floor.

---

## Pricing math (Anthropic 2026)

| Token category | Multiplier vs base input rate |
|---|---|
| Standard input | 1.00× |
| Cache write (`cache_creation_input_tokens`) | **1.25×** (one-time premium) |
| Cache read (`cache_read_input_tokens`) | **0.10×** (90% discount) |

The break-even is hit on the **second** call within the cache TTL: turn 1
pays 1.25× to write, every subsequent turn within ~5 minutes pays 0.10×
on the cached prefix. Net savings approach 90% of the cached portion as
turn count grows.

---

## SDK wiring (anthropic-python ≥ 0.34)

The SDK accepts `cache_control` directly on `TextBlockParam` blocks. No
beta header is required (caching is GA). Pass system as a list of blocks
rather than a string:

```python
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=...)
resp = await client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1500,
    system=[
        {
            "type": "text",
            "text": STABLE_SYSTEM_BLOCK,            # ≥ 4.3K tokens for Haiku 4.5
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": dynamic_per_turn_block,          # NO cache_control
        },
    ],
    messages=[...],
)
usage = resp.usage
# usage.cache_creation_input_tokens — > 0 on first turn
# usage.cache_read_input_tokens     — > 0 on subsequent turns
```

Stream API is the same — see `bridge-core/bridge_core/claude_stream.py`.

---

## What goes in the cached block

The block is content the model needs **every turn** but that doesn't
change between turns. Good candidates:

- Identity / voice / persona
- Static product inventory (slugs, one-line descriptions)
- Standing rules (KJ_RULEZ automation mandate, Brain endpoint
  verification rule, paste-and-go standard)
- Capability spec (tool grammar, action directive grammar)
- Cost discipline rules
- Tooling decision precedents (what to never suggest)
- Operations playbook (common patterns)

What stays OUT (per-turn dynamic block):

- Current datetime
- Active session counts
- Today's spend
- Per-turn fetched context (handoffs, memories, project rows)
- Conversation history
- The user's message itself

---

## Verification protocol

### Step 1 — Count actual tokens

The Anthropic SDK's `messages.count_tokens` (≥ 0.40) is the cleanest path.
On older SDKs, send a real `messages.create` with `max_tokens=4` and read
back `usage.input_tokens` from the response. Don't trust character-÷-4
heuristics — they overstate by ~15-25% on prose-heavy English.

### Step 2 — Binary-search the floor

Don't trust documented floors. Build a probe that varies the stable
block size and reports `cache_creation_input_tokens`:

```python
async def probe(stable_text):
    resp = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4,
        system=[{"type":"text","text":stable_text,"cache_control":{"type":"ephemeral"}}],
        messages=[{"role":"user","content":"ok"}],
    )
    return resp.usage.cache_creation_input_tokens

# Try sizes spanning the documented floor ±100%
for mult in (1.0, 1.5, 2.0, 2.5):
    cw = await probe(stable_block * int(mult))
    print(f"{mult}x → cache_creation = {cw}")
```

A `cache_creation_input_tokens` of 0 means the block was below the floor.
A non-zero value means it qualified for caching.

### Step 3 — Confirm cache READ on a second call

Within 5 minutes of the first call, send the **same** `system=[...]`
list (identical strings, identical cache_control). Read back
`usage.cache_read_input_tokens` — should equal the prior turn's
`cache_creation_input_tokens`.

### Step 4 — Pad incrementally if Step 2 fails

If your stable block falls below the empirical floor, expand it with
substantive content (not lorem ipsum — the model uses every token,
filler hurts quality). Good padding sources:

- More product descriptions
- Operational playbooks for common queries
- Tooling-decision precedents
- Concrete cost examples

### Step 5 — Confirm cost reduction empirically

Pull the last 2 cost_log rows for the same conversation:

```sql
SELECT cost_usd, tokens_in, tokens_out, details, created_at
FROM kjcodedeck.cost_log
WHERE source_system = 'bridge'
  AND conversation_id = '{your_test_conv_id}'
ORDER BY created_at DESC LIMIT 2;
```

The cached turn (newer) should cost roughly 18-20% of the uncached turn
(older) for fast-intent queries. **KJE BridgeDeck production result: 82%
reduction ($0.00470 → $0.00085).**

---

## Common pitfalls

1. **Caching disabled in cheap_mode.** BridgeDeck's `cheap_mode` setting
   skips the cached-blocks path because the savings don't matter when
   you're already pinned to Haiku with a tiny output cap. If you can't
   verify caching, check `cheap_mode` first.
2. **Cache TTL is ~5 minutes.** Identical-system calls more than 5 minutes
   apart will both be cache misses (first writes, second writes again).
   This is fine for active conversations; surprise for nightly cron jobs.
3. **Cache key includes the entire system list.** Adding even a single
   character to the dynamic block doesn't break the cache; adding a
   character to the cached block does (it invalidates).
4. **Cache key includes the model.** Switching from Haiku to Sonnet
   mid-conversation pays a fresh write on the new model.
5. **Tokenizer quirks under-bill the system block in your local
   estimator.** Anthropic's tokenizer expands certain characters
   differently than `len(text)//4`. Always use `count_tokens` or a real
   API response for sizing decisions.
6. **Trusting Anthropic's published cache floor.** As of April 2026, the
   documented Haiku 4.5 floor (2,048 tokens) is empirically wrong — real
   floor is ~4,200 tokens. Always run your own binary-search probe
   (test 2K, 3K, 4K, 5K stable blocks) before sizing your stable block.
   KJE empirical data:

   | Stable block size | cache_creation result |
   |-------------------|------------------------|
   | 2,581 tok | 0 (no cache) |
   | 4,081 tok | 0 (no cache) |
   | 4,298 tok | 4,298 ✅ |
   | 4,574 tok | 4,574 ✅ |

---

## KJ BridgeDeck reference implementation

- `bridge-core/bridge_core/prompts.py::STABLE_SYSTEM_BLOCK` — 4,298-token
  stable block. Includes empire inventory, infrastructure map, standing
  rules, directive grammar, ops playbook, tooling precedents.
- `bridge-core/bridge_core/prompts.py::build_cached_system_blocks(...)` —
  returns `[stable_block_with_cache_control, dynamic_block]`.
- `bridge-core/bridge_core/chat.py` — gates caching on
  `settings.bridge.prompt_caching_enabled` (default true) and skips it
  when `cheap_mode` is on.
- `bridge-core/bridge_core/claude_stream.py::calculate_cost` — applies
  the 1.25× / 0.10× multipliers to `cache_creation_input_tokens` and
  `cache_read_input_tokens` respectively.
- `bridge-core/bridge_core/claude_stream.py::stream_claude_response`
  surfaces `cache_creation_tokens` and `cache_read_tokens` in the
  `done` SSE event so the UI can show cache-hit metadata under each
  bubble.

---

## Revision log

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-04-27 | Initial card based on documented floors (1,024 / 2,048). |
| v1.1 | 2026-04-27 | Empirical Haiku 4.5 floor correction (~4,200 tok), production result 82% savings, common pitfall #6 added. Source: KJ BridgeDeck commits 1cdf7ef + c04bbbb. |
