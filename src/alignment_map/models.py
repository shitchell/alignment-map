"""Data models for alignment map."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class CheckResult(Enum):
    """Result of an alignment check."""

    OK = "ok"
    UNMAPPED_FILE = "unmapped_file"
    UNMAPPED_LINES = "unmapped_lines"
    MAP_NOT_UPDATED = "map_not_updated"
    STALE_DOC = "stale_doc"
    HUMAN_ESCALATION = "human_escalation"


@dataclass
class LineRange:
    """A range of lines in a file."""

    start: int
    end: int

    @classmethod
    def from_string(cls, s: str) -> "LineRange":
        """Parse a line range from 'start-end' format."""
        parts = s.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid line range format: {s}")
        return cls(start=int(parts[0]), end=int(parts[1]))

    def contains(self, line: int) -> bool:
        """Check if a line number is within this range."""
        return self.start <= line <= self.end

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"


@dataclass
class Block:
    """A mapped block of code or documentation."""

    name: str
    lines: LineRange
    last_updated: datetime | None = None
    last_update_comment: str | None = None
    last_reviewed: datetime | None = None
    aligned_with: list[str] = field(default_factory=list)
    block_id: str | None = None


@dataclass
class FileMapping:
    """Mapping for a single file."""

    file_path: Path
    blocks: list[Block]


@dataclass
class AlignmentMap:
    """The complete alignment map."""

    version: int
    mappings: list[FileMapping]
    requires_human: list[str] = field(default_factory=list)
    technical: list[str] = field(default_factory=list)
    settings: dict[str, object] = field(default_factory=dict)

    def get_file_mapping(self, file_path: Path) -> FileMapping | None:
        """Get the mapping for a file."""
        for mapping in self.mappings:
            if mapping.file_path == file_path:
                return mapping
        return None

    def is_human_required(self, doc_path: str) -> bool:
        """Check if a document requires human review."""
        from fnmatch import fnmatch

        for pattern in self.requires_human:
            if fnmatch(doc_path, pattern):
                return True
        return False


@dataclass
class ChangedLine:
    """A line that was changed in a file."""

    line_number: int
    content: str
    change_type: str  # 'added', 'removed', 'modified'


@dataclass
class FileChange:
    """Changes to a single file."""

    file_path: Path
    changed_lines: list[ChangedLine]


@dataclass
class CheckFailure:
    """A single check failure."""

    result: CheckResult
    file_path: Path
    message: str
    block: Block | None = None
    aligned_doc: str | None = None
    doc_section: str | None = None
    suggestion: str | None = None


@dataclass
class DocumentSection:
    """An extracted section from a document."""

    path: Path
    anchor: str
    title: str
    content: str
    last_reviewed: datetime | None = None
