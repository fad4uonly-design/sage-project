/**
 * SAGE Router
 *
 * Determines how to handle each incoming user message:
 *
 *   memory  -> explicit memory store OR relevant stored memory
 *   notes   -> local notes operation
 *   web     -> explicit/current external-information request
 *   direct  -> everything else
 *
 * The router remains deliberately simple and deterministic.
 */

import { parseMemoryIntent, recallMemory } from "./memory";
import { parseNotesIntent } from "./notes";
import { searchKnowledgeScored } from "./knowledge";
import { verifyCalculation } from "./tools";

export type RouteDecision =
  | {
      route: "memory";
      subtype: "store";
      intent: { key: string; value: string };
    }
  | {
      route: "memory";
      subtype: "recall";
      matches: Awaited<ReturnType<typeof recallMemory>>;
    }
  | {
      route: "notes";
      intent: ReturnType<typeof parseNotesIntent>;
    }
  | {
      route: "web";
      query: string;
    }
  | {
      route: "knowledge";
      query: string;
      matches: Awaited<ReturnType<typeof searchKnowledgeScored>>;
    }
  | {
      route: "tool";
      tool: "calculate";
      expression: string;
    }
  | {
      route: "direct";
    };

function parseWebIntent(input: string): string | null {
  const trimmed = input.trim();

  const patterns = [
    /^(?:please\s+)?search\s+(?:the\s+)?web\s+(?:for\s+)?(.+)$/i,
    /^(?:please\s+)?search\s+online\s+(?:for\s+)?(.+)$/i,
    /^(?:please\s+)?look\s+(?:it\s+)?up\s+online(?:\s+for)?\s+(.+)$/i,
    /^(?:please\s+)?look\s+up\s+(.+)$/i,
    /^(?:please\s+)?find\s+(?:online|on\s+the\s+web)\s+(.+)$/i,
  ];

  for (const pattern of patterns) {
    const match = trimmed.match(pattern);

    if (match?.[1]?.trim()) {
      return match[1].trim();
    }
  }

  const currentPattern =
    /^(?:what(?:'s| is)|tell me)\s+(?:the\s+)?(?:latest|current|recent)\s+(.+)$/i;

  const currentMatch = trimmed.match(currentPattern);

  if (currentMatch?.[1]?.trim()) {
    return `latest ${currentMatch[1].trim()}`;
  }

  return null;
}

function parseKnowledgeIntent(input: string): string | null {
  const patterns = [
    /^(?:please\s+)?search\s+(?:my\s+)?knowledge\s+(?:for\s+)?(.+)$/i,
    /^(?:please\s+)?search\s+(?:my\s+)?documents?\s+(?:for\s+)?(.+)$/i,
    /^(?:what|tell me)\s+does\s+(?:my\s+)?knowledge\s+say\s+about\s+(.+)$/i,
  ];

  for (const pattern of patterns) {
    const match = input.trim().match(pattern);
    if (match?.[1]?.trim()) return match[1].trim();
  }

  return null;
}

function parseCalculationIntent(input: string): string | null {
  const match = input.trim().match(/^(?:calculate|compute)\s+(.+?)[.?]?$/i);
  if (!match?.[1]) return null;

  const expression = match[1].trim();
  // Tool-R0: only route to the calculator when the expression passes the
  // verify-then-answer gate; an unverifiable expression is not a calculation.
  return verifyCalculation(expression).verified ? expression : null;
}

/**
 * Route the user input to the appropriate handler.
 */
export async function route(userInput: string): Promise<RouteDecision> {
  const trimmed = userInput.trim();

  // Memory store has highest priority.
  const memoryIntent = parseMemoryIntent(trimmed);

  if (memoryIntent) {
    return {
      route: "memory",
      subtype: "store",
      intent: memoryIntent,
    };
  }

  // Local notes.
  const notesIntent = parseNotesIntent(trimmed);

  if (notesIntent) {
    return {
      route: "notes",
      intent: notesIntent,
    };
  }

  // Deterministic calculation has precedence over model completion.
  const calculation = parseCalculationIntent(trimmed);
  if (calculation) {
    return { route: "tool", tool: "calculate", expression: calculation };
  }

  // Knowledge retrieval is explicit for now, preventing accidental context
  // injection until its relevance evaluation is more mature.
  const knowledgeQuery = parseKnowledgeIntent(trimmed);
  if (knowledgeQuery) {
    return {
      route: "knowledge",
      query: knowledgeQuery,
      matches: await searchKnowledgeScored(knowledgeQuery),
    };
  }

  // Explicit/current web request.
  const webQuery = parseWebIntent(trimmed);

  if (webQuery) {
    return {
      route: "web",
      query: webQuery,
    };
  }

  // Memory recall.
  const memoryMatches = await recallMemory(trimmed);

  if (memoryMatches.length > 0) {
    return {
      route: "memory",
      subtype: "recall",
      matches: memoryMatches,
    };
  }

  // Direct answer.
  return {
    route: "direct",
  };
}
