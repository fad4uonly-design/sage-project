import { listWorkflows } from "@/sage/workflows";

export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({ workflows: listWorkflows() });
}
