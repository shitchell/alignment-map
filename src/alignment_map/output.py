"""Output formatting for alignment check results."""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .models import CheckFailure, CheckResult

console = Console()


def print_check_results(failures: list[CheckFailure]) -> None:
    """Print all check failures in a formatted way."""
    if not failures:
        console.print("\n[bold green]✓ Alignment check passed[/bold green]\n")
        return

    console.print("\n[bold red]ALIGNMENT CHECK FAILED[/bold red]\n")

    # Group failures by type
    by_type: dict[CheckResult, list[CheckFailure]] = {}
    for failure in failures:
        by_type.setdefault(failure.result, []).append(failure)

    # Print each type
    for result_type, type_failures in by_type.items():
        print_failure_group(result_type, type_failures)

    # Print summary
    console.print(f"\n[bold red]Total failures: {len(failures)}[/bold red]\n")


def print_failure_group(result_type: CheckResult, failures: list[CheckFailure]) -> None:
    """Print a group of failures of the same type."""
    if result_type == CheckResult.UNMAPPED_FILE:
        print_unmapped_files(failures)
    elif result_type == CheckResult.UNMAPPED_LINES:
        print_unmapped_lines(failures)
    elif result_type == CheckResult.MAP_NOT_UPDATED:
        print_map_not_updated(failures)
    elif result_type == CheckResult.STALE_DOC:
        print_stale_docs(failures)
    elif result_type == CheckResult.HUMAN_ESCALATION:
        print_human_escalation(failures)


def print_unmapped_files(failures: list[CheckFailure]) -> None:
    """Print unmapped file failures."""
    console.print("[bold yellow]✗ Unmapped files[/bold yellow]\n")

    for failure in failures:
        console.print(f"  [cyan]{failure.file_path}[/cyan]")
        console.print(f"    {failure.message}\n")
        if failure.suggestion:
            console.print(Panel(failure.suggestion, title="Suggestion", border_style="dim"))
        console.print()


def print_unmapped_lines(failures: list[CheckFailure]) -> None:
    """Print unmapped lines failures."""
    console.print("[bold yellow]✗ Unmapped lines[/bold yellow]\n")

    for failure in failures:
        console.print(f"  [cyan]{failure.file_path}[/cyan]")
        console.print(f"    {failure.message}")
        if failure.block:
            console.print(f"    Nearest block: \"{failure.block.name}\" (lines {failure.block.lines})")
        console.print()
        if failure.suggestion:
            console.print(Panel(failure.suggestion, title="Suggestion", border_style="dim"))
        console.print()


def print_map_not_updated(failures: list[CheckFailure]) -> None:
    """Print failures where alignment map wasn't updated."""
    console.print("[bold yellow]✗ Alignment map not updated[/bold yellow]\n")

    for failure in failures:
        console.print(f"  [cyan]{failure.file_path}[/cyan]")
        if failure.block:
            console.print(f"    Block: \"{failure.block.name}\"")
            console.print(f"    Current last_updated: {failure.block.last_updated}")
            console.print(f"    Current comment: {failure.block.last_update_comment}")
        console.print()
        if failure.suggestion:
            console.print(Panel(failure.suggestion, title="Required Update", border_style="yellow"))
        console.print()


def print_stale_docs(failures: list[CheckFailure]) -> None:
    """Print stale document failures."""
    console.print("[bold yellow]✗ Stale documents require review[/bold yellow]\n")

    for failure in failures:
        console.print(f"  Modified: [cyan]{failure.file_path}[/cyan]")
        if failure.block:
            console.print(f"    Block: \"{failure.block.name}\"")
        console.print(f"    Aligned document: [yellow]{failure.aligned_doc}[/yellow]")
        console.print()

        # Print the document section
        if failure.doc_section:
            section_panel = Panel(
                failure.doc_section,
                title=f"[bold]{failure.aligned_doc}[/bold]",
                border_style="blue",
                padding=(1, 2),
            )
            console.print(section_panel)
            console.print()

        # Print instructions
        instructions = Text()
        instructions.append("To proceed:\n", style="bold")
        instructions.append("  • Review the above section\n")
        instructions.append("  • Update the document if your changes require it\n")
        instructions.append("  • Update ", style="")
        instructions.append("last_reviewed", style="cyan")
        instructions.append(" in the document's frontmatter\n")

        console.print(Panel(instructions, title="Instructions", border_style="green"))
        console.print()


def print_human_escalation(failures: list[CheckFailure]) -> None:
    """Print failures requiring human escalation."""
    console.print("[bold red]⚠️  HUMAN REVIEW REQUIRED[/bold red]\n")

    for failure in failures:
        console.print(f"  Modified: [cyan]{failure.file_path}[/cyan]")
        if failure.block:
            console.print(f"    Block: \"{failure.block.name}\"")
        console.print(f"    Document: [red]{failure.aligned_doc}[/red]")
        console.print()

        # Print the document section
        if failure.doc_section:
            section_panel = Panel(
                failure.doc_section,
                title=f"[bold red]{failure.aligned_doc}[/bold red]",
                border_style="red",
                padding=(1, 2),
            )
            console.print(section_panel)
            console.print()

        # Print escalation instructions
        instructions = Text()
        instructions.append("This document cannot be modified without human approval.\n\n", style="bold red")
        instructions.append("To proceed:\n", style="bold")
        instructions.append("  • Have a human review this change\n")
        instructions.append("  • Human updates ", style="")
        instructions.append("last_reviewed", style="cyan")
        instructions.append(" in the document\n")
        instructions.append("  • Or human approves skip in commit message:\n")
        instructions.append('    git commit -m "... [human-reviewed: <doc> alignment verified]"', style="dim")

        console.print(Panel(instructions, title="Human Escalation Required", border_style="red"))
        console.print()
