/**
 * SAGE Local Notes Tool
 *
 * Allows SAGE to read and write user notes stored in SQLite.
 * This is SAGE's local "file system" equivalent — persistent structured
 * text accessible by title or tag.
 */

import { db } from "@/db";
import { notes } from "@/db/schema";
import { like, or, desc, eq } from "drizzle-orm";

export interface Note {
  id: number;
  title: string;
  content: string;
  tags: string[];
  createdAt: Date;
  updatedAt: Date;
}

export type NoteToolResult = {
  action: "search" | "create" | "list" | "read";
  notes: Note[];
  message: string;
};

/**
 * Search notes by query (title, content, or tag match).
 */
export async function searchNotes(query: string): Promise<Note[]> {
  const terms = query
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length >= 2);

  if (terms.length === 0) {
    return db.select().from(notes).orderBy(desc(notes.updatedAt)).limit(10);
  }

  const conditions = terms.flatMap((t) => [
    like(notes.title, `%${t}%`),
    like(notes.content, `%${t}%`),
  ]);

  return db
    .select()
    .from(notes)
    .where(or(...conditions))
    .orderBy(desc(notes.updatedAt))
    .limit(10);
}

/**
 * List all notes (most recent first).
 */
export async function listNotes(limit = 10): Promise<Note[]> {
  return db.select().from(notes).orderBy(desc(notes.updatedAt)).limit(limit);
}

/**
 * Read a specific note by id.
 */
export async function readNote(id: number): Promise<Note | null> {
  const [note] = await db.select().from(notes).where(eq(notes.id, id));
  return note ?? null;
}

/**
 * Create a new note.
 */
export async function createNote(
  title: string,
  content: string,
  tags: string[] = []
): Promise<Note> {
  const [note] = await db
    .insert(notes)
    .values({ title, content, tags })
    .returning();
  return note;
}

/**
 * Format notes as a readable context block for the model.
 */
export function formatNotesForContext(noteList: Note[]): string {
  if (noteList.length === 0) return "No notes found.";
  return noteList
    .map(
      (n) =>
        `[Note #${n.id}] ${n.title}\n${n.content}${n.tags.length ? `\nTags: ${n.tags.join(", ")}` : ""}`
    )
    .join("\n\n---\n\n");
}

/**
 * Parse a user message for notes-related intent.
 * Returns the detected intent type, or null if no notes intent found.
 */
export type NotesIntent =
  | { type: "search"; query: string }
  | { type: "list" }
  | { type: "create"; title: string; content: string; tags: string[] }
  | { type: "read"; id: number };

export function parseNotesIntent(input: string): NotesIntent | null {
  const lower = input.toLowerCase().trim();

  // List notes
  if (
    /\b(list|show|display)\b.*(notes?|my notes?)/i.test(lower) ||
    /\bmy notes?\b/i.test(lower) ||
    /\bshow\s+notes?\b/i.test(lower)
  ) {
    return { type: "list" };
  }

  // Create note
  const createMatch = lower.match(
    /^(?:create|add|write|save|make)\s+(?:a\s+)?note[:\s]+(.+)$/i
  );
  if (createMatch) {
    const body = input.slice(input.toLowerCase().indexOf(createMatch[1])).trim();
    // First line as title, rest as content
    const lines = body.split("\n");
    const title = lines[0].trim().slice(0, 100);
    const content = lines.slice(1).join("\n").trim() || title;
    return { type: "create", title, content, tags: [] };
  }

  // Read note by id
  const readMatch = lower.match(/\b(?:show|read|open|get)\s+note\s+#?(\d+)\b/i);
  if (readMatch) {
    return { type: "read", id: parseInt(readMatch[1], 10) };
  }

  // Search notes
  if (/\b(search|find|look\s+(?:in|at|for))\b.*(notes?)/i.test(lower)) {
    const q = lower
      .replace(/\b(search|find|look\s+(?:in|at|for)|in|my|notes?|for)\b/g, " ")
      .trim();
    return { type: "search", query: q };
  }

  return null;
}
