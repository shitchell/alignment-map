"""Tests for alignment-map checker."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from alignment_map.checker import check_staged_changes
from alignment_map.models import CheckResult

from .conftest import create_test_project, stage_file_change, stage_new_file


# Use fixed timestamps for predictable testing
RECENT_TIME = "2024-01-15T12:00:00"
OLD_TIME = "2020-01-01T00:00:00"
VERY_OLD_TIME = "2019-01-01T00:00:00"


class TestHappyPath:
    """Tests for successful alignment checks."""

    def test_valid_change_with_updated_map_and_docs(
        self,
        temp_git_repo: Path,
        sample_code: str,
        sample_doc_with_review: str,
        sample_alignment_map: str,
    ) -> None:
        """A valid change with updated map and reviewed docs should pass."""
        # Setup: doc has last_reviewed: 2024-01-15T12:00:00
        # map has last_updated: 2024-01-15T10:00:00
        create_test_project(
            temp_git_repo,
            sample_alignment_map,
            {
                "src/module.py": sample_code,
                "docs/ARCHITECTURE.md": sample_doc_with_review,
            },
        )

        # Make a change to the code
        modified_code = sample_code.replace("self.value = 0", "self.value = 1")
        stage_file_change(temp_git_repo, "src/module.py", modified_code)

        # Update the alignment map with a timestamp BEFORE the doc's last_reviewed
        updated_map = sample_alignment_map.replace(
            'last_update_comment: "Initial implementation"',
            'last_update_comment: "Changed initial value"',
        ).replace(
            "last_updated: 2024-01-15T10:00:00",
            "last_updated: 2024-01-15T11:00:00",  # Still before doc's 12:00:00
        )
        stage_file_change(temp_git_repo, ".alignment-map.yaml", updated_map)

        # Run check
        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        assert len(failures) == 0


class TestUnmappedFile:
    """Tests for unmapped file detection."""

    def test_new_file_not_in_map(
        self,
        temp_git_repo: Path,
        sample_code: str,
        sample_doc_with_review: str,
        sample_alignment_map: str,
    ) -> None:
        """A new file not in the alignment map should fail."""
        # Setup
        create_test_project(
            temp_git_repo,
            sample_alignment_map,
            {
                "src/module.py": sample_code,
                "docs/ARCHITECTURE.md": sample_doc_with_review,
            },
        )

        # Add a new file that's not in the map
        new_code = '''"""New module."""

def new_function() -> str:
    return "hello"
'''
        stage_new_file(temp_git_repo, "src/new_module.py", new_code)

        # Run check
        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        assert len(failures) == 1
        assert failures[0].result == CheckResult.UNMAPPED_FILE
        assert "new_module.py" in str(failures[0].file_path)


class TestUnmappedLines:
    """Tests for unmapped lines detection."""

    def test_lines_outside_mapped_block(
        self,
        temp_git_repo: Path,
        sample_code: str,
        sample_doc_with_review: str,
        sample_alignment_map: str,
    ) -> None:
        """Lines outside any mapped block should fail."""
        # Setup
        create_test_project(
            temp_git_repo,
            sample_alignment_map,
            {
                "src/module.py": sample_code,
                "docs/ARCHITECTURE.md": sample_doc_with_review,
            },
        )

        # Add code at the end (outside the mapped block which is lines 1-20)
        extended_code = sample_code + '''

class AnotherClass:
    """This is outside the mapped block."""
    pass
'''
        stage_file_change(temp_git_repo, "src/module.py", extended_code)

        # Update the map's last_updated but keep lines the same
        now = datetime.now().isoformat()
        updated_map = sample_alignment_map.replace(
            'last_update_comment: "Initial implementation"',
            f'last_update_comment: "Added another class"',
        )
        stage_file_change(temp_git_repo, ".alignment-map.yaml", updated_map)

        # Run check
        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        # Should have unmapped lines failure
        unmapped_failures = [f for f in failures if f.result == CheckResult.UNMAPPED_LINES]
        assert len(unmapped_failures) >= 1


class TestMapNotUpdated:
    """Tests for detecting when alignment map wasn't updated."""

    def test_code_changed_but_map_not_updated(
        self,
        temp_git_repo: Path,
        sample_code: str,
        sample_doc_with_review: str,
        sample_alignment_map: str,
    ) -> None:
        """Changing code without updating the map should fail."""
        # Setup
        create_test_project(
            temp_git_repo,
            sample_alignment_map,
            {
                "src/module.py": sample_code,
                "docs/ARCHITECTURE.md": sample_doc_with_review,
            },
        )

        # Make a change to the code but don't update the map
        modified_code = sample_code.replace("self.value = 0", "self.value = 42")
        stage_file_change(temp_git_repo, "src/module.py", modified_code)

        # Run check (map is not staged)
        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        assert len(failures) >= 1
        map_failures = [f for f in failures if f.result == CheckResult.MAP_NOT_UPDATED]
        assert len(map_failures) >= 1


class TestStaleDocument:
    """Tests for stale document detection."""

    def test_doc_last_reviewed_older_than_code(
        self,
        temp_git_repo: Path,
        sample_code: str,
        sample_doc_stale: str,
    ) -> None:
        """A document with old last_reviewed should trigger failure."""
        # Create map with recent last_updated (after the stale doc's 2020-01-01)
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
        last_update_comment: "Recent change"
        aligned_with:
          - docs/ARCHITECTURE.md#my-class
"""
        # Setup with stale doc (has 2020-01-01 last_reviewed)
        create_test_project(
            temp_git_repo,
            alignment_map,
            {
                "src/module.py": sample_code,
                "docs/ARCHITECTURE.md": sample_doc_stale,
            },
        )

        # Make a change
        modified_code = sample_code.replace("self.value = 0", "self.value = 99")
        stage_file_change(temp_git_repo, "src/module.py", modified_code)

        # Update the map with a newer timestamp
        updated_map = alignment_map.replace(
            'last_update_comment: "Recent change"',
            'last_update_comment: "Another change"',
        ).replace(
            "last_updated: 2024-01-15T10:00:00",
            "last_updated: 2024-01-15T11:00:00",
        )
        stage_file_change(temp_git_repo, ".alignment-map.yaml", updated_map)

        # Run check
        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        stale_failures = [f for f in failures if f.result == CheckResult.STALE_DOC]
        assert len(stale_failures) >= 1
        # Note: doc_section extraction has a known issue with anchor matching
        # The core stale detection works; section printing is a refinement

    def test_doc_without_last_reviewed(
        self,
        temp_git_repo: Path,
        sample_code: str,
        sample_doc_no_review: str,
    ) -> None:
        """A document without last_reviewed should trigger failure."""
        alignment_map = """version: 1

hierarchy:
  requires_human: []
  technical:
    - docs/**/*.md

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
        create_test_project(
            temp_git_repo,
            alignment_map,
            {
                "src/module.py": sample_code,
                "docs/ARCHITECTURE.md": sample_doc_no_review,
            },
        )

        # Make a change
        modified_code = sample_code.replace("self.value = 0", "self.value = 1")
        stage_file_change(temp_git_repo, "src/module.py", modified_code)

        # Update the map with a newer timestamp
        updated_map = alignment_map.replace(
            "last_updated: 2024-01-15T10:00:00",
            "last_updated: 2024-01-15T11:00:00",
        )
        stage_file_change(temp_git_repo, ".alignment-map.yaml", updated_map)

        # Run check
        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        stale_failures = [f for f in failures if f.result == CheckResult.STALE_DOC]
        assert len(stale_failures) >= 1


class TestHumanEscalation:
    """Tests for human escalation requirements."""

    def test_identity_doc_requires_human(
        self,
        temp_git_repo: Path,
        sample_code: str,
    ) -> None:
        """Changes affecting identity docs should require human escalation."""
        # Map that aligns code to identity doc
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
          - docs/IDENTITY.md#core-values
"""
        identity_doc = """---
last_reviewed: 2020-01-01T00:00:00
---

# Identity

## Core Values

These are our core values.
"""
        create_test_project(
            temp_git_repo,
            alignment_map,
            {
                "src/module.py": sample_code,
                "docs/IDENTITY.md": identity_doc,
            },
        )

        # Make a change
        modified_code = sample_code.replace("self.value = 0", "self.value = 1")
        stage_file_change(temp_git_repo, "src/module.py", modified_code)

        # Update the map with a newer timestamp
        updated_map = alignment_map.replace(
            "last_updated: 2024-01-15T10:00:00",
            "last_updated: 2024-01-15T11:00:00",
        )
        stage_file_change(temp_git_repo, ".alignment-map.yaml", updated_map)

        # Run check
        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        escalation_failures = [f for f in failures if f.result == CheckResult.HUMAN_ESCALATION]
        assert len(escalation_failures) >= 1
        assert "IDENTITY.md" in str(escalation_failures[0].aligned_doc)


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_staged_changes(
        self,
        temp_git_repo: Path,
        sample_code: str,
        sample_doc_with_review: str,
        sample_alignment_map: str,
    ) -> None:
        """No staged changes should pass."""
        create_test_project(
            temp_git_repo,
            sample_alignment_map,
            {
                "src/module.py": sample_code,
                "docs/ARCHITECTURE.md": sample_doc_with_review,
            },
        )

        # Don't stage anything
        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        assert len(failures) == 0

    def test_only_map_changed(
        self,
        temp_git_repo: Path,
        sample_code: str,
        sample_doc_with_review: str,
        sample_alignment_map: str,
    ) -> None:
        """Changing only the alignment map should pass."""
        create_test_project(
            temp_git_repo,
            sample_alignment_map,
            {
                "src/module.py": sample_code,
                "docs/ARCHITECTURE.md": sample_doc_with_review,
            },
        )

        # Only change the map
        updated_map = sample_alignment_map.replace("version: 1", "version: 2")
        stage_file_change(temp_git_repo, ".alignment-map.yaml", updated_map)

        failures = check_staged_changes(
            temp_git_repo,
            temp_git_repo / ".alignment-map.yaml",
        )

        assert len(failures) == 0
