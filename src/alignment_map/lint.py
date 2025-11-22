"""Map linting and auto-fix functionality."""

import ast
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console

from .models import AlignmentMap, LineRange, OverlapError
from .parser import extract_document_section
from .suggest import find_ast_node_end
from .touch import extract_target_name


def lint_alignment_map(
    project_root: Path,
    map_path: Path,
) -> list[dict]:
    """Lint the alignment map and return list of issues with fixes.

    Returns a list of fix dictionaries with the following structure:
    {
        "file": str,           # File path
        "block": str,          # Block name
        "issue": str,          # Issue type: line_drift, missing_file, invalid_lines, missing_anchor
        "old_lines": str,      # Original lines (for line_drift/invalid_lines)
        "new_lines": str,      # Suggested new lines (for line_drift)
        "action": str,         # auto or manual
        "confidence": str,     # high, medium, low
        "description": str,    # Human-readable description
        "reason": str,         # Reason for manual fix (if manual)
    }
    """
    fixes: list[dict] = []

    # Parse the alignment map
    try:
        alignment_map = AlignmentMap.load(map_path)
    except Exception as e:
        # Can't parse the map - return a single critical error
        fixes.append({
            "file": str(map_path),
            "block": "",
            "issue": "parse_error",
            "action": "manual",
            "confidence": "high",
            "description": f"Failed to parse alignment map: {e}",
            "reason": "Cannot parse alignment map file",
        })
        return fixes

    # Check all mappings
    for mapping in alignment_map.mappings:
        file_path = project_root / mapping.file

        # Check if file exists
        if not file_path.exists():
            fix = {
                "file": str(mapping.file),
                "block": "",
                "issue": "missing_file",
                "confidence": "high",
                "description": f"File not found: {mapping.file}",
            }

            # Check for orphaned references
            refs = alignment_map.get_all_references_to(str(mapping.file))
            if refs:
                fix["action"] = "manual"
                fix["reason"] = f"Has {len(refs)} orphaned reference(s)"
                fix["orphaned_refs"] = [
                    f"{path}:{block.name}" for path, block in refs
                ]
            else:
                fix["action"] = "auto"

            fixes.append(fix)
            # Skip checking blocks for missing files
            continue

        # Read file content for line checks
        try:
            file_content = file_path.read_text()
            line_count = len(file_content.split("\n"))
        except Exception as e:
            fixes.append({
                "file": str(mapping.file),
                "block": "",
                "issue": "read_error",
                "action": "manual",
                "confidence": "high",
                "description": f"Cannot read file: {e}",
                "reason": "Cannot read file to validate",
            })
            continue

        # Check each block
        for block in mapping.blocks:
            # Check line range is valid
            if block.lines.end > line_count:
                fix = {
                    "file": str(mapping.file),
                    "block": block.name,
                    "issue": "invalid_lines",
                    "old_lines": str(block.lines),
                    "confidence": "high",
                    "description": f"Block '{block.name}' ends at line {block.lines.end} but file has {line_count} lines",
                }

                # Check if block has dependencies
                has_alignments = bool(block.aligned_with)
                refs = alignment_map.get_all_references_to(f"{mapping.file}#{block.name}")

                if has_alignments or refs:
                    fix["action"] = "manual"
                    fix["reason"] = "Block has dependencies"
                    if block.aligned_with:
                        fix["aligns_with"] = block.aligned_with
                    if refs:
                        fix["referenced_by"] = [f"{p}:{b.name}" for p, b in refs]
                else:
                    fix["action"] = "auto"

                fixes.append(fix)
                # Don't check for line drift if lines are already invalid
                continue

            # Check for line drift using AST
            new_lines = detect_line_drift(
                project_root,
                mapping.file,
                block.name,
                block.lines,
            )

            if new_lines is not None and new_lines != block.lines:
                fix = {
                    "file": str(mapping.file),
                    "block": block.name,
                    "issue": "line_drift",
                    "old_lines": str(block.lines),
                    "new_lines": str(new_lines),
                    "confidence": "high",
                    "description": f"Block '{block.name}' has drifted from {block.lines} to {new_lines}",
                }

                # Check if update would cause overlap
                would_overlap = False
                overlap_with = None
                for other in mapping.blocks:
                    if other.name != block.name and new_lines.overlaps(other.lines):
                        would_overlap = True
                        overlap_with = other
                        break

                if would_overlap:
                    fix["action"] = "manual"
                    fix["reason"] = "Would overlap with existing block"
                    fix["overlap_with"] = f"{overlap_with.name} ({overlap_with.lines})"
                else:
                    fix["action"] = "auto"

                fixes.append(fix)

            # Check aligned docs exist and anchors resolve
            for aligned_ref in block.aligned_with:
                parts = aligned_ref.split("#")
                doc_path_str = parts[0]
                anchor = parts[1] if len(parts) > 1 else None

                # Skip code references (src/)
                if doc_path_str.startswith("src/"):
                    continue

                doc_path = project_root / doc_path_str

                # Check doc exists
                if not doc_path.exists():
                    fixes.append({
                        "file": str(mapping.file),
                        "block": block.name,
                        "issue": "missing_anchor",
                        "aligned_ref": aligned_ref,
                        "action": "manual",
                        "confidence": "high",
                        "description": f"Aligned document not found: {doc_path_str}",
                        "reason": "Cannot determine correct anchor automatically",
                    })
                    continue

                # Check anchor resolves
                if anchor:
                    section = extract_document_section(doc_path, anchor)
                    if section is None:
                        fixes.append({
                            "file": str(mapping.file),
                            "block": block.name,
                            "issue": "missing_anchor",
                            "aligned_ref": aligned_ref,
                            "action": "manual",
                            "confidence": "medium",
                            "description": f"Anchor '{anchor}' not found in {doc_path_str}",
                            "reason": "Cannot determine correct anchor automatically",
                        })

    return fixes


def detect_line_drift(
    project_root: Path,
    file_path: Path,
    block_name: str,
    expected_lines: LineRange,
) -> LineRange | None:
    """Detect if a block has drifted from its expected lines.

    Returns new LineRange if drifted, None if matches or can't determine.
    Uses AST parsing to find where the code actually is.
    """
    full_path = project_root / file_path

    if not full_path.exists():
        return None

    # Only handle Python files with AST
    if full_path.suffix != ".py":
        return None

    try:
        code = full_path.read_text()
        tree = ast.parse(code)
    except (SyntaxError, Exception):
        return None

    # Extract the actual identifier from block name
    target_name = extract_target_name(block_name)

    # Search for matching AST node
    for node in ast.walk(tree):
        node_name = None

        if isinstance(node, ast.ClassDef):
            node_name = node.name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node_name = node.name

        if node_name == target_name:
            start_line = node.lineno
            end_line = find_ast_node_end(node)
            actual_lines = LineRange(start=start_line, end=end_line)

            # Return actual lines if different from expected
            if actual_lines.start != expected_lines.start or actual_lines.end != expected_lines.end:
                return actual_lines
            else:
                return None  # Lines match, no drift

    # Try searching inside classes for methods
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name == target_name:
                        start_line = item.lineno
                        end_line = find_ast_node_end(item)
                        actual_lines = LineRange(start=start_line, end=end_line)

                        if actual_lines.start != expected_lines.start or actual_lines.end != expected_lines.end:
                            return actual_lines
                        else:
                            return None

    # Couldn't find the block - return None (unknown)
    return None


def write_fixes_file(
    fixes_path: Path,
    fixes: list[dict],
) -> None:
    """Write fixes to .alignment-map.fixes file."""
    fixes_data = {
        "generated": datetime.now().isoformat(),
        "fixes": fixes,
    }

    with open(fixes_path, "w") as f:
        yaml.dump(fixes_data, f, default_flow_style=False, sort_keys=False)


def apply_fixes_file(
    project_root: Path,
    map_path: Path,
    fixes_path: Path,
) -> tuple[list[str], list[dict]]:
    """Apply auto fixes from .alignment-map.fixes and return results.

    Returns a tuple of:
        - List of human-readable strings describing what was fixed
        - List of manual fixes that were skipped
    """
    console = Console()
    actions_taken: list[str] = []
    skipped_manual: list[dict] = []

    # Load fixes file
    with open(fixes_path) as f:
        fixes_data = yaml.safe_load(f)

    fixes = fixes_data.get("fixes", [])

    if not fixes:
        return (["No fixes to apply"], [])

    # Load the alignment map
    with open(map_path) as f:
        map_data = yaml.safe_load(f)

    # Track files and blocks to remove
    files_to_remove: set[str] = set()
    blocks_to_remove: list[tuple[str, str]] = []  # (file, block_name)
    alignments_to_remove: list[tuple[str, str, str]] = []  # (file, block_name, aligned_ref)

    # Apply each fix
    for fix in fixes:
        issue = fix.get("issue", "")
        action = fix.get("action", "")
        file_path = fix.get("file", "")
        block_name = fix.get("block", "")

        # Skip manual fixes
        if action == "manual":
            skipped_manual.append(fix)
            continue

        # Only apply auto fixes
        if action != "auto":
            # Legacy support for old action types
            pass

        # Handle different issue types
        if issue == "missing_file":
            files_to_remove.add(file_path)
            actions_taken.append(f"Removed file mapping: {file_path}")

        elif issue == "line_drift" and "new_lines" in fix:
            # Update block lines
            new_lines = fix["new_lines"]
            old_lines = fix.get("old_lines", "")

            for mapping in map_data.get("mappings", []):
                if mapping["file"] == file_path:
                    for block_data in mapping.get("blocks", []):
                        if block_data["name"] == block_name:
                            block_data["lines"] = new_lines
                            actions_taken.append(
                                f"Updated {file_path}:{block_name} lines {old_lines} -> {new_lines}"
                            )
                            break

        elif issue == "invalid_lines":
            # Remove block with invalid lines (only if auto)
            blocks_to_remove.append((file_path, block_name))
            actions_taken.append(f"Removed block with invalid lines: {file_path}:{block_name}")

    # Remove alignments
    for file_path, block_name, aligned_ref in alignments_to_remove:
        for mapping in map_data.get("mappings", []):
            if mapping["file"] == file_path:
                for block_data in mapping.get("blocks", []):
                    if block_data["name"] == block_name:
                        if "aligned_with" in block_data and aligned_ref in block_data["aligned_with"]:
                            block_data["aligned_with"].remove(aligned_ref)

    # Remove blocks
    for file_path, block_name in blocks_to_remove:
        for mapping in map_data.get("mappings", []):
            if mapping["file"] == file_path:
                mapping["blocks"] = [
                    b for b in mapping.get("blocks", [])
                    if b["name"] != block_name
                ]

    # Remove file mappings
    map_data["mappings"] = [
        m for m in map_data.get("mappings", [])
        if m["file"] not in files_to_remove
    ]

    # Write back the updated map
    with open(map_path, "w") as f:
        yaml.dump(map_data, f, default_flow_style=False, sort_keys=False)

    return (actions_taken, skipped_manual)
