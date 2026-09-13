/**
 * GET /api/sage/log — recent interaction log entries (for testing/inspection)
 */

import { getRecentLogs } from "@/sage/logger";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const logs = await getRecentLogs(20);
    return Response.json({ logs });
  } catch (err) {
    console.error("[/api/sage/log GET]", err);
    return Response.json({ error: "Failed to load logs." }, { status: 500 });
  }
}
