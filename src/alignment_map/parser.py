"""Parsers for alignment map and markdown documents."""

import re
from datetime import datetime
from pathlib import Path

import yaml

from .models import AlignmentMap, Block, DocumentSection, FileMapping, LineRange


def parse_alignment_map(map_path: Path) -> AlignmentMap:
    """Parse the alignment map YAML file."""
    with open(map_path) as f:
        data = yaml.safe_load(f)

    version = data.get("version", 1)

    # Parse hierarchy
    hierarchy = data.get("hierarchy", {})
    requires_human = hierarchy.get("requires_human", [])
    technical = hierarchy.get("technical", [])

    # Parse settings
    settings = data.get("settings", {})

    # Parse mappings
    mappings: list[FileMapping] = []
    for mapping_data in data.get("mappings", []):
        file_path = Path(mapping_data["file"])
        blocks: list[Block] = []

        for block_data in mapping_data.get("blocks", []):
            block = Block(
                name=block_data["name"],
                lines=LineRange.from_string(block_data["lines"]),
                last_updated=parse_datetime(block_data.get("last_updated")),
                last_update_comment=block_data.get("last_update_comment"),
                last_reviewed=parse_datetime(block_data.get("last_reviewed")),
                aligned_with=block_data.get("aligned_with", []),
                block_id=block_data.get("id"),
            )
            blocks.append(block)

        mappings.append(FileMapping(file_path=file_path, blocks=blocks))

    return AlignmentMap(
        version=version,
        mappings=mappings,
        requires_human=requires_human,
        technical=technical,
        settings=settings,
    )


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse an ISO 8601 datetime string or return existing datetime."""
    if value is None:
        return None
    # PyYAML auto-converts ISO 8601 strings to datetime objects
    if isinstance(value, datetime):
        return value
    # Normalize the string
    normalized = value.replace("Z", "").split("+")[0]
    # Remove microseconds if present for simpler parsing
    if "." in normalized:
        normalized = normalized.split(".")[0]
    # Handle various datetime formats
    for fmt in [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",  # Python's datetime.__str__() format
        "%Y-%m-%d",
    ]:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unable to parse datetime: {value}")


def extract_document_section(doc_path: Path, anchor: str) -> DocumentSection | None:
    """Extract a section from a markdown document by anchor."""
    if not doc_path.exists():
        return None

    content = doc_path.read_text()

    # Extract last_reviewed from frontmatter or comment
    last_reviewed = extract_last_reviewed(content)

    # Convert anchor to expected header text
    # e.g., "#3-rich-self-contained-problem-objects" -> "3. Rich, Self-Contained Problem Objects"
    # This is a simplified approach; real implementation might need more sophisticated matching
    anchor_pattern = anchor.lstrip("#").replace("-", "[- ]?")

    # Find the header matching the anchor
    # Note: Double braces {{1,6}} needed to escape from f-string formatting
    header_pattern = rf"^(#{{1,6}})\s+.*{anchor_pattern}.*$"
    lines = content.split("\n")

    start_idx = None
    header_level = None
    title = ""

    for i, line in enumerate(lines):
        if re.match(header_pattern, line, re.IGNORECASE):
            start_idx = i
            match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if match:
                header_level = len(match.group(1))
                title = match.group(2)
            break

    if start_idx is None:
        return None

    # Find the end of the section (next header of same or higher level)
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[i])
        if match and len(match.group(1)) <= header_level:
            end_idx = i
            break

    section_content = "\n".join(lines[start_idx:end_idx]).strip()

    return DocumentSection(
        path=doc_path,
        anchor=anchor,
        title=title,
        content=section_content,
        last_reviewed=last_reviewed,
    )


def extract_last_reviewed(content: str) -> datetime | None:
    """Extract last_reviewed from document frontmatter or comment."""
    # Check YAML frontmatter
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if frontmatter_match:
        try:
            frontmatter = yaml.safe_load(frontmatter_match.group(1))
            if frontmatter and "last_reviewed" in frontmatter:
                return parse_datetime(frontmatter["last_reviewed"])
        except yaml.YAMLError:
            pass

    # Check HTML comment
    comment_match = re.search(r"<!--\s*last_reviewed:\s*([^\s]+)\s*-->", content)
    if comment_match:
        return parse_datetime(comment_match.group(1))

    return None


def get_document_last_reviewed(doc_path: Path) -> datetime | None:
    """Get the last_reviewed timestamp from a document."""
    if not doc_path.exists():
        return None
    content = doc_path.read_text()
    return extract_last_reviewed(content)
