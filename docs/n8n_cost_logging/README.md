# n8n Cost-Logging Migration Guide — kj_autonomous

Empire-wide cost reporting per KJ_RULEZ. Every n8n workflow that calls
Anthropic must POST a cost row to BridgeDeck `/cost/ingest` after the
Anthropic call completes. This guide gives you drop-in artifacts and the
exact migration steps for the existing 7-8 agents in `kj_autonomous`.

**Standing rule (per Jim's existing memory):** NEVER modify existing n8n
workflows. Always create NEW versions, mark old ones inactive, never
delete or overwrite. This guide is built around that rule.

---

## Files in this folder

- `bridgedeck_cost_log_node.json` — a single `httpRequest` node JSON you
  can drop into any workflow as-is.
- `agent_template_with_cost.json` — a complete tiny workflow showing the
  Anthropic-call → log-cost → passthrough pattern. Useful as a reference
  when wiring an existing agent.
- `README.md` — this file.

---

## Step-by-step migration (per agent)

For each existing agent (Agent 1 through Agent 7-8), repeat:

### 1. In n8n at `https://kj-autonomous.up.railway.app`, **Duplicate** the
existing agent workflow.

- Open the agent workflow.
- Top-right menu → **Duplicate**.
- Rename the copy to `<original_name>_v2_costlogging` (e.g.
  `agent_1_lead_qualify_v2_costlogging`).

### 2. Identify every Anthropic HTTP Request node in the duplicate.

Search the workflow for nodes whose URL is
`https://api.anthropic.com/v1/messages`. Most agents have exactly one;
some have a couple.

### 3. After each Anthropic node, insert a new HTTP Request node.

Easiest path: **Import** the node from
`bridgedeck_cost_log_node.json`. In n8n you can copy the JSON to your
clipboard, then in the workflow editor select an empty area and paste —
n8n imports the single node.

If "import single node" isn't available in your n8n version, manually
create a new HTTP Request node with these exact settings:

| Field | Value |
|---|---|
| **Method** | `POST` |
| **URL** | `https://kj-bridgedeck-api.onrender.com/cost/ingest` |
| **Headers** → Authorization | `Bearer bridgedeck-kj-2026-kingjames` |
| **Headers** → Content-Type | `application/json` |
| **Body Content Type** | `JSON` |
| **JSON Body** | (see template below) |
| **Options → Timeout** | `5000` |
| **Options → Response → Never Error** | `true` |

JSON body template (replace `agent_<N>_<task>` with the actual agent name):

```json
{
  "source_system": "kj_autonomous",
  "project_slug": "kj_autonomous",
  "model": "{{ $json.model || 'claude-sonnet-4-5' }}",
  "tokens_in": {{ $json.usage?.input_tokens || 0 }},
  "tokens_out": {{ $json.usage?.output_tokens || 0 }},
  "cache_read_tokens": {{ $json.usage?.cache_read_input_tokens || 0 }},
  "cache_write_tokens": {{ $json.usage?.cache_creation_input_tokens || 0 }},
  "cost_usd": {{ ((($json.usage?.input_tokens || 0) / 1000000) * 3.0) + ((($json.usage?.output_tokens || 0) / 1000000) * 15.0) }},
  "intent": "agent_<N>_<task>"
}
```

### 4. Wire the new node between the Anthropic node and whatever was downstream.

```
[Anthropic Call] → [Log Cost to BridgeDeck] → [next node...]
```

The cost-log node passes through whatever was in `$json` on input, so
downstream nodes that depended on the Anthropic response shape continue
to work as long as you reference `$('Anthropic Call').item.json` rather
than `$json` after this node. If your existing nodes already use
`$json.*` directly, add a small Code node after the cost-log to re-map
the input back to the Anthropic response (see
`agent_template_with_cost.json` for the pattern).

### 5. Test the new workflow once.

Click **Execute Workflow** with realistic test data. Verify both:

a. The cost-log node returned HTTP 200 (look at its right pane in the
   execution detail). The response should be:
   `{"logged":true,"logged_at":"...","cap_status":"ok"}`

b. Curl `/cost/by-source?days=1` and confirm `kj_autonomous` appears
   with the cost incrementing:

   ```bash
   curl -s "https://kj-bridgedeck-api.onrender.com/cost/by-source?days=1" \
     -H "Authorization: Bearer bridgedeck-kj-2026-kingjames"
   ```

### 6. Activate the new workflow + deactivate the old one.

- New workflow → **Active** toggle → ON.
- Old workflow (the one without cost-logging) → **Active** toggle → OFF.
- Add an internal note on the old workflow: "Superseded by
  `<new_name>` on YYYY-MM-DD. Kept inactive for rollback only."

Never delete the old workflow. Per Jim's standing rule, inactive copies
are the rollback path.

### 7. Repeat steps 1-6 for every other agent.

7-8 agents total. Recommended order:

1. Agent 1 (highest volume)
2. Agent 2
3. ...sequentially through Agent 7-8

---

## Verification across all agents

After all 7-8 agents have v2_costlogging versions activated:

```bash
curl -s "https://kj-bridgedeck-api.onrender.com/cost/coverage" \
  -H "Authorization: Bearer bridgedeck-kj-2026-kingjames" | jq
```

Expected: `kj_autonomous` shows up under `coverage` with
`instrumented: true` and `calls_24h > 0`.

---

## Cost calculation note

The JSON body uses **Sonnet 4.5 pricing** (`$3/M in, $15/M out`) as the
default. If a particular agent uses Haiku 4.5, change the cost expression to:

```
{{ ((($json.usage?.input_tokens || 0) / 1000000) * 0.80) + ((($json.usage?.output_tokens || 0) / 1000000) * 4.00) }}
```

The pricing table lives in `kj-bridgedeck/kje-cost-logger/pricing.py`.
Keep these n8n expressions in sync with that file when Anthropic
publishes new rates.

---

## What this does NOT cover

- **OpenAI calls in n8n.** Use the same pattern but change `source_system`
  if the OpenAI traffic is from a different logical product, or keep
  `kj_autonomous` and add `intent` like `agent_5_whisper_transcribe`.
- **Vapi / Plivo / non-LLM cost.** Use the same `/cost/ingest` endpoint
  but compute cost via your own formula (per-minute, per-call, etc.) and
  set `model` to a descriptive string like `vapi-call` or `plivo-rvm`.

---

## Rollback

If a v2 workflow misbehaves:

1. Old workflow toggle → ON.
2. New workflow toggle → OFF.
3. Open an issue in `kj-bridgedeck` referencing this guide.

The cost-log node is fire-and-forget with `neverError: true`, so a
BridgeDeck outage cannot break an agent — but if the wiring is wrong
(e.g. you accidentally broke a downstream `$json` reference), the
rollback is one toggle.
