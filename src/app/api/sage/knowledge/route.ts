import { NextRequest } from "next/server";
import { ingestKnowledge, listKnowledge, searchKnowledge } from "@/sage/knowledge";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const query = req.nextUrl.searchParams.get("q")?.trim();
  const documents = query ? await searchKnowledge(query) : await listKnowledge();
  return Response.json({ documents });
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as { title?: string; content?: string; source?: string };
  const title = body.title?.trim();
  const content = body.content?.trim();
  if (!title || !content) {
    return Response.json({ error: "title and content are required." }, { status: 400 });
  }
  const document = await ingestKnowledge(title, content, body.source?.trim() || "user");
  return Response.json({ document }, { status: 201 });
}
