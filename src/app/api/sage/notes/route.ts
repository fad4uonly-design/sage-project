/**
 * GET  /api/sage/notes        — list notes
 * POST /api/sage/notes        — create a note
 */

import { NextRequest } from "next/server";
import { listNotes, createNote } from "@/sage/notes";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const all = await listNotes(20);
    return Response.json({ notes: all });
  } catch (err) {
    console.error("[/api/sage/notes GET]", err);
    return Response.json({ error: "Failed to load notes." }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as {
      title?: string;
      content?: string;
      tags?: string[];
    };
    const title = (body.title ?? "").trim();
    const content = (body.content ?? "").trim();
    if (!title || !content) {
      return Response.json(
        { error: "title and content are required." },
        { status: 400 }
      );
    }
    const note = await createNote(title, content, body.tags ?? []);
    return Response.json({ note });
  } catch (err) {
    console.error("[/api/sage/notes POST]", err);
    return Response.json({ error: "Failed to create note." }, { status: 500 });
  }
}
