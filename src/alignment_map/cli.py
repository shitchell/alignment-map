"""CLI for alignment-map tool."""

import json
import subprocess
import sys
from pathlib import Path

import click

from .checker import check_staged_changes
from .git import find_project_root, get_repo_root
from .output import print_check_results


@click.group()
@click.version_option()
def main() -> None:
    """Alignment Map - Enforce coherency across code and documentation."""
    pass


@main.command()
@click.option("--staged", is_flag=True, default=True, help="Check staged changes (default)")
@click.option("--all", "check_all", is_flag=True, help="Check all files")
@click.option("--files", multiple=True, help="Check specific files")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def check(staged: bool, check_all: bool, files: tuple[str, ...], mapfile: Path | None) -> None:
    """Check alignment of code changes."""
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"

    if not map_path.exists():
        click.echo(f"Error: Alignment map not found: {map_path}", err=True)
        click.echo("\nCreate .alignment-map.yaml to define code-to-doc alignments.", err=True)
        sys.exit(2)

    if check_all or files:
        click.echo("Warning: --all and --files not yet implemented, checking staged changes", err=True)

    failures = check_staged_changes(project_root, map_path)
    print_check_results(failures)

    if failures:
        sys.exit(1)
    sys.exit(0)


@main.command()
@click.option("--fix-lines", is_flag=True, help="Attempt to auto-fix line numbers")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def validate(fix_lines: bool, mapfile: Path | None) -> None:
    """Validate the alignment map itself."""
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"

    if not map_path.exists():
        click.echo(f"Error: Alignment map not found: {map_path}", err=True)
        sys.exit(2)

    from .parser import parse_alignment_map

    try:
        alignment_map = parse_alignment_map(map_path)
    except Exception as e:
        click.echo(f"Error parsing alignment map: {e}", err=True)
        sys.exit(2)

    errors: list[str] = []

    # Check all referenced files exist
    for mapping in alignment_map.mappings:
        file_path = project_root / mapping.file_path
        if not file_path.exists():
            errors.append(f"File not found: {mapping.file_path}")

        # Check line ranges are valid
        if file_path.exists():
            line_count = len(file_path.read_text().split("\n"))
            for block in mapping.blocks:
                if block.lines.end > line_count:
                    errors.append(
                        f"{mapping.file_path}: Block '{block.name}' "
                        f"ends at line {block.lines.end} but file has {line_count} lines"
                    )

        # Check aligned docs exist
        for block in mapping.blocks:
            for aligned_ref in block.aligned_with:
                doc_path_str = aligned_ref.split("#")[0]
                if not doc_path_str.startswith("src/"):  # Skip code refs
                    doc_path = project_root / doc_path_str
                    if not doc_path.exists():
                        errors.append(f"Aligned doc not found: {aligned_ref}")

    if errors:
        click.echo("Alignment map validation failed:\n", err=True)
        for error in errors:
            click.echo(f"  ✗ {error}", err=True)
        sys.exit(1)

    click.echo("✓ Alignment map is valid")
    sys.exit(0)


@main.command()
@click.argument("file_path")
@click.option("--block", required=True, help="Block name")
@click.option("--lines", required=True, help="Line range (e.g., 1-50)")
@click.option("--aligned-with", multiple=True, required=True, help="Aligned documents")
@click.option("--comment", help="Description of the change")
@click.option("--extend", "strategy", flag_value="extend", help="Extend existing block")
@click.option("--split", "strategy", flag_value="split", help="Split existing block")
@click.option("--replace", "strategy", flag_value="replace", help="Replace existing block")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def update(
    file_path: str,
    block: str,
    lines: str,
    aligned_with: tuple[str, ...],
    comment: str | None,
    strategy: str | None,
    mapfile: Path | None,
) -> None:
    """Add or update a block in the alignment map."""
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"
    if not map_path.exists():
        # Create initial map structure
        initial_map = """version: 1

hierarchy:
  requires_human: []
  technical:
    - docs/**/*.md

mappings: []
"""
        map_path.write_text(initial_map)
        click.echo("Created new alignment map")

    from .models import LineRange
    from .update import update_block

    try:
        line_range = LineRange.from_string(lines)
    except ValueError as e:
        click.echo(f"Error: Invalid line range format: {e}", err=True)
        sys.exit(2)

    success = update_block(
        project_root,
        map_path,
        Path(file_path),
        block,
        line_range,
        list(aligned_with),
        comment,
        strategy,
    )

    sys.exit(0 if success else 1)


@main.command()
@click.argument("file_path", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output in JSON format")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def suggest(file_path: str | None, output_json: bool, mapfile: Path | None) -> None:
    """Suggest block boundaries for unmapped code."""
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"
    if not map_path.exists():
        click.echo("Error: Alignment map not found", err=True)
        sys.exit(2)

    from .suggest import print_suggestions, suggest_blocks

    file_to_check = Path(file_path) if file_path else None
    suggestions = suggest_blocks(project_root, map_path, file_to_check)

    if output_json:
        # Convert Path keys to strings for JSON serialization
        json_suggestions = {str(k): [
            {
                "name": s.name,
                "lines": str(s.lines),
                "type": s.block_type,
                "confidence": s.confidence,
            } for s in v
        ] for k, v in suggestions.items()}
        click.echo(json.dumps(json_suggestions, indent=2))
    else:
        print_suggestions(suggestions)

    sys.exit(0)


@main.command()
@click.argument("file_spec", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output in JSON format")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def trace(file_spec: str | None, output_json: bool, mapfile: Path | None) -> None:
    """Print all context needed to review a file/line.

    Usage: alignment-map trace FILE[:LINE]
    """
    if not file_spec:
        click.echo("Error: FILE argument required", err=True)
        click.echo("Usage: alignment-map trace FILE[:LINE]", err=True)
        sys.exit(2)

    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"
    if not map_path.exists():
        click.echo("Error: Alignment map not found", err=True)
        sys.exit(2)

    # Parse FILE[:LINE] format
    if ":" in file_spec:
        file_path_str, line_str = file_spec.rsplit(":", 1)
        try:
            line_number = int(line_str)
        except ValueError:
            click.echo(f"Error: Invalid line number: {line_str}", err=True)
            sys.exit(2)
    else:
        file_path_str = file_spec
        line_number = None

    from .parser import parse_alignment_map
    from .trace import trace_file_location

    alignment_map = parse_alignment_map(map_path)
    result = trace_file_location(
        project_root,
        alignment_map,
        Path(file_path_str),
        line_number,
        output_json,
    )

    if output_json and result:
        click.echo(json.dumps(result, indent=2))

    sys.exit(0 if result else 1)


@main.command()
@click.argument("file_path")
@click.option("--json", "output_json", is_flag=True, help="Output in JSON format")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def review(file_path: str, output_json: bool, mapfile: Path | None) -> None:
    """Pre-flight check showing what docs would need review."""
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"
    if not map_path.exists():
        click.echo("Error: Alignment map not found", err=True)
        sys.exit(2)

    from .review import review_file

    result = review_file(project_root, map_path, Path(file_path), output_json)

    if output_json and result:
        click.echo(json.dumps(result, indent=2))

    sys.exit(0 if result else 1)


@main.command()
@click.option("--format", "output_format", type=click.Choice(["dot", "ascii", "json"]), default="ascii")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def graph(output_format: str, mapfile: Path | None) -> None:
    """Visualize alignment relationships."""
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"
    if not map_path.exists():
        click.echo("Error: Alignment map not found", err=True)
        sys.exit(2)

    from .graph import generate_graph

    result = generate_graph(project_root, map_path, output_format)

    if output_format == "json":
        click.echo(json.dumps(result, indent=2))
    elif output_format == "dot":
        click.echo(result)
    # ASCII output is printed directly by generate_graph

    sys.exit(0)


@main.command("update-lines")
@click.argument("file_path")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def update_lines(file_path: str, mapfile: Path | None) -> None:
    """Update line numbers for a file after refactoring."""
    # TODO: Implement line number updating
    click.echo(f"Update-lines command not yet implemented for: {file_path}")
    sys.exit(0)


@main.command("install-hook")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def install_hook(mapfile: Path | None) -> None:
    """Install the pre-commit git hook."""
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError:
        # For install-hook, we still need a git repo for the hook itself
        try:
            project_root = get_repo_root()
        except subprocess.CalledProcessError:
            click.echo("Error: Not in a git repository", err=True)
            sys.exit(2)

    hooks_dir = project_root / ".git" / "hooks"
    hook_path = hooks_dir / "pre-commit"

    # Include --mapfile in hook if it was used during installation
    mapfile_option = f" --mapfile {mapfile}" if mapfile else ""

    hook_content = f'''#!/bin/sh
# Alignment Map pre-commit hook
# Installed by: alignment-map install-hook{mapfile_option}

alignment-map check --staged{mapfile_option}

exit $?
'''

    if hook_path.exists():
        # Check if it's our hook or another one
        existing = hook_path.read_text()
        if "alignment-map" in existing:
            click.echo("Alignment map hook already installed")
            sys.exit(0)
        else:
            click.echo(f"Warning: Existing pre-commit hook found at {hook_path}", err=True)
            click.echo("Appending alignment-map check...", err=True)
            with open(hook_path, "a") as f:
                f.write(f"\n# Alignment Map check\nalignment-map check --staged{mapfile_option} || exit $?\n")
    else:
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)
        click.echo(f"✓ Installed pre-commit hook at {hook_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
