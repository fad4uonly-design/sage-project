import {
  integer,
  sqliteTable,
  text,
} from "drizzle-orm/sqlite-core";
import { sql } from "drizzle-orm";

// SAGE is a local, single-user application. SQLite is intentionally the
// persistence boundary for the first-stage system: no database server is
// required and the complete state can live in one local file.

export const conversations = sqliteTable("conversations", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  title: text("title").notNull().default("New Conversation"),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

export const messages = sqliteTable("messages", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  conversationId: integer("conversation_id")
    .notNull()
    .references(() => conversations.id, { onDelete: "cascade" }),
  role: text("role").notNull(),
  content: text("content").notNull(),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

export const interactionLog = sqliteTable("interaction_log", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  conversationId: integer("conversation_id"),
  userInput: text("user_input").notNull(),
  routeUsed: text("route_used").notNull(),
  toolResult: text("tool_result"),
  finalResponse: text("final_response").notNull(),
  modelUsed: text("model_used"),
  metadata: text("metadata", { mode: "json" }),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

export const memory = sqliteTable("memory", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  key: text("key").notNull(),
  value: text("value").notNull(),
  source: text("source").notNull().default("user"),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

export const notes = sqliteTable("notes", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  title: text("title").notNull(),
  content: text("content").notNull(),
  // SQLite has no native array type. Tags are stored as JSON text and exposed
  // as string[] through Drizzle's JSON mode.
  tags: text("tags", { mode: "json" }).$type<string[]>().notNull(),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

/** Locally ingested source material for the first SAGE knowledge capability. */
export const knowledgeDocuments = sqliteTable("knowledge_documents", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  title: text("title").notNull(),
  content: text("content").notNull(),
  source: text("source").notNull().default("user"),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

/**
 * Improvement proposals are deliberately separate from execution. A proposal
 * may be evaluated and approved, but it can never mutate SAGE by itself.
 */
export const improvementProposals = sqliteTable("improvement_proposals", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  goal: text("goal").notNull(),
  hypothesis: text("hypothesis").notNull(),
  evaluationPlan: text("evaluation_plan").notNull(),
  status: text("status").notNull().default("proposed"),
  evidence: text("evidence"),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

/** Measured candidate runs; evidence belongs to a proposal and is immutable after recording. */
export const improvementExperiments = sqliteTable("improvement_experiments", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  proposalId: integer("proposal_id").notNull().references(() => improvementProposals.id, { onDelete: "cascade" }),
  task: text("task").notNull(),
  baselineScore: integer("baseline_score").notNull(),
  candidateScore: integer("candidate_score").notNull(),
  evidence: text("evidence").notNull(),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

/**
 * Evolver: one iterated alternative (a prompt, strategy, or parameter set).
 * Variants form a lineage through parentId; promotion always requires
 * measured evidence from a SOUP comparison, never an autonomous decision.
 */
export const evolverVariants = sqliteTable("evolver_variants", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull(),
  generation: integer("generation").notNull().default(0),
  parentId: integer("parent_id"),
  /** The variant content itself, e.g. the prompt text or strategy config. */
  payload: text("payload").notNull(),
  /** What changed relative to the parent (empty for generation 0 roots). */
  mutation: text("mutation"),
  status: text("status").notNull().default("candidate"),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
  updatedAt: integer("updated_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

/** SOUP: one cheap comparison run across variants on a small eval set. */
export const soupRuns = sqliteTable("soup_runs", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull(),
  evalSetName: text("eval_set_name").notNull().default("builtin"),
  baselineVariantId: integer("baseline_variant_id")
    .notNull()
    .references(() => evolverVariants.id, { onDelete: "cascade" }),
  winnerVariantId: integer("winner_variant_id"),
  status: text("status").notNull().default("completed"),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});

/** SOUP: per-variant, per-case trial results. Scores are integers 0..100. */
export const soupTrials = sqliteTable("soup_trials", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  runId: integer("run_id").notNull().references(() => soupRuns.id, { onDelete: "cascade" }),
  variantId: integer("variant_id").notNull().references(() => evolverVariants.id, { onDelete: "cascade" }),
  caseId: text("case_id").notNull(),
  score: integer("score").notNull(),
  response: text("response").notNull(),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull().default(sql`(unixepoch() * 1000)`),
});
