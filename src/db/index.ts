import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const defaultDbPath = join(/*turbopackIgnore: true*/ process.cwd(), "data", "sage.sqlite");
const databasePath = process.env.SAGE_DB_PATH
  ? resolve(process.env.SAGE_DB_PATH)
  : defaultDbPath;
mkdirSync(dirname(databasePath), { recursive: true });

const globalForDb = globalThis as typeof globalThis & {
  __sageSqlite?: Database.Database;
};

export const sqlite =
  globalForDb.__sageSqlite ?? new Database(databasePath);

sqlite.pragma("foreign_keys = ON");

if (process.env.NODE_ENV !== "production") {
  globalForDb.__sageSqlite = sqlite;
}

// First-stage SAGE intentionally self-initializes its small local schema.
// Migrations can be introduced later if the schema becomes independently
// versioned; there is no need for a migration service at this stage.
sqlite.exec(`
  CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'New Conversation',
    created_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000)
  );

  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000)
  );

  CREATE TABLE IF NOT EXISTS interaction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER,
    user_input TEXT NOT NULL,
    route_used TEXT NOT NULL,
    tool_result TEXT,
    final_response TEXT NOT NULL,
    model_used TEXT,
    metadata TEXT,
    created_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000)
  );

  CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    created_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000)
  );

  CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000)
  );

  CREATE TABLE IF NOT EXISTS knowledge_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    created_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000)
  );

  CREATE TABLE IF NOT EXISTS improvement_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    evaluation_plan TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    evidence TEXT,
    created_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000)
  );

  CREATE TABLE IF NOT EXISTS improvement_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    task TEXT NOT NULL,
    baseline_score INTEGER NOT NULL,
    candidate_score INTEGER NOT NULL,
    evidence TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch() * 1000)
  );
`);

export const db = drizzle(sqlite);
export { databasePath };
