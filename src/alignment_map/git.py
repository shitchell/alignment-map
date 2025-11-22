"""Git operations for alignment checking."""

import subprocess
from pathlib import Path

from .models import ChangedLine, FileChange


def get_staged_changes(project_root: Path) -> list[FileChange]:
    """Get all staged changes in the repository."""
    # Get list of staged files
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )

    files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    changes: list[FileChange] = []

    for file_path in files:
        changed_lines = get_file_changed_lines(project_root, file_path, staged=True)
        changes.append(FileChange(file_path=Path(file_path), changed_lines=changed_lines))

    return changes


def get_file_changed_lines(project_root: Path, file_path: str, staged: bool = True) -> list[ChangedLine]:
    """Get the changed lines for a specific file."""
    diff_args = ["git", "diff", "--unified=0"]
    if staged:
        diff_args.append("--cached")
    diff_args.append(file_path)

    result = subprocess.run(
        diff_args,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )

    return parse_diff_output(result.stdout)


def parse_diff_output(diff_output: str) -> list[ChangedLine]:
    """Parse git diff output to extract changed line numbers."""
    changed_lines: list[ChangedLine] = []

    current_line = 0
    in_hunk = False

    for line in diff_output.split("\n"):
        # Parse hunk header: @@ -start,count +start,count @@
        if line.startswith("@@"):
            # Extract the new file line numbers
            import re

            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                current_line = int(match.group(1))
                in_hunk = True
            continue

        if not in_hunk:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            # Added line
            changed_lines.append(
                ChangedLine(
                    line_number=current_line,
                    content=line[1:],
                    change_type="added",
                )
            )
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            # Removed line (don't increment current_line)
            pass
        elif line.startswith(" "):
            # Context line
            current_line += 1

    return changed_lines


def get_repo_root() -> Path:
    """Get the root directory of the git repository."""
    ## TODO: Replace subprocess git calls with pygit2 or Dulwich for cleaner implementation
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def find_project_root(start_path: Path | None = None, mapfile: Path | None = None) -> Path:
    """Find the project root directory.

    Priority:
    1. If mapfile is provided, use its parent directory
    2. Reverse tree crawl to find .alignment-map.yaml
    3. Fall back to git root

    Args:
        start_path: Directory to start searching from (default: current working directory)
        mapfile: Explicit path to alignment map file

    Returns:
        Path to project root directory

    Raises:
        FileNotFoundError: If no project root can be determined
    """
    if mapfile:
        return mapfile.parent.resolve()

    # Start from current directory or provided path
    current = (start_path or Path.cwd()).resolve()

    # Crawl up looking for .alignment-map.yaml
    while current != current.parent:
        if (current / ".alignment-map.yaml").exists():
            return current
        current = current.parent

    # Check root directory
    if (current / ".alignment-map.yaml").exists():
        return current

    # Fall back to git root
    ## TODO: Replace subprocess git calls with pygit2 or Dulwich for cleaner implementation
    try:
        return get_repo_root()
    except subprocess.CalledProcessError:
        raise FileNotFoundError(
            "Could not find .alignment-map.yaml in directory tree. "
            "Use --mapfile to specify the path explicitly."
        )


def is_file_staged(project_root: Path, file_path: Path) -> bool:
    """Check if a file is staged for commit."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )
    staged_files = [f.strip() for f in result.stdout.strip().split("\n")]
    return str(file_path) in staged_files
