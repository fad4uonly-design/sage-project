/**
 * GET /api/sage/conversations/[id]/messages — load messages for a conversation
 */

import { NextRequest } from "next/server";
import { db } from "@/db";
import { messages } from "@/db/schema";
import { eq, asc } from "drizzle-orm";

export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const conversationId = parseInt(id, 10);
    if (isNaN(conversationId)) {
      return Response.json({ error: "Invalid conversation id." }, { status: 400 });
    }

    const msgs = await db
      .select()
      .from(messages)
      .where(eq(messages.conversationId, conversationId))
      .orderBy(asc(messages.createdAt));

    return Response.json({ messages: msgs });
  } catch (err) {
    console.error("[/api/sage/conversations/[id]/messages GET]", err);
    return Response.json({ error: "Failed to load messages." }, { status: 500 });
  }
}
