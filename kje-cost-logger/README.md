# kje-cost-logger

Empire-wide cost reporting client for KJE products.

After every Anthropic / OpenAI call, push a row to BridgeDeck's
`/cost/ingest` endpoint so the empire has a single source of truth for
spend across all 30+ products.

```python
from kje_cost_logger import CostLogger
import os

logger = CostLogger(
    bridgedeck_url=os.environ["BRIDGEDECK_URL"],          # https://kj-bridgedeck-api.onrender.com
    api_key=os.environ["BRIDGEDECK_INGEST_KEY"],          # BRIDGEDECK_ADMIN_KEY value
    source_system="agentenginez",                          # your product slug
    project_slug="agentenginez",                           # Brain project slug
)

response = await anthropic.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1500,
    messages=[...],
)
await logger.log_anthropic_call(response, model="claude-sonnet-4-5", intent="lead_qualify")
```

For the full doctrine — recommended priority order, decorator usage,
manual logging for non-Anthropic providers, and the empire-wide rule
mandating instrumentation — see `docs/EMPIRE_COST_LOGGING_BUILD_CARD.md`
in the `kj-bridgedeck` repo.
