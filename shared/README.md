# Shared Contracts

This directory holds the **authoritative type definitions** shared across every Bridge agent. All components import from here.

## Files

- `contracts.py` — Pydantic models used by Bridge-B (watcher), Bridge-C (API), Bridge-D (Bridge core)
- `contracts.ts` — TypeScript mirrors used by Bridge-E (UI)

## Rules

1. **Never modify in isolation.** Changing a contract breaks every agent. Coordinate changes explicitly.
2. **Keep the two files in sync.** If `LiveSession` gains a field in `.py`, add it to `.ts` in the same commit.
3. **Contracts match the Supabase schema.** `supabase/schema.sql` is the source of truth for persisted shapes; these are the in-memory representations.
4. **Brain API shapes mirror Brain v1.4.0 exactly.** Changing `SessionHandoff` requires coordinating with the Brain deploy.

## How each agent imports

### Python (Bridge-B, C, D)

```python
# Assuming repo root is on PYTHONPATH
from shared.contracts import LiveSession, SessionHandoff, HistoryEvent
```

Or if the agent is installed as a package, add `shared/` to `sys.path` in the bootstrap.

### TypeScript (Bridge-E)

```typescript
import type { LiveSession, SessionHandoff, HistoryEvent } from "../shared/contracts";
```

For the Cloudflare Pages deploy, copy or symlink `contracts.ts` into the UI build input.

## Adding a new contract

1. Edit `contracts.py` — add Pydantic model + Literal types as needed.
2. Mirror in `contracts.ts` — same names, same shape.
3. If the contract corresponds to a new persisted field, update `supabase/schema.sql` and `docs/HISTORY_LOG.md` or `docs/ADMIN_SETTINGS.md` as appropriate.
4. Bump `BUILD_STATE.md` version.
