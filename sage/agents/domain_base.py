"""
Domain Agent base — consistent internal architecture for all specialists.

Agent
├── Capability Profile
├── Domain Knowledge (KG + seeds)
├── Reasoning Strategy Selector
├── Workflow Library
├── Tool Manager
├── Memory Interface
├── Knowledge Graph Interface
├── Planner
├── Decision Engine
└── Response Generator
"""

from __future__ import annotations

import re
from typing import Any

from sage.agents.interfaces import AgentResult, AgentTask
from sage.agents.profile import AgentCapabilityProfile
from sage.agents.workflows.library import WorkflowLibrary, WorkflowResult
from sage.logging import get_logger
from sage.utils.ids import new_id

log = get_logger(__name__)


class DomainAgent:
    """
    Shared backbone for Agriculture, Finance, Business, Programming, etc.

    Subclasses implement:
      - profile (class attribute or property)
      - register_workflows()
      - maybe override select_workflow / enrich_domain_context
    """

    profile: AgentCapabilityProfile

    def __init__(self, container: Any, agent_id: str | None = None) -> None:
        self._container = container
        self._id = agent_id or f"agent_{self.profile.principal}"
        self.workflows = WorkflowLibrary()
        self.register_workflows()

    # --- Agent protocol ---

    @property
    def id(self) -> str:
        return self._id

    @property
    def domain(self) -> str:
        return self.profile.domain

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self.profile.capabilities)

    async def can_handle(self, task: AgentTask) -> float:
        if task.domain and task.domain == self.domain:
            return 0.95
        desc = task.description.lower()
        hits = sum(1 for c in self.profile.capabilities if c in desc)
        score = 0.15
        if hits:
            score = min(0.9, 0.35 + hits * 0.15)
        # workflow trigger boost
        matches = self.workflows.match(desc, domain=self.domain, limit=1)
        if matches:
            score = max(score, 0.4 + matches[0][1] * 0.5)
        if self.domain in desc:
            score = max(score, 0.7)
        return score

    async def execute(self, task: AgentTask) -> AgentResult:
        try:
            ctx = await self.build_context(task)
            wf_match = self.workflows.match(task.description, domain=self.domain, limit=1)
            if wf_match and wf_match[0][1] >= 0.25:
                wf, _score = wf_match[0]
                result = await self.workflows.run(
                    wf.id, ctx, params={"task": task.description, **(task.metadata or {})}
                )
                text = await self.generate_response(task, ctx, workflow_result=result)
                # Optional collaboration
                collab = await self.maybe_collaborate(task, ctx, result)
                if collab:
                    text = text + "\n\n" + collab
                return AgentResult(
                    task_id=task.id,
                    agent_id=self.id,
                    success=result.success,
                    output=text,
                    data={
                        "workflow_id": result.workflow_id,
                        "workflow": result.workflow_name,
                        "domain": self.domain,
                        **result.data,
                    },
                    error=result.error,
                )

            # No strong workflow — reason + plan + respond
            text = await self.default_execute(task, ctx)
            collab = await self.maybe_collaborate(task, ctx, None)
            if collab:
                text = text + "\n\n" + collab
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                success=True,
                output=text,
                data={"domain": self.domain, "mode": "default"},
            )
        except Exception as exc:
            log.exception("domain_agent.failed", agent=self.id)
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                success=False,
                output="",
                error=str(exc),
            )

    # --- architecture hooks ---

    def register_workflows(self) -> None:
        """Subclass registers domain workflows into self.workflows."""

    async def build_context(self, task: AgentTask) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "task": task.description,
            "domain": self.domain,
            "agent_id": self.id,
            "memories": [],
            "graph_facts": [],
            "documents": [],
            "preferences": {},
        }
        # Memory
        from sage.memory.interfaces import MemorySystem

        mem = self._container.try_resolve(MemorySystem)
        if mem:
            items = await mem.recall(task.description, limit=6)
            ctx["memories"] = [m.content for m in items]

        # Knowledge graph
        from sage.knowledge.graph.interfaces import KnowledgeGraph

        kg = self._container.try_resolve(KnowledgeGraph)
        if kg:
            entities = await kg.search_entities(task.description, limit=5)
            facts: list[str] = []
            for ent in entities:
                for t in await kg.neighbors(ent.id, direction="both", limit=4):
                    facts.append(f"{t.subject.name} —{t.relation}→ {t.object.name}")
            ctx["graph_facts"] = facts[:12]
            ctx["kg"] = kg

        # Retrieval (optional richer)
        from sage.retrieval.interfaces import Retriever

        retriever = self._container.try_resolve(Retriever)
        if retriever:
            result = await retriever.retrieve(task.description, limit=8)
            ctx["memories"] = list(dict.fromkeys(ctx["memories"] + result.memories))
            ctx["graph_facts"] = list(dict.fromkeys(ctx["graph_facts"] + result.graph_facts))
            ctx["documents"] = result.documents
            ctx["retrieval_confidence"] = result.overall_confidence

        await self.enrich_domain_context(task, ctx)
        return ctx

    async def enrich_domain_context(self, task: AgentTask, ctx: dict[str, Any]) -> None:
        """Subclass hook for domain-specific context."""

    def select_strategy(self, task: AgentTask, ctx: dict[str, Any]) -> str | None:
        """Pick preferred reasoning strategy name from profile."""
        prefs = self.profile.reasoning_strategies
        return prefs[0] if prefs else None

    async def reason(self, problem: str, ctx: dict[str, Any]) -> str:
        from sage.reasoning.interfaces import ReasoningEngine
        from sage.reasoning.models import ReasoningContext, StrategyKind

        engine = self._container.try_resolve(ReasoningEngine)
        if not engine:
            return ""
        strategy_name = self.select_strategy(
            AgentTask(description=problem, domain=self.domain), ctx
        )
        strategy = StrategyKind.AUTO
        if strategy_name:
            try:
                strategy = StrategyKind(strategy_name)
            except ValueError:
                strategy = StrategyKind.AUTO
        result = await engine.reason(
            problem,
            context=ReasoningContext(
                memories=list(ctx.get("memories") or []),
                graph_facts=list(ctx.get("graph_facts") or []),
                documents=list(ctx.get("documents") or []),
                knowledge=list(ctx.get("documents") or []),
            ),
            strategy=strategy,
            use_retrieval=False,
        )
        ctx["reasoning"] = result
        if result.explainability:
            return result.explainability.format()
        return f"**{result.strategy.value}** ({result.confidence:.2f})\n\n{result.conclusion}"

    async def plan(self, goal: str, ctx: dict[str, Any]) -> str:
        from sage.planning.interfaces import PlanningEngine

        engine = self._container.try_resolve(PlanningEngine)
        if not engine:
            return ""
        g = await engine.create_goal(goal, priority=0.7, metadata={"domain": self.domain})
        plan = await engine.plan(g.id)
        ctx["plan"] = plan
        lines = [f"**Plan:** {plan.title}", ""]
        for step in plan.steps:
            lines.append(f"{step.index + 1}. {step.title} — {step.detail}")
        return "\n".join(lines)

    async def decide(self, request: Any) -> Any:
        from sage.decision.engine import DecisionEngine

        engine = self._container.try_resolve(DecisionEngine)
        if not engine:
            return None
        return await engine.decide(request)

    async def use_tool(self, name: str, **params: Any) -> Any:
        from sage.tools.interfaces import ToolManager

        tm = self._container.try_resolve(ToolManager)
        if not tm:
            return None
        return await tm.invoke(name, **params)

    async def remember(self, content: str, *, importance: float = 0.7) -> str | None:
        from sage.memory.interfaces import MemorySystem
        from sage.memory.models import MemoryItem, MemoryType

        mem = self._container.try_resolve(MemorySystem)
        if not mem:
            return None
        return await mem.store(
            MemoryItem(
                type=MemoryType.FACT,
                content=content,
                importance=importance,
                confidence=0.8,
                source=self.profile.principal,
                tags=[self.domain, "agent"],
            )
        )

    async def default_execute(self, task: AgentTask, ctx: dict[str, Any]) -> str:
        parts: list[str] = [f"### {self.profile.display_name}", ""]
        reasoning = await self.reason(task.description, ctx)
        if reasoning:
            parts.append(reasoning)
        # Light plan for how/plan-ish requests
        if re.search(r"\b(plan|schedule|how to|steps|roadmap)\b", task.description, re.I):
            plan_text = await self.plan(task.description, ctx)
            if plan_text:
                parts.extend(["", plan_text])
        if ctx.get("graph_facts"):
            parts.extend(["", "**Domain knowledge (graph):**"])
            for f in ctx["graph_facts"][:6]:
                parts.append(f"- {f}")
        return "\n".join(parts)

    async def generate_response(
        self,
        task: AgentTask,
        ctx: dict[str, Any],
        *,
        workflow_result: WorkflowResult | None = None,
    ) -> str:
        parts = [f"### {self.profile.display_name}", ""]
        if workflow_result:
            parts.append(f"**Workflow:** {workflow_result.workflow_name}")
            parts.append("")
            parts.append(workflow_result.output or "(no output)")
            if workflow_result.steps:
                parts.append("")
                parts.append("**Steps completed:**")
                for s in workflow_result.steps:
                    title = s.get("title") or s.get("id") or "step"
                    status = s.get("status", "done")
                    parts.append(f"- {title} [{status}]")
        if ctx.get("graph_facts") and not (workflow_result and workflow_result.output):
            parts.append("")
            parts.append("**Graph context:**")
            for f in ctx["graph_facts"][:5]:
                parts.append(f"- {f}")
        return "\n".join(parts)

    async def maybe_collaborate(
        self,
        task: AgentTask,
        ctx: dict[str, Any],
        workflow_result: WorkflowResult | None,
    ) -> str:
        """
        Cross-agent collaboration when task needs another domain.

        Returns a section string or empty. Depth-limited to avoid recursion loops.
        """
        meta = dict(task.metadata or {})
        depth = int(meta.get("collab_depth") or 0)
        if depth >= 1:
            # Already inside a collaboration hop — do not fan out further
            return ""
        if meta.get("disable_collaboration"):
            return ""

        collab_domains = list(self.profile.collaborate_with)
        if not collab_domains:
            return ""

        desc = task.description.lower()
        needed: list[str] = []
        triggers = {
            "finance": (
                "cost",
                "budget",
                "price",
                "loan",
                "profit",
                "expense",
                "cash flow",
                "investment",
                "roi",
            ),
            "business": ("market", "competitor", "swot", "pricing strategy", "kpi", "go-to-market"),
            "agriculture": ("crop", "soil", "irrigation", "harvest", "pest", "fertilizer"),
            "programming": ("code", "api", "debug", "refactor", "python", "git"),
            "planning": ("schedule", "timeline", "milestone"),
        }
        for domain in collab_domains:
            keys = triggers.get(domain, ())
            if any(k in desc for k in keys) and domain != self.domain:
                needed.append(domain)

        if workflow_result and workflow_result.data.get("collaborate"):
            for d in workflow_result.data["collaborate"]:
                if d not in needed and d != self.domain:
                    needed.append(d)

        # Never call back into the parent domain
        parent = meta.get("parent_domain")
        if parent:
            needed = [d for d in needed if d != parent]

        if not needed:
            return ""

        from sage.agents.interfaces import AgentOrchestrator, AgentTask as AT

        orch = self._container.try_resolve(AgentOrchestrator)
        if not orch:
            return ""

        sections: list[str] = ["---", "### Specialist collaboration"]
        for domain in needed[:2]:
            sub = await orch.dispatch(
                AT(
                    description=task.description,
                    domain=domain,
                    metadata={
                        "collaborator_of": self.id,
                        "parent_domain": self.domain,
                        "collab_depth": depth + 1,
                        "disable_collaboration": False,
                    },
                )
            )
            if sub.success and sub.output:
                sections.append(f"\n#### Input from {domain} agent\n")
                body = sub.output.strip()
                # Strip nested collaboration sections from collaborators
                if "### Specialist collaboration" in body:
                    body = body.split("### Specialist collaboration")[0].strip()
                if len(body) > 2500:
                    body = body[:2500] + "\n…"
                sections.append(body)
        if len(sections) <= 2:
            return ""
        return "\n".join(sections)
