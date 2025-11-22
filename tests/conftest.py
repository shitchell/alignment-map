"""Pytest configuration and fixtures for alignment-map tests."""

import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_git_repo() -> Generator[Path, None, None]:
    """Create a temporary git repository for testing."""
    # Create temp directory
    temp_dir = Path(tempfile.mkdtemp(prefix="alignment-map-test-"))

    try:
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=temp_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=temp_dir,
            check=True,
            capture_output=True,
        )

        yield temp_dir
    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_alignment_map() -> str:
    """Return a sample alignment map YAML content."""
    return """version: 1

hierarchy:
  requires_human:
    - docs/IDENTITY.md
  technical:
    - docs/ARCHITECTURE.md
    - docs/**/*.md

mappings:
  - file: src/module.py
    blocks:
      - name: MyClass
        lines: 1-20
        last_updated: 2024-01-15T10:00:00
        last_update_comment: "Initial implementation"
        aligned_with:
          - docs/ARCHITECTURE.md#my-class
"""


@pytest.fixture
def sample_doc_with_review() -> str:
    """Return a sample document with last_reviewed."""
    return """---
last_reviewed: 2024-01-15T12:00:00
---

# Architecture

## My Class

This section describes MyClass and its responsibilities.

It should be kept in sync with the implementation.
"""


@pytest.fixture
def sample_doc_stale() -> str:
    """Return a sample document with old last_reviewed."""
    return """---
last_reviewed: 2020-01-01T00:00:00
---

# Architecture

## My Class

This section describes MyClass and its responsibilities.
"""


@pytest.fixture
def sample_doc_no_review() -> str:
    """Return a sample document without last_reviewed."""
    return """# Architecture

## My Class

This section describes MyClass and its responsibilities.
"""


@pytest.fixture
def sample_code() -> str:
    """Return sample Python code."""
    return '''"""Sample module."""


class MyClass:
    """A sample class."""

    def __init__(self) -> None:
        """Initialize the class."""
        self.value = 0

    def increment(self) -> None:
        """Increment the value."""
        self.value += 1

    def get_value(self) -> int:
        """Get the current value."""
        return self.value
'''


def create_test_project(
    repo_path: Path,
    alignment_map: str,
    files: dict[str, str],
) -> None:
    """Create a test project structure in the given repo."""
    # Create directories
    (repo_path / "src").mkdir(exist_ok=True)
    (repo_path / "docs").mkdir(exist_ok=True)

    # Write alignment map
    (repo_path / ".alignment-map.yaml").write_text(alignment_map)

    # Write files
    for file_path, content in files.items():
        full_path = repo_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def stage_file_change(repo_path: Path, file_path: str, new_content: str) -> None:
    """Modify a file and stage it."""
    full_path = repo_path / file_path
    full_path.write_text(new_content)
    subprocess.run(["git", "add", file_path], cwd=repo_path, check=True, capture_output=True)


def stage_new_file(repo_path: Path, file_path: str, content: str) -> None:
    """Create a new file and stage it."""
    full_path = repo_path / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    subprocess.run(["git", "add", file_path], cwd=repo_path, check=True, capture_output=True)
