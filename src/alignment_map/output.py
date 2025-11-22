"""Output formatting for alignment check results."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .models import CheckFailure, CheckResult, LineRange

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


def print_block_modification_trace(
    project_root: Path,
    file_path: Path,
    block_name: str,
    lines: LineRange,
    aligned_with: list[str],
) -> None:
    """Print trace output after a block modification.

    Shows:
    1. The actual code block (read lines from file)
    2. Aligned document sections (extract and print them)
    3. Instruction to review alignment
    """
    from .parser import extract_document_section, get_document_last_reviewed

    # Print code block header
    console.print(f"\n[bold cyan]{'━' * 3} Code Block {'━' * 3}[/bold cyan]")

    # Read and print the code lines
    full_file_path = project_root / file_path
    if full_file_path.exists():
        file_lines = full_file_path.read_text().split("\n")
        # Show up to 20 lines or full block if smaller
        start_idx = lines.start - 1  # Convert to 0-indexed
        end_idx = min(lines.end, len(file_lines))
        show_lines = file_lines[start_idx:end_idx]

        # Limit display to first 15 and last 3 lines if too long
        if len(show_lines) > 20:
            for i, line in enumerate(show_lines[:15]):
                line_num = lines.start + i
                console.print(f"[dim]{line_num:4}|[/dim] {line}")
            console.print("[dim]...[/dim]")
            for i, line in enumerate(show_lines[-3:]):
                line_num = lines.end - 2 + i
                console.print(f"[dim]{line_num:4}|[/dim] {line}")
        else:
            for i, line in enumerate(show_lines):
                line_num = lines.start + i
                console.print(f"[dim]{line_num:4}|[/dim] {line}")
    else:
        console.print(f"[yellow]File not found: {full_file_path}[/yellow]")

    # Print aligned documents
    if aligned_with:
        console.print(f"\n[bold cyan]{'━' * 3} Aligned Documents {'━' * 3}[/bold cyan]")

        for aligned_ref in aligned_with:
            # Parse the reference
            if "#" in aligned_ref:
                doc_path_str, anchor = aligned_ref.split("#", 1)
            else:
                doc_path_str = aligned_ref
                anchor = ""

            # Skip code references
            if doc_path_str.startswith("src/") or ":" in aligned_ref:
                console.print(f"[dim]{aligned_ref} (code reference)[/dim]")
                continue

            doc_path = project_root / doc_path_str

            # Print document header
            console.print(f"\n[yellow]{aligned_ref}[/yellow]")

            if doc_path.exists():
                # Get last_reviewed
                last_reviewed = get_document_last_reviewed(doc_path)
                if last_reviewed:
                    console.print(f"  [dim]last_reviewed: {last_reviewed.isoformat()}[/dim]")
                else:
                    console.print("  [dim]last_reviewed: NOT SET[/dim]")

                # Extract and print section
                if anchor:
                    section = extract_document_section(doc_path, anchor)
                    if section:
                        # Print section content with indentation
                        console.print()
                        section_lines = section.content.split("\n")
                        # Limit to first 15 lines
                        if len(section_lines) > 15:
                            for line in section_lines[:15]:
                                console.print(f"  {line}")
                            console.print("  [dim]...[/dim]")
                        else:
                            for line in section_lines:
                                console.print(f"  {line}")
                    else:
                        console.print(f"  [yellow]Section '{anchor}' not found in document[/yellow]")
                else:
                    # No anchor, show first few lines
                    content = doc_path.read_text()
                    first_lines = content.split("\n")[:10]
                    console.print()
                    for line in first_lines:
                        console.print(f"  {line}")
                    if len(content.split("\n")) > 10:
                        console.print("  [dim]...[/dim]")
            else:
                console.print(f"  [red]Document does not exist![/red]")

    # Print footer with instructions
    console.print(f"\n[bold cyan]{'━' * 56}[/bold cyan]")
    console.print(
        "\n[yellow]Review the above to ensure alignment. If docs need updating,[/yellow]"
    )
    console.print(
        "[yellow]modify them and update their last_reviewed timestamps.[/yellow]\n"
    )
