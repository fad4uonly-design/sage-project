import { getArchitecture } from "@/sage/architecture";

export const dynamic = "force-dynamic";

/** Public, read-only view of SAGE's capability boundaries and maturity. */
export async function GET() {
  return Response.json({ capabilities: getArchitecture() });
}
