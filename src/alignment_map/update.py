"""Update command implementation - adds or modifies blocks with overlap handling."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from .models import AlignmentMap, Block, LineRange


OverlapStrategy = Literal["extend", "split", "replace"]


def update_block(
    project_root: Path,
    map_path: Path,
    file_path: Path,
    block_name: str,
    lines: LineRange,
    aligned_with: list[str],
    comment: str | None = None,
    strategy: OverlapStrategy | None = None,
) -> tuple[bool, LineRange | None, list[str] | None]:
    """Update or add a block in the alignment map.

    Returns:
        Tuple of (success, final_lines, final_aligned_with) for trace printing.
    """
    console = Console()

    # Parse existing map
    try:
        alignment_map = AlignmentMap.load(map_path)
    except Exception as e:
        console.print(f"[red]Error parsing alignment map: {e}[/red]")
        return False, None, None

    # Check if file exists
    full_file_path = project_root / file_path
    if not full_file_path.exists():
        console.print(f"[red]Error: File does not exist: {file_path}[/red]")
        return False, None, None

    # Check line range validity
    file_lines = len(full_file_path.read_text().split("\n"))
    if lines.end > file_lines:
        console.print(
            f"[red]Error: Line range {lines} exceeds file length ({file_lines} lines)[/red]"
        )
        return False, None, None

    # Find or create file mapping
    file_mapping = alignment_map.get_file_mapping(file_path)
    if file_mapping is None:
        # New file - no overlaps possible
        new_block = Block(
            name=block_name,
            lines=lines,
            last_updated=datetime.now(),
            last_update_comment=comment or "Initial mapping",
            aligned_with=aligned_with,
        )

        # Load raw YAML to preserve formatting
        with open(map_path) as f:
            map_data = yaml.safe_load(f)

        # Add new file mapping
        if "mappings" not in map_data:
            map_data["mappings"] = []

        map_data["mappings"].append({
            "file": str(file_path),
            "blocks": [{
                "name": new_block.name,
                "lines": str(new_block.lines),
                "last_updated": new_block.last_updated.isoformat(),
                "last_update_comment": new_block.last_update_comment,
                "aligned_with": new_block.aligned_with,
            }],
        })

        # Write back
        with open(map_path, "w") as f:
            yaml.dump(map_data, f, default_flow_style=False, sort_keys=False)

        console.print(f"[green]✓ Added new file mapping for {file_path}[/green]")
        return True, lines, aligned_with

    # Check for overlaps with existing blocks
    overlapping_blocks = find_overlapping_blocks(file_mapping.blocks, lines)

    if overlapping_blocks:
        # Handle overlaps
        return handle_block_overlap(
            map_path,
            file_path,
            file_mapping,
            block_name,
            lines,
            aligned_with,
            comment,
            overlapping_blocks,
            strategy,
        )
    else:
        # No overlaps - add new block
        return add_new_block_to_file(
            map_path,
            file_path,
            block_name,
            lines,
            aligned_with,
            comment,
        )


def find_overlapping_blocks(blocks: list[Block], lines: LineRange) -> list[Block]:
    """Find blocks that overlap with the given line range."""
    overlapping = []
    for block in blocks:
        if lines_overlap(block.lines, lines):
            overlapping.append(block)
    return overlapping


def lines_overlap(range1: LineRange, range2: LineRange) -> bool:
    """Check if two line ranges overlap."""
    return not (range1.end < range2.start or range2.end < range1.start)


def handle_block_overlap(
    map_path: Path,
    file_path: Path,
    file_mapping: Any,
    block_name: str,
    lines: LineRange,
    aligned_with: list[str],
    comment: str | None,
    overlapping_blocks: list[Block],
    strategy: OverlapStrategy | None,
) -> tuple[bool, LineRange | None, list[str] | None]:
    """Handle overlapping blocks based on strategy.

    Returns:
        Tuple of (success, final_lines, final_aligned_with) for trace printing.
    """
    console = Console()

    # Show overlap details
    console.print(f"\n[yellow]Warning: Lines {lines} overlap with existing block(s):[/yellow]\n")

    for block in overlapping_blocks:
        console.print(f"  • [cyan]{block.name}[/cyan] (lines {block.lines})")

    # Determine suggested strategy
    suggested_strategy = suggest_overlap_strategy(lines, overlapping_blocks)

    # Show suggestion
    console.print(f"\n[bold]Suggested strategy: --{suggested_strategy}[/bold]")
    console.print(get_strategy_explanation(suggested_strategy, lines, overlapping_blocks))

    # If no strategy provided, show options and exit
    if strategy is None:
        console.print("\n[bold]Options:[/bold]")
        console.print("  [cyan]--extend[/cyan]    Extend existing block to include new lines")
        console.print("  [cyan]--split[/cyan]     Split existing block at the boundary")
        console.print("  [cyan]--replace[/cyan]   Replace existing block entirely")
        console.print()
        console.print("[yellow]Re-run with one of the above flags to proceed.[/yellow]")
        return False, None, None

    # Apply the strategy
    if strategy == "extend":
        return apply_extend_strategy(
            map_path, file_path, lines, aligned_with, comment, overlapping_blocks[0]
        )
    elif strategy == "split":
        return apply_split_strategy(
            map_path, file_path, block_name, lines, aligned_with, comment, overlapping_blocks[0]
        )
    elif strategy == "replace":
        return apply_replace_strategy(
            map_path, file_path, block_name, lines, aligned_with, comment, overlapping_blocks[0]
        )
    else:
        console.print(f"[red]Invalid strategy: {strategy}[/red]")
        return False, None, None


def suggest_overlap_strategy(
    lines: LineRange, overlapping_blocks: list[Block]
) -> OverlapStrategy:
    """Suggest the best strategy for handling overlaps."""
    if len(overlapping_blocks) == 1:
        block = overlapping_blocks[0]

        # Check if new range is subset of existing
        if lines.start >= block.lines.start and lines.end <= block.lines.end:
            return "extend"

        # Check if new range completely contains existing
        if lines.start <= block.lines.start and lines.end >= block.lines.end:
            return "replace"

        # Partial overlap
        return "split"

    # Multiple overlaps - likely replace
    return "replace"


def get_strategy_explanation(
    strategy: OverlapStrategy, lines: LineRange, blocks: list[Block]
) -> str:
    """Get explanation for why a strategy was suggested."""
    if strategy == "extend":
        return (
            f"Lines {lines} fall within the existing block {blocks[0].lines}.\n"
            "This likely means you're adding detail to an existing section."
        )
    elif strategy == "split":
        return (
            f"Lines {lines} partially overlap with {blocks[0].lines}.\n"
            "Splitting allows you to create a more granular mapping."
        )
    elif strategy == "replace":
        if len(blocks) > 1:
            return (
                f"Lines {lines} overlap with multiple blocks.\n"
                "Replacing will consolidate them into a single mapping."
            )
        else:
            return (
                f"Lines {lines} completely contain {blocks[0].lines}.\n"
                "Replacing will update the block boundaries."
            )
    return ""


def apply_extend_strategy(
    map_path: Path,
    file_path: Path,
    lines: LineRange,
    aligned_with: list[str],
    comment: str | None,
    existing_block: Block,
) -> tuple[bool, LineRange | None, list[str] | None]:
    """Extend an existing block to include new lines.

    Returns:
        Tuple of (success, final_lines, final_aligned_with) for trace printing.
    """
    console = Console()

    # Calculate extended range
    new_start = min(existing_block.lines.start, lines.start)
    new_end = max(existing_block.lines.end, lines.end)
    extended_range = LineRange(start=new_start, end=new_end)

    # Update the YAML file
    with open(map_path) as f:
        map_data = yaml.safe_load(f)

    # Merge aligned_with lists (unique)
    merged_aligned = sorted(list(set(existing_block.aligned_with) | set(aligned_with)))

    # Find and update the block
    for mapping in map_data["mappings"]:
        if mapping["file"] == str(file_path):
            for block in mapping["blocks"]:
                if block["name"] == existing_block.name:
                    # Update block
                    block["lines"] = str(extended_range)
                    block["last_updated"] = datetime.now().isoformat()
                    block["last_update_comment"] = comment or f"Extended block from {existing_block.lines} to {extended_range}"
                    block["aligned_with"] = merged_aligned
                    break

    # Write back
    with open(map_path, "w") as f:
        yaml.dump(map_data, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓ Extended block '{existing_block.name}' to lines {extended_range}[/green]")
    return True, extended_range, merged_aligned


def apply_split_strategy(
    map_path: Path,
    file_path: Path,
    block_name: str,
    lines: LineRange,
    aligned_with: list[str],
    comment: str | None,
    existing_block: Block,
) -> tuple[bool, LineRange | None, list[str] | None]:
    """Split an existing block at the boundary.

    Returns:
        Tuple of (success, final_lines, final_aligned_with) for trace printing.
        Returns the new block's lines and aligned_with (not the split parts).
    """
    console = Console()

    # Determine split points
    splits = []

    # Part before overlap (if any)
    if existing_block.lines.start < lines.start:
        splits.append({
            "name": f"{existing_block.name} (part 1)",
            "lines": LineRange(start=existing_block.lines.start, end=lines.start - 1),
            "aligned_with": existing_block.aligned_with,
        })

    # The new block
    splits.append({
        "name": block_name,
        "lines": lines,
        "aligned_with": aligned_with,
    })

    # Part after overlap (if any)
    if existing_block.lines.end > lines.end:
        splits.append({
            "name": f"{existing_block.name} (part 2)",
            "lines": LineRange(start=lines.end + 1, end=existing_block.lines.end),
            "aligned_with": existing_block.aligned_with,
        })

    # Update the YAML file
    with open(map_path) as f:
        map_data = yaml.safe_load(f)

    # Find and replace the block
    for mapping in map_data["mappings"]:
        if mapping["file"] == str(file_path):
            # Remove old block
            mapping["blocks"] = [
                b for b in mapping["blocks"]
                if b["name"] != existing_block.name
            ]

            # Add split blocks
            for split in splits:
                mapping["blocks"].append({
                    "name": split["name"],
                    "lines": str(split["lines"]),
                    "last_updated": datetime.now().isoformat(),
                    "last_update_comment": comment or f"Split from '{existing_block.name}'",
                    "aligned_with": split["aligned_with"],
                })
            break

    # Write back
    with open(map_path, "w") as f:
        yaml.dump(map_data, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓ Split block '{existing_block.name}' into {len(splits)} blocks[/green]")
    return True, lines, aligned_with


def apply_replace_strategy(
    map_path: Path,
    file_path: Path,
    block_name: str,
    lines: LineRange,
    aligned_with: list[str],
    comment: str | None,
    existing_block: Block,
) -> tuple[bool, LineRange | None, list[str] | None]:
    """Replace an existing block entirely.

    Returns:
        Tuple of (success, final_lines, final_aligned_with) for trace printing.
    """
    console = Console()

    # Update the YAML file
    with open(map_path) as f:
        map_data = yaml.safe_load(f)

    # Find and replace the block
    for mapping in map_data["mappings"]:
        if mapping["file"] == str(file_path):
            for i, block in enumerate(mapping["blocks"]):
                if block["name"] == existing_block.name:
                    # Replace block
                    mapping["blocks"][i] = {
                        "name": block_name,
                        "lines": str(lines),
                        "last_updated": datetime.now().isoformat(),
                        "last_update_comment": comment or f"Replaced '{existing_block.name}'",
                        "aligned_with": aligned_with,
                    }
                    break

    # Write back
    with open(map_path, "w") as f:
        yaml.dump(map_data, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓ Replaced block '{existing_block.name}' with '{block_name}' (lines {lines})[/green]")
    return True, lines, aligned_with


def add_new_block_to_file(
    map_path: Path,
    file_path: Path,
    block_name: str,
    lines: LineRange,
    aligned_with: list[str],
    comment: str | None,
) -> tuple[bool, LineRange | None, list[str] | None]:
    """Add a new block to an existing file mapping.

    Returns:
        Tuple of (success, final_lines, final_aligned_with) for trace printing.
    """
    console = Console()

    # Update the YAML file
    with open(map_path) as f:
        map_data = yaml.safe_load(f)

    # Find the file mapping and add block
    for mapping in map_data["mappings"]:
        if mapping["file"] == str(file_path):
            mapping["blocks"].append({
                "name": block_name,
                "lines": str(lines),
                "last_updated": datetime.now().isoformat(),
                "last_update_comment": comment or "Added new block",
                "aligned_with": aligned_with,
            })
            break

    # Write back
    with open(map_path, "w") as f:
        yaml.dump(map_data, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓ Added new block '{block_name}' (lines {lines}) to {file_path}[/green]")
    return True, lines, aligned_with