"""CLI for alignment-map tool."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Literal

import click

from .checker import check_staged_changes
from .git import find_project_root, get_repo_root
from .output import (
    print_block_modification_trace,
    print_check_results,
    print_lint_summary,
    print_manual_fix_context,
)


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


@main.command("map-lint")
@click.option("--apply", "apply_fixes", is_flag=True, help="Apply fixes from .alignment-map.fixes")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def map_lint(apply_fixes: bool, mapfile: Path | None) -> None:
    """Validate the alignment map itself.

    Without --apply: Lint the map and write suggested fixes to .alignment-map.fixes
    With --apply: Apply fixes from the .alignment-map.fixes file
    """
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"
    fixes_path = map_path.parent / ".alignment-map.fixes"

    if not map_path.exists():
        click.echo(f"Error: Alignment map not found: {map_path}", err=True)
        sys.exit(2)

    from .lint import apply_fixes_file, lint_alignment_map, write_fixes_file
    from .models import AlignmentMap

    if apply_fixes:
        # Apply mode - read and apply fixes from file
        if not fixes_path.exists():
            click.echo(f"Error: No fixes file found at {fixes_path}", err=True)
            click.echo("\nRun 'alignment-map map-lint' first to generate fixes.", err=True)
            sys.exit(2)

        actions, skipped = apply_fixes_file(project_root, map_path, fixes_path)

        if actions:
            click.echo("Applied fixes:\n")
            for action in actions:
                click.echo(f"  [green]+[/green] {action}", err=False)
            click.echo("")

        # Show context for manual fixes
        if skipped:
            click.echo(f"\nSkipped {len(skipped)} manual fix(es):\n", err=True)

            # Load alignment map for context
            try:
                alignment_map = AlignmentMap.load(map_path)
                for fix in skipped:
                    print_manual_fix_context(project_root, alignment_map, fix)
            except Exception:
                # Fallback to simple output if map can't be loaded
                for fix in skipped:
                    issue_type = fix.get("issue", "unknown")
                    description = fix.get("description", "")
                    reason = fix.get("reason", "")
                    click.echo(f"  - [{issue_type}] {description}", err=True)
                    if reason:
                        click.echo(f"    Reason: {reason}", err=True)

        # Delete the fixes file after successful apply
        fixes_path.unlink()
        click.echo(f"Deleted {fixes_path}")

        if skipped:
            click.echo(f"\nAuto fixes applied. {len(skipped)} manual fix(es) require attention.")
            sys.exit(1)  # Exit with error if there are manual fixes remaining
        else:
            click.echo("\nAll fixes applied successfully")
            sys.exit(0)

    else:
        # Lint mode - check for issues and write fixes file
        fixes = lint_alignment_map(project_root, map_path)

        if not fixes:
            click.echo("Alignment map is valid")
            # Remove stale fixes file if it exists
            if fixes_path.exists():
                fixes_path.unlink()
            sys.exit(0)

        # Write fixes to file
        write_fixes_file(fixes_path, fixes)

        # Categorize fixes
        auto_fixes = [f for f in fixes if f.get("action") == "auto"]
        manual_fixes = [f for f in fixes if f.get("action") == "manual"]

        # Print summary
        click.echo("Alignment map issues found:\n", err=True)

        if auto_fixes:
            click.echo(f"[green]Auto-fixable ({len(auto_fixes)}):[/green]", err=True)
            for fix in auto_fixes:
                issue_type = fix.get("issue", "unknown")
                description = fix.get("description", "")
                click.echo(f"  + [{issue_type}] {description}", err=True)
            click.echo("")

        if manual_fixes:
            click.echo(f"[yellow]Requires manual review ({len(manual_fixes)}):[/yellow]", err=True)
            for fix in manual_fixes:
                issue_type = fix.get("issue", "unknown")
                description = fix.get("description", "")
                reason = fix.get("reason", "")
                click.echo(f"  ! [{issue_type}] {description}", err=True)
                if reason:
                    click.echo(f"      Reason: {reason}", err=True)

        click.echo(f"\nFixes written to: {fixes_path}", err=True)

        if auto_fixes:
            click.echo("Run 'alignment-map map-lint --apply' to apply auto fixes.", err=True)

        if manual_fixes:
            click.echo(f"\n{len(manual_fixes)} issue(s) require manual review.", err=True)

        sys.exit(1)


@main.command("block-add")
@click.argument("file_path")
@click.option("--block", required=True, help="Block name")
@click.option("--lines", required=True, help="Line range (e.g., 1-50)")
@click.option("--aligned-with", multiple=True, required=True, help="Aligned documents")
@click.option("--comment", help="Description of the change")
@click.option("--extend", "strategy", flag_value="extend", help="Extend existing block")
@click.option("--split", "strategy", flag_value="split", help="Split existing block")
@click.option("--replace", "strategy", flag_value="replace", help="Replace existing block")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def block_add(
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

    # Cast strategy to the expected Literal type
    strategy_typed: Literal["extend", "split", "replace"] | None = None
    if strategy in ("extend", "split", "replace"):
        strategy_typed = strategy  # type: ignore[assignment]

    success, final_lines, final_aligned = update_block(
        project_root,
        map_path,
        Path(file_path),
        block,
        line_range,
        list(aligned_with),
        comment,
        strategy_typed,
    )

    # Print trace if successful
    if success and final_lines and final_aligned is not None:
        print_block_modification_trace(
            project_root,
            Path(file_path),
            block,
            final_lines,
            final_aligned,
        )

    sys.exit(0 if success else 1)


@main.command("block-touch")
@click.argument("file_path")
@click.option("--name", required=True, help="Block name to update")
@click.option("--comment", required=True, help="Description of the change")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def block_touch(file_path: str, name: str, comment: str, mapfile: Path | None) -> None:
    """Update an existing block's metadata with smart line detection."""
    try:
        project_root = find_project_root(mapfile=mapfile)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    map_path = mapfile if mapfile else project_root / ".alignment-map.yaml"

    if not map_path.exists():
        click.echo(f"Error: Alignment map not found: {map_path}", err=True)
        sys.exit(2)

    from .touch import touch_block

    success, new_lines, aligned_with = touch_block(
        project_root,
        map_path,
        Path(file_path),
        name,
        comment,
    )

    # Print trace if successful
    if success and new_lines and aligned_with is not None:
        print_block_modification_trace(
            project_root,
            Path(file_path),
            name,
            new_lines,
            aligned_with,
        )

    sys.exit(0 if success else 1)


@main.command("block-suggest")
@click.argument("file_path", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output in JSON format")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def block_suggest(file_path: str | None, output_json: bool, mapfile: Path | None) -> None:
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

    from .models import AlignmentMap
    from .trace import trace_file_location

    alignment_map = AlignmentMap.load(map_path)
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


@main.command("map-graph")
@click.option("--format", "output_format", type=click.Choice(["dot", "ascii", "json"]), default="ascii")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def map_graph(output_format: str, mapfile: Path | None) -> None:
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


@main.command("hook-install")
@click.option("--mapfile", "-m", type=click.Path(exists=True, path_type=Path), help="Path to alignment map file")
def hook_install(mapfile: Path | None) -> None:
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
