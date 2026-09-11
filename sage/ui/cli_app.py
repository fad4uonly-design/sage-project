"""Rich interactive CLI shell for SAGE."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from sage import __tagline__, __version__
from sage.conversation.interfaces import ConversationEngine
from sage.core.engine import SageEngine

console = Console()


def _print_banner() -> None:
    console.print(
        Panel.fit(
            f"[bold cyan]SAGE[/bold cyan] v{__version__}\n[dim]{__tagline__}[/dim]",
            border_style="cyan",
        )
    )
    console.print(
        "[dim]Commands: /help  /status  /memories  /agents  /tools  /quit[/dim]\n"
    )


async def run_interactive_shell(engine: SageEngine) -> None:
    """REPL loop backed by the Conversation Engine."""
    _print_banner()
    conv = engine.container.resolve(ConversationEngine)
    session = await conv.start_session(user_id=engine.settings.conversation.default_user_id)
    console.print(f"[green]Session[/green] {session.id}\n")

    try:
        while True:
            try:
                user_input = console.input("[bold green]you>[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Interrupted.[/dim]")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                should_exit = await _handle_slash(engine, user_input)
                if should_exit:
                    break
                continue

            turn = await conv.respond(session.id, user_input)
            console.print()
            console.print(Panel(Markdown(turn.assistant_message), title="SAGE", border_style="cyan"))
            console.print()
    finally:
        await conv.end_session(session.id)
        console.print("[dim]Session ended.[/dim]")


async def _handle_slash(engine: SageEngine, command: str) -> bool:
    """Return True if the shell should exit."""
    cmd = command.strip()
    head, _, arg = cmd.partition(" ")
    head = head.lower()

    if head in {"/quit", "/exit", "/q"}:
        return True

    if head in {"/help", "/h", "/?"}:
        console.print(
            Markdown(
                """
### SAGE shell commands
- `/status` — system & module health
- `/memories [query]` — recall memories
- `/agents` — list agents
- `/tools` — list tools
- `/help` — this help
- `/quit` — exit

### Natural language shortcuts
- `remember: ...` — store a long-term memory
- `what do you remember about X`
- `plan ...` — create a goal and plan
- `reason about ...` / `should I ...`
- `research ...`
"""
            )
        )
        return False

    if head == "/status":
        health = await engine.health()
        table = Table(title=f"SAGE {engine.state.value} · {health.level.value}")
        table.add_column("Module")
        table.add_column("Level")
        table.add_column("Message")
        for m in health.modules:
            style = {
                "healthy": "green",
                "degraded": "yellow",
                "unhealthy": "red",
            }.get(m.level.value, "white")
            table.add_row(m.name, f"[{style}]{m.level.value}[/{style}]", m.message)
        console.print(table)
        st = engine.status_dict()
        console.print(
            f"[dim]session={st['session_id']} modules={len(st['modules'])} "
            f"boot_ms={ (st.get('boot') or {}).get('boot_duration_ms')}[/dim]"
        )
        return False

    if head == "/memories":
        from sage.memory.interfaces import MemorySystem

        mem = engine.container.resolve(MemorySystem)
        items = await mem.recall(arg.strip(), limit=15)
        if not items:
            console.print("[dim]No memories found.[/dim]")
        else:
            for item in items:
                console.print(
                    f"[cyan]{item.id}[/cyan] [{item.type.value}] "
                    f"(imp={item.importance:.2f}) {item.content}"
                )
        return False

    if head == "/agents":
        from sage.agents.interfaces import AgentOrchestrator

        orch = engine.container.resolve(AgentOrchestrator)
        for a in orch.list_agents():
            caps = ", ".join(a["capabilities"])
            console.print(f"[cyan]{a['id']}[/cyan] domain={a['domain']} caps=[{caps}]")
        return False

    if head == "/tools":
        from sage.tools.interfaces import ToolManager

        tm = engine.container.resolve(ToolManager)
        for t in tm.list_tools():
            console.print(f"[cyan]{t.name}[/cyan] — {t.description}")
        return False

    console.print(f"[yellow]Unknown command:[/yellow] {head} (try /help)")
    return False
