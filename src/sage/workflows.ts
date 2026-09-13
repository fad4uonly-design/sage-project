/** Workflow catalog; execution is intentionally deferred until approvals exist. */

export interface SAGEWorkflow {
  id: string;
  name: string;
  status: "designed";
  steps: readonly string[];
}

export const SAGE_WORKFLOWS: readonly SAGEWorkflow[] = [
  { id: "knowledge-review", name: "Knowledge review", status: "designed", steps: ["retrieve", "summarize", "request approval before external action"] },
  { id: "model-evaluation", name: "Model evaluation", status: "designed", steps: ["select capability", "run benchmark", "record result", "request approval before adoption"] },
];

export function listWorkflows(): readonly SAGEWorkflow[] {
  return SAGE_WORKFLOWS;
}
