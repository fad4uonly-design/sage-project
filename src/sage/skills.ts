/** Native SAGE skill catalog. Skills are declarative and independently testable. */

export interface SAGESkill {
  id: string;
  name: string;
  capability: string;
  status: "active" | "designed";
  description: string;
}

export const SAGE_SKILLS: readonly SAGESkill[] = [
  { id: "memory.recall", name: "Recall memory", capability: "memory", status: "active", description: "Retrieve relevant local user memories." },
  { id: "knowledge.retrieve", name: "Retrieve knowledge", capability: "knowledge", status: "active", description: "Search locally ingested source material." },
  { id: "tool.calculate", name: "Calculate", capability: "tool-reasoning", status: "active", description: "Evaluate a bounded arithmetic expression deterministically." },
  { id: "workflow.run", name: "Run workflow", capability: "workflows", status: "designed", description: "Execute an approved, observable workflow." },
  { id: "agent.delegate", name: "Delegate agent", capability: "agents", status: "designed", description: "Delegate a bounded task to a named agent role." },
];

export function listSkills(): readonly SAGESkill[] {
  return SAGE_SKILLS;
}
