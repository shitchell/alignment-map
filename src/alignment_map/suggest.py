"""Suggest command implementation - suggests block boundaries for unmapped code."""

import ast
import re
from pathlib import Path
from typing import Any, Union

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import AlignmentMap, Block, LineRange


class BlockSuggestion:
    """A suggested code block."""

    def __init__(
        self,
        name: str,
        lines: LineRange,
        block_type: str,
        confidence: str = "high",
    ):
        self.name = name
        self.lines = lines
        self.block_type = block_type  # 'class', 'function', 'method', etc.
        self.confidence = confidence  # 'high', 'medium', 'low'


def suggest_blocks(
    project_root: Path,
    map_path: Path,
    file_path: Path | None = None,
) -> dict[Path, list[BlockSuggestion]]:
    """Suggest block boundaries for unmapped code."""
    console = Console()

    # Parse existing map
    try:
        alignment_map = AlignmentMap.load(map_path)
    except Exception as e:
        console.print(f"[red]Error parsing alignment map: {e}[/red]")
        return {}

    # Determine files to analyze
    if file_path:
        files_to_analyze = [file_path]
    else:
        # Find all Python files that aren't fully mapped
        files_to_analyze = find_unmapped_files(project_root, alignment_map)

    suggestions = {}

    for file in files_to_analyze:
        full_path = project_root / file if not Path(file).is_absolute() else Path(file)

        if not full_path.exists():
            console.print(f"[yellow]Warning: File not found: {file}[/yellow]")
            continue

        # Get existing blocks for this file
        file_mapping = alignment_map.get_file_mapping(file)
        existing_blocks = file_mapping.blocks if file_mapping else []

        # Analyze file based on extension
        if full_path.suffix == ".py":
            file_suggestions = suggest_python_blocks(full_path, existing_blocks)
        else:
            file_suggestions = suggest_generic_blocks(full_path, existing_blocks)

        if file_suggestions:
            suggestions[file] = file_suggestions

    return suggestions


def find_unmapped_files(project_root: Path, alignment_map: AlignmentMap) -> list[Path]:
    """Find files that aren't fully mapped."""
    unmapped = []

    # Find all source files
    for pattern in ["**/*.py", "**/*.js", "**/*.ts", "**/*.java", "**/*.go"]:
        for file_path in project_root.glob(pattern):
            # Skip test files and hidden directories
            if any(part.startswith(".") for part in file_path.parts):
                continue
            if "test" in file_path.name.lower():
                continue

            rel_path = file_path.relative_to(project_root)

            # Check if file is in map
            file_mapping = alignment_map.get_file_mapping(rel_path)
            if file_mapping is None:
                unmapped.append(rel_path)
            else:
                # Check if file is fully covered
                file_lines = len(file_path.read_text().split("\n"))
                covered_lines = set()
                for block in file_mapping.blocks:
                    for line in range(block.lines.start, block.lines.end + 1):
                        covered_lines.add(line)

                # If less than 80% covered, consider it unmapped
                coverage = len(covered_lines) / file_lines if file_lines > 0 else 0
                if coverage < 0.8:
                    unmapped.append(rel_path)

    return unmapped


def suggest_python_blocks(
    file_path: Path, existing_blocks: list[Any]
) -> list[BlockSuggestion]:
    """Suggest blocks for a Python file using AST parsing."""
    suggestions = []

    try:
        code = file_path.read_text()
        tree = ast.parse(code)

        for node in ast.walk(tree):
            suggestion = None

            if isinstance(node, ast.ClassDef):
                # Class definition
                start_line = node.lineno
                end_line = find_ast_node_end(node)

                suggestion = BlockSuggestion(
                    name=f"{node.name} class",
                    lines=LineRange(start=start_line, end=end_line),
                    block_type="class",
                    confidence="high",
                )

            elif isinstance(node, ast.FunctionDef):
                # Function/method definition
                # Check if it's a method (inside a class)
                is_method = any(
                    isinstance(parent, ast.ClassDef)
                    for parent in ast.walk(tree)
                    if hasattr(parent, "body") and node in parent.body
                )

                start_line = node.lineno
                end_line = find_ast_node_end(node)

                block_type = "method" if is_method else "function"
                suggestion = BlockSuggestion(
                    name=f"{node.name} {block_type}",
                    lines=LineRange(start=start_line, end=end_line),
                    block_type=block_type,
                    confidence="high",
                )

            elif isinstance(node, ast.AsyncFunctionDef):
                # Async function/method
                start_line = node.lineno
                end_line = find_ast_node_end(node)

                suggestion = BlockSuggestion(
                    name=f"{node.name} async function",
                    lines=LineRange(start=start_line, end=end_line),
                    block_type="async_function",
                    confidence="high",
                )

            # Check if suggestion overlaps with existing blocks
            if suggestion and not overlaps_with_existing(suggestion, existing_blocks):
                suggestions.append(suggestion)

    except SyntaxError as e:
        # AST parsing failed - fall back to pattern-based suggestions
        return suggest_python_blocks_fallback(file_path, existing_blocks)
    except Exception:
        # Other error - fall back
        return suggest_python_blocks_fallback(file_path, existing_blocks)

    return suggestions


def find_ast_node_end(node: ast.AST) -> int:
    """Find the end line of an AST node."""
    # Get start line if available
    lineno = getattr(node, "lineno", 1)
    end_line: int = lineno if isinstance(lineno, int) else 1

    for child in ast.walk(node):
        child_lineno = getattr(child, "lineno", None)
        if child_lineno is not None and isinstance(child_lineno, int):
            end_line = max(end_line, child_lineno)
        child_end_lineno = getattr(child, "end_lineno", None)
        if child_end_lineno is not None and isinstance(child_end_lineno, int):
            end_line = max(end_line, child_end_lineno)

    return end_line


def suggest_python_blocks_fallback(
    file_path: Path, existing_blocks: list[Any]
) -> list[BlockSuggestion]:
    """Fallback pattern-based suggestion for Python files."""
    suggestions = []
    lines = file_path.read_text().split("\n")

    # Patterns to look for
    class_pattern = re.compile(r"^class\s+(\w+)")
    function_pattern = re.compile(r"^def\s+(\w+)")
    async_function_pattern = re.compile(r"^async\s+def\s+(\w+)")

    current_block = None
    current_indent = 0

    for i, line in enumerate(lines, 1):
        # Calculate indent
        indent = len(line) - len(line.lstrip())

        # Check for class
        match = class_pattern.match(line.lstrip())
        if match:
            # Save previous block if any
            if current_block:
                current_block.lines.end = i - 1
                if not overlaps_with_existing(current_block, existing_blocks):
                    suggestions.append(current_block)

            current_block = BlockSuggestion(
                name=f"{match.group(1)} class",
                lines=LineRange(start=i, end=i),  # End will be updated
                block_type="class",
                confidence="medium",
            )
            current_indent = indent
            continue

        # Check for function
        match = function_pattern.match(line.lstrip())
        if match:
            # If inside a class (higher indent), it's a method
            is_method = current_block and current_block.block_type == "class" and indent > current_indent

            if not is_method:
                # Save previous block if any
                if current_block:
                    current_block.lines.end = i - 1
                    if not overlaps_with_existing(current_block, existing_blocks):
                        suggestions.append(current_block)

                current_block = BlockSuggestion(
                    name=f"{match.group(1)} function",
                    lines=LineRange(start=i, end=i),
                    block_type="function",
                    confidence="medium",
                )
                current_indent = indent

        # Check for async function
        match = async_function_pattern.match(line.lstrip())
        if match:
            # Save previous block if any
            if current_block and indent <= current_indent:
                current_block.lines.end = i - 1
                if not overlaps_with_existing(current_block, existing_blocks):
                    suggestions.append(current_block)

                current_block = BlockSuggestion(
                    name=f"{match.group(1)} async function",
                    lines=LineRange(start=i, end=i),
                    block_type="async_function",
                    confidence="medium",
                )
                current_indent = indent

    # Save last block
    if current_block:
        current_block.lines.end = len(lines)
        if not overlaps_with_existing(current_block, existing_blocks):
            suggestions.append(current_block)

    return suggestions


def suggest_generic_blocks(file_path: Path, existing_blocks: list[Any]) -> list[BlockSuggestion]:
    """Suggest blocks for non-Python files using generic patterns."""
    suggestions = []
    lines = file_path.read_text().split("\n")
    extension = file_path.suffix

    # Define patterns based on file type
    patterns = get_patterns_for_extension(extension)

    if not patterns:
        # No patterns for this file type
        # Suggest the whole file as a single block if unmapped
        if not existing_blocks:
            suggestions.append(
                BlockSuggestion(
                    name=f"{file_path.stem} file",
                    lines=LineRange(start=1, end=len(lines)),
                    block_type="file",
                    confidence="low",
                )
            )
        return suggestions

    # Use patterns to find blocks
    for i, line in enumerate(lines, 1):
        for pattern_info in patterns:
            match = pattern_info["pattern"].match(line.lstrip())
            if match:
                # Find the end of this block (next match or end of file)
                end_line = len(lines)
                for j in range(i + 1, len(lines) + 1):
                    if j > len(lines):
                        break
                    next_line = lines[j - 1]
                    for p in patterns:
                        if p["pattern"].match(next_line.lstrip()):
                            end_line = j - 1
                            break
                    if end_line != len(lines):
                        break

                suggestion = BlockSuggestion(
                    name=f"{match.group(1) if match.groups() else 'Block'} {pattern_info['type']}",
                    lines=LineRange(start=i, end=end_line),
                    block_type=pattern_info["type"],
                    confidence="low",
                )

                if not overlaps_with_existing(suggestion, existing_blocks):
                    suggestions.append(suggestion)

    return suggestions


def get_patterns_for_extension(extension: str) -> list[dict[str, Any]]:
    """Get regex patterns for different file extensions."""
    patterns = {
        ".js": [
            {"pattern": re.compile(r"^class\s+(\w+)"), "type": "class"},
            {"pattern": re.compile(r"^function\s+(\w+)"), "type": "function"},
            {"pattern": re.compile(r"^const\s+(\w+)\s*=\s*\("), "type": "function"},
            {"pattern": re.compile(r"^export\s+class\s+(\w+)"), "type": "class"},
        ],
        ".ts": [
            {"pattern": re.compile(r"^export\s+class\s+(\w+)"), "type": "class"},
            {"pattern": re.compile(r"^class\s+(\w+)"), "type": "class"},
            {"pattern": re.compile(r"^interface\s+(\w+)"), "type": "interface"},
            {"pattern": re.compile(r"^function\s+(\w+)"), "type": "function"},
            {"pattern": re.compile(r"^export\s+function\s+(\w+)"), "type": "function"},
        ],
        ".java": [
            {"pattern": re.compile(r"^public\s+class\s+(\w+)"), "type": "class"},
            {"pattern": re.compile(r"^class\s+(\w+)"), "type": "class"},
            {"pattern": re.compile(r"^public\s+interface\s+(\w+)"), "type": "interface"},
            {"pattern": re.compile(r"^\s*(public|private|protected)?\s*\w+\s+(\w+)\s*\("), "type": "method"},
        ],
        ".go": [
            {"pattern": re.compile(r"^type\s+(\w+)\s+struct"), "type": "struct"},
            {"pattern": re.compile(r"^type\s+(\w+)\s+interface"), "type": "interface"},
            {"pattern": re.compile(r"^func\s+(\w+)"), "type": "function"},
            {"pattern": re.compile(r"^func\s+\(\w+\s+\*?\w+\)\s+(\w+)"), "type": "method"},
        ],
    }

    return patterns.get(extension, [])


def overlaps_with_existing(
    suggestion: BlockSuggestion, existing_blocks: list[Any]
) -> bool:
    """Check if a suggestion overlaps with existing blocks."""
    for block in existing_blocks:
        # Check if ranges overlap
        if not (
            suggestion.lines.end < block.lines.start
            or suggestion.lines.start > block.lines.end
        ):
            return True
    return False


def print_suggestions(suggestions: dict[Path, list[BlockSuggestion]]) -> None:
    """Print suggestions in a formatted way."""
    console = Console()

    if not suggestions:
        console.print("[green]No unmapped code found![/green]")
        return

    for file_path, file_suggestions in suggestions.items():
        console.print(f"\n[bold cyan]Unmapped code in {file_path}:[/bold cyan]\n")

        # Create a table
        table = Table(show_header=True, header_style="bold")
        table.add_column("Lines", style="yellow")
        table.add_column("Type", style="cyan")
        table.add_column("Name")
        table.add_column("Confidence")

        for suggestion in file_suggestions:
            confidence_style = {
                "high": "green",
                "medium": "yellow",
                "low": "red",
            }.get(suggestion.confidence, "white")

            table.add_row(
                str(suggestion.lines),
                suggestion.block_type,
                suggestion.name,
                f"[{confidence_style}]{suggestion.confidence}[/{confidence_style}]",
            )

        console.print(table)

        # Print commands
        console.print("\n[bold]To add these blocks, run:[/bold]\n")
        for suggestion in file_suggestions:
            command = (
                f"  alignment-map update {file_path} "
                f'--block "{suggestion.name}" '
                f"--lines {suggestion.lines} "
                f"--aligned-with <DOC>"
            )
            console.print(f"[dim]{command}[/dim]")

    # Print grep patterns as fallback
    console.print("\n[bold]Fallback grep patterns:[/bold]\n")
    console.print('  [dim]grep -n "^def \\|^class " <file>  # Python[/dim]')
    console.print('  [dim]grep -n "^function \\|^class " <file>  # JavaScript[/dim]')
    console.print('  [dim]grep -n "^func " <file>  # Go[/dim]')
    console.print("\n[yellow]Note: NEVER guess document alignments. Always specify --aligned-with explicitly.[/yellow]")