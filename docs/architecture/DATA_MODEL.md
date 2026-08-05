# SAGE Data Model (Initial — SQLite)

> Milestone 1 will implement this schema. Documented here so M0 interfaces align with persistence.

## Principles

- SQLite first file: `$SAGE_DATA_DIR/sage.db`
- ULIDs (or UUID4) as string primary keys for sortability / distribution
- Timestamps in UTC ISO-8601
- Soft-delete where user data may need recovery (`deleted_at`)
- JSON columns for flexible metadata (SQLite `TEXT` + JSON1)

---

## Tables (summary)

### `schema_migrations`
| Column | Type | Notes |
|---|---|---|
| version | INTEGER PK | Monotonic |
| applied_at | TEXT | UTC |
| name | TEXT | |

### `memories`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| type | TEXT | MemoryType enum |
| content | TEXT | |
| summary | TEXT NULL | |
| importance | REAL | 0.0–1.0 |
| confidence | REAL | 0.0–1.0 |
| source | TEXT NULL | conversation / document / user / agent |
| source_ref | TEXT NULL | |
| tags | TEXT | JSON array |
| metadata | TEXT | JSON object |
| embedding_id | TEXT NULL | FK future |
| created_at | TEXT | |
| updated_at | TEXT | |
| last_accessed_at | TEXT NULL | |
| access_count | INTEGER | default 0 |
| expires_at | TEXT NULL | short-term expiry |
| deleted_at | TEXT NULL | |

Indexes: `type`, `importance`, `created_at`, `deleted_at`

### `knowledge_documents`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| path | TEXT | Original path |
| title | TEXT NULL | |
| media_type | TEXT | |
| category | TEXT NULL | |
| checksum | TEXT | Dedup |
| size_bytes | INTEGER | |
| status | TEXT | pending/ready/error |
| summary | TEXT NULL | |
| metadata | TEXT | JSON |
| ingested_at | TEXT | |
| deleted_at | TEXT NULL | |

### `knowledge_chunks`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| document_id | TEXT FK | |
| chunk_index | INTEGER | |
| content | TEXT | |
| metadata | TEXT | JSON |
| embedding_id | TEXT NULL | |

### `knowledge_relations`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| source_id | TEXT | |
| target_id | TEXT | |
| relation | TEXT | |
| weight | REAL | default 1.0 |
| metadata | TEXT | JSON |
| created_at | TEXT | |

### `preferences`
| Column | Type | Notes |
|---|---|---|
| key | TEXT PK | |
| value | TEXT | JSON |
| confidence | REAL | |
| source | TEXT | explicit / learned |
| updated_at | TEXT | |

### `goals`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| description | TEXT | |
| status | TEXT | |
| priority | REAL | |
| metadata | TEXT | JSON |
| created_at | TEXT | |
| updated_at | TEXT | |
| completed_at | TEXT NULL | |

### `plans`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| goal_id | TEXT FK | |
| title | TEXT | |
| status | TEXT | |
| steps | TEXT | JSON array of steps |
| created_at | TEXT | |
| updated_at | TEXT | |

### `tasks`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| plan_id | TEXT NULL FK | |
| title | TEXT | |
| status | TEXT | |
| priority | REAL | |
| due_at | TEXT NULL | |
| metadata | TEXT | JSON |
| created_at | TEXT | |
| updated_at | TEXT | |

### `conversations` / `conversation_turns`
Session and turn history for the Conversation Engine.

### `files`
File Manager index (path, checksum, mime, tags, indexed_at).

### `plugins_state`
Plugin enabled flags and per-plugin JSON settings.

### `event_log` (optional, config-gated)
Durable audit of domain events for debugging / learning replay.

---

## Future

- Optional vector table / external vector store for embeddings  
- Optional Postgres backend behind the same repository interfaces  
- Full-text search via SQLite FTS5 for memories and chunks  
