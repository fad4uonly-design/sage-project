/**
 * SAGE improvement loop, inspired by Ornith's task/scaffold/evaluation cycle.
 *
 * This is intentionally not autonomous self-modification. It records a
 * falsifiable proposal and its evaluation plan, then requires a user decision
 * before any later executor may act on it.
 */

import { db } from "@/db";
import { improvementExperiments, improvementProposals } from "@/db/schema";
import { asc, desc, eq } from "drizzle-orm";

export type ImprovementStatus = "proposed" | "approved" | "rejected" | "evaluated";

export interface ImprovementProposalInput {
  goal: string;
  hypothesis: string;
  evaluationPlan: string;
}

export interface ImprovementExperimentInput {
  proposalId: number;
  task: string;
  baselineScore: number;
  candidateScore: number;
  evidence: string;
}

export async function proposeImprovement(input: ImprovementProposalInput) {
  const [proposal] = await db
    .insert(improvementProposals)
    .values({
      goal: input.goal.trim(),
      hypothesis: input.hypothesis.trim(),
      evaluationPlan: input.evaluationPlan.trim(),
      status: "proposed",
    })
    .returning();
  return proposal;
}

export async function listImprovements(limit = 50) {
  return db
    .select()
    .from(improvementProposals)
    .orderBy(desc(improvementProposals.updatedAt))
    .limit(limit);
}

export async function decideImprovement(
  id: number,
  status: Extract<ImprovementStatus, "approved" | "rejected">
) {
  const [proposal] = await db
    .update(improvementProposals)
    .set({ status, updatedAt: new Date() })
    .where(eq(improvementProposals.id, id))
    .returning();
  return proposal ?? null;
}

export async function recordExperiment(input: ImprovementExperimentInput) {
  const [proposal] = await db
    .select({ status: improvementProposals.status })
    .from(improvementProposals)
    .where(eq(improvementProposals.id, input.proposalId));

  if (!proposal) throw new Error("Proposal not found.");
  if (proposal.status !== "approved") {
    throw new Error("Only an approved proposal may record an experiment.");
  }

  const [experiment] = await db
    .insert(improvementExperiments)
    .values({
      proposalId: input.proposalId,
      task: input.task.trim(),
      baselineScore: input.baselineScore,
      candidateScore: input.candidateScore,
      evidence: input.evidence.trim(),
    })
    .returning();
  return experiment;
}

export async function getImprovementEvidence(proposalId: number) {
  const experiments = await db
    .select()
    .from(improvementExperiments)
    .where(eq(improvementExperiments.proposalId, proposalId))
    .orderBy(asc(improvementExperiments.createdAt));

  const averageDelta = experiments.length === 0
    ? null
    : experiments.reduce((total, experiment) => total + experiment.candidateScore - experiment.baselineScore, 0) / experiments.length;

  return {
    experiments,
    averageDelta,
    recommendation: averageDelta === null
      ? "insufficient-evidence"
      : averageDelta > 0
        ? "candidate-improves-measured-score"
        : "do-not-promote",
  } as const;
}
