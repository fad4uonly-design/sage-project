"""
FastAPI application factory — REST + WebSocket.

Bind to 0.0.0.0 for preview environments. CORS open for local dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from sage import __tagline__, __version__
from sage.api.deps import get_engine, set_engine
from sage.api.schemas import (
    ApprovalDecide,
    AskRequest,
    AskResponse,
    AutomationRun,
    GoalCreate,
    MemoryStore,
    OK,
    ProjectCreate,
    StatusResponse,
    WorkflowStart,
)
from sage.core.engine import SageEngine
from sage.logging import get_logger

log = get_logger(__name__)

API_V1 = "/api/v1"


def create_app(engine: SageEngine) -> FastAPI:
    set_engine(engine)
    app = FastAPI(
        title="SAGE API",
        version="1.0.0",
        description=f"{__tagline__} — versioned HTTP/WS surface (v1)",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).resolve().parent.parent / "ui" / "web"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> Any:
        index_path = static_dir / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return HTMLResponse(
            f"<h1>SAGE v{__version__}</h1><p>Dashboard not found. API at {API_V1}/status</p>"
        )

    @app.get(f"{API_V1}/status", response_model=StatusResponse)
    async def status() -> StatusResponse:
        eng = get_engine()
        health = await eng.health()
        return StatusResponse(
            version=__version__,
            state=eng.state.value,
            env=eng.settings.env,
            modules=eng.registry.names(),
            health_level=health.level.value,
            health_message=health.message,
        )

    @app.get(f"{API_V1}/health")
    async def health() -> dict[str, Any]:
        eng = get_engine()
        h = await eng.health()
        return {
            "level": h.level.value,
            "message": h.message,
            "modules": [
                {
                    "name": m.name,
                    "level": m.level.value,
                    "message": m.message,
                    "critical": m.critical,
                }
                for m in h.modules
            ],
        }

    @app.post(f"{API_V1}/ask", response_model=AskResponse)
    async def ask(body: AskRequest) -> AskResponse:
        eng = get_engine()
        reply = await eng.ask(body.message, user_id=body.user_id)
        return AskResponse(reply=reply)

    # --- Context ---
    @app.get(f"{API_V1}/context")
    async def context(refresh: bool = False) -> dict[str, Any]:
        from sage.context.engine import CognitiveContextEngine

        eng = get_engine()
        cce = eng.container.resolve(CognitiveContextEngine)  # type: ignore[type-abstract]
        if refresh:
            await cce.generate_suggestions()
        ctx = await cce.fuse()
        return ctx.model_dump()

    @app.get(f"{API_V1}/suggestions")
    async def suggestions(limit: int = 20) -> list[dict[str, Any]]:
        from sage.context.engine import CognitiveContextEngine

        eng = get_engine()
        cce = eng.container.resolve(CognitiveContextEngine)  # type: ignore[type-abstract]
        items = await cce.suggestions(limit=limit)
        return [s.model_dump() for s in items]

    @app.post(f"{API_V1}/suggestions/{{suggestion_id}}/dismiss", response_model=OK)
    async def dismiss_suggestion(suggestion_id: str) -> OK:
        from sage.context.engine import CognitiveContextEngine

        eng = get_engine()
        cce = eng.container.resolve(CognitiveContextEngine)  # type: ignore[type-abstract]
        ok = await cce.dismiss_suggestion(suggestion_id)
        return OK(ok=ok)

    # --- Projects / Goals ---
    @app.get(f"{API_V1}/projects")
    async def list_projects() -> list[dict[str, Any]]:
        from sage.projects.manager import ProjectManager

        eng = get_engine()
        pm = eng.container.resolve(ProjectManager)  # type: ignore[type-abstract]
        return [p.model_dump() for p in await pm.list(limit=100)]

    @app.post(f"{API_V1}/projects")
    async def create_project(body: ProjectCreate) -> dict[str, Any]:
        from sage.context.engine import CognitiveContextEngine
        from sage.projects.manager import ProjectManager

        eng = get_engine()
        pm = eng.container.resolve(ProjectManager)  # type: ignore[type-abstract]
        p = await pm.create(
            body.name,
            description=body.description,
            priority=body.priority,
            domain=body.domain,
        )
        if body.activate:
            cce = eng.container.try_resolve(CognitiveContextEngine)  # type: ignore[type-abstract]
            if cce:
                await cce.set_active_project(p.id)
        return p.model_dump()

    @app.get(f"{API_V1}/goals")
    async def list_goals() -> list[dict[str, Any]]:
        from sage.goals.engine import GoalEngine

        eng = get_engine()
        ge = eng.container.resolve(GoalEngine)  # type: ignore[type-abstract]
        return [g.model_dump() for g in await ge.list(limit=100)]

    @app.post(f"{API_V1}/goals")
    async def create_goal(body: GoalCreate) -> dict[str, Any]:
        from sage.goals.engine import GoalEngine

        eng = get_engine()
        ge = eng.container.resolve(GoalEngine)  # type: ignore[type-abstract]
        g = await ge.create(
            body.title,
            horizon=body.horizon,
            priority=body.priority,
            project_id=body.project_id,
            description=body.description,
        )
        return g.model_dump()

    # --- Memory ---
    @app.post(f"{API_V1}/memory")
    async def store_memory(body: MemoryStore) -> dict[str, Any]:
        from sage.memory.interfaces import MemorySystem
        from sage.memory.models import MemoryItem, MemoryType

        eng = get_engine()
        mem = eng.container.resolve(MemorySystem)  # type: ignore[type-abstract]
        mid = await mem.store(
            MemoryItem(
                type=MemoryType.LONG_TERM,
                content=body.content,
                importance=body.importance,
                source="api",
            )
        )
        return {"id": mid}

    @app.get(f"{API_V1}/memory")
    async def recall_memory(q: str = "", limit: int = 20) -> list[dict[str, Any]]:
        from sage.memory.interfaces import MemorySystem

        eng = get_engine()
        mem = eng.container.resolve(MemorySystem)  # type: ignore[type-abstract]
        items = await mem.recall(q, limit=limit)
        return [i.model_dump() for i in items]

    # --- Knowledge ---
    @app.get(f"{API_V1}/knowledge/stats")
    async def kg_stats() -> dict[str, Any]:
        from sage.knowledge.graph.interfaces import KnowledgeGraph

        eng = get_engine()
        kg = eng.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
        return await kg.stats()

    @app.get(f"{API_V1}/knowledge/search")
    async def kg_search(q: str, limit: int = 20) -> list[dict[str, Any]]:
        from sage.knowledge.graph.interfaces import KnowledgeGraph

        eng = get_engine()
        kg = eng.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
        ents = await kg.search_entities(q, limit=limit)
        return [e.model_dump() for e in ents]

    # --- Workflows / Automation / Audit / Approval ---
    @app.get(f"{API_V1}/workflows")
    async def list_workflows() -> list[dict[str, Any]]:
        from sage.workflow.engine import WorkflowEngine

        eng = get_engine()
        wf = eng.container.resolve(WorkflowEngine)  # type: ignore[type-abstract]
        defs = await wf.list_definitions()
        return [
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "version": d.version,
                "tags": d.tags,
            }
            for d in defs
        ]

    @app.post(f"{API_V1}/workflows/run")
    async def run_workflow(body: WorkflowStart) -> dict[str, Any]:
        from sage.workflow.engine import WorkflowEngine

        eng = get_engine()
        wf = eng.container.resolve(WorkflowEngine)  # type: ignore[type-abstract]
        ctx = dict(body.context)
        if body.task:
            ctx["task"] = body.task
        run = await wf.start(body.name, context=ctx, principal="api")
        return run.model_dump()

    @app.get(f"{API_V1}/automations")
    async def list_automations() -> list[dict[str, Any]]:
        from sage.automation.manager import AutomationManager

        eng = get_engine()
        mgr = eng.container.resolve(AutomationManager)  # type: ignore[type-abstract]
        return [j.model_dump() for j in await mgr.list_jobs()]

    @app.post(f"{API_V1}/automations/run")
    async def run_automation(body: AutomationRun) -> dict[str, Any]:
        from sage.automation.manager import AutomationManager

        eng = get_engine()
        mgr = eng.container.resolve(AutomationManager)  # type: ignore[type-abstract]
        return await mgr.run_job(body.name, context=body.context)

    @app.get(f"{API_V1}/audit")
    async def list_audit(limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
        from sage.audit.logger import ExecutionAudit

        eng = get_engine()
        audit = eng.container.resolve(ExecutionAudit)  # type: ignore[type-abstract]
        return [r.model_dump() for r in await audit.list_recent(limit=limit, kind=kind)]

    @app.get(f"{API_V1}/approvals/pending")
    async def pending_approvals() -> list[dict[str, Any]]:
        from sage.approval.engine import ApprovalEngine

        eng = get_engine()
        appr = eng.container.resolve(ApprovalEngine)  # type: ignore[type-abstract]
        return [r.model_dump() for r in await appr.list_pending()]

    @app.post(f"{API_V1}/approvals/{{request_id}}")
    async def decide_approval(request_id: str, body: ApprovalDecide) -> dict[str, Any]:
        from sage.approval.engine import ApprovalEngine

        eng = get_engine()
        appr = eng.container.resolve(ApprovalEngine)  # type: ignore[type-abstract]
        try:
            req = await appr.decide(
                request_id, approve=body.approve, decided_by=body.decided_by
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return req.model_dump()

    # --- Discovery / Reflection ---
    @app.post(f"{API_V1}/discovery/run")
    async def run_discovery(limit: int = 15) -> list[dict[str, Any]]:
        from sage.discovery.engine import DiscoveryEngine

        eng = get_engine()
        disc = eng.container.resolve(DiscoveryEngine)  # type: ignore[type-abstract]
        insights = await disc.discover(limit=limit)
        return [i.model_dump() for i in insights]

    @app.get(f"{API_V1}/discovery")
    async def list_discovery(limit: int = 30) -> list[dict[str, Any]]:
        from sage.discovery.engine import DiscoveryEngine

        eng = get_engine()
        disc = eng.container.resolve(DiscoveryEngine)  # type: ignore[type-abstract]
        return [i.model_dump() for i in await disc.list_recent(limit=limit)]

    @app.post(f"{API_V1}/reflect")
    async def run_reflect() -> dict[str, Any]:
        from sage.reflection.engine import ReflectionEngine

        eng = get_engine()
        re_ = eng.container.resolve(ReflectionEngine)  # type: ignore[type-abstract]
        r = await re_.reflect()
        return r.model_dump()

    @app.get(f"{API_V1}/agents")
    async def list_agents() -> list[dict[str, Any]]:
        from sage.agents.interfaces import AgentOrchestrator

        eng = get_engine()
        orch = eng.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
        return orch.list_agents()

    @app.get(f"{API_V1}/skills")
    async def list_skills() -> list[dict[str, Any]]:
        from sage.skills.interfaces import SkillLibrary

        eng = get_engine()
        lib = eng.container.resolve(SkillLibrary)  # type: ignore[type-abstract]
        return [m.model_dump() for m in lib.list_skills()]

    @app.get(f"{API_V1}/tools")
    async def list_tools() -> list[dict[str, Any]]:
        from sage.tools.interfaces import ToolManager

        eng = get_engine()
        tm = eng.container.resolve(ToolManager)  # type: ignore[type-abstract]
        return [t.model_dump() for t in tm.list_tools()]

    # --- WebSocket chat ---
    @app.websocket(f"{API_V1}/ws/chat")
    async def ws_chat(ws: WebSocket) -> None:
        await ws.accept()
        eng = get_engine()
        from sage.conversation.interfaces import ConversationEngine

        conv = eng.container.resolve(ConversationEngine)  # type: ignore[type-abstract]
        session = await conv.start_session(user_id="ws")
        await ws.send_json({"type": "ready", "session_id": session.id, "version": __version__})
        try:
            while True:
                data = await ws.receive_json()
                msg = str(data.get("message") or "").strip()
                if not msg:
                    continue
                if msg in {"/quit", "/close"}:
                    break
                turn = await conv.respond(session.id, msg)
                await ws.send_json(
                    {
                        "type": "reply",
                        "user": msg,
                        "assistant": turn.assistant_message,
                        "meta": turn.metadata,
                    }
                )
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.exception("api.ws_error")
            try:
                await ws.send_json({"type": "error", "error": str(exc)})
            except Exception:
                pass
        finally:
            try:
                await conv.end_session(session.id)
            except Exception:
                pass

    return app
