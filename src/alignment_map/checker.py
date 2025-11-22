"""Core alignment checking logic."""

from datetime import datetime
from pathlib import Path

from .git import get_staged_changes, is_file_staged
from .models import AlignmentMap, Block, CheckFailure, CheckResult, FileChange
from .parser import extract_document_section, get_document_last_reviewed


def check_staged_changes(project_root: Path, map_path: Path) -> list[CheckFailure]:
    """Check all staged changes for alignment issues."""
    alignment_map = AlignmentMap.load(map_path)
    staged_changes = get_staged_changes(project_root)
    failures: list[CheckFailure] = []

    # Also check if the alignment map itself was updated
    map_updated = is_file_staged(project_root, map_path.relative_to(project_root))

    for file_change in staged_changes:
        # Skip the alignment map file itself
        if file_change.file_path == map_path.relative_to(project_root):
            continue

        file_failures = check_file_change(
            project_root, alignment_map, file_change, map_updated
        )
        failures.extend(file_failures)

    return failures


def check_file_change(
    project_root: Path,
    alignment_map: AlignmentMap,
    file_change: FileChange,
    map_updated: bool,
) -> list[CheckFailure]:
    """Check a single file change for alignment issues."""
    failures: list[CheckFailure] = []

    # Get file mapping
    file_mapping = alignment_map.get_file_mapping(file_change.file_path)

    if file_mapping is None:
        # File not in alignment map
        failures.append(
            CheckFailure(
                result=CheckResult.UNMAPPED_FILE,
                file_path=file_change.file_path,
                message=f"File not in alignment map: {file_change.file_path}",
                suggestion=generate_file_mapping_suggestion(file_change.file_path),
            )
        )
        return failures

    # Check each changed line
    for changed_line in file_change.changed_lines:
        block = find_block_for_line(file_mapping.blocks, changed_line.line_number)

        if block is None:
            # Line not in any mapped block
            nearest = find_nearest_block(file_mapping.blocks, changed_line.line_number)
            failures.append(
                CheckFailure(
                    result=CheckResult.UNMAPPED_LINES,
                    file_path=file_change.file_path,
                    message=f"Line {changed_line.line_number} not in any mapped block",
                    block=nearest,
                    suggestion=generate_unmapped_lines_suggestion(
                        file_change.file_path, changed_line.line_number, nearest
                    ),
                )
            )
            continue

        # Check if block was updated in the map
        if not map_updated:
            failures.append(
                CheckFailure(
                    result=CheckResult.MAP_NOT_UPDATED,
                    file_path=file_change.file_path,
                    message=f"Block '{block.name}' modified but alignment map not updated",
                    block=block,
                    suggestion=generate_map_update_suggestion(block),
                )
            )
            # Don't check aligned docs if map wasn't updated
            continue

        # Check aligned documents
        for aligned_ref in block.aligned_with:
            doc_failure = check_aligned_document(
                project_root, alignment_map, file_change.file_path, block, aligned_ref
            )
            if doc_failure:
                failures.append(doc_failure)

    # Deduplicate failures (same block might be hit multiple times)
    return deduplicate_failures(failures)


def find_block_for_line(blocks: list[Block], line_number: int) -> Block | None:
    """Find the block containing a specific line."""
    for block in blocks:
        if block.lines.contains(line_number):
            return block
    return None


def find_nearest_block(blocks: list[Block], line_number: int) -> Block | None:
    """Find the nearest block to a line number."""
    if not blocks:
        return None

    nearest = blocks[0]
    min_distance = abs(line_number - blocks[0].lines.start)

    for block in blocks[1:]:
        distance = min(
            abs(line_number - block.lines.start),
            abs(line_number - block.lines.end),
        )
        if distance < min_distance:
            min_distance = distance
            nearest = block

    return nearest


def check_aligned_document(
    project_root: Path,
    alignment_map: AlignmentMap,
    file_path: Path,
    block: Block,
    aligned_ref: str,
) -> CheckFailure | None:
    """Check if an aligned document is stale."""
    # Parse the reference (path#anchor or path)
    if "#" in aligned_ref:
        doc_path_str, anchor = aligned_ref.split("#", 1)
    else:
        doc_path_str = aligned_ref
        anchor = ""

    doc_path = project_root / doc_path_str

    # Check if it's a code reference (has line numbers or refers to src/)
    if doc_path_str.startswith("src/") or ":" in aligned_ref:
        # Code-to-code reference - check other code block
        # For now, skip these (could be expanded later)
        return None

    # Get the document's last_reviewed
    last_reviewed = get_document_last_reviewed(doc_path)

    if last_reviewed is None:
        # Document has no last_reviewed field - always needs review
        section = extract_document_section(doc_path, anchor) if anchor else None
        return CheckFailure(
            result=CheckResult.STALE_DOC,
            file_path=file_path,
            message=f"Document has no last_reviewed: {aligned_ref}",
            block=block,
            aligned_doc=aligned_ref,
            doc_section=section.content if section else None,
            suggestion=f"Add last_reviewed field to {doc_path_str}",
        )

    # Compare timestamps
    if block.last_updated and last_reviewed < block.last_updated:
        section = extract_document_section(doc_path, anchor) if anchor else None

        # Check if human escalation is required
        if alignment_map.is_human_required(doc_path_str):
            return CheckFailure(
                result=CheckResult.HUMAN_ESCALATION,
                file_path=file_path,
                message=f"Human review required for: {aligned_ref}",
                block=block,
                aligned_doc=aligned_ref,
                doc_section=section.content if section else None,
                suggestion="Have a human review and update last_reviewed",
            )

        return CheckFailure(
            result=CheckResult.STALE_DOC,
            file_path=file_path,
            message=f"Stale document: {aligned_ref}",
            block=block,
            aligned_doc=aligned_ref,
            doc_section=section.content if section else None,
            suggestion=f"Review and update last_reviewed in {doc_path_str}",
        )

    return None


def deduplicate_failures(failures: list[CheckFailure]) -> list[CheckFailure]:
    """Remove duplicate failures (same file, result, and block)."""
    seen: set[tuple[Path, CheckResult, str | None]] = set()
    unique: list[CheckFailure] = []

    for failure in failures:
        key = (failure.file_path, failure.result, failure.block.name if failure.block else None)
        if key not in seen:
            seen.add(key)
            unique.append(failure)

    return unique


def generate_file_mapping_suggestion(file_path: Path) -> str:
    """Generate a suggestion for adding a file to the alignment map."""
    return f"""Add to .alignment-map.yaml:

  - file: {file_path}
    blocks:
      - name: <describe the block>
        lines: 1-<end line>
        last_updated: {datetime.now().isoformat()}
        last_update_comment: "Initial mapping"
        aligned_with:
          - docs/ARCHITECTURE.md#<relevant-section>"""


def generate_unmapped_lines_suggestion(
    file_path: Path, line_number: int, nearest: Block | None
) -> str:
    """Generate a suggestion for unmapped lines."""
    if nearest:
        return f"""Either extend the nearest block or add a new one:

  Nearest block: "{nearest.name}" (lines {nearest.lines})

  Option 1 - Extend block:
    lines: {nearest.lines.start}-{max(nearest.lines.end, line_number + 10)}

  Option 2 - Add new block for lines around {line_number}"""
    return f"Add a new block covering line {line_number}"


def generate_map_update_suggestion(block: Block) -> str:
    """Generate a suggestion for updating the alignment map."""
    return f"""Update the block entry in .alignment-map.yaml:

  - name: {block.name}
    lines: {block.lines}
    last_updated: {datetime.now().isoformat()}
    last_update_comment: "<describe your change>"
    aligned_with:
      {chr(10).join(f'- {ref}' for ref in block.aligned_with)}"""
