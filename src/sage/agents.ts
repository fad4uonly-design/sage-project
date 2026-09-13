/** Named SAGE agent roles. Implementations are added only with bounded tools and tests. */

export interface SAGEAgent {
  id: string;
  name: string;
  status: "designed";
  scope: string;
}

export const SAGE_AGENTS: readonly SAGEAgent[] = [
  { id: "research", name: "Research agent", status: "designed", scope: "Collect and synthesize approved sources." },
  { id: "planner", name: "Planning agent", status: "designed", scope: "Prepare a bounded plan without executing external actions." },
];

export function listAgents(): readonly SAGEAgent[] {
  return SAGE_AGENTS;
}
