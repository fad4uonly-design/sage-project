import { listAgents } from "@/sage/agents";

export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({ agents: listAgents() });
}
