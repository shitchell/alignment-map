# Pydantic Model Refactoring

This document outlines the migration of alignment-map models from dataclasses to Pydantic BaseModels with business logic methods.

---

## Overview

### Goals
1. **Centralize business logic** - Overlap detection, validation, etc. live on the models
2. **Type safety** - Pydantic validation on construction
3. **DRY code** - No more duplicated logic across modules
4. **Schema validation** - Lint the map file structure via Pydantic

### Key Principles
- Lower-level methods take explicit `project_root` parameter when needed
- AlignmentMap orchestrates and auto-injects its stored `_project_root`
- All models are Pydantic BaseModels (including runtime types like CheckFailure)
- Private attributes (`PrivateAttr`) for non-serialized state

---

## Required Reading

Before implementing, understand the current codebase:

1. **`src/alignment_map/models.py`** - Current dataclasses to replace
2. **`src/alignment_map/parser.py`** - Loading/parsing to simplify
3. **`src/alignment_map/update.py`** - Overlap detection logic to move into models
4. **`src/alignment_map/touch.py`** - Line detection logic to reuse
5. **`src/alignment_map/lint.py`** - Validation logic to move into models
6. **`tests/test_commands.py`** - Tests to update

---

## New Model Structure

### LineRange

```python
from pydantic import BaseModel, model_validator

class LineRange(BaseModel):
    """A range of lines in a file."""
    start: int
    end: int

    @model_validator(mode='before')
    @classmethod
    def parse_string(cls, data):
        """Parse '10-50' format."""
        if isinstance(data, str):
            parts = data.split('-')
            if len(parts) != 2:
                raise ValueError(f"Invalid line range format: {data}")
            return {'start': int(parts[0]), 'end': int(parts[1])}
        return data

    @model_validator(mode='after')
    def validate_range(self):
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

    # For YAML serialization as string
    def __get_pydantic_serializer__(self):
        return str(self)
```

### Block

```python
from datetime import datetime
from pydantic import BaseModel, Field

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
```

### FileMapping

```python
from pathlib import Path
from pydantic import BaseModel

class OverlapError(Exception):
    """Raised when a block operation would cause overlap."""
    pass

class BlockNotFoundError(Exception):
    """Raised when a block is not found."""
    pass

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
            for block2 in self.blocks[i + 1:]:
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

    def validate_against_file(self, project_root: Path) -> list[dict]:
        """Validate this mapping against actual files.

        Returns list of issues found.
        """
        issues = []
        full_path = project_root / self.file

        if not full_path.exists():
            issues.append({
                'issue': 'missing_file',
                'file': str(self.file),
                'message': f"File not found: {self.file}",
            })
            return issues

        # Check line ranges
        file_lines = len(full_path.read_text().splitlines())
        for block in self.blocks:
            if block.lines.end > file_lines:
                issues.append({
                    'issue': 'invalid_lines',
                    'file': str(self.file),
                    'block': block.name,
                    'message': f"Block '{block.name}' ends at line {block.lines.end} "
                               f"but file has {file_lines} lines",
                    'old_lines': str(block.lines),
                })

        # Check for overlaps
        for block1, block2 in self.check_overlaps():
            issues.append({
                'issue': 'overlap',
                'file': str(self.file),
                'blocks': [block1.name, block2.name],
                'message': f"Blocks '{block1.name}' and '{block2.name}' overlap",
            })

        return issues
```

### Hierarchy

```python
class Hierarchy(BaseModel):
    """Document hierarchy for escalation rules."""
    requires_human: list[str] = Field(default_factory=list)
    technical: list[str] = Field(default_factory=list)
```

### Settings

```python
class Settings(BaseModel):
    """Alignment map settings."""
    line_tolerance: int = 10
    fuzzy_match: bool = True
    require_complete_coverage: bool = False
```

### AlignmentMap (Root Model)

```python
from pydantic import BaseModel, PrivateAttr
import yaml

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
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _serialize_for_yaml(self) -> dict:
        """Serialize to dict with LineRange as strings."""
        data = self.model_dump(exclude={'_project_root'})
        # Convert LineRange objects to strings
        for mapping in data.get('mappings', []):
            for block in mapping.get('blocks', []):
                if 'lines' in block and isinstance(block['lines'], dict):
                    block['lines'] = f"{block['lines']['start']}-{block['lines']['end']}"
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

    def remove_file_mapping(self, file_path: Path) -> tuple[FileMapping, list[tuple[Path, Block]]]:
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

    def lint(self) -> list[dict]:
        """Lint the alignment map against the project.

        Returns list of all issues found.
        """
        issues = []

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
        self,
        file_path: Path,
        block: Block,
        aligned_ref: str
    ) -> list[dict]:
        """Validate a single aligned reference."""
        issues = []

        # Parse reference
        if '#' in aligned_ref:
            doc_path_str, anchor = aligned_ref.split('#', 1)
        else:
            doc_path_str = aligned_ref
            anchor = None

        # Skip code references
        if doc_path_str.startswith('src/') or ':' in aligned_ref:
            return issues

        doc_path = self.project_root / doc_path_str

        # Check doc exists
        if not doc_path.exists():
            issues.append({
                'issue': 'missing_aligned_doc',
                'file': str(file_path),
                'block': block.name,
                'aligned_ref': aligned_ref,
                'message': f"Aligned document not found: {doc_path_str}",
            })
            return issues

        # Check anchor exists
        if anchor:
            content = doc_path.read_text()
            # Simple anchor check - look for heading with anchor text
            anchor_pattern = anchor.replace('-', '[- ]?')
            import re
            if not re.search(rf'^#+\s+.*{anchor_pattern}', content, re.IGNORECASE | re.MULTILINE):
                issues.append({
                    'issue': 'missing_anchor',
                    'file': str(file_path),
                    'block': block.name,
                    'aligned_ref': aligned_ref,
                    'message': f"Anchor '{anchor}' not found in {doc_path_str}",
                })

        return issues
```

### Runtime Types (Also Pydantic)

Convert existing runtime types to Pydantic for consistency:

```python
from enum import Enum

class CheckResult(str, Enum):
    """Result of an alignment check."""
    OK = "ok"
    UNMAPPED_FILE = "unmapped_file"
    UNMAPPED_LINES = "unmapped_lines"
    MAP_NOT_UPDATED = "map_not_updated"
    STALE_DOC = "stale_doc"
    HUMAN_ESCALATION = "human_escalation"

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
```

---

## Module Migration Guide

### models.py

Complete rewrite with all the Pydantic models above. This is the core of the change.

### parser.py

**Simplify significantly:**

```python
"""Parsers for alignment map and markdown documents."""

from datetime import datetime
from pathlib import Path
import re
import yaml

from .models import AlignmentMap, DocumentSection

# Remove parse_alignment_map - replaced by AlignmentMap.load()
# Remove parse_datetime - Pydantic handles this

def extract_document_section(doc_path: Path, anchor: str) -> DocumentSection | None:
    """Extract a section from a markdown document by anchor."""
    # Keep this function - it's about document parsing, not map parsing
    ...

def extract_last_reviewed(content: str) -> datetime | None:
    """Extract last_reviewed from document frontmatter."""
    # Keep this function
    ...

def get_document_last_reviewed(doc_path: Path) -> datetime | None:
    """Get the last_reviewed timestamp from a document."""
    # Keep this function
    ...
```

### update.py

**Use FileMapping methods:**

```python
def update_block(...) -> tuple[bool, LineRange | None, list[str] | None]:
    # Load map using new method
    alignment_map = AlignmentMap.load(map_path)

    file_mapping = alignment_map.get_file_mapping(file_path)

    if file_mapping is None:
        # Create new file mapping
        new_block = Block(
            name=block_name,
            lines=lines,
            last_updated=datetime.now(),
            last_update_comment=comment or "Initial mapping",
            aligned_with=aligned_with,
        )
        file_mapping = FileMapping(file=file_path, blocks=[new_block])
        alignment_map.add_file_mapping(file_mapping)
        alignment_map.save(map_path)
        return (True, lines, aligned_with)

    # Check for overlaps using model method
    overlapping = [b for b in file_mapping.blocks if lines.overlaps(b.lines)]

    if overlapping:
        # Handle overlaps...
        pass
    else:
        # Use model method - raises on overlap
        try:
            new_block = Block(...)
            file_mapping.add_block(new_block)
            alignment_map.save(map_path)
        except OverlapError as e:
            console.print(f"[red]{e}[/red]")
            return (False, None, None)
```

### touch.py

**Use FileMapping.update_block_lines():**

```python
def touch_block(...) -> bool:
    alignment_map = AlignmentMap.load(map_path)
    file_mapping = alignment_map.get_file_mapping(file_path)

    if not file_mapping:
        # Error...
        return False

    try:
        file_mapping.update_block_lines(block_name, new_lines, comment)
        alignment_map.save(map_path)
        return True
    except BlockNotFoundError:
        console.print(f"[red]Block not found: {block_name}[/red]")
        return False
    except OverlapError as e:
        console.print(f"[red]{e}[/red]")
        return False
```

### lint.py

**Use AlignmentMap.lint():**

```python
def lint_alignment_map(project_root: Path, map_path: Path) -> list[dict]:
    try:
        alignment_map = AlignmentMap.load(map_path)
    except ValidationError as e:
        # Pydantic validation failed - return as lint errors
        return [{'issue': 'schema_error', 'message': str(e)}]

    return alignment_map.lint()
```

### checker.py

**Use model methods:**

```python
def check_staged_changes(project_root: Path, map_path: Path) -> list[CheckFailure]:
    alignment_map = AlignmentMap.load(map_path)
    # ... rest uses alignment_map.get_file_mapping(), etc.
```

### cli.py

**Minor updates to use new loading:**

```python
# Instead of:
from .parser import parse_alignment_map
alignment_map = parse_alignment_map(map_path)

# Use:
from .models import AlignmentMap
alignment_map = AlignmentMap.load(map_path)
```

---

## Testing Updates

### Update Fixtures

```python
@pytest.fixture
def sample_alignment_map_obj(temp_git_repo: Path) -> AlignmentMap:
    """Return a sample AlignmentMap object."""
    map_content = """version: 1
hierarchy:
  requires_human:
    - docs/IDENTITY.md
  technical:
    - docs/ARCHITECTURE.md
mappings:
  - file: src/module.py
    blocks:
      - name: MyClass
        lines: 1-20
        last_updated: 2024-01-15T10:00:00
        aligned_with:
          - docs/ARCHITECTURE.md#my-class
"""
    map_path = temp_git_repo / ".alignment-map.yaml"
    map_path.write_text(map_content)
    return AlignmentMap.load(map_path)
```

### Add Model Unit Tests

Create `tests/test_models.py`:

```python
"""Tests for Pydantic models."""

import pytest
from datetime import datetime
from pathlib import Path

from alignment_map.models import (
    LineRange, Block, FileMapping, AlignmentMap,
    OverlapError, BlockNotFoundError,
)


class TestLineRange:
    def test_parse_from_string(self):
        lr = LineRange.model_validate("10-50")
        assert lr.start == 10
        assert lr.end == 50

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            LineRange(start=50, end=10)

    def test_contains(self):
        lr = LineRange(start=10, end=20)
        assert lr.contains(15)
        assert not lr.contains(5)

    def test_overlaps(self):
        lr1 = LineRange(start=10, end=20)
        lr2 = LineRange(start=15, end=25)
        lr3 = LineRange(start=25, end=35)

        assert lr1.overlaps(lr2)
        assert not lr1.overlaps(lr3)


class TestBlock:
    def test_overlaps_with(self):
        b1 = Block(name="A", lines=LineRange(start=1, end=10))
        b2 = Block(name="B", lines=LineRange(start=5, end=15))
        b3 = Block(name="C", lines=LineRange(start=20, end=30))

        assert b1.overlaps_with(b2)
        assert not b1.overlaps_with(b3)


class TestFileMapping:
    def test_add_block_success(self):
        fm = FileMapping(file=Path("test.py"), blocks=[])
        block = Block(name="A", lines=LineRange(start=1, end=10))
        fm.add_block(block)
        assert len(fm.blocks) == 1

    def test_add_block_overlap_error(self):
        fm = FileMapping(file=Path("test.py"), blocks=[
            Block(name="A", lines=LineRange(start=1, end=10))
        ])
        with pytest.raises(OverlapError):
            fm.add_block(Block(name="B", lines=LineRange(start=5, end=15)))

    def test_update_block_lines(self):
        fm = FileMapping(file=Path("test.py"), blocks=[
            Block(name="A", lines=LineRange(start=1, end=10))
        ])
        fm.update_block_lines("A", LineRange(start=5, end=15), "Moved")
        assert fm.blocks[0].lines.start == 5
        assert fm.blocks[0].last_update_comment == "Moved"

    def test_remove_block(self):
        fm = FileMapping(file=Path("test.py"), blocks=[
            Block(name="A", lines=LineRange(start=1, end=10))
        ])
        removed = fm.remove_block("A")
        assert removed.name == "A"
        assert len(fm.blocks) == 0


class TestAlignmentMap:
    def test_load_and_save(self, temp_git_repo: Path):
        # Create a map file
        content = """version: 1
hierarchy:
  requires_human: []
  technical: []
mappings: []
"""
        map_path = temp_git_repo / ".alignment-map.yaml"
        map_path.write_text(content)

        # Load it
        am = AlignmentMap.load(map_path)
        assert am.version == 1
        assert am._project_root == temp_git_repo

        # Modify and save
        am.mappings.append(FileMapping(
            file=Path("test.py"),
            blocks=[Block(name="Test", lines=LineRange(start=1, end=10))]
        ))
        am.save(map_path)

        # Reload and verify
        am2 = AlignmentMap.load(map_path)
        assert len(am2.mappings) == 1

    def test_get_all_references_to(self):
        am = AlignmentMap(
            version=1,
            mappings=[
                FileMapping(
                    file=Path("a.py"),
                    blocks=[Block(
                        name="A",
                        lines=LineRange(start=1, end=10),
                        aligned_with=["docs/foo.md"]
                    )]
                ),
                FileMapping(
                    file=Path("b.py"),
                    blocks=[Block(
                        name="B",
                        lines=LineRange(start=1, end=10),
                        aligned_with=["docs/foo.md#section"]
                    )]
                )
            ]
        )

        refs = am.get_all_references_to("docs/foo.md")
        assert len(refs) == 2
```

---

## Implementation Order

1. **models.py** - Complete rewrite with all Pydantic models
2. **parser.py** - Simplify, remove redundant functions
3. **tests/test_models.py** - Add unit tests for models
4. **Update other modules** - One at a time:
   - checker.py
   - update.py
   - touch.py
   - lint.py
   - trace.py
   - suggest.py
   - graph.py
   - output.py
   - cli.py
5. **Update existing tests** - Fix imports and assertions
6. **Run full test suite** - Ensure all tests pass

---

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    "click>=8.0",
    "pyyaml>=6.0",
    "rich>=13.0",
    "pydantic>=2.0",  # Add this
]
```

---

## Commit Strategy

This is a significant refactor. Consider:
1. Single commit with all changes (simpler history)
2. Or split into: models → parser → each module (easier to review)

Recommended: Single commit since it's a coordinated change.

```bash
git add -A
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
Migrate to Pydantic models with business logic

- Convert all dataclasses to Pydantic BaseModels
- Add methods: overlap detection, validation, CRUD operations
- Centralize business logic on models (DRY)
- Simplify parser.py - delegate to model's load()
- Add comprehensive model unit tests
- Update all modules to use new model methods

This refactor centralizes validation and business logic on the models,
eliminating code duplication across modules. The AlignmentMap.lint()
orchestrator method auto-injects project_root for file-based validation.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Summary

This refactoring:
1. **Centralizes logic** - Overlap detection, validation in one place
2. **Enables safe auto-fix** - Model methods enforce invariants
3. **Improves testability** - Unit test models directly
4. **Adds schema validation** - Pydantic validates on load
5. **Simplifies modules** - They delegate to model methods

The result is a more maintainable codebase where business rules are explicit and enforced by the type system.
