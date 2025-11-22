"""Tests for new CLI commands."""

import json
from pathlib import Path

import pytest

from alignment_map.models import LineRange
from alignment_map.suggest import BlockSuggestion, suggest_python_blocks
from alignment_map.trace import collect_trace_data, trace_file_location
from alignment_map.update import find_overlapping_blocks, suggest_overlap_strategy
from alignment_map.review import collect_review_data, estimate_review_impact
from alignment_map.graph import build_graph_data
from alignment_map.parser import parse_alignment_map

from .conftest import create_test_project


class TestTraceCommand:
    """Tests for the trace command."""

    def test_trace_file_with_alignments(self, temp_git_repo: Path) -> None:
        """Test tracing a file that has alignments."""
        # Create project with alignment
        alignment_map = """version: 1

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
        last_update_comment: "Initial"
        aligned_with:
          - docs/ARCHITECTURE.md#my-class
"""
        doc_content = """---
last_reviewed: 2024-01-15T12:00:00
---

# Architecture

## My Class

This is the MyClass section.
"""
        code_content = """class MyClass:
    pass
"""

        create_test_project(
            temp_git_repo,
            alignment_map,
            {
                "src/module.py": code_content,
                "docs/ARCHITECTURE.md": doc_content,
            },
        )

        # Run trace
        alignment_map_obj = parse_alignment_map(temp_git_repo / ".alignment-map.yaml")
        result = trace_file_location(
            temp_git_repo,
            alignment_map_obj,
            Path("src/module.py"),
            line_number=5,
            output_json=True,
        )

        assert result is not None
        assert result["file"] == "src/module.py"
        assert len(result["blocks"]) == 1
        assert result["blocks"][0]["name"] == "MyClass"
        assert len(result["aligned_documents"]) == 1
        assert result["aligned_documents"][0]["path"] == "docs/ARCHITECTURE.md"
        assert len(result["staleness_checks"]) == 1
        assert result["staleness_checks"][0]["status"] == "current"

    def test_trace_unmapped_file(self, temp_git_repo: Path) -> None:
        """Test tracing a file not in the alignment map."""
        alignment_map = """version: 1
mappings: []
"""
        create_test_project(temp_git_repo, alignment_map, {})

        alignment_map_obj = parse_alignment_map(temp_git_repo / ".alignment-map.yaml")
        result = trace_file_location(
            temp_git_repo,
            alignment_map_obj,
            Path("src/unmapped.py"),
            output_json=True,
        )

        assert result is not None
        assert result["error"] == "unmapped_file"

    def test_trace_specific_line(self, temp_git_repo: Path) -> None:
        """Test tracing a specific line in a file."""
        alignment_map = """version: 1
mappings:
  - file: src/module.py
    blocks:
      - name: Block1
        lines: 1-10
        aligned_with: []
      - name: Block2
        lines: 11-20
        aligned_with: []
"""
        create_test_project(
            temp_git_repo,
            alignment_map,
            {"src/module.py": "\n" * 20},  # 20 lines
        )

        alignment_map_obj = parse_alignment_map(temp_git_repo / ".alignment-map.yaml")

        # Trace line 15 (should be in Block2)
        result = trace_file_location(
            temp_git_repo,
            alignment_map_obj,
            Path("src/module.py"),
            line_number=15,
            output_json=True,
        )

        assert result is not None
        assert len(result["blocks"]) == 1
        assert result["blocks"][0]["name"] == "Block2"


class TestUpdateCommand:
    """Tests for the update command."""

    def test_find_overlapping_blocks(self) -> None:
        """Test finding overlapping blocks."""
        from alignment_map.models import Block

        blocks = [
            Block(name="Block1", lines=LineRange(1, 10)),
            Block(name="Block2", lines=LineRange(20, 30)),
            Block(name="Block3", lines=LineRange(40, 50)),
        ]

        # No overlap
        overlaps = find_overlapping_blocks(blocks, LineRange(12, 18))
        assert len(overlaps) == 0

        # Overlap with Block1
        overlaps = find_overlapping_blocks(blocks, LineRange(5, 15))
        assert len(overlaps) == 1
        assert overlaps[0].name == "Block1"

        # Overlap with Block2
        overlaps = find_overlapping_blocks(blocks, LineRange(25, 35))
        assert len(overlaps) == 1
        assert overlaps[0].name == "Block2"

        # Multiple overlaps
        overlaps = find_overlapping_blocks(blocks, LineRange(1, 45))
        assert len(overlaps) == 3

    def test_suggest_overlap_strategy(self) -> None:
        """Test overlap strategy suggestions."""
        from alignment_map.models import Block

        # Subset -> extend
        block = Block(name="Block", lines=LineRange(10, 30))
        strategy = suggest_overlap_strategy(LineRange(15, 25), [block])
        assert strategy == "extend"

        # Superset -> replace
        strategy = suggest_overlap_strategy(LineRange(5, 35), [block])
        assert strategy == "replace"

        # Partial overlap -> split
        strategy = suggest_overlap_strategy(LineRange(25, 40), [block])
        assert strategy == "split"

        # Multiple overlaps -> replace
        blocks = [
            Block(name="Block1", lines=LineRange(10, 20)),
            Block(name="Block2", lines=LineRange(25, 35)),
        ]
        strategy = suggest_overlap_strategy(LineRange(15, 30), blocks)
        assert strategy == "replace"


class TestSuggestCommand:
    """Tests for the suggest command."""

    def test_suggest_python_blocks_with_ast(self) -> None:
        """Test suggesting Python blocks using AST parsing."""
        code = '''"""Module docstring."""


class MyClass:
    """A class."""

    def __init__(self):
        """Init method."""
        pass

    def method(self):
        """A method."""
        return 42


def standalone_function():
    """A function."""
    return "hello"


async def async_function():
    """An async function."""
    return "async"
'''
        # Create a temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_file = Path(f.name)

        try:
            suggestions = suggest_python_blocks(temp_file, [])

            assert len(suggestions) >= 3  # At least class and two functions

            # Check for class
            class_suggestions = [s for s in suggestions if s.block_type == "class"]
            assert len(class_suggestions) == 1
            assert "MyClass" in class_suggestions[0].name

            # Check for functions
            func_suggestions = [s for s in suggestions if "function" in s.block_type]
            assert len(func_suggestions) >= 2

            # All should have high confidence (AST parsing)
            for s in suggestions:
                assert s.confidence == "high"
        finally:
            temp_file.unlink()

    def test_suggest_blocks_with_existing(self) -> None:
        """Test suggesting blocks when some already exist."""
        from alignment_map.models import Block

        code = '''class Class1:
    pass

class Class2:
    pass
'''
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_file = Path(f.name)

        try:
            # Existing block covers Class1
            existing = [Block(name="Class1", lines=LineRange(1, 2))]
            suggestions = suggest_python_blocks(temp_file, existing)

            # Should only suggest Class2
            assert len(suggestions) == 1
            assert "Class2" in suggestions[0].name
        finally:
            temp_file.unlink()


class TestReviewCommand:
    """Tests for the review command."""

    def test_review_file_with_alignments(self, temp_git_repo: Path) -> None:
        """Test reviewing a file with alignments."""
        alignment_map = """version: 1

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
          - docs/ARCHITECTURE.md
          - docs/IDENTITY.md
"""
        arch_doc = """---
last_reviewed: 2024-01-15T12:00:00
---

# Architecture
"""
        identity_doc = """---
last_reviewed: 2024-01-01T00:00:00
---

# Identity
"""

        create_test_project(
            temp_git_repo,
            alignment_map,
            {
                "src/module.py": "class MyClass:\n    pass\n",
                "docs/ARCHITECTURE.md": arch_doc,
                "docs/IDENTITY.md": identity_doc,
            },
        )

        alignment_map_obj = parse_alignment_map(temp_git_repo / ".alignment-map.yaml")
        file_mapping = alignment_map_obj.get_file_mapping(Path("src/module.py"))

        result = collect_review_data(
            temp_git_repo,
            alignment_map_obj,
            Path("src/module.py"),
            file_mapping,
        )

        assert result["file"] == "src/module.py"
        assert len(result["blocks"]) == 1
        assert result["review_requirements"]["total_docs"] == 2
        assert result["review_requirements"]["requires_human"] == 1  # IDENTITY.md
        assert result["review_requirements"]["requires_update"] == 1  # IDENTITY.md is stale
        assert result["review_requirements"]["already_current"] == 1  # ARCHITECTURE.md

    def test_estimate_review_impact(self) -> None:
        """Test impact estimation."""
        # Minimal impact - no docs
        data = {
            "review_requirements": {
                "total_docs": 0,
                "requires_human": 0,
                "requires_update": 0,
                "already_current": 0,
            }
        }
        impact = estimate_review_impact(data)
        assert impact["level"] == "minimal"

        # High impact - requires human
        data["review_requirements"]["total_docs"] = 2
        data["review_requirements"]["requires_human"] = 1
        impact = estimate_review_impact(data)
        assert impact["level"] == "high"

        # Medium impact - many docs to update
        data["review_requirements"]["requires_human"] = 0
        data["review_requirements"]["requires_update"] = 3
        impact = estimate_review_impact(data)
        assert impact["level"] == "medium"

        # Low impact - few docs to update
        data["review_requirements"]["requires_update"] = 1
        impact = estimate_review_impact(data)
        assert impact["level"] == "low"


class TestGraphCommand:
    """Tests for the graph command."""

    def test_build_graph_data(self, temp_git_repo: Path) -> None:
        """Test building graph data from alignment map."""
        alignment_map = """version: 1

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
        aligned_with:
          - docs/ARCHITECTURE.md#my-class
  - file: docs/ARCHITECTURE.md
    blocks:
      - name: Architecture overview
        lines: 1-50
        last_reviewed: 2024-01-15T00:00:00
        aligned_with:
          - docs/IDENTITY.md
"""

        create_test_project(temp_git_repo, alignment_map, {})
        alignment_map_obj = parse_alignment_map(temp_git_repo / ".alignment-map.yaml")

        graph_data = build_graph_data(alignment_map_obj)

        # Check nodes
        assert len(graph_data["nodes"]) >= 4  # At least 2 files and 2 blocks

        file_nodes = [n for n in graph_data["nodes"] if n["type"] == "file"]
        block_nodes = [n for n in graph_data["nodes"] if n["type"] == "block"]

        assert len(file_nodes) >= 3  # src/module.py, docs/ARCHITECTURE.md, docs/IDENTITY.md
        assert len(block_nodes) == 2  # MyClass and Architecture overview

        # Check edges
        assert len(graph_data["edges"]) == 2  # Two alignments

        # Check stats
        assert graph_data["stats"]["total_files"] >= 3
        assert graph_data["stats"]["total_blocks"] == 2
        assert graph_data["stats"]["total_alignments"] == 2
        assert graph_data["stats"]["code_files"] == 1
        assert graph_data["stats"]["doc_files"] >= 2
        assert graph_data["stats"]["human_required_docs"] == 1  # IDENTITY.md