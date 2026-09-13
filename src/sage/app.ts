/**
 * SAGE Application Boundary
 *
 * This is the single entry point for all SAGE interactions.
 * The UI calls only this function — it never touches memory, notes,
 * router, model, or logger directly.
 *
 *   const result = await handleMessage(userInput, conversationId, history);
 *
 * Architecture:
 *   handleMessage
 *     → router.route()
 *         ├── "memory/store"  → storeMemory()  → model (confirmation)
 *         ├── "memory/recall" → recallMemory()  → model (with context)
 *         ├── "notes"         → notes tool       → model (with context)
 *         └── "direct"        → model (no extra context)
 *     → logInteraction()
 */


import { storeMemory, recallMemory } from "./memory";
import {
  searchNotes,
  listNotes,
  readNote,
  createNote,
  formatNotesForContext,
} from "./notes";
import { type ModelMessage } from "./model";
import { getSAGECore } from "./core";
import { searchWeb, formatWebCitations } from "./web";
import { formatKnowledgeCitations, type ScoredKnowledge } from "./knowledge";
import { verifyCalculation } from "./tools";
import { logInteraction } from "./logger";
import { db } from "@/db";
import { conversations, messages } from "@/db/schema";
import { asc, eq } from "drizzle-orm";

export interface ConversationMessage {
  role: "user" | "assistant";
  content: string;
}

export interface SAGEResponse {
  content: string;
  routeUsed: "direct" | "memory" | "notes" | "web" | "knowledge" | "tool";
  toolStatus?: string; // e.g. "Using memory..." — for the UI status indicator
  modelUsed: string;
  conversationId: number;
}

export class SAGEApplicationError extends Error {
  constructor(
    message: string,
    public readonly code: "CONVERSATION_NOT_FOUND" | "INVALID_INPUT"
  ) {
    super(message);
    this.name = "SAGEApplicationError";
  }
}

async function resolveConversation(
  userInput: string,
  conversationId?: number
): Promise<number> {
  if (conversationId !== undefined) {
    const [conversation] = await db
      .select({ id: conversations.id })
      .from(conversations)
      .where(eq(conversations.id, conversationId));

    if (!conversation) {
      throw new SAGEApplicationError(
        "Conversation not found.",
        "CONVERSATION_NOT_FOUND"
      );
    }

    return conversation.id;
  }

  const [conversation] = await db
    .insert(conversations)
    .values({ title: userInput.slice(0, 60) })
    .returning({ id: conversations.id });

  return conversation.id;
}

async function loadConversationHistory(
  conversationId: number
): Promise<ConversationMessage[]> {
  const rows = await db
    .select({ role: messages.role, content: messages.content })
    .from(messages)
    .where(eq(messages.conversationId, conversationId))
    .orderBy(asc(messages.createdAt));

  return rows
    .slice(-20)
    .filter((row) => row.role === "user" || row.role === "assistant")
    .map((row) => ({
      role: row.role as ConversationMessage["role"],
      content: row.content,
    }));
}

const SAGE_SYSTEM_PROMPT = `You are SAGE, a personal AI assistant. You are helpful, concise, and direct.
You do not fabricate facts. If you don't know something, say so.
You have access to the user's memory and local notes through your tools.
When memory or note context is provided to you, use it to give a grounded answer.
Keep responses focused and avoid unnecessary verbosity.`;

function matchesToMemoryAnswer(matches: Awaited<ReturnType<typeof recallMemory>>): string {
  if (matches.length === 0) return "I couldn't find anything relevant in memory.";
  if (matches.length === 1) return `From memory: ${matches[0].value}`;
  return ["From memory:", ...matches.map((match) => `- ${match.value}`)].join("\n");
}

function notesToDeterministicAnswer(
  intent: NonNullable<ReturnType<typeof import("./notes").parseNotesIntent>>,
  notesList: Awaited<ReturnType<typeof listNotes>>,
  toolResult: string
): string {
  switch (intent.type) {
    case "create":
      return `Note saved: ${intent.title}`;
    case "read":
      return toolResult.startsWith("[Note #") ? toolResult : `Note #${intent.id} not found.`;
    case "search":
      return notesList.length === 0 ? `No notes found for: ${intent.query}` : `Notes matching "${intent.query}":\n${toolResult}`;
    case "list":
      return notesList.length === 0 ? "No local notes found." : `Local notes:\n${toolResult}`;
  }
}

function knowledgeToDeterministicAnswer(matches: ScoredKnowledge[]): string {
  if (matches.length === 0) return "I couldn't find anything relevant in your local knowledge.";
  return [
    "From your local knowledge:",
    ...matches.map((match) => `- ${match.document.title}: ${match.document.content}`),
    "",
    "Sources:",
    formatKnowledgeCitations(matches),
  ].join("\n");
}


/**
 * Handle one user message through the full SAGE pipeline.
 *
 * @param userInput      The raw user message string.
 * @param conversationId Optional conversation ID for logging.
 */
export async function handleMessage(
  userInput: string,
  conversationId?: number
): Promise<SAGEResponse> {
  const trimmedInput = userInput.trim();
  if (!trimmedInput) {
    throw new SAGEApplicationError(
      "Message cannot be empty.",
      "INVALID_INPUT"
    );
  }

  const resolvedConversationId = await resolveConversation(
    trimmedInput,
    conversationId
  );
  const history = await loadConversationHistory(resolvedConversationId);

  await db.insert(messages).values({
    conversationId: resolvedConversationId,
    role: "user",
    content: trimmedInput,
  });

  const core = getSAGECore();
  const brain = core.brain;

  // ── Route decision ──────────────────────────────────────────────────────────
  const decision = await core.router(trimmedInput);

  let toolResult: string | undefined;
  let toolStatus: string | undefined;
  let systemContext = SAGE_SYSTEM_PROMPT;
  let routeUsed: SAGEResponse["routeUsed"] = "direct";
  let notesList: Awaited<ReturnType<typeof listNotes>> = [];

  // ── Handle each route ───────────────────────────────────────────────────────

  if (decision.route === "memory" && decision.subtype === "store") {
    routeUsed = "memory";
    toolStatus = "Storing memory…";

    const { key, value } = decision.intent;
    await storeMemory(key, value, "user");
    toolResult = `Stored memory: key="${key}", value="${value}"`;

    systemContext =
      SAGE_SYSTEM_PROMPT +
      `\n\nYou have just stored the following memory entry:\nKey: ${key}\nValue: ${value}\n` +
      `Confirm to the user that you have remembered this, briefly.`;
  } else if (decision.route === "memory" && decision.subtype === "recall") {
    routeUsed = "memory";
    toolStatus = "Using memory…";

    const matches = decision.matches;
    const contextBlock = matches
      .map((m) => `[Memory] ${m.key}: ${m.value}`)
      .join("\n");
    toolResult = contextBlock;

    systemContext =
      SAGE_SYSTEM_PROMPT +
      `\n\nRelevant memory entries:\n${contextBlock}\n\n` +
      `Use this memory context to answer the user's question.`;
  } else if (decision.route === "notes") {
    routeUsed = "notes";
    const intent = decision.intent!;
    if (intent.type === "list") {
      toolStatus = "Reading local notes…";
      notesList = await listNotes(10);
      toolResult = formatNotesForContext(notesList);
      systemContext =
        SAGE_SYSTEM_PROMPT +
        `\n\nThe user's notes:\n${toolResult}\n\nList these notes clearly.`;
    } else if (intent.type === "search") {
      toolStatus = "Searching local notes…";
      notesList = await searchNotes(intent.query);
      toolResult = formatNotesForContext(notesList);
      systemContext =
        SAGE_SYSTEM_PROMPT +
        `\n\nSearch results from the user's notes:\n${toolResult}\n\n` +
        `Present the matching notes to the user.`;
    } else if (intent.type === "read") {
      toolStatus = "Reading note…";
      const note = await readNote(intent.id);
      toolResult = note
        ? formatNotesForContext([note])
        : `Note #${intent.id} not found.`;
      systemContext =
        SAGE_SYSTEM_PROMPT +
        `\n\nNote content:\n${toolResult}\n\nPresent this note to the user.`;
    } else if (intent.type === "create") {
      toolStatus = "Creating note…";
      const newNote = await createNote(intent.title, intent.content, intent.tags);
      toolResult = `Created note #${newNote.id}: "${newNote.title}"`;
      systemContext =
        SAGE_SYSTEM_PROMPT +
        `\n\nYou have just created a note:\nTitle: ${newNote.title}\nContent: ${newNote.content}\n` +
        `Confirm to the user that the note has been saved.`;
    }
  } else if (decision.route === "knowledge") {
    routeUsed = "knowledge";
    toolStatus = "Searching local knowledge…";
    const contextBlock = decision.matches
      .map(
        (match, index) =>
          `[${index + 1}] ${match.document.title} (confidence ${match.confidence.toFixed(2)}): ${match.document.content}`
      )
      .join("\n");
    toolResult = contextBlock || "No relevant local knowledge found.";
    systemContext =
      SAGE_SYSTEM_PROMPT +
      `\n\nLocal knowledge results with confidence scores:\n${toolResult}\n\n` +
      "Answer only from these results and cite them by their [n] numbers. " +
      "Mention when a cited source has low confidence (below 0.6). " +
      "Say when the local knowledge has no answer.";
  } else if (decision.route === "tool" && decision.tool === "calculate") {
    routeUsed = "tool";
    toolStatus = "Calculating…";
    // Tool-R0 verify-then-answer gate: an answer is released only when two
    // independent evaluation paths agree on the result.
    const verification = verifyCalculation(decision.expression);
    toolResult = verification.verified
      ? `${decision.expression} = ${verification.value} (verified by two independent evaluations)`
      : `I could not verify a trustworthy answer for: ${decision.expression}. ${verification.reason ?? "Verification failed."}`;
  } else if (decision.route === "web") {
    routeUsed = "web";
    toolStatus = "Searching the web…";
    const results = await searchWeb(decision.query);
    toolResult = results.length === 0
      ? "No web results found."
      : formatWebCitations(results);
    systemContext =
      SAGE_SYSTEM_PROMPT +
      `\n\nWeb search results with citations:\n${toolResult}\n\n` +
      "Use only these search results. Cite them by their [n] numbers and include source URLs when useful.";
  }
  // else: direct — no tool, no extra context

  // ── Build message history for the model ─────────────────────────────────────
  const modelMessages: ModelMessage[] = [
    ...history.map((m) => ({ role: m.role, content: m.content })),
    { role: "user", content: trimmedInput },
  ];

  // ── Call the model ──────────────────────────────────────────────────────────
  let finalResponse: string;
  try {
    if (decision.route === "tool" && decision.tool === "calculate") {
      finalResponse = toolResult ?? "Calculation failed.";
    } else if (brain.id === "stub" && decision.route === "memory" && decision.subtype === "recall") {
      finalResponse = matchesToMemoryAnswer(decision.matches);
    } else if (brain.id === "stub" && decision.route === "knowledge") {
      finalResponse = knowledgeToDeterministicAnswer(decision.matches);
    } else if (brain.id === "stub" && decision.route === "notes" && decision.intent) {
      finalResponse = notesToDeterministicAnswer(decision.intent, notesList, toolResult ?? "No notes found.");
    } else {
      const result = await brain.complete(modelMessages, systemContext);
      finalResponse = result.content;
    }
  } catch (err) {
    console.error("[SAGE app] Model error:", err);
    finalResponse =
      "I encountered an error generating a response. Please try again.";
  }

  await db.insert(messages).values({
    conversationId: resolvedConversationId,
    role: "assistant",
    content: finalResponse,
  });

  await db
    .update(conversations)
    .set({ updatedAt: new Date() })
    .where(eq(conversations.id, resolvedConversationId));

  // ── Log the interaction ─────────────────────────────────────────────────────
  await logInteraction({
    conversationId: resolvedConversationId,
    userInput: trimmedInput,
    routeUsed,
    toolResult,
    finalResponse,
    modelUsed: brain.id,
    metadata: { decision: decision.route },
  });

  return {
    content: finalResponse,
    routeUsed,
    toolStatus,
    modelUsed: brain.id,
    conversationId: resolvedConversationId,
  };
}








