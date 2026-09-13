import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const SAGE_API_URL = process.env.SAGE_API_URL || "http://localhost:8000/api/v1";

/**
 * GET /api/sage/improvements/experiments
 * Fetch SOUP runs, trials, or evidence for a variant.
 */
export async function GET(req: NextRequest) {
  const runId = req.nextUrl.searchParams.get("runId");
  const variantId = req.nextUrl.searchParams.get("variantId");

  try {
    if (runId) {
      // Get run details, trials, and trace
      const [runRes, trialsRes, traceRes] = await Promise.all([
        fetch(`${SAGE_API_URL}/soup/runs/${runId}`),
        fetch(`${SAGE_API_URL}/soup/runs/${runId}/trials`),
        fetch(`${SAGE_API_URL}/soup/runs/${runId}/trace`),
      ]);

      const run = runRes.ok ? await runRes.json() : null;
      const trials = trialsRes.ok ? await trialsRes.json() : [];
      const trace = traceRes.ok ? await traceRes.json() : null;

      return Response.json({ run, trials, trace });
    }

    if (variantId) {
      // Get variant lineage
      const lineageRes = await fetch(`${SAGE_API_URL}/evolver/variants/${variantId}/lineage`);
      const lineage = lineageRes.ok ? await lineageRes.json() : [];
      return Response.json({ lineage });
    }

    return Response.json({ error: "runId or variantId is required." }, { status: 400 });
  } catch (error) {
    console.error("Error fetching experiment evidence:", error);
    return Response.json(
      { error: "Failed to fetch experiment evidence from SAGE API" },
      { status: 500 }
    );
  }
}

/**
 * POST /api/sage/improvements/experiments
 * Execute a SOUP comparison experiment.
 */
export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    name?: string;
    variantIds?: string[];
    evalSet?: Array<{ id: string; input: string; expected?: string }>;
    evalSetName?: string;
  };

  const name = body.name?.trim() || "Dashboard Comparison";
  const variantIds = body.variantIds;

  if (!variantIds || !Array.isArray(variantIds) || variantIds.length === 0) {
    return Response.json(
      { error: "variantIds array is required." },
      { status: 400 }
    );
  }

  try {
    const response = await fetch(`${SAGE_API_URL}/soup/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        variant_ids: variantIds,
        eval_set: body.evalSet || [],
        eval_set_name: body.evalSetName || "dashboard",
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to run SOUP comparison: ${response.statusText}`);
    }

    const report = await response.json();
    return Response.json({ experiment: report }, { status: 201 });
  } catch (error) {
    console.error("Error running experiment:", error);
    return Response.json(
      { error: error instanceof Error ? error.message : "Could not run experiment." },
      { status: 500 }
    );
  }
}
