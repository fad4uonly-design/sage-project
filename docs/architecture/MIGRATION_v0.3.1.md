# Migration notes — v0.3.0 → v0.3.1

## Summary

v0.3.1 adds the **Business Intelligence Suite** without requiring database schema migrations. SQLite string columns already store entity/relation types.

## Code import compatibility

```python
# Still valid
from sage.agents.domain import BusinessAgent
from sage.agents.domain.business import BusinessAgent

# New
from sage.agents.domain.business import create_business_advisors, MarketingAdvisor
```

## Behavioral changes

1. **Agent count increases** — health/`list_agents` includes ~12 BI domains.
2. **Intent routing** — phrases like "marketing plan", "break-even", "kpi dashboard" route to specialized BI domains instead of generic business/chat.
3. **KG boot seed** — additional business ontology triples are inserted on first boot (and idempotently reinforced on later boots via upsert).

## Config

No new required settings. Optional future: `agents.business_intelligence: true` (currently always on when agents enabled).

## Rollback

Pin package to `0.3.0` and redeploy. BI seed entities remain in KG harmlessly.
