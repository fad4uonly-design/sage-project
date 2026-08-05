# Getting Started with SAGE

## Install

```bash
cd sage
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

> Requires **Python 3.13+**. (The design targets 3.14+ when available.)

## First boot

```bash
# Interactive shell
sage start

# One-shot
sage ask "Hello SAGE"

# Health check
sage status

# Store a memory from CLI
sage remember "I run a small farm near Al Farwaniyah"
```

## Interactive tips

Inside `sage start`:

| Input | Effect |
|---|---|
| `remember: my name is Alex` | Long-term memory |
| `what do you remember about names` | Recall |
| `plan a study schedule for calculus` | Planning engine |
| `should I expand the greenhouse?` | Reasoning engine |
| `research irrigation` | Research agent |
| `/status` | Module health table |
| `/memories` | List/search memories |
| `/agents` | List agents |
| `/quit` | Exit |

## Programmatic use

```python
import asyncio
from sage import SageEngine

async def main():
    engine = await SageEngine.create()
    try:
        print(await engine.ask("Hello"))
    finally:
        await engine.shutdown()

asyncio.run(main())
```

See `examples/quickstart.py`.

## Configuration

1. Package defaults: `sage/config/defaults.yaml`
2. User file: `$SAGE_DATA_DIR/config/sage.yaml`
3. Environment: `SAGE_*` (nested with `__`, e.g. `SAGE_LOGGING__LEVEL=DEBUG`)
4. CLI flags

Connect a real model later:

```yaml
models:
  default_provider: openai   # or anthropic
  default_model_name: gpt-4o-mini
  openai_api_key: sk-...     # prefer env: SAGE_MODELS__OPENAI_API_KEY
```

Until then, the **stub** provider keeps every subsystem online offline.

## Tests

```bash
pytest
```

## Next milestones

- **M1 polish** — FTS5 memory search, richer consolidation  
- **M2** — PDF/DOCX/OCR knowledge, stronger reasoning strategies  
- **M3** — more agents, plugin permissions, shell/network tools (gated)  
- **M4** — FastAPI + web dashboard  
