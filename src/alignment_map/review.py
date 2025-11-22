"""Review command implementation - pre-flight check showing what docs would need review."""

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import AlignmentMap
from .parser import extract_document_section, get_document_last_reviewed, parse_alignment_map


def review_file(
    project_root: Path,
    map_path: Path,
    file_path: Path,
    output_json: bool = False,
) -> dict[str, Any] | None:
    """Review what documentation would need updating if a file is modified."""
    console = Console()

    # Parse alignment map
    try:
        alignment_map = parse_alignment_map(map_path)
    except Exception as e:
        if output_json:
            return {"error": "map_parse_error", "message": str(e)}
        else:
            console.print(f"[red]Error parsing alignment map: {e}[/red]")
            return None

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
            console.print(f"[red]Error: File not in alignment map: {file_path}[/red]")
            console.print("\n[yellow]This file needs to be added to the alignment map before changes can be made.[/yellow]")
            console.print(f"\nRun: [cyan]alignment-map update {file_path} --block <NAME> --lines <RANGE> --aligned-with <DOC>[/cyan]")
            return None

    # Collect review data
    review_data = collect_review_data(project_root, alignment_map, file_path, file_mapping)

    if output_json:
        return review_data
    else:
        print_review_output(review_data)
        return review_data


def collect_review_data(
    project_root: Path,
    alignment_map: AlignmentMap,
    file_path: Path,
    file_mapping: Any,
) -> dict[str, Any]:
    """Collect all review data for a file."""
    review_data = {
        "file": str(file_path),
        "blocks": [],
        "documents_to_review": [],
        "review_requirements": {
            "total_docs": 0,
            "requires_human": 0,
            "requires_update": 0,
            "already_current": 0,
        },
    }

    docs_seen = set()

    for block in file_mapping.blocks:
        block_info = {
            "name": block.name,
            "lines": str(block.lines),
            "last_updated": block.last_updated.isoformat() if block.last_updated else None,
            "last_update_comment": block.last_update_comment,
            "aligned_docs": [],
        }

        # Check each aligned document
        for aligned_ref in block.aligned_with:
            if "#" in aligned_ref:
                doc_path_str, anchor = aligned_ref.split("#", 1)
            else:
                doc_path_str = aligned_ref
                anchor = ""

            # Skip code references
            if doc_path_str.startswith("src/") or ":" in aligned_ref:
                continue

            doc_path = project_root / doc_path_str

            # Create doc info
            doc_info = {
                "path": doc_path_str,
                "anchor": anchor,
                "exists": doc_path.exists(),
                "requires_human": alignment_map.is_human_required(doc_path_str),
                "last_reviewed": None,
                "review_status": "unknown",
                "section_preview": None,
            }

            if doc_path.exists():
                # Get last_reviewed
                last_reviewed = get_document_last_reviewed(doc_path)
                if last_reviewed:
                    doc_info["last_reviewed"] = last_reviewed.isoformat()

                    # Determine review status
                    if block.last_updated:
                        if last_reviewed >= block.last_updated:
                            doc_info["review_status"] = "current"
                        else:
                            doc_info["review_status"] = "needs_review"
                    else:
                        doc_info["review_status"] = "no_block_timestamp"
                else:
                    doc_info["review_status"] = "no_review_timestamp"

                # Get section preview
                if anchor:
                    section = extract_document_section(doc_path, anchor)
                    if section:
                        # First 200 chars
                        doc_info["section_preview"] = section.content[:200] + ("..." if len(section.content) > 200 else "")
            else:
                doc_info["review_status"] = "missing"

            block_info["aligned_docs"].append(doc_info)

            # Track in documents to review
            if doc_path_str not in docs_seen:
                docs_seen.add(doc_path_str)
                review_data["documents_to_review"].append(doc_info)

                # Update requirements
                review_data["review_requirements"]["total_docs"] += 1
                if doc_info["requires_human"]:
                    review_data["review_requirements"]["requires_human"] += 1
                if doc_info["review_status"] in ["needs_review", "no_review_timestamp", "missing"]:
                    review_data["review_requirements"]["requires_update"] += 1
                elif doc_info["review_status"] == "current":
                    review_data["review_requirements"]["already_current"] += 1

        review_data["blocks"].append(block_info)

    # Add estimated impact
    review_data["estimated_impact"] = estimate_review_impact(review_data)

    return review_data


def estimate_review_impact(review_data: dict[str, Any]) -> dict[str, str]:
    """Estimate the impact of making changes to this file."""
    reqs = review_data["review_requirements"]

    if reqs["total_docs"] == 0:
        return {
            "level": "minimal",
            "description": "No aligned documents to review",
            "time_estimate": "< 1 minute",
        }

    if reqs["requires_human"] > 0:
        return {
            "level": "high",
            "description": f"Requires human review of {reqs['requires_human']} identity/design doc(s)",
            "time_estimate": "15-60 minutes (human review)",
        }

    if reqs["requires_update"] > 2:
        return {
            "level": "medium",
            "description": f"Need to review {reqs['requires_update']} technical documents",
            "time_estimate": "5-15 minutes",
        }

    if reqs["requires_update"] > 0:
        return {
            "level": "low",
            "description": f"Need to review {reqs['requires_update']} document(s)",
            "time_estimate": "2-5 minutes",
        }

    return {
        "level": "minimal",
        "description": "All documents are current",
        "time_estimate": "< 1 minute (timestamp update only)",
    }


def print_review_output(review_data: dict[str, Any]) -> None:
    """Print review data in a formatted way."""
    console = Console()

    # Header
    console.print(f"\n[bold cyan]Pre-flight Review for {review_data['file']}[/bold cyan]\n")

    # Summary panel
    reqs = review_data["review_requirements"]
    impact = review_data["estimated_impact"]

    summary_text = f"""[bold]Documents to Review:[/bold] {reqs['total_docs']}
  • Already current: {reqs['already_current']}
  • Need review: {reqs['requires_update']}
  • Require human: {reqs['requires_human']}

[bold]Impact Level:[/bold] {get_impact_color(impact['level'])}
{impact['description']}
[dim]Estimated time: {impact['time_estimate']}[/dim]"""

    console.print(Panel(summary_text, title="Summary", border_style="cyan"))

    # Blocks and their alignments
    console.print("\n[bold]Code Blocks and Alignments:[/bold]\n")

    for block in review_data["blocks"]:
        console.print(f"📦 [cyan]{block['name']}[/cyan] (lines {block['lines']})")

        if block["last_updated"]:
            console.print(f"   Last updated: {block['last_updated']}")

        if not block["aligned_docs"]:
            console.print("   [yellow]⚠️  No aligned documents[/yellow]")
        else:
            for doc in block["aligned_docs"]:
                status_icon = get_status_icon(doc["review_status"])
                doc_style = "red" if doc["requires_human"] else "white"

                doc_display = f"   {status_icon} [{doc_style}]{doc['path']}"
                if doc["anchor"]:
                    doc_display += f"#{doc['anchor']}"
                doc_display += f"[/{doc_style}]"

                if doc["requires_human"]:
                    doc_display += " [red](human)[/red]"

                console.print(doc_display)

                # Show status details
                if doc["review_status"] == "needs_review":
                    console.print(f"      [yellow]Needs review (last: {doc['last_reviewed']})[/yellow]")
                elif doc["review_status"] == "no_review_timestamp":
                    console.print("      [yellow]Missing last_reviewed field[/yellow]")
                elif doc["review_status"] == "missing":
                    console.print("      [red]Document does not exist![/red]")
                elif doc["review_status"] == "current":
                    console.print(f"      [green]Current (reviewed: {doc['last_reviewed']})[/green]")

                # Show preview if available
                if doc["section_preview"]:
                    console.print(f"      [dim]{doc['section_preview']}[/dim]")

        console.print()

    # Documents requiring action
    docs_needing_review = [
        d for d in review_data["documents_to_review"]
        if d["review_status"] in ["needs_review", "no_review_timestamp", "missing"]
    ]

    if docs_needing_review:
        console.print("[bold]Documents Requiring Action:[/bold]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Document", style="cyan")
        table.add_column("Status")
        table.add_column("Type")
        table.add_column("Action Required")

        for doc in docs_needing_review:
            doc_type = "Human" if doc["requires_human"] else "Technical"
            status = {
                "needs_review": "Stale",
                "no_review_timestamp": "No timestamp",
                "missing": "Missing",
            }.get(doc["review_status"], "Unknown")

            action = {
                "needs_review": "Review & update last_reviewed",
                "no_review_timestamp": "Add last_reviewed field",
                "missing": "Create document",
            }.get(doc["review_status"], "Review")

            table.add_row(
                doc["path"],
                get_status_with_color(status),
                doc_type,
                action,
            )

        console.print(table)

    # Instructions
    console.print("\n[bold]Next Steps:[/bold]")

    if impact["level"] in ["high", "medium"]:
        console.print("1. Review the documents listed above before making changes")
        console.print("2. Make your code changes")
        console.print("3. Update alignment map with new last_updated timestamp")
        console.print("4. Review documents again and update their last_reviewed timestamps")
        console.print("5. Commit your changes")
    elif impact["level"] == "low":
        console.print("1. Make your code changes")
        console.print("2. Update alignment map with new last_updated timestamp")
        console.print("3. Review the affected document(s)")
        console.print("4. Update last_reviewed timestamp(s)")
        console.print("5. Commit your changes")
    else:
        console.print("1. Make your code changes")
        console.print("2. Update alignment map with new last_updated timestamp")
        console.print("3. Commit your changes")

    if reqs["requires_human"] > 0:
        console.print("\n[bold red]⚠️  Human Review Required[/bold red]")
        console.print("Changes to this file affect identity or design documents.")
        console.print("A human must review and approve these changes.")


def get_status_icon(status: str) -> str:
    """Get icon for review status."""
    return {
        "current": "✅",
        "needs_review": "⚠️",
        "no_review_timestamp": "❌",
        "missing": "🚫",
        "no_block_timestamp": "❓",
        "unknown": "❓",
    }.get(status, "❓")


def get_impact_color(level: str) -> str:
    """Get colored impact level."""
    colors = {
        "minimal": "[green]Minimal[/green]",
        "low": "[yellow]Low[/yellow]",
        "medium": "[bold yellow]Medium[/bold yellow]",
        "high": "[bold red]High[/bold red]",
    }
    return colors.get(level, level)


def get_status_with_color(status: str) -> str:
    """Get colored status text."""
    colors = {
        "Stale": "[yellow]Stale[/yellow]",
        "No timestamp": "[yellow]No timestamp[/yellow]",
        "Missing": "[red]Missing[/red]",
        "Current": "[green]Current[/green]",
    }
    return colors.get(status, status)