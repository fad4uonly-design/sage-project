"""Agent registry and orchestrator — capability-aware dispatch."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sage.agents.interfaces import Agent, AgentResult, AgentTask
from sage.events.bus import EventBus
from sage.events.events import AgentEvents, Event
from sage.logging import get_logger

log = get_logger(__name__)


class DefaultAgentOrchestrator:
    def __init__(
        self,
        events: EventBus | None = None,
        *,
        container: Any | None = None,
    ) -> None:
        self._agents: dict[str, Agent] = {}
        self._events = events
        self._container = container

    def register(self, agent: Agent) -> None:
        self._agents[agent.id] = agent
        log.info("agents.registered", id=agent.id, domain=agent.domain)

    def list_agents(self) -> list[dict[str, Any]]:
        return [
            {
                "id": a.id,
                "domain": a.domain,
                "capabilities": sorted(a.capabilities),
            }
            for a in self._agents.values()
        ]

    async def dispatch(self, task: AgentTask) -> AgentResult:
        if not self._agents:
            return AgentResult(
                task_id=task.id,
                agent_id="none",
                success=False,
                output="",
                error="No agents registered",
            )

        # Capability registry scores (domain + declared capabilities)
        cap_boost: dict[str, float] = {}
        if self._container is not None:
            from sage.capabilities.interfaces import CapabilityRegistry

            reg = self._container.try_resolve(CapabilityRegistry)
            if reg:
                try:
                    matches = await reg.find_for_task(task.description)
                    for desc, score in matches:
                        # Map principal name → agent domain affinity
                        cap_boost[desc.domain] = max(cap_boost.get(desc.domain, 0.0), score)
                        cap_boost[desc.principal] = max(
                            cap_boost.get(desc.principal, 0.0), score
                        )
                except Exception:
                    log.exception("agents.capability_lookup_failed")

        scored: list[tuple[float, Agent]] = []
        for agent in self._agents.values():
            score = await agent.can_handle(task)
            score += cap_boost.get(agent.domain, 0.0) * 0.5
            # principal-style ids
            for key, boost in cap_boost.items():
                if key in agent.id or key.replace("_", "") in agent.id.replace("_", ""):
                    score += boost * 0.2
            if task.domain and task.domain == agent.domain:
                score = max(score, 0.9)
            scored.append((score, agent))
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]

        if self._events:
            await self._events.publish(
                Event(
                    type=AgentEvents.TASK_STARTED,
                    payload={
                        "task_id": task.id,
                        "agent_id": best.id,
                        "score": best_score,
                        "domain": best.domain,
                    },
                    source="agents",
                )
            )

        try:
            result = await best.execute(task)
        except Exception as exc:
            log.exception("agents.execute_failed", agent=best.id)
            result = AgentResult(
                task_id=task.id,
                agent_id=best.id,
                success=False,
                output="",
                error=str(exc),
            )

        if self._events:
            evt = AgentEvents.TASK_COMPLETED if result.success else AgentEvents.TASK_FAILED
            await self._events.publish(
                Event(
                    type=evt,
                    payload={
                        "task_id": task.id,
                        "agent_id": result.agent_id,
                        "success": result.success,
                    },
                    source="agents",
                )
            )
        return result

    async def collaborate(self, task: AgentTask, agent_ids: Sequence[str]) -> AgentResult:
        outputs: list[str] = []
        last: AgentResult | None = None
        for aid in agent_ids:
            agent = self._agents.get(aid)
            if agent is None:
                outputs.append(f"[{aid}] not found")
                continue
            result = await agent.execute(task)
            last = result
            outputs.append(f"## {agent.domain} ({agent.id})\n{result.output}")
        return AgentResult(
            task_id=task.id,
            agent_id="collaborative",
            success=True,
            output="\n\n".join(outputs),
            data={"agents": list(agent_ids), "last_success": last.success if last else False},
        )
