"""Touch command implementation - updates existing block metadata with smart line detection."""

import ast
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console

from .models import AlignmentMap, Block, LineRange
from .suggest import find_ast_node_end


def touch_block(
    project_root: Path,
    map_path: Path,
    file_path: Path,
    block_name: str,
    comment: str,
) -> tuple[bool, LineRange | None, list[str] | None]:
    """Update an existing block's metadata with smart line detection.

    Returns:
        Tuple of (success, new_lines, aligned_with) for trace printing.
    """
    console = Console()

    # Parse existing map
    try:
        alignment_map = AlignmentMap.load(map_path)
    except Exception as e:
        console.print(f"[red]Error parsing alignment map: {e}[/red]")
        return False, None, None

    # Find the block
    file_mapping = alignment_map.get_file_mapping(file_path)
    if file_mapping is None:
        console.print(f"[red]Error: File not in alignment map: {file_path}[/red]")
        return False, None, None

    existing_block = None
    for block in file_mapping.blocks:
        if block.name == block_name:
            existing_block = block
            break

    if existing_block is None:
        console.print(f"[red]Error: Block '{block_name}' not found in {file_path}[/red]")
        console.print("\n[yellow]Available blocks:[/yellow]")
        for block in file_mapping.blocks:
            console.print(f"  - {block.name} (lines {block.lines})")
        return False, None, None

    # Check if file exists
    full_file_path = project_root / file_path
    if not full_file_path.exists():
        console.print(f"[red]Error: File does not exist: {file_path}[/red]")
        return False, None, None

    # Use AST to find where the code moved
    new_lines = find_block_current_location(
        full_file_path, block_name, existing_block.lines
    )

    if new_lines is None:
        # Couldn't find the block - keep original lines
        new_lines = existing_block.lines
        console.print(
            f"[yellow]Warning: Could not detect code movement for '{block_name}'. "
            f"Keeping original lines {existing_block.lines}[/yellow]"
        )

    # Check for overlaps with other blocks (not this one)
    for block in file_mapping.blocks:
        if block.name != block_name:
            if lines_overlap(block.lines, new_lines):
                console.print(
                    f"[red]Error: New lines {new_lines} would overlap with "
                    f"block '{block.name}' (lines {block.lines})[/red]"
                )
                return False, None, None

    # Update the YAML file
    with open(map_path) as f:
        map_data = yaml.safe_load(f)

    # Find and update the block
    for mapping in map_data["mappings"]:
        if mapping["file"] == str(file_path):
            for block_data in mapping["blocks"]:
                if block_data["name"] == block_name:
                    old_lines = block_data["lines"]
                    block_data["lines"] = str(new_lines)
                    block_data["last_updated"] = datetime.now().isoformat()
                    block_data["last_update_comment"] = comment
                    break

    # Write back
    with open(map_path, "w") as f:
        yaml.dump(map_data, f, default_flow_style=False, sort_keys=False)

    # Print success message
    if str(new_lines) != old_lines:
        console.print(
            f"[green]✓ Updated block '{block_name}' lines {old_lines} -> {new_lines}[/green]"
        )
    else:
        console.print(
            f"[green]✓ Updated block '{block_name}' (lines {new_lines})[/green]"
        )

    return True, new_lines, existing_block.aligned_with


def find_block_current_location(
    file_path: Path,
    block_name: str,
    old_lines: LineRange,
) -> LineRange | None:
    """Find the current location of a named block using AST.

    Uses multiple strategies:
    1. AST parsing for function/class names
    2. Fuzzy matching if name contains type hints (e.g., "MyClass class")
    """
    if file_path.suffix != ".py":
        # For non-Python files, return original lines
        return old_lines

    try:
        code = file_path.read_text()
        tree = ast.parse(code)
    except (SyntaxError, Exception):
        # Can't parse, return original lines
        return old_lines

    # Extract the actual name from block name (e.g., "MyClass class" -> "MyClass")
    target_name = extract_target_name(block_name)

    # Search for matching AST node
    for node in ast.walk(tree):
        node_name = None

        if isinstance(node, ast.ClassDef):
            node_name = node.name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node_name = node.name

        if node_name == target_name:
            start_line = node.lineno  # type: ignore[attr-defined]
            end_line = find_ast_node_end(node)
            return LineRange(start=start_line, end=end_line)

    # Try fuzzy matching for methods inside classes
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name == target_name:
                        start_line = item.lineno
                        end_line = find_ast_node_end(item)
                        return LineRange(start=start_line, end=end_line)

    return None


def extract_target_name(block_name: str) -> str:
    """Extract the actual identifier from a block name.

    Examples:
        "MyClass class" -> "MyClass"
        "my_function function" -> "my_function"
        "my_method method" -> "my_method"
        "some_func async function" -> "some_func"
        "MyClass" -> "MyClass"
    """
    # Common suffixes to strip - order matters! Longer suffixes first
    suffixes = [" async function", " async_function", " class", " function", " method"]

    for suffix in suffixes:
        if block_name.endswith(suffix):
            return block_name[:-len(suffix)]

    return block_name


def lines_overlap(range1: LineRange, range2: LineRange) -> bool:
    """Check if two line ranges overlap."""
    return not (range1.end < range2.start or range2.end < range1.start)
