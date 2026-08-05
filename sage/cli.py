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


if __name__ == "__main__":
    app()
