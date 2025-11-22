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


def get_tracked_files(project_root: Path) -> list[Path]:
    """Get all files tracked by git."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(f.strip()) for f in result.stdout.strip().split("\n") if f.strip()]


def load_gitignore_patterns(project_root: Path) -> list[str]:
    """Load patterns from .gitignore file."""
    gitignore_path = project_root / ".gitignore"
    if not gitignore_path.exists():
        return []

    patterns = []
    for line in gitignore_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        patterns.append(line)
    return patterns


def should_ignore_file(
    file_path: Path,
    ignore_patterns: list[str],
    gitignore_patterns: list[str] | None = None,
) -> bool:
    """Check if a file should be ignored."""
    from fnmatch import fnmatch
    path_str = str(file_path)

    def matches_pattern(path: str, pattern: str) -> bool:
        """Check if path matches pattern with ** support."""
        # Handle ** patterns by checking if any part of the path matches
        if "**" in pattern:
            # For patterns like "**/tests/**", check if 'tests' is in the path
            parts = pattern.split("**")
            if len(parts) == 2:
                prefix, suffix = parts
                prefix = prefix.rstrip("/")
                suffix = suffix.lstrip("/")

                # Check if pattern is directory-based like "**/tests/**"
                if prefix == "" and suffix == "":
                    return False
                elif prefix == "":
                    # Pattern like "**/tests/**" - check if any path component matches
                    if suffix:
                        middle = suffix.split("/")[0] if "/" in suffix else suffix
                        if middle:
                            path_parts = path.split("/")
                            # Check if any directory in the path matches
                            return any(fnmatch(part, middle) for part in path_parts[:-1]) or \
                                   any(fnmatch(part, middle) for part in path_parts)
                    return False
                elif suffix == "":
                    # Pattern like "tests/**"
                    return path.startswith(prefix.rstrip("/") + "/") or fnmatch(path, prefix + "*")
            elif len(parts) == 3 and parts[0] == "" and parts[2] == "":
                # Pattern like "**/tests/**" with middle part
                middle = parts[1].strip("/")
                if middle:
                    path_parts = path.split("/")
                    return any(fnmatch(part, middle) for part in path_parts)
            # For complex ** patterns, try direct fnmatch
            return fnmatch(path, pattern)
        else:
            # Simple pattern - match against path or filename
            return fnmatch(path, pattern) or fnmatch(Path(path).name, pattern)

    for pattern in ignore_patterns:
        if matches_pattern(path_str, pattern):
            return True

    if gitignore_patterns:
        for pattern in gitignore_patterns:
            if matches_pattern(path_str, pattern):
                return True

    return False
