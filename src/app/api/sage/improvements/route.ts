import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const SAGE_API_URL = process.env.SAGE_API_URL || "http://localhost:8000/api/v1";

/**
 * GET /api/sage/improvements
 * List improvement proposals (variants) from the Python SAGE API.
 */
export async function GET() {
  try {
    const response = await fetch(`${SAGE_API_URL}/evolver/variants?status=candidate`);
    if (!response.ok) {
      throw new Error(`Failed to fetch variants: ${response.statusText}`);
    }
    const variants = await response.json();
    return Response.json({ proposals: variants });
  } catch (error) {
    console.error("Error fetching improvements:", error);
    return Response.json(
      { error: "Failed to fetch improvements from SAGE API" },
      { status: 500 }
    );
  }
}

/**
 * POST /api/sage/improvements
 * Propose a new improvement variant via the Python SAGE API.
 */
export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    goal?: string;
    hypothesis?: string;
    evaluationPlan?: string;
  };
  const goal = body.goal?.trim();
  const hypothesis = body.hypothesis?.trim();
  const evaluationPlan = body.evaluationPlan?.trim();

  if (!goal || !hypothesis || !evaluationPlan) {
    return Response.json(
      { error: "goal, hypothesis, and evaluationPlan are required." },
      { status: 400 }
    );
  }

  // Construct variant payload from improvement fields
  const payload = `Goal: ${goal}\nHypothesis: ${hypothesis}\nEvaluation Plan: ${evaluationPlan}`;
  const name = goal.toLowerCase().replace(/\s+/g, "-").substring(0, 50);

  try {
    const response = await fetch(`${SAGE_API_URL}/evolver/variants`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        payload,
        mutation_description: hypothesis,
        mutation_target: "system_prompt",
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to propose variant: ${response.statusText}`);
    }

    const variant = await response.json();
    return Response.json({ proposal: variant }, { status: 201 });
  } catch (error) {
    console.error("Error proposing improvement:", error);
    return Response.json(
      { error: "Failed to propose improvement to SAGE API" },
      { status: 500 }
    );
  }
}

/**
 * PATCH /api/sage/improvements
 * Apply or retire a variant based on decision.
 */
export async function PATCH(req: NextRequest) {
  const body = (await req.json()) as {
    id?: string;
    decision?: string;
    run_id?: string;
    mean_score?: number;
    baseline_mean_score?: number;
  };

  if (!body.id || (body.decision !== "approved" && body.decision !== "rejected")) {
    return Response.json(
      { error: "id and an approved or rejected decision are required." },
      { status: 400 }
    );
  }

  try {
    if (body.decision === "approved") {
      // Apply variant with evidence
      const response = await fetch(`${SAGE_API_URL}/evolver/variants/${body.id}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved: true,
          approver: "dashboard",
          reason: "Approved via dashboard",
          run_id: body.run_id || "manual",
          mean_score: body.mean_score || 100,
          baseline_mean_score: body.baseline_mean_score || 50,
          cases_evaluated: 1,
          cases_won: 1,
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to apply variant: ${response.statusText}`);
      }

      const variant = await response.json();
      return Response.json({ proposal: variant });
    } else {
      // Retire variant
      const response = await fetch(`${SAGE_API_URL}/evolver/variants/${body.id}/retire`, {
        method: "POST",
      });

      if (!response.ok) {
        throw new Error(`Failed to retire variant: ${response.statusText}`);
      }

      const variant = await response.json();
      return Response.json({ proposal: variant });
    }
  } catch (error) {
    console.error("Error updating improvement:", error);
    return Response.json(
      { error: "Failed to update improvement via SAGE API" },
      { status: 500 }
    );
  }
}
