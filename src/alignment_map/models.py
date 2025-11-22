"""Data models for alignment map using Pydantic."""

import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, PrivateAttr, model_validator


class CheckResult(str, Enum):
    """Result of an alignment check."""

    OK = "ok"
    UNMAPPED_FILE = "unmapped_file"
    UNMAPPED_LINES = "unmapped_lines"
    MAP_NOT_UPDATED = "map_not_updated"
    STALE_DOC = "stale_doc"
    HUMAN_ESCALATION = "human_escalation"


class OverlapError(Exception):
    """Raised when a block operation would cause overlap."""

    pass


class BlockNotFoundError(Exception):
    """Raised when a block is not found."""

    pass


class LineRange(BaseModel):
    """A range of lines in a file."""

    start: int
    end: int

    @model_validator(mode="before")
    @classmethod
    def parse_string(cls, data: str | dict[str, int]) -> dict[str, int]:
        """Parse '10-50' format."""
        if isinstance(data, str):
            parts = data.split("-")
            if len(parts) != 2:
                raise ValueError(f"Invalid line range format: {data}")
            return {"start": int(parts[0]), "end": int(parts[1])}
        return data

    @model_validator(mode="after")
    def validate_range(self) -> "LineRange":
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self

    def contains(self, line: int) -> bool:
        """Check if a line number is within this range."""
        return self.start <= line <= self.end

    def overlaps(self, other: "LineRange") -> bool:
        """Check if two line ranges overlap."""
        return not (self.end < other.start or other.end < self.start)

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"

    @classmethod
    def from_string(cls, s: str) -> "LineRange":
        """Parse a line range from 'start-end' format.

        Compatibility method for existing code.
        """
        return cls.model_validate(s)


class Block(BaseModel):
    """A mapped block of code or documentation."""

    name: str
    lines: LineRange
    last_updated: datetime | None = None
    last_update_comment: str | None = None
    last_reviewed: datetime | None = None
    aligned_with: list[str] = Field(default_factory=list)
    id: str | None = None  # For cross-references

    def overlaps_with(self, other: "Block") -> bool:
        """Check if this block overlaps with another."""
        return self.lines.overlaps(other.lines)

    def contains_line(self, line: int) -> bool:
        """Check if this block contains a specific line."""
        return self.lines.contains(line)


class FileMapping(BaseModel):
    """Mapping for a single file."""

    file: Path
    blocks: list[Block]

    def get_block(self, name: str) -> Block | None:
        """Get a block by name."""
        for block in self.blocks:
            if block.name == name:
                return block
        return None

    def find_block_for_line(self, line: int) -> Block | None:
        """Find the block containing a specific line."""
        for block in self.blocks:
            if block.contains_line(line):
                return block
        return None

    def check_overlaps(self) -> list[tuple[Block, Block]]:
        """Find all overlapping block pairs."""
        overlaps = []
        for i, block1 in enumerate(self.blocks):
            for block2 in self.blocks[i + 1 :]:
                if block1.overlaps_with(block2):
                    overlaps.append((block1, block2))
        return overlaps

    def add_block(self, block: Block) -> None:
        """Add a block, raising if it would overlap."""
        for existing in self.blocks:
            if block.overlaps_with(existing):
                raise OverlapError(
                    f"Block '{block.name}' ({block.lines}) overlaps with "
                    f"'{existing.name}' ({existing.lines})"
                )
        self.blocks.append(block)

    def remove_block(self, name: str) -> Block:
        """Remove a block by name, returning it."""
        for i, block in enumerate(self.blocks):
            if block.name == name:
                return self.blocks.pop(i)
        raise BlockNotFoundError(f"Block not found: {name}")

    def update_block_lines(
        self,
        name: str,
        new_lines: LineRange,
        new_comment: str | None = None,
    ) -> None:
        """Update a block's lines, raising if it would overlap."""
        block = self.get_block(name)
        if not block:
            raise BlockNotFoundError(f"Block not found: {name}")

        # Check for overlaps with other blocks
        for other in self.blocks:
            if other.name != name and new_lines.overlaps(other.lines):
                raise OverlapError(
                    f"New lines {new_lines} overlap with "
                    f"'{other.name}' ({other.lines})"
                )

        block.lines = new_lines
        block.last_updated = datetime.now()
        if new_comment:
            block.last_update_comment = new_comment

    def validate_against_file(self, project_root: Path) -> list[dict[str, str | list[str]]]:
        """Validate this mapping against actual files.

        Returns list of issues found.
        """
        issues: list[dict[str, str | list[str]]] = []
        full_path = project_root / self.file

        if not full_path.exists():
            issues.append(
                {
                    "issue": "missing_file",
                    "file": str(self.file),
                    "message": f"File not found: {self.file}",
                }
            )
            return issues

        # Check line ranges
        file_lines = len(full_path.read_text().splitlines())
        for block in self.blocks:
            if block.lines.end > file_lines:
                issues.append(
                    {
                        "issue": "invalid_lines",
                        "file": str(self.file),
                        "block": block.name,
                        "message": f"Block '{block.name}' ends at line {block.lines.end} "
                        f"but file has {file_lines} lines",
                        "old_lines": str(block.lines),
                    }
                )

        # Check for overlaps
        for block1, block2 in self.check_overlaps():
            issues.append(
                {
                    "issue": "overlap",
                    "file": str(self.file),
                    "blocks": [block1.name, block2.name],
                    "message": f"Blocks '{block1.name}' and '{block2.name}' overlap",
                }
            )

        return issues


class Hierarchy(BaseModel):
    """Document hierarchy for escalation rules."""

    requires_human: list[str] = Field(default_factory=list)
    technical: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    """Alignment map settings."""

    line_tolerance: int = 10
    fuzzy_match: bool = True
    require_complete_coverage: bool = False


class AlignmentMap(BaseModel):
    """The complete alignment map."""

    version: int
    hierarchy: Hierarchy = Field(default_factory=Hierarchy)
    settings: Settings = Field(default_factory=Settings)
    mappings: list[FileMapping] = Field(default_factory=list)

    # Private attribute - not serialized
    _project_root: Path | None = PrivateAttr(default=None)

    @classmethod
    def load(cls, path: Path) -> "AlignmentMap":
        """Load alignment map from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        instance = cls.model_validate(data)
        instance._project_root = path.parent.resolve()
        return instance

    def save(self, path: Path) -> None:
        """Save alignment map to YAML file."""
        # Custom serialization to handle LineRange as string
        data = self._serialize_for_yaml()
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _serialize_for_yaml(self) -> dict[str, Any]:
        """Serialize to dict with LineRange as strings."""
        data: dict[str, Any] = self.model_dump(exclude={"_project_root"})
        # Convert LineRange objects to strings and Path to str
        for mapping in data.get("mappings", []):
            # Convert file path to string
            if isinstance(mapping.get("file"), Path):
                mapping["file"] = str(mapping["file"])
            for block in mapping.get("blocks", []):
                if "lines" in block and isinstance(block["lines"], dict):
                    block["lines"] = f"{block['lines']['start']}-{block['lines']['end']}"
                # Remove None values for cleaner YAML
                if block.get("id") is None:
                    del block["id"]
                if block.get("last_reviewed") is None:
                    del block["last_reviewed"]
        return data

    @property
    def project_root(self) -> Path:
        """Get project root, raising if not set."""
        if not self._project_root:
            raise ValueError(
                "project_root not set. Use AlignmentMap.load() or set_project_root()"
            )
        return self._project_root

    def set_project_root(self, root: Path) -> None:
        """Explicitly set project root."""
        self._project_root = root.resolve()

    # --- Query methods ---

    def get_file_mapping(self, file_path: Path) -> FileMapping | None:
        """Get the mapping for a file."""
        for mapping in self.mappings:
            if mapping.file == file_path:
                return mapping
        return None

    def is_human_required(self, doc_path: str) -> bool:
        """Check if a document requires human review."""
        from fnmatch import fnmatch

        for pattern in self.hierarchy.requires_human:
            if fnmatch(doc_path, pattern):
                return True
        return False

    def get_all_references_to(self, target: str) -> list[tuple[Path, Block]]:
        """Find all blocks that reference the given file or doc.

        Useful for impact analysis before removing a file.
        """
        references = []
        for mapping in self.mappings:
            for block in mapping.blocks:
                if any(target in ref for ref in block.aligned_with):
                    references.append((mapping.file, block))
        return references

    # --- Mutation methods ---

    def add_file_mapping(self, file_mapping: FileMapping) -> None:
        """Add a new file mapping."""
        if self.get_file_mapping(file_mapping.file):
            raise ValueError(f"Mapping already exists for {file_mapping.file}")
        self.mappings.append(file_mapping)

    def remove_file_mapping(
        self, file_path: Path
    ) -> tuple[FileMapping, list[tuple[Path, Block]]]:
        """Remove a file mapping, returning it and any orphaned references.

        Returns:
            Tuple of (removed mapping, list of blocks that referenced it)
        """
        # Find references first
        references = self.get_all_references_to(str(file_path))

        # Remove the mapping
        for i, mapping in enumerate(self.mappings):
            if mapping.file == file_path:
                removed = self.mappings.pop(i)
                return (removed, references)

        raise ValueError(f"No mapping found for {file_path}")

    # --- Orchestrator methods (use stored project_root) ---

    def lint(self) -> list[dict[str, Any]]:
        """Lint the alignment map against the project.

        Returns list of all issues found.
        """
        issues: list[dict[str, Any]] = []

        for mapping in self.mappings:
            issues.extend(mapping.validate_against_file(self.project_root))

        # Check aligned doc references
        for mapping in self.mappings:
            for block in mapping.blocks:
                for aligned_ref in block.aligned_with:
                    doc_issues = self._validate_aligned_ref(
                        mapping.file, block, aligned_ref
                    )
                    issues.extend(doc_issues)

        return issues

    def _validate_aligned_ref(
        self, file_path: Path, block: Block, aligned_ref: str
    ) -> list[dict[str, str]]:
        """Validate a single aligned reference."""
        issues: list[dict[str, str]] = []

        # Parse reference
        if "#" in aligned_ref:
            doc_path_str, anchor = aligned_ref.split("#", 1)
        else:
            doc_path_str = aligned_ref
            anchor = None

        # Skip code references
        if doc_path_str.startswith("src/") or ":" in aligned_ref:
            return issues

        doc_path = self.project_root / doc_path_str

        # Check doc exists
        if not doc_path.exists():
            issues.append(
                {
                    "issue": "missing_aligned_doc",
                    "file": str(file_path),
                    "block": block.name,
                    "aligned_ref": aligned_ref,
                    "message": f"Aligned document not found: {doc_path_str}",
                }
            )
            return issues

        # Check anchor exists
        if anchor:
            content = doc_path.read_text()
            # Simple anchor check - look for heading with anchor text
            anchor_pattern = anchor.replace("-", "[- ]?")
            if not re.search(
                rf"^#+\s+.*{anchor_pattern}",
                content,
                re.IGNORECASE | re.MULTILINE,
            ):
                issues.append(
                    {
                        "issue": "missing_anchor",
                        "file": str(file_path),
                        "block": block.name,
                        "aligned_ref": aligned_ref,
                        "message": f"Anchor '{anchor}' not found in {doc_path_str}",
                    }
                )

        return issues


# --- Runtime Types (Also Pydantic) ---


class ChangedLine(BaseModel):
    """A line that was changed in a file."""

    line_number: int
    content: str
    change_type: str  # 'added', 'removed', 'modified'


class FileChange(BaseModel):
    """Changes to a single file."""

    file_path: Path
    changed_lines: list[ChangedLine]


class CheckFailure(BaseModel):
    """A single check failure."""

    result: CheckResult
    file_path: Path
    message: str
    block: Block | None = None
    aligned_doc: str | None = None
    doc_section: str | None = None
    suggestion: str | None = None


class DocumentSection(BaseModel):
    """An extracted section from a document."""

    path: Path
    anchor: str
    title: str
    content: str
    last_reviewed: datetime | None = None
