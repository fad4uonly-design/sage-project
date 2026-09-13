/**
 * SAGE Knowledge
 *
 * A deliberately small local retrieval layer. It gives SAGE a stable
 * ingestion/search contract now; embeddings and a vector index can replace
 * the keyword implementation later without changing callers.
 */

import { db } from "@/db";
import { knowledgeDocuments } from "@/db/schema";
import { desc, like, or } from "drizzle-orm";

export interface KnowledgeDocument {
  id: number;
  title: string;
  content: string;
  source: string;
  createdAt: Date;
  updatedAt: Date;
}

const STOP_WORDS = new Set([
  "the", "and", "for", "that", "this", "with", "from", "what", "when",
  "where", "which", "about", "have", "has", "are", "was", "were", "into",
  "your", "you", "our", "their", "a", "an", "of", "in", "on", "to", "is",
]);

function keywords(input: string): string[] {
  return [...new Set(
    input.toLowerCase().match(/[a-z0-9]{3,}/g)?.filter((word) => !STOP_WORDS.has(word)) ?? []
  )].slice(0, 8);
}

export async function ingestKnowledge(
  title: string,
  content: string,
  source = "user"
): Promise<KnowledgeDocument> {
  const [document] = await db
    .insert(knowledgeDocuments)
    .values({ title: title.trim(), content: content.trim(), source })
    .returning();

  return document;
}

export async function searchKnowledgeScored(
  query: string,
  limit = 5
): Promise<ScoredKnowledge[]> {
  const terms = keywords(query);
  if (terms.length === 0) return [];

  const conditions = terms.flatMap((term) => [
    like(knowledgeDocuments.title, `%${term}%`),
    like(knowledgeDocuments.content, `%${term}%`),
  ]);
  const candidates = await db
    .select()
    .from(knowledgeDocuments)
    .where(or(...conditions))
    .orderBy(desc(knowledgeDocuments.updatedAt))
    .limit(30);

  // RAGforge: carry per-source confidence alongside the document so callers
  // can cite sources with their reliability instead of bare text.
  return candidates
    .map((document) => {
      const haystack = `${document.title} ${document.content}`.toLowerCase();
      const score = terms.filter((term) => haystack.includes(term)).length;
      return {
        document,
        score,
        confidence: Math.min(0.95, 0.35 + 0.12 * score),
      };
    })
    .filter(({ score }) => score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, limit);
}

export interface ScoredKnowledge {
  document: KnowledgeDocument;
  /** Number of query terms matched in title+content. */
  score: number;
  /** Heuristic confidence in [0.35, 0.95] derived from term coverage. */
  confidence: number;
}

/**
 * Format scored knowledge matches as numbered citations with confidence.
 * RAGforge: per-layer confidence surfaced to the user, not hidden in metadata.
 */
export function formatKnowledgeCitations(matches: ScoredKnowledge[]): string {
  if (matches.length === 0) return "";
  return matches
    .map(
      (match, index) =>
        `[${index + 1}] ${match.document.title} (confidence ${match.confidence.toFixed(2)}) — ${match.document.content}`
    )
    .join("\n");
}

export async function searchKnowledge(query: string, limit = 5): Promise<KnowledgeDocument[]> {
  const scored = await searchKnowledgeScored(query, limit);
  return scored.map(({ document }) => document);
}

export async function listKnowledge(limit = 20): Promise<KnowledgeDocument[]> {
  return db.select().from(knowledgeDocuments).orderBy(desc(knowledgeDocuments.updatedAt)).limit(limit);
}
