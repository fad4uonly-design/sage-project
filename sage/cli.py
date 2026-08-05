"""SAGE command-line interface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from sage import __tagline__, __version__

app = typer.Typer(
    name="sage",
    help=f"SAGE — Smart Autonomous General Engine\n{__tagline__}",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@app.callback()
def main() -> None:
    """SAGE CLI root."""


@app.command()
def version() -> None:
    """Print SAGE version."""
    console.print(f"SAGE v{__version__} — {__tagline__}")


@app.command()
def start(
    data_dir: Optional[Path] = typer.Option(
        None, "--data-dir", help="Override SAGE data directory"
    ),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to sage.yaml"),
    log_level: Optional[str] = typer.Option(None, "--log-level", help="DEBUG|INFO|WARNING|ERROR"),
) -> None:
    """Boot SAGE and open the interactive shell."""

    async def _go() -> None:
        from sage.core.engine import SageEngine
        from sage.ui.cli_app import run_interactive_shell

        overrides: dict[str, Any] = {}
        if data_dir is not None:
            overrides["data_dir"] = str(data_dir)
            overrides["db_path"] = str(Path(data_dir) / "sage.db")
        if log_level is not None:
            overrides["logging"] = {"level": log_level}

        engine = await SageEngine.create(
            config_file=str(config) if config else None,
            overrides=overrides or None,
        )
        try:
            await run_interactive_shell(engine)
        finally:
            await engine.shutdown()

    _run(_go())


@app.command()
def status(
    data_dir: Optional[Path] = typer.Option(None, "--data-dir"),
    config: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """Boot briefly, print health, and shut down."""

    async def _go() -> None:
        from sage.core.engine import SageEngine

        overrides: dict[str, Any] = {}
        if data_dir is not None:
            overrides["data_dir"] = str(data_dir)
            overrides["db_path"] = str(Path(data_dir) / "sage.db")

        engine = await SageEngine.create(
            config_file=str(config) if config else None,
            overrides=overrides or None,
        )
        try:
            health = await engine.health()
            table = Table(title=f"SAGE v{__version__} · {engine.state.value}")
            table.add_column("Module")
            table.add_column("Level")
            table.add_column("Critical")
            table.add_column("Message")
            for m in health.modules:
                table.add_row(
                    m.name,
                    m.level.value,
                    "yes" if m.critical else "",
                    m.message,
                )
            console.print(table)
            boot = engine.boot_report
            if boot:
                console.print(
                    f"[dim]boot {boot.boot_duration_ms:.1f}ms · "
                    f"modules={len(boot.modules_initialized)} · "
                    f"failed={boot.modules_failed}[/dim]"
                )
        finally:
            await engine.shutdown()

    _run(_go())


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Message to send to SAGE"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir"),
    config: Optional[Path] = typer.Option(None, "--config"),
) -> None:
    """One-shot question (non-interactive)."""

    async def _go() -> None:
        from sage.core.engine import SageEngine

        overrides: dict[str, Any] = {}
        if data_dir is not None:
            overrides["data_dir"] = str(data_dir)
            overrides["db_path"] = str(Path(data_dir) / "sage.db")

        engine = await SageEngine.create(
            config_file=str(config) if config else None,
            overrides=overrides or None,
        )
        try:
            answer = await engine.ask(prompt)
            console.print(answer)
        finally:
            await engine.shutdown()

    _run(_go())


@app.command("remember")
def remember_cmd(
    fact: str = typer.Argument(..., help="Fact to store in long-term memory"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir"),
) -> None:
    """Store a fact in long-term memory."""

    async def _go() -> None:
        from sage.core.engine import SageEngine
        from sage.memory.interfaces import MemorySystem
        from sage.memory.models import MemoryItem, MemoryType

        overrides: dict[str, Any] = {}
        if data_dir is not None:
            overrides["data_dir"] = str(data_dir)
            overrides["db_path"] = str(Path(data_dir) / "sage.db")

        engine = await SageEngine.create(overrides=overrides or None)
        try:
            mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
            mid = await mem.store(
                MemoryItem(
                    type=MemoryType.LONG_TERM,
                    content=fact,
                    importance=0.8,
                    confidence=0.95,
                    source="cli",
                )
            )
            console.print(f"[green]Stored[/green] {mid}")
        finally:
            await engine.shutdown()

    _run(_go())


def _overrides(data_dir: Optional[Path]) -> dict[str, Any] | None:
    if data_dir is None:
        return None
    return {"data_dir": str(data_dir), "db_path": str(Path(data_dir) / "sage.db")}


@app.command("run-workflow")
def run_workflow_cmd(
    name: str = typer.Argument(..., help="Workflow definition id or name"),
    task: str = typer.Option("", "--task", help="Task / goal text for the workflow context"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir"),
) -> None:
    """Run a registered workflow to completion (or until approval is required)."""

    async def _go() -> None:
        from sage.core.engine import SageEngine
        from sage.workflow.engine import WorkflowEngine

        engine = await SageEngine.create(overrides=_overrides(data_dir))
        try:
            wf = engine.container.resolve(WorkflowEngine)  # type: ignore[type-abstract]
            run = await wf.start(name, context={"task": task or name}, principal="cli")
            console.print(f"[cyan]run[/cyan] {run.id}  status={run.status.value}")
            if run.error:
                console.print(f"[red]error[/red] {run.error}")
            if run.result:
                console.print(run.result)
            # Print last textual outputs
            for step in run.step_history[-5:]:
                console.print(f"  [dim]{step.step_id}[/dim] {step.status}")
        finally:
            await engine.shutdown()

    _run(_go())


@app.command("automations")
def automations_cmd(
    data_dir: Optional[Path] = typer.Option(None, "--data-dir"),
    enable: Optional[str] = typer.Option(None, "--enable", help="Enable job by name"),
    run: Optional[str] = typer.Option(None, "--run", help="Run job by name now"),
) -> None:
    """List, enable, or run automation jobs."""

    async def _go() -> None:
        from sage.automation.manager import AutomationManager
        from sage.core.engine import SageEngine

        engine = await SageEngine.create(overrides=_overrides(data_dir))
        try:
            mgr = engine.container.resolve(AutomationManager)  # type: ignore[type-abstract]
            if enable:
                ok = await mgr.enable(enable, True)
                console.print(f"{'Enabled' if ok else 'Not found'}: {enable}")
            if run:
                result = await mgr.run_job(run)
                console.print(result)
            jobs = await mgr.list_jobs()
            table = Table(title="Automation jobs")
            table.add_column("Name")
            table.add_column("Trigger")
            table.add_column("Enabled")
            table.add_column("Runs")
            table.add_column("Last")
            for j in jobs:
                table.add_row(
                    j.name,
                    j.trigger_type,
                    "yes" if j.enabled else "",
                    str(j.run_count),
                    j.last_status or "",
                )
            console.print(table)
        finally:
            await engine.shutdown()

    _run(_go())


@app.command("approve")
def approve_cmd(
    request_id: str = typer.Argument(..., help="Approval request id"),
    deny: bool = typer.Option(False, "--deny", help="Deny instead of approve"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir"),
) -> None:
    """Approve or deny a pending approval request."""

    async def _go() -> None:
        from sage.approval.engine import ApprovalEngine
        from sage.core.engine import SageEngine

        engine = await SageEngine.create(overrides=_overrides(data_dir))
        try:
            appr = engine.container.resolve(ApprovalEngine)  # type: ignore[type-abstract]
            req = await appr.decide(request_id, approve=not deny, decided_by="cli")
            console.print(f"{req.id} → {req.status.value}")
        finally:
            await engine.shutdown()

    _run(_go())


@app.command("audit")
def audit_cmd(
    limit: int = typer.Option(20, "--limit"),
    kind: Optional[str] = typer.Option(None, "--kind"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir"),
) -> None:
    """Show recent execution audit records."""

    async def _go() -> None:
        from sage.audit.logger import ExecutionAudit
        from sage.core.engine import SageEngine

        engine = await SageEngine.create(overrides=_overrides(data_dir))
        try:
            audit = engine.container.resolve(ExecutionAudit)  # type: ignore[type-abstract]
            rows = await audit.list_recent(limit=limit, kind=kind)
            table = Table(title="Execution audit")
            table.add_column("Time")
            table.add_column("Kind")
            table.add_column("Status")
            table.add_column("Summary")
            for r in rows:
                table.add_row(r.created_at[11:19], r.kind, r.status, (r.summary or "")[:60])
            console.print(table)
        finally:
            await engine.shutdown()

    _run(_go())


if __name__ == "__main__":
    app()
