/**
 * GET  /api/sage/conversations        — list all conversations
 * POST /api/sage/conversations        — create a new conversation
 */

import { db } from "@/db";
import { conversations } from "@/db/schema";
import { desc } from "drizzle-orm";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const all = await db
      .select()
      .from(conversations)
      .orderBy(desc(conversations.updatedAt))
      .limit(50);
    return Response.json({ conversations: all });
  } catch (err) {
    console.error("[/api/sage/conversations GET]", err);
    return Response.json({ error: "Failed to load conversations." }, { status: 500 });
  }
}

export async function POST() {
  try {
    const [conv] = await db
      .insert(conversations)
      .values({ title: "New Conversation" })
      .returning();
    return Response.json({ conversation: conv });
  } catch (err) {
    console.error("[/api/sage/conversations POST]", err);
    return Response.json({ error: "Failed to create conversation." }, { status: 500 });
  }
}
