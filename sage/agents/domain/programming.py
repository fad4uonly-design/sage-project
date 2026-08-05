"""Programming Agent — code, debug, docs, architecture, tests, git, plugins."""

from __future__ import annotations

import re
import textwrap
from typing import Any

from sage.agents.domain_base import DomainAgent
from sage.agents.profile import AgentCapabilityProfile
from sage.agents.workflows.library import Workflow, WorkflowResult, WorkflowStep, new_workflow_id


class ProgrammingAgent(DomainAgent):
    profile = AgentCapabilityProfile(
        principal="programming_agent",
        domain="programming",
        display_name="Programming Agent",
        description="Code generation, refactoring, debugging, docs, tests, git, SAGE plugins",
        capabilities=[
            "code",
            "python",
            "debug",
            "refactor",
            "test",
            "api",
            "git",
            "documentation",
            "architecture",
            "plugin",
            "implement",
            "function",
            "class",
            "bug",
        ],
        tools=[],
        permissions=["filesystem.read", "memory.read", "memory.write"],
        reasoning_strategies=["logical", "mathematical", "multi_step"],
        workflows=[
            "wf_programming_scaffold",
            "wf_programming_debug",
            "wf_programming_refactor",
            "wf_programming_tests",
            "wf_programming_plugin",
            "wf_programming_review",
        ],
        collaborate_with=["business", "planning"],
        confidence_threshold=0.3,
    )

    def register_workflows(self) -> None:
        self.workflows.register(
            Workflow(
                id=new_workflow_id("programming", "scaffold"),
                name="Code Scaffold",
                domain="programming",
                description="Generate a starter module/function scaffold",
                triggers=["write code", "implement", "generate code", "create function", "scaffold"],
                steps=[
                    WorkflowStep(id="s1", title="Clarify interface"),
                    WorkflowStep(id="s2", title="Scaffold"),
                    WorkflowStep(id="s3", title="Usage notes"),
                ],
                handler=self._wf_scaffold,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("programming", "debug"),
                name="Debug Assist",
                domain="programming",
                description="Structured debugging checklist",
                triggers=["debug", "bug", "error", "exception", "traceback", "not working"],
                steps=[
                    WorkflowStep(id="s1", title="Reproduce"),
                    WorkflowStep(id="s2", title="Isolate"),
                    WorkflowStep(id="s3", title="Hypotheses"),
                    WorkflowStep(id="s4", title="Fix & verify"),
                ],
                handler=self._wf_debug,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("programming", "refactor"),
                name="Refactor Plan",
                domain="programming",
                description="Safe refactoring sequence",
                triggers=["refactor", "clean up", "simplify code", "restructure"],
                steps=[
                    WorkflowStep(id="s1", title="Smell inventory"),
                    WorkflowStep(id="s2", title="Safety nets"),
                    WorkflowStep(id="s3", title="Stepwise plan"),
                ],
                handler=self._wf_refactor,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("programming", "tests"),
                name="Test Generation Plan",
                domain="programming",
                description="Unit/integration test outline",
                triggers=["unit test", "write tests", "pytest", "test coverage"],
                steps=[
                    WorkflowStep(id="s1", title="Behaviors"),
                    WorkflowStep(id="s2", title="Cases"),
                    WorkflowStep(id="s3", title="Fixtures"),
                ],
                handler=self._wf_tests,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("programming", "plugin"),
                name="SAGE Plugin Scaffold",
                domain="programming",
                description="Scaffold a SAGE plugin package",
                triggers=["plugin", "sage plugin", "extension"],
                steps=[
                    WorkflowStep(id="s1", title="Manifest"),
                    WorkflowStep(id="s2", title="Entrypoint"),
                    WorkflowStep(id="s3", title="Permissions"),
                ],
                handler=self._wf_plugin,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("programming", "review"),
                name="Architecture Review",
                domain="programming",
                description="Lightweight architecture review checklist",
                triggers=["architecture review", "code review", "design review"],
                steps=[
                    WorkflowStep(id="s1", title="Boundaries"),
                    WorkflowStep(id="s2", title="Risks"),
                    WorkflowStep(id="s3", title="Recommendations"),
                ],
                handler=self._wf_review,
            )
        )

    async def _wf_scaffold(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        name = _snake_name(task) or "feature"
        cls = _pascal(name)
        todo = task[:120].replace('"""', "'")
        code = textwrap.dedent(
            f'''\
            """{name.replace("_", " ").title()} — generated scaffold."""

            from __future__ import annotations

            from dataclasses import dataclass
            from typing import Any


            @dataclass
            class {cls}Result:
                success: bool
                data: dict[str, Any]
                message: str = ""


            def {name}(*, raw: str, options: dict[str, Any] | None = None) -> {cls}Result:
                """
                TODO: implement core behavior for: {todo}
                """
                options = options or {{}}
                # 1) validate inputs
                if not raw:
                    return {cls}Result(False, {{}}, "raw input required")
                # 2) process
                data = {{"length": len(raw), "options": options}}
                # 3) return
                return {cls}Result(True, data, "ok")
            '''
        )
        lines = [
            f"**Scaffold:** `{name}.py`",
            "",
            "```python",
            code.rstrip(),
            "```",
            "",
            "**Next:** add tests, wire into module, update Capability Registry if agent-facing.",
        ]
        return WorkflowResult(
            workflow_id="wf_programming_scaffold",
            workflow_name="Code Scaffold",
            success=True,
            steps=[
                {"id": "s1", "title": "Clarify interface", "status": "done"},
                {"id": "s2", "title": "Scaffold", "status": "done"},
                {"id": "s3", "title": "Usage notes", "status": "done"},
            ],
            output="\n".join(lines),
            data={"module": name},
        )

    async def _wf_debug(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        lines = [
            "**Debug assist**",
            f"_Issue:_ {task[:200]}",
            "",
            "1. **Reproduce** — minimal input that fails every time; capture full traceback.",
            "2. **Reduce** — bisect to smallest code path (comment halves / binary search commits).",
            "3. **Hypotheses** (pick 2 max):",
            "   - Wrong assumption about input shape/state",
            "   - Race / ordering / uninitialized state",
            "   - Off-by-one / boundary",
            "   - External dependency failure",
            "4. **Instrument** — log inputs/outputs at boundaries; assert invariants.",
            "5. **Fix** — smallest change; add regression test before moving on.",
            "6. **Verify** — original case + nearby edges + unrelated smoke.",
        ]
        return WorkflowResult(
            workflow_id="wf_programming_debug",
            workflow_name="Debug Assist",
            success=True,
            steps=[
                {"id": "s1", "title": "Reproduce", "status": "done"},
                {"id": "s2", "title": "Isolate", "status": "done"},
                {"id": "s3", "title": "Hypotheses", "status": "done"},
                {"id": "s4", "title": "Fix & verify", "status": "done"},
            ],
            output="\n".join(lines),
            data={},
        )

    async def _wf_refactor(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        lines = [
            "**Refactor plan**",
            "",
            "1. Characterize smells (duplication, long method, feature envy, tight coupling).",
            "2. Establish safety net (tests or characterization tests).",
            "3. Apply one refactoring at a time (extract function → rename → move).",
            "4. Keep public API stable or provide migration shims.",
            "5. Re-run tests after each step; commit atomically.",
        ]
        return WorkflowResult(
            workflow_id="wf_programming_refactor",
            workflow_name="Refactor Plan",
            success=True,
            steps=[
                {"id": "s1", "title": "Smell inventory", "status": "done"},
                {"id": "s2", "title": "Safety nets", "status": "done"},
                {"id": "s3", "title": "Stepwise plan", "status": "done"},
            ],
            output="\n".join(lines),
            data={},
        )

    async def _wf_tests(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        name = _snake_name(task) or "feature"
        code = textwrap.dedent(
            f'''\
            import pytest

            # from your_module import {name}

            @pytest.mark.asyncio
            async def test_{name}_happy_path():
                # arrange
                # act
                # assert
                assert True

            def test_{name}_rejects_empty():
                with pytest.raises(ValueError):
                    raise ValueError("empty")
            '''
        )
        lines = [
            "**Test plan**",
            "- Happy path",
            "- Invalid input / empty",
            "- Boundary values",
            "- Integration with one collaborator (DB/event)",
            "",
            "```python",
            code.rstrip(),
            "```",
        ]
        return WorkflowResult(
            workflow_id="wf_programming_tests",
            workflow_name="Test Generation Plan",
            success=True,
            steps=[
                {"id": "s1", "title": "Behaviors", "status": "done"},
                {"id": "s2", "title": "Cases", "status": "done"},
                {"id": "s3", "title": "Fixtures", "status": "done"},
            ],
            output="\n".join(lines),
            data={},
        )

    async def _wf_plugin(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        slug = _snake_name(task) or "my_plugin"
        slug = slug.replace("sage_", "").replace("plugin", "").strip("_") or "my_plugin"
        manifest = textwrap.dedent(
            f'''\
            id: {slug}
            name: {slug.replace("_", " ").title()}
            version: 0.1.0
            description: SAGE plugin scaffold
            entrypoint: plugin:Plugin
            enabled: true
            permissions:
              - memory.read
              - notifications
            '''
        )
        plugin_py = textwrap.dedent(
            '''\
            from __future__ import annotations
            from typing import TYPE_CHECKING
            from sage.plugins.manifest import PluginManifest

            if TYPE_CHECKING:
                from sage.core.container import Container


            class Plugin:
                def __init__(self) -> None:
                    self._manifest = PluginManifest(
                        id="SLUG",
                        name="NAME",
                        version="0.1.0",
                        permissions=["memory.read", "notifications"],
                    )

                @property
                def manifest(self) -> PluginManifest:
                    return self._manifest

                async def on_load(self, container: Container) -> None:
                    from sage.logging import get_logger
                    get_logger("plugin.SLUG").info("loaded")

                async def on_unload(self) -> None:
                    pass
            '''.replace("SLUG", slug).replace("NAME", slug.replace("_", " ").title())
        )
        lines = [
            f"**SAGE plugin scaffold:** `plugins/{slug}/`",
            "",
            "**plugin.yaml**",
            "```yaml",
            manifest.rstrip(),
            "```",
            "",
            "**plugin.py**",
            "```python",
            plugin_py.rstrip(),
            "```",
            "",
            "Dangerous permissions (shell, internet, secrets) stay pending until user grants them.",
        ]
        return WorkflowResult(
            workflow_id="wf_programming_plugin",
            workflow_name="SAGE Plugin Scaffold",
            success=True,
            steps=[
                {"id": "s1", "title": "Manifest", "status": "done"},
                {"id": "s2", "title": "Entrypoint", "status": "done"},
                {"id": "s3", "title": "Permissions", "status": "done"},
            ],
            output="\n".join(lines),
            data={"plugin": slug},
        )

    async def _wf_review(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        lines = [
            "**Architecture review checklist**",
            "",
            "- [ ] Clear module boundaries / dependency direction",
            "- [ ] Interfaces for swappable adapters (models, storage, tools)",
            "- [ ] Failure isolation (plugins, tools, agents)",
            "- [ ] Observability (logs, health, audit)",
            "- [ ] Security (permissions, secrets, least privilege)",
            "- [ ] Testability (unit + integration on critical paths)",
            "- [ ] Data ownership & migrations",
            "",
            "**Top risks to name explicitly:** coupling, hidden state, unbounded tools, missing tests.",
        ]
        return WorkflowResult(
            workflow_id="wf_programming_review",
            workflow_name="Architecture Review",
            success=True,
            steps=[
                {"id": "s1", "title": "Boundaries", "status": "done"},
                {"id": "s2", "title": "Risks", "status": "done"},
                {"id": "s3", "title": "Recommendations", "status": "done"},
            ],
            output="\n".join(lines),
            data={},
        )


def _snake_name(text: str) -> str:
    # try quoted or "function X" patterns
    m = re.search(r"(?:function|module|class|named)\s+([A-Za-z_][\w]*)", text, re.I)
    if m:
        return re.sub(r"[^a-z0-9_]", "_", m.group(1).lower())
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    stop = {"write", "code", "implement", "create", "generate", "please", "function", "python", "the", "for", "and"}
    words = [w for w in words if w not in stop][:3]
    return "_".join(words) if words else ""


def _pascal(snake: str) -> str:
    return "".join(p.title() for p in snake.split("_") if p)
