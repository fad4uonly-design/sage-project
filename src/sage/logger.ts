/**
 * SAGE Interaction Logger
 *
 * Records every SAGE interaction in the interaction_log table.
 * This is the SQLite interaction log
 * described in the SAGE architecture. It is an append-only audit trail.
 */

import { db } from "@/db";
import { interactionLog } from "@/db/schema";
import { desc } from "drizzle-orm";

export interface LogEntry {
  conversationId?: number;
  userInput: string;
  routeUsed: "direct" | "memory" | "notes" | "web" | "knowledge" | "tool";
  toolResult?: string;
  finalResponse: string;
  modelUsed?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Append one interaction to the log.
 */
export async function logInteraction(entry: LogEntry): Promise<void> {
  try {
    await db.insert(interactionLog).values({
      conversationId: entry.conversationId ?? null,
      userInput: entry.userInput,
      routeUsed: entry.routeUsed,
      toolResult: entry.toolResult ?? null,
      finalResponse: entry.finalResponse,
      modelUsed: entry.modelUsed ?? null,
      metadata: entry.metadata ?? null,
    });
  } catch (err) {
    // Logging must never break the main response flow
    console.error("[SAGE logger] Failed to write interaction log:", err);
  }
}

/**
 * Retrieve the most recent log entries (for testing/inspection).
 */
export async function getRecentLogs(limit = 20) {
  return db
    .select()
    .from(interactionLog)
    .orderBy(desc(interactionLog.createdAt))
    .limit(limit);
}
