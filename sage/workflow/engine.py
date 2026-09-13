"""
Workflow Engine — sequential / parallel / conditional / loop execution
with retries, checkpoints, approval gates, and resume.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Protocol, runtime_checkable

from sage.logging import get_logger
from sage.utils.time import utcnow_iso
from sage.workflow.models import (
    StepRunRecord,
    StepType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStepDef,
)
from sage.workflow.store import WorkflowStore

log = get_logger(__name__)

_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


@runtime_checkable
class WorkflowEngine(Protocol):
    async def register(self, definition: WorkflowDefinition) -> WorkflowDefinition: ...

    async def get_definition(self, definition_id: str) -> WorkflowDefinition | None: ...

    async def list_definitions(self) -> list[WorkflowDefinition]: ...

    async def start(
        self,
        definition_id: str,
        *,
        context: dict[str, Any] | None = None,
        principal: str = "core",
    ) -> WorkflowRun: ...

    async def resume(self, run_id: str) -> WorkflowRun: ...

    async def cancel(self, run_id: str) -> WorkflowRun: ...

    async def get_run(self, run_id: str) -> WorkflowRun | None: ...


class DefaultWorkflowEngine:
    def __init__(self, store: WorkflowStore, container: Any) -> None:
        self._store = store
        self._container = container
        self._definitions: dict[str, WorkflowDefinition] = {}

    async def register(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        self._definitions[definition.id] = definition
        # Also index by name for convenience
        self._definitions[definition.name] = definition
        await self._store.save_definition(definition)
        log.info("workflow.registered", id=definition.id, name=definition.name)
        return definition

    async def get_definition(self, definition_id: str) -> WorkflowDefinition | None:
        if definition_id in self._definitions:
            return self._definitions[definition_id]
        return await self._store.load_definition(definition_id)

    async def list_definitions(self) -> list[WorkflowDefinition]:
        seen: set[str] = set()
        out: list[WorkflowDefinition] = []
        for d in self._definitions.values():
            if d.id in seen:
                continue
            seen.add(d.id)
            out.append(d)
        # merge DB
        for d in await self._store.list_definitions():
            if d.id not in seen:
                out.append(d)
                seen.add(d.id)
        return out

    async def start(
        self,
        definition_id: str,
        *,
        context: dict[str, Any] | None = None,
        principal: str = "core",
    ) -> WorkflowRun:
        definition = await self.get_definition(definition_id)
        if definition is None:
            raise KeyError(f"Unknown workflow: {definition_id}")
        run = WorkflowRun(
            definition_id=definition.id,
            definition_name=definition.name,
            status=WorkflowStatus.RUNNING,
            context=dict(context or {}),
            current_step=definition.entry,
            principal=principal,
            checkpoint={"next": definition.entry, "visited": []},
        )
        await self._store.save_run(run)
        await self._audit(
            kind="workflow",
            status="started",
            workflow_run_id=run.id,
            summary=f"Started {definition.name}",
            principal=principal,
        )
        return await self._execute(run, definition)

    async def resume(self, run_id: str) -> WorkflowRun:
        run = await self._store.load_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status not in {
            WorkflowStatus.PAUSED,
            WorkflowStatus.WAITING_APPROVAL,
            WorkflowStatus.PENDING,
        }:
            if run.status == WorkflowStatus.RUNNING:
                pass
            else:
                return run
        definition = await self.get_definition(run.definition_id)
        if definition is None:
            raise KeyError(run.definition_id)
        run.status = WorkflowStatus.RUNNING
        run.updated_at = utcnow_iso()
        return await self._execute(run, definition)

    async def cancel(self, run_id: str) -> WorkflowRun:
        run = await self._store.load_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run.status = WorkflowStatus.CANCELLED
        run.completed_at = utcnow_iso()
        run.updated_at = run.completed_at
        await self._store.save_run(run)
        await self._audit(
            kind="workflow",
            status="cancelled",
            workflow_run_id=run.id,
            summary=f"Cancelled {run.definition_name}",
            principal=run.principal,
        )
        return run

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        return await self._store.load_run(run_id)

    async def _execute(
        self, run: WorkflowRun, definition: WorkflowDefinition
    ) -> WorkflowRun:
        steps = definition.step_map()
        next_id: str | None = run.current_step or definition.entry
        safety = 0
        max_steps = 200

        while next_id and safety < max_steps:
            safety += 1
            if run.status == WorkflowStatus.CANCELLED:
                break
            step = steps.get(next_id)
            if step is None:
                run.status = WorkflowStatus.FAILED
                run.error = f"Unknown step: {next_id}"
                break

            # when guard
            if step.when and not self._eval_condition(step.when, run.context):
                next_id = step.next
                run.current_step = next_id
                run.checkpoint = {
                    "next": next_id,
                    "visited": run.checkpoint.get("visited", []) + [step.id + ":skipped"],
                }
                continue

            record = StepRunRecord(step_id=step.id, status="running")
            t0 = time.perf_counter()
            attempt = 0
            last_err: str | None = None
            output: Any = None

            while attempt < max(1, step.retry.max_attempts):
                attempt += 1
                record.attempt = attempt
                try:
                    output = await self._run_step(step, run)
                    record.status = "succeeded"
                    record.output = output
                    last_err = None
                    break
                except _ApprovalNeededError as appr:
                    record.status = "waiting_approval"
                    record.error = str(appr)
                    run.status = WorkflowStatus.WAITING_APPROVAL
                    run.error = str(appr)
                    run.current_step = step.id
                    run.checkpoint = {
                        "next": step.id,
                        "approval_request_id": appr.request_id,
                        "visited": run.checkpoint.get("visited", []),
                    }
                    record.completed_at = utcnow_iso()
                    run.step_history.append(record)
                    run.updated_at = utcnow_iso()
                    await self._store.save_run(run)
                    await self._store.save_step(run.id, record)
                    await self._audit(
                        kind="workflow",
                        status="waiting_approval",
                        workflow_run_id=run.id,
                        summary=f"Waiting approval at {step.id}",
                        principal=run.principal,
                        detail={"approval_request_id": appr.request_id},
                    )
                    return run
                except Exception as exc:
                    last_err = str(exc)
                    log.warning(
                        "workflow.step_error",
                        run=run.id,
                        step=step.id,
                        attempt=attempt,
                        error=last_err,
                    )
                    if attempt < step.retry.max_attempts and step.retry.delay_seconds:
                        await asyncio.sleep(step.retry.delay_seconds)
                    elif attempt < step.retry.max_attempts:
                        continue
                    else:
                        break

            duration = (time.perf_counter() - t0) * 1000
            record.completed_at = utcnow_iso()

            if last_err and record.status != "succeeded":
                record.status = "failed"
                record.error = last_err
                run.step_history.append(record)
                await self._store.save_step(run.id, record)
                await self._audit(
                    kind="workflow",
                    status="step_failed",
                    workflow_run_id=run.id,
                    summary=f"Step {step.id} failed: {last_err}",
                    principal=run.principal,
                    duration_ms=duration,
                )
                if step.on_error == "continue" and step.next:
                    next_id = step.next
                    continue
                if step.on_error and step.on_error not in {"fail", "continue"}:
                    next_id = step.on_error
                    continue
                run.status = WorkflowStatus.FAILED
                run.error = last_err
                run.current_step = step.id
                break

            # success path — store output
            if step.input_key:
                run.context[step.input_key] = output
            run.context[f"steps.{step.id}"] = output
            run.step_history.append(record)
            await self._store.save_step(run.id, record)
            await self._audit(
                kind="workflow",
                status="step_ok",
                workflow_run_id=run.id,
                summary=f"Step {step.id} ({step.type.value}) ok",
                principal=run.principal,
                duration_ms=duration,
                skill_id=step.skill_id,
                tool_name=step.tool_name,
            )

            # Determine next
            if step.type == StepType.CONDITION:
                branch = bool(output)
                next_id = step.if_true if branch else step.if_false
            else:
                next_id = step.next

            run.current_step = next_id
            visited = list(run.checkpoint.get("visited") or [])
            visited.append(step.id)
            run.checkpoint = {"next": next_id, "visited": visited}
            run.updated_at = utcnow_iso()
            await self._store.save_run(run)

        if run.status == WorkflowStatus.RUNNING:
            if next_id is None:
                run.status = WorkflowStatus.SUCCEEDED
                run.result = {
                    "context_keys": list(run.context.keys()),
                    "last": run.context.get("result")
                    or run.context.get("summary")
                    or run.step_history[-1].output
                    if run.step_history
                    else None,
                }
                run.completed_at = utcnow_iso()
            elif safety >= max_steps:
                run.status = WorkflowStatus.FAILED
                run.error = "Max step safety limit reached"
                run.completed_at = utcnow_iso()

        run.updated_at = utcnow_iso()
        await self._store.save_run(run)
        await self._audit(
            kind="workflow",
            status=run.status.value,
            workflow_run_id=run.id,
            summary=f"Workflow {run.definition_name} → {run.status.value}",
            principal=run.principal,
            detail={"error": run.error} if run.error else {},
        )
        return run

    async def _run_step(self, step: WorkflowStepDef, run: WorkflowRun) -> Any:
        params = self._render(step.params, run.context)
        task = str(params.get("task") or run.context.get("task") or run.definition_name)

        if step.type == StepType.SET:
            for k, v in params.items():
                run.context[k] = self._render_value(v, run.context)
            return params

        if step.type == StepType.CONDITION:
            expr = step.when or params.get("expr") or "false"
            return self._eval_condition(str(expr), run.context)

        if step.type == StepType.SKILL:
            from sage.skills.interfaces import SkillLibrary

            lib = self._container.try_resolve(SkillLibrary)
            if not lib:
                raise RuntimeError("SkillLibrary unavailable")
            skill_id = step.skill_id or params.get("skill_id")
            if not skill_id:
                raise ValueError(f"Step {step.id}: skill_id required")
            result = await lib.invoke(
                skill_id,
                task=task,
                params=params,
                context={
                    "memories": run.context.get("memories") or [],
                    "graph_facts": run.context.get("graph_facts") or [],
                    "documents": run.context.get("documents") or [],
                    **{k: v for k, v in run.context.items() if not k.startswith("_")},
                },
                principal=run.principal,
            )
            if not result.success:
                raise RuntimeError(result.error or f"Skill {skill_id} failed")
            return {
                "output": result.output,
                "data": result.data,
                "confidence": result.confidence,
                "skill_id": skill_id,
            }

        if step.type == StepType.TOOL:
            from sage.tools.interfaces import ToolManager

            tm = self._container.try_resolve(ToolManager)
            if not tm:
                raise RuntimeError("ToolManager unavailable")
            name = step.tool_name or params.get("tool")
            if not name:
                raise ValueError(f"Step {step.id}: tool_name required")
            # Approval gate for tools
            await self._maybe_approve("tool", name, f"workflow:{run.id}", run)
            tool_params = {k: v for k, v in params.items() if k not in {"task", "tool"}}
            result = await tm.invoke(name, **tool_params)
            if not result.success:
                raise RuntimeError(result.error or f"Tool {name} failed")
            return result.output

        if step.type == StepType.AGENT:
            from sage.agents.interfaces import AgentOrchestrator, AgentTask

            orch = self._container.try_resolve(AgentOrchestrator)
            if not orch:
                raise RuntimeError("AgentOrchestrator unavailable")
            domain = step.agent_domain or params.get("domain")
            result = await orch.dispatch(
                AgentTask(
                    description=task,
                    domain=domain,
                    metadata={"workflow_run_id": run.id, "collab_depth": 0},
                )
            )
            if not result.success:
                raise RuntimeError(result.error or "Agent failed")
            return {"output": result.output, "agent_id": result.agent_id, "data": result.data}

        if step.type == StepType.APPROVAL:
            resource = str(params.get("resource_id") or step.skill_id or "workflow")
            rtype = str(params.get("resource_type") or "workflow")
            await self._maybe_approve(rtype, resource, f"step:{step.id}", run, force=True)
            return {"approved": True}

        if step.type == StepType.PARALLEL:
            child_ids = step.steps or list(params.get("steps") or [])
            smap = {}
            # Look up definition from run
            definition = await self.get_definition(run.definition_id)
            if not definition:
                raise RuntimeError("definition missing")
            smap = definition.step_map()
            coros = []
            for cid in child_ids:
                child = smap.get(cid)
                if child:
                    coros.append(self._run_step(child, run))
            if not coros:
                return []
            results = await asyncio.gather(*coros, return_exceptions=True)
            out: list[dict[str, str]] = []
            for r in results:
                out.append(r if isinstance(r, dict) else {"error": str(r)})
            return out

        if step.type == StepType.LOOP:
            key = step.over or params.get("over")
            body_id = step.body or params.get("body")
            items = run.context.get(str(key)) or params.get("items") or []
            if not isinstance(items, list):
                items = list(items) if items else []
            definition = await self.get_definition(run.definition_id)
            body = definition.step_map().get(str(body_id)) if definition else None
            if body is None:
                raise ValueError(f"Loop body step not found: {body_id}")
            outputs = []
            for i, item in enumerate(items):
                run.context["loop.item"] = item
                run.context["loop.index"] = i
                outputs.append(await self._run_step(body, run))
            return outputs

        if step.type == StepType.MEMORY:
            from sage.memory.interfaces import MemorySystem
            from sage.memory.models import MemoryItem, MemoryType

            mem = self._container.try_resolve(MemorySystem)
            if not mem:
                return None
            content = str(params.get("content") or task)
            mid = await mem.store(
                MemoryItem(
                    type=MemoryType.FACT,
                    content=content,
                    importance=float(params.get("importance", 0.6)),
                    source="workflow",
                    source_ref=run.id,
                    tags=["workflow", run.definition_name],
                )
            )
            return {"memory_id": mid}

        if step.type == StepType.NOTIFY:
            msg = str(params.get("message") or task)
            log.info("workflow.notify", run=run.id, message=msg[:200])
            return {"notified": True, "message": msg}

        if step.type == StepType.DECISION:
            # Use weighted comparison skill if available
            from sage.skills.interfaces import SkillLibrary

            lib = self._container.try_resolve(SkillLibrary)
            if lib:
                result = await lib.invoke(
                    "skill_decision_weighted",
                    task=task,
                    params=params,
                    context=run.context,
                    principal=run.principal,
                )
                if result.success:
                    return {"output": result.output, "data": result.data}
            return {"output": f"Decision deferred: {task}"}

        raise ValueError(f"Unsupported step type: {step.type}")

    async def _maybe_approve(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
        run: WorkflowRun,
        *,
        force: bool = False,
    ) -> None:
        from sage.approval.engine import ApprovalEngine
        from sage.approval.models import ApprovalStatus
        from sage.config.settings import Settings

        engine = self._container.try_resolve(ApprovalEngine)
        if not engine:
            return
        settings = self._container.try_resolve(Settings)
        test_mode = bool(settings and settings.env == "test")
        decision = await engine.check(
            resource_type,
            resource_id,
            action,
            principal=run.principal,
            payload={"workflow_run_id": run.id},
            auto_approve_in_test=test_mode,
        )
        if decision.allowed:
            return
        if decision.status == ApprovalStatus.PENDING and decision.request:
            raise _ApprovalNeededError(decision.request.id, decision.message)
        raise RuntimeError(decision.message or "Approval denied")

    def _render(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {k: self._render_value(v, context) for k, v in params.items()}

    def _render_value(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):

            def repl(m: re.Match[str]) -> str:
                v = self._lookup(context, m.group(1))
                return "" if v is None else str(v)

            if _TEMPLATE_RE.search(value):
                return _TEMPLATE_RE.sub(repl, value)
            return value
        if isinstance(value, dict):
            return {k: self._render_value(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render_value(v, context) for v in value]
        return value

    def _lookup(self, context: dict[str, Any], path: str) -> Any:
        cur: Any = context
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def _eval_condition(self, expr: str, context: dict[str, Any]) -> bool:
        expr = expr.strip()
        if expr.lower() in {"true", "1", "yes"}:
            return True
        if expr.lower() in {"false", "0", "no", ""}:
            return False
        # equality: key == value
        if "==" in expr:
            left, _, right = expr.partition("==")
            lv = self._lookup(context, left.strip())
            rv = right.strip().strip("'\"")
            return str(lv) == rv
        if "!=" in expr:
            left, _, right = expr.partition("!=")
            lv = self._lookup(context, left.strip())
            rv = right.strip().strip("'\"")
            return str(lv) != rv
        # truthiness of context key
        val = self._lookup(context, expr)
        return bool(val)

    async def _audit(self, **kwargs: Any) -> None:
        from sage.audit.logger import ExecutionAudit

        audit = self._container.try_resolve(ExecutionAudit)
        if audit:
            try:
                await audit.record(**kwargs)
            except Exception:
                log.exception("workflow.audit_failed")


class _ApprovalNeededError(Exception):
    def __init__(self, request_id: str, message: str) -> None:
        self.request_id = request_id
        super().__init__(message)
