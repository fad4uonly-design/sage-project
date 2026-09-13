/**
 * SAGE Memory
 *
 * Simple key/value memory store backed by SQLite.
 * Memory entries can be written explicitly and retrieved through
 * keyword matching.
 */

import { db } from "@/db";
import { memory } from "@/db/schema";
import { like, or, desc } from "drizzle-orm";

export interface MemoryEntry {
  id: number;
  key: string;
  value: string;
  source: string;
  createdAt: Date;
}

/**
 * Store a new memory entry.
 */
export async function storeMemory(
  key: string,
  value: string,
  source: "user" | "system" = "user"
): Promise<MemoryEntry> {
  const [entry] = await db
    .insert(memory)
    .values({ key, value, source })
    .returning();

  return entry;
}

/**
 * Retrieve memory entries relevant to the given query.
 *
 * Uses simple keyword matching, then ranks candidates by:
 *   1. number of keyword matches
 *   2. exact key match
 *
 * This remains deliberately simple and deterministic.
 */
export async function recallMemory(query: string): Promise<MemoryEntry[]> {
  const stopWords = new Set([
    "the", "and", "for", "that", "this", "with", "from",
    "you", "are", "was", "has", "can", "will", "do", "did",
    "is", "in", "on", "at", "to", "a", "an", "of", "it",
    "my", "me", "i", "we", "our", "your",
  ]);

  const tokenize = (text: string): string[] =>
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter((word) => word.length >= 3 && !stopWords.has(word));

  const keywords = tokenize(query);

  if (keywords.length === 0) return [];

  const personalPatterns = [
    /\bmy\b/i,
    /\bmine\b/i,
    /\bme\b/i,
    /\bdo i\b/i,
    /\bam i\b/i,
    /\bwhere do i\b/i,
    /\bwhat do i\b/i,
    /\bwhat am i\b/i,
    /\btell me about my\b/i,
  ];

  const isPersonalQuery = personalPatterns.some((pattern) =>
    pattern.test(query)
  );

  const conditions = keywords.flatMap((kw) => [
    like(memory.key, `%${kw}%`),
    like(memory.value, `%${kw}%`),
  ]);

  const candidates = await db
    .select()
    .from(memory)
    .where(or(...conditions))
    .orderBy(desc(memory.updatedAt))
    .limit(20);

  const ranked = candidates
    .map((entry) => {
      const keyWords = new Set(tokenize(entry.key));
      const valueWords = new Set(tokenize(entry.value));

      const matchedKeywords = keywords.filter(
        (kw) => keyWords.has(kw) || valueWords.has(kw)
      );

      const matchCount = matchedKeywords.length;

      const exactKeyMatch = keywords.some(
        (kw) => entry.key.trim().toLowerCase() === kw
      );

      return {
        entry,
        matchCount,
        exactKeyMatch,
      };
    })
    .filter(({ matchCount, exactKeyMatch }) => {
      if (exactKeyMatch) return true;

      if (keywords.length === 1) {
        return matchCount >= 1;
      }

      if (isPersonalQuery) {
        return matchCount >= 1;
      }

      return matchCount >= 2;
    })
    .sort((a, b) => {
      if (b.matchCount !== a.matchCount) {
        return b.matchCount - a.matchCount;
      }

      if (a.exactKeyMatch !== b.exactKeyMatch) {
        return a.exactKeyMatch ? -1 : 1;
      }

      return b.entry.updatedAt.getTime() - a.entry.updatedAt.getTime();
    })
    .map(({ entry }) => entry)
    .slice(0, 5);

  // Deduplicate repeated facts.
  const seen = new Set<string>();

  return ranked.filter((entry) => {
    const identity =
      `${entry.key.trim().toLowerCase()}\0${entry.value.trim().toLowerCase()}`;

    if (seen.has(identity)) return false;

    seen.add(identity);
    return true;
  });
}

/**
 * Get all memory entries for inspection/debugging.
 */
export async function getAllMemory(): Promise<MemoryEntry[]> {
  return db
    .select()
    .from(memory)
    .orderBy(desc(memory.updatedAt))
    .limit(50);
}

/**
 * Parse a user message for explicit memory-store intent.
 */
export function parseMemoryIntent(
  input: string
): { key: string; value: string } | null {
  const lower = input.toLowerCase().trim();

  const patterns = [
    /^(?:please\s+)?remember\s+that\s+(.+)$/i,
    /^(?:please\s+)?remember[:\s]+(.+)$/i,
    /^(?:please\s+)?store\s+(?:that\s+)?(.+)$/i,
    /^(?:please\s+)?note\s+(?:that\s+)?(.+)$/i,
  ];

  for (const pattern of patterns) {
    const match = lower.match(pattern);

    if (!match) continue;

    const fact = match[1].trim();

    const isMatch = fact.match(/^(.+?)\s+is\s+(.+)$/i);

    if (isMatch) {
      return {
        key: isMatch[1].trim(),
        value: fact,
      };
    }

    return {
      key: "fact",
      value: fact,
    };
  }

  return null;
}



