"""Trace command implementation - prints all context needed to review a file/line."""

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import AlignmentMap, Block, CheckResult, DocumentSection, FileMapping
from .parser import extract_document_section, get_document_last_reviewed


def trace_file_location(
    project_root: Path,
    alignment_map: AlignmentMap,
    file_path: Path,
    line_number: int | None = None,
    output_json: bool = False,
) -> dict[str, Any] | None:
    """Trace alignment context for a file/line location."""
    # Get file mapping
    file_mapping = alignment_map.get_file_mapping(file_path)

    if file_mapping is None:
        if output_json:
            return {
                "error": "unmapped_file",
                "message": f"File not in alignment map: {file_path}",
                "file": str(file_path),
            }
        else:
            console = Console()
            console.print(f"[red]Error: File not in alignment map: {file_path}[/red]")
            return None

    # Find the relevant block(s)
    blocks_to_trace = []
    if line_number is not None:
        # Find specific block containing the line
        for block in file_mapping.blocks:
            if block.lines.contains(line_number):
                blocks_to_trace.append(block)
                break

        if not blocks_to_trace:
            # No block contains this line
            if output_json:
                return {
                    "error": "unmapped_line",
                    "message": f"Line {line_number} not in any mapped block",
                    "file": str(file_path),
                    "line": line_number,
                }
            else:
                console = Console()
                console.print(f"[red]Error: Line {line_number} not in any mapped block[/red]")
                return None
    else:
        # Trace all blocks in the file
        blocks_to_trace = file_mapping.blocks

    # Collect trace data
    trace_data = collect_trace_data(
        project_root, alignment_map, file_path, blocks_to_trace
    )

    if output_json:
        return trace_data
    else:
        print_trace_output(trace_data)
        return trace_data


def collect_trace_data(
    project_root: Path,
    alignment_map: AlignmentMap,
    file_path: Path,
    blocks: list[Block],
) -> dict[str, Any]:
    """Collect all trace data for the given blocks."""
    trace_data: dict[str, Any] = {
        "file": str(file_path),
        "blocks": [],
        "aligned_documents": [],
        "hierarchy": [],
        "staleness_checks": [],
    }

    aligned_docs_seen = set()

    for block in blocks:
        # Add block info
        block_info = {
            "name": block.name,
            "lines": str(block.lines),
            "last_updated": block.last_updated.isoformat() if block.last_updated else None,
            "last_update_comment": block.last_update_comment,
            "aligned_with": block.aligned_with,
        }
        trace_data["blocks"].append(block_info)

        # Process each aligned document
        for aligned_ref in block.aligned_with:
            if aligned_ref in aligned_docs_seen:
                continue
            aligned_docs_seen.add(aligned_ref)

            # Parse the reference
            if "#" in aligned_ref:
                doc_path_str, anchor = aligned_ref.split("#", 1)
            else:
                doc_path_str = aligned_ref
                anchor = ""

            # Skip code references
            if doc_path_str.startswith("src/") or ":" in aligned_ref:
                continue

            doc_path = project_root / doc_path_str

            # Get document info
            doc_info = {
                "path": doc_path_str,
                "anchor": anchor,
                "exists": doc_path.exists(),
                "last_reviewed": None,
                "section_content": None,
                "requires_human": alignment_map.is_human_required(doc_path_str),
            }

            if doc_path.exists():
                # Get last_reviewed
                last_reviewed = get_document_last_reviewed(doc_path)
                if last_reviewed:
                    doc_info["last_reviewed"] = last_reviewed.isoformat()

                # Extract section if anchor provided
                if anchor:
                    section = extract_document_section(doc_path, anchor)
                    if section:
                        doc_info["section_content"] = section.content
                else:
                    # Read entire document if no anchor
                    doc_info["section_content"] = doc_path.read_text()

                # Check staleness
                if block.last_updated and last_reviewed:
                    if last_reviewed < block.last_updated:
                        staleness = {
                            "block": block.name,
                            "document": doc_path_str,
                            "block_updated": block.last_updated.isoformat(),
                            "doc_reviewed": last_reviewed.isoformat(),
                            "status": "stale",
                            "requires_human": doc_info["requires_human"],
                        }
                        trace_data["staleness_checks"].append(staleness)
                    else:
                        staleness = {
                            "block": block.name,
                            "document": doc_path_str,
                            "block_updated": block.last_updated.isoformat(),
                            "doc_reviewed": last_reviewed.isoformat(),
                            "status": "current",
                        }
                        trace_data["staleness_checks"].append(staleness)

            trace_data["aligned_documents"].append(doc_info)

    # Build hierarchy (unique docs from all aligned docs)
    hierarchy = build_document_hierarchy(
        project_root, alignment_map, trace_data["aligned_documents"]
    )
    trace_data["hierarchy"] = hierarchy

    return trace_data


def build_document_hierarchy(
    project_root: Path,
    alignment_map: AlignmentMap,
    aligned_docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the document hierarchy from aligned docs up to identity."""
    hierarchy: list[dict[str, Any]] = []
    docs_to_trace = set(doc["path"] for doc in aligned_docs)
    docs_traced: set[str] = set()

    while docs_to_trace:
        current_doc = docs_to_trace.pop()
        if current_doc in docs_traced:
            continue
        docs_traced.add(current_doc)

        # Add to hierarchy
        level = "identity" if "IDENTITY" in current_doc.upper() else (
            "design" if "DESIGN" in current_doc.upper() or "PRINCIPLES" in current_doc.upper() else
            "technical"
        )

        hierarchy.append({
            "document": current_doc,
            "level": level,
            "requires_human": alignment_map.is_human_required(current_doc),
        })

        # Find what this doc aligns with (trace upward)
        doc_mapping = alignment_map.get_file_mapping(Path(current_doc))
        if doc_mapping:
            for block in doc_mapping.blocks:
                for aligned_ref in block.aligned_with:
                    parent_doc = aligned_ref.split("#")[0]
                    if parent_doc not in docs_traced and not parent_doc.startswith("src/"):
                        docs_to_trace.add(parent_doc)

    # Sort hierarchy by level (identity -> design -> technical)
    level_order = {"identity": 0, "design": 1, "technical": 2}
    hierarchy.sort(key=lambda x: level_order.get(x["level"], 99))

    return hierarchy


def print_trace_output(trace_data: dict[str, Any]) -> None:
    """Print trace data in a formatted way."""
    console = Console()

    # Print header
    console.print(f"\n[bold cyan]Trace Report for {trace_data['file']}[/bold cyan]\n")

    # Print blocks
    console.print("[bold]Code Blocks:[/bold]")
    for block in trace_data["blocks"]:
        console.print(f"  • [cyan]{block['name']}[/cyan] (lines {block['lines']})")
        if block['last_updated']:
            console.print(f"    Last updated: {block['last_updated']}")
        if block['last_update_comment']:
            console.print(f"    Comment: {block['last_update_comment']}")
        console.print()

    # Print aligned documents with sections
    if trace_data["aligned_documents"]:
        console.print("[bold]Aligned Documents:[/bold]\n")

        for doc in trace_data["aligned_documents"]:
            # Document header
            doc_style = "red" if doc["requires_human"] else "yellow"
            header = f"[{doc_style}]{doc['path']}"
            if doc['anchor']:
                header += f"#{doc['anchor']}"
            header += f"[/{doc_style}]"

            if doc["requires_human"]:
                header += " [red](requires human review)[/red]"

            console.print(header)

            # Document metadata
            if doc['last_reviewed']:
                console.print(f"  Last reviewed: {doc['last_reviewed']}")
            elif doc['exists']:
                console.print("  [yellow]Last reviewed: NOT SET[/yellow]")

            if not doc['exists']:
                console.print("  [red]Document does not exist![/red]")

            # Document section content
            if doc['section_content']:
                console.print()
                section_panel = Panel(
                    doc['section_content'][:1000] + ("..." if len(doc['section_content']) > 1000 else ""),
                    title=f"Section Content",
                    border_style="blue",
                    padding=(1, 2),
                )
                console.print(section_panel)

            console.print()

    # Print hierarchy
    if trace_data["hierarchy"]:
        console.print("[bold]Document Hierarchy:[/bold]")
        for item in trace_data["hierarchy"]:
            indent = "  " * (["identity", "design", "technical"].index(item["level"]))
            marker = "⚠️ " if item["requires_human"] else "📄 "
            console.print(f"{indent}{marker} {item['document']} ({item['level']})")
        console.print()

    # Print staleness status
    if trace_data["staleness_checks"]:
        console.print("[bold]Staleness Status:[/bold]")

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Block", style="cyan")
        table.add_column("Document")
        table.add_column("Status")
        table.add_column("Action Required")

        for check in trace_data["staleness_checks"]:
            status_style = "red" if check["status"] == "stale" else "green"
            status_text = "❌ STALE" if check["status"] == "stale" else "✓ Current"

            if check["status"] == "stale":
                if check.get("requires_human"):
                    action = "Human review required"
                else:
                    action = "Review and update doc"
            else:
                action = "None"

            table.add_row(
                check["block"],
                check["document"],
                f"[{status_style}]{status_text}[/{status_style}]",
                action,
            )

        console.print(table)
        console.print()

    # Print instructions
    if any(check["status"] == "stale" for check in trace_data.get("staleness_checks", [])):
        instructions = Text()
        instructions.append("Next Steps:\n", style="bold yellow")
        instructions.append("1. Review the stale documents shown above\n")
        instructions.append("2. Update documents if changes affect them\n")
        instructions.append("3. Update 'last_reviewed' timestamp in each document\n")
        instructions.append("4. Update alignment map with 'last_updated' and comment\n")

        console.print(Panel(instructions, title="Required Actions", border_style="yellow"))