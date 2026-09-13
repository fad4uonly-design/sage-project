import { listSkills } from "@/sage/skills";

export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({ skills: listSkills() });
}
