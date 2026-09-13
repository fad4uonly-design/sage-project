/**
 * SAGE Chat API Route
 *
 * POST /api/sage/chat
 *
 * Body:
 *   { message: string, conversationId?: number }
 *
 * Response:
 *   { content, routeUsed, toolStatus, modelUsed, conversationId }
 *
 * This is the single API endpoint the UI calls. It delegates entirely to
 * the SAGE application boundary (handleMessage). No SAGE logic lives here.
 */

import { NextRequest } from "next/server";
import { handleMessage, SAGEApplicationError } from "@/sage/app";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as {
      message?: string;
      conversationId?: number;
    };

    const userInput = (body.message ?? "").trim();
    if (!userInput) {
      return Response.json(
        { error: "Message cannot be empty." },
        { status: 400 }
      );
    }

    const result = await handleMessage(userInput, body.conversationId);

    return Response.json({
      content: result.content,
      routeUsed: result.routeUsed,
      toolStatus: result.toolStatus,
      modelUsed: result.modelUsed,
      conversationId: result.conversationId,
    });
  } catch (err) {
    if (err instanceof SAGEApplicationError) {
      const status = err.code === "INVALID_INPUT" ? 400 : 404;
      return Response.json({ error: err.message }, { status });
    }

    console.error("[/api/sage/chat] Unhandled error:", err);
    return Response.json(
      { error: "An unexpected error occurred. Please try again." },
      { status: 500 }
    );
  }
}
