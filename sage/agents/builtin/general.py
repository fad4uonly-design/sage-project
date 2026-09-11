"""Built-in agents shipped with SAGE core."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sage.agents.base import BaseAgent
from sage.agents.interfaces import AgentResult, AgentTask

if TYPE_CHECKING:
    from sage.core.container import Container


class GeneralAssistantAgent(BaseAgent):
    domain = "general"
    capabilities = frozenset({"help", "assist", "question", "explain"})

    def __init__(self, container: Container, agent_id: str | None = None) -> None:
        super().__init__(agent_id)
        self._container = container

    async def execute(self, task: AgentTask) -> AgentResult:
        from sage.models.interfaces import CompletionRequest, Message, ModelRouter

        router = self._container.try_resolve(ModelRouter)
        if router is None:
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                success=True,
                output=f"Acknowledged task: {task.description}",
            )
        lm = router.get_language_model()
        resp = await lm.complete(
            CompletionRequest(
                messages=[
                    Message(
                        role="system",
                        content="You are a SAGE general assistant agent. Be concise and helpful.",
                    ),
                    Message(role="user", content=task.description),
                ]
            )
        )
        return AgentResult(
            task_id=task.id,
            agent_id=self.id,
            success=True,
            output=resp.content,
            data={"provider": resp.provider, "model": resp.model},
        )


class ResearchAgent(BaseAgent):
    domain = "research"
    capabilities = frozenset({"research", "investigate", "find", "search", "lookup"})

    def __init__(self, container: Container, agent_id: str | None = None) -> None:
        super().__init__(agent_id)
        self._container = container

    async def execute(self, task: AgentTask) -> AgentResult:
        from sage.knowledge.interfaces import KnowledgeManager
        from sage.memory.interfaces import MemorySystem

        parts: list[str] = [f"Research brief for: {task.description}"]
        km = self._container.try_resolve(KnowledgeManager)
        mem = self._container.try_resolve(MemorySystem)

        if km:
            hits = await km.search(task.description, limit=5)
            if hits:
                parts.append("Knowledge hits:")
                for h in hits:
                    parts.append(f"- [{h.category}] {h.title}: {h.snippet[:160]}")
            else:
                parts.append("No knowledge documents matched.")
        if mem:
            memories = await mem.recall(task.description, limit=5)
            if memories:
                parts.append("Related memories:")
                for m in memories:
                    parts.append(f"- ({m.type.value}) {m.content[:160]}")

        return AgentResult(
            task_id=task.id,
            agent_id=self.id,
            success=True,
            output="\n".join(parts),
        )


class PlanningAgent(BaseAgent):
    domain = "planning"
    capabilities = frozenset({"plan", "schedule", "goal", "roadmap", "organize"})

    def __init__(self, container: Container, agent_id: str | None = None) -> None:
        super().__init__(agent_id)
        self._container = container

    async def execute(self, task: AgentTask) -> AgentResult:
        from sage.planning.interfaces import PlanningEngine

        engine = self._container.try_resolve(PlanningEngine)
        if engine is None:
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                success=False,
                output="",
                error="Planning engine unavailable",
            )
        goal = await engine.create_goal(task.description, priority=task.priority)
        plan = await engine.plan(goal.id)
        lines = [f"Goal: {goal.description}", f"Plan: {plan.title}", "Steps:"]
        for step in plan.steps:
            lines.append(f"  {step.index + 1}. {step.title} — {step.detail}")
        return AgentResult(
            task_id=task.id,
            agent_id=self.id,
            success=True,
            output="\n".join(lines),
            data={"goal_id": goal.id, "plan_id": plan.id},
        )


class DocumentAgent(BaseAgent):
    domain = "documents"
    capabilities = frozenset({"document", "summarize", "ingest", "pdf", "file", "analyze"})

    def __init__(self, container: Container, agent_id: str | None = None) -> None:
        super().__init__(agent_id)
        self._container = container

    async def execute(self, task: AgentTask) -> AgentResult:
        from sage.knowledge.interfaces import KnowledgeManager

        km = self._container.try_resolve(KnowledgeManager)
        path = (task.metadata or {}).get("path")
        if km and path:
            doc = await km.ingest(path)
            summary = await km.summarize(doc.id)
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                success=True,
                output=f"Ingested «{doc.title}» [{doc.category}]\nSummary: {summary}",
                data={"document_id": doc.id},
            )
        if km:
            hits = await km.search(task.description, limit=5)
            if not hits:
                return AgentResult(
                    task_id=task.id,
                    agent_id=self.id,
                    success=True,
                    output="No matching documents. Provide metadata.path to ingest a file.",
                )
            lines = ["Document matches:"] + [
                f"- {h.title} ({h.category}): {h.snippet[:120]}" for h in hits
            ]
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                success=True,
                output="\n".join(lines),
            )
        return AgentResult(
            task_id=task.id,
            agent_id=self.id,
            success=False,
            output="",
            error="Knowledge manager unavailable",
        )
