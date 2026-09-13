/**
 * SAGE architecture registry.
 *
 * This file is the boundary between SAGE and the projects that inspire its
 * future capabilities.  The projects are research references, not runtime
 * dependencies: SAGE owns its interfaces and can replace an implementation
 * after it has passed an evaluation.
 */

export type CapabilityStatus = "active" | "designed" | "research";

export type SAGECapabilityId =
  | "memory"
  | "knowledge"
  | "agents"
  | "workflows"
  | "skills"
  | "tool-reasoning"
  | "learning"
  | "inspection"
  | "self-improvement"
  | "evolution"
  | "efficient-inference"
  | "local-inference"
  | "scalable-inference"
  | "small-model-research"
  | "multimodal"
  | "speech"
  | "baseline-transformer"
  | "efficient-architecture"
  | "brain";

export interface SAGECapability {
  id: SAGECapabilityId;
  name: string;
  status: CapabilityStatus;
  inspiration: string[];
  principle: string;
}

export const SAGE_CAPABILITIES: readonly SAGECapability[] = [
  { id: "memory", name: "Memory", status: "active", inspiration: ["TurboVec"], principle: "Store and retrieve user facts through a replaceable memory index." },
  { id: "knowledge", name: "RAG / Knowledge", status: "active", inspiration: ["RAGforge"], principle: "Ground answers in local retrieval; evolve to evaluated embedding retrieval before calling it RAG." },
  { id: "agents", name: "Agents", status: "designed", inspiration: ["AgentForge"], principle: "Use explicit roles, tools, and approval boundaries." },
  { id: "workflows", name: "Workflows / Automation", status: "designed", inspiration: ["n8n"], principle: "Represent repeatable work as observable, user-controlled workflows." },
  { id: "skills", name: "Skills", status: "designed", inspiration: ["OpenSkill"], principle: "Make capabilities declarative, versioned, and evaluable." },
  { id: "tool-reasoning", name: "Tool reasoning", status: "active", inspiration: ["Tool-R0"], principle: "Use deterministic tools where a model-generated answer is not reliable." },
  { id: "learning", name: "Learning / training", status: "research", inspiration: ["SOUP"], principle: "Track experiments, data, and evaluations before adopting a trained variant." },
  { id: "inspection", name: "Model inspection", status: "research", inspiration: ["NNsight"], principle: "Keep interventions observable, reversible, and separate from production inference." },
  { id: "self-improvement", name: "Self-improvement", status: "active", inspiration: ["Ornith"], principle: "Propose improvements, record measured experiments, and require approval; never self-modify autonomously." },
  { id: "evolution", name: "Evolution", status: "research", inspiration: ["Evolver"], principle: "Iterate using measured outcomes, never unreviewed self-modification." },
  { id: "efficient-inference", name: "Efficient inference", status: "research", inspiration: ["Turbo", "TurboQuant"], principle: "Optimize only when measured resource limits justify it." },
  { id: "local-inference", name: "Local inference", status: "active", inspiration: ["Ollama", "llama.cpp"], principle: "Keep a local, swappable inference path." },
  { id: "scalable-inference", name: "Scalable inference", status: "designed", inspiration: ["vLLM"], principle: "Add a serving backend without changing SAGE application logic." },
  { id: "small-model-research", name: "Small-model research", status: "research", inspiration: ["OLMo 3", "Pythia", "SmolLM2"], principle: "Compare small models with controlled, task-specific evaluations." },
  { id: "multimodal", name: "Multimodal", status: "designed", inspiration: ["SmolVLM"], principle: "Add image understanding behind a dedicated perception interface." },
  { id: "speech", name: "Speech", status: "designed", inspiration: ["Whisper Tiny"], principle: "Add speech recognition behind a dedicated transcription interface." },
  { id: "baseline-transformer", name: "Baseline transformer", status: "research", inspiration: ["GPT-2 Small"], principle: "Retain simple baselines for experiments and regression comparisons." },
  { id: "efficient-architecture", name: "Efficient architecture", status: "research", inspiration: ["OpenELM"], principle: "Study efficient architectures before changing the model layer." },
  { id: "brain", name: "General-purpose brain", status: "active", inspiration: ["Qwen2.5", "Qwen3"], principle: "Route language work through a model provider selected by capability and configuration." },
];

export function getArchitecture(): readonly SAGECapability[] {
  return SAGE_CAPABILITIES;
}

export function getCapability(id: SAGECapabilityId): SAGECapability {
  const capability = SAGE_CAPABILITIES.find((item) => item.id === id);

  if (!capability) throw new Error(`Unknown SAGE capability: ${id}`);

  return capability;
}
