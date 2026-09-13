import { NextRequest } from "next/server";
import { calculate } from "@/sage/tools";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = (await req.json()) as { expression?: string };
  try {
    return Response.json({ result: calculate(body.expression ?? "") });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Calculation failed." },
      { status: 400 }
    );
  }
}
