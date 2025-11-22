"""Graph command implementation - visualize alignment relationships."""

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

from .models import AlignmentMap


def generate_graph(
    project_root: Path,
    map_path: Path,
    output_format: str = "ascii",
) -> str | dict[str, Any]:
    """Generate a graph visualization of alignment relationships."""
    console = Console()

    # Parse alignment map
    try:
        alignment_map = AlignmentMap.load(map_path)
    except Exception as e:
        if output_format == "json":
            return {"error": "map_parse_error", "message": str(e)}
        else:
            console.print(f"[red]Error parsing alignment map: {e}[/red]")
            return ""

    # Build graph data
    graph_data = build_graph_data(alignment_map)

    # Generate output based on format
    if output_format == "dot":
        return generate_dot_graph(graph_data)
    elif output_format == "json":
        return graph_data
    else:  # ascii
        return generate_ascii_graph(graph_data, console)


def build_graph_data(alignment_map: AlignmentMap) -> dict[str, Any]:
    """Build graph data structure from alignment map."""
    nodes = []
    edges = []
    node_ids = {}
    next_id = 0

    # Create nodes for all files and their blocks
    for mapping in alignment_map.mappings:
        file_id = f"file_{next_id}"
        next_id += 1
        node_ids[str(mapping.file)] = file_id

        nodes.append({
            "id": file_id,
            "label": str(mapping.file),
            "type": "file",
            "is_code": str(mapping.file).startswith("src/"),
            "is_doc": str(mapping.file).endswith(".md"),
            "requires_human": alignment_map.is_human_required(str(mapping.file)),
        })

        # Add blocks as child nodes
        for block in mapping.blocks:
            block_id = f"block_{next_id}"
            next_id += 1

            # Store block ID for edge creation
            block_key = f"{mapping.file}#{block.id or block.name}"
            node_ids[block_key] = block_id

            nodes.append({
                "id": block_id,
                "label": block.name,
                "type": "block",
                "parent": file_id,
                "lines": str(block.lines),
                "last_updated": block.last_updated.isoformat() if block.last_updated else None,
                "last_reviewed": block.last_reviewed.isoformat() if block.last_reviewed else None,
            })

            # Create edges from this block to aligned items
            for aligned_ref in block.aligned_with:
                # Parse the reference
                if "#" in aligned_ref:
                    target_file, target_anchor = aligned_ref.split("#", 1)
                else:
                    target_file = aligned_ref
                    target_anchor = None

                # Find or create target node
                if target_file not in node_ids:
                    # Create node for referenced file
                    target_id = f"file_{next_id}"
                    next_id += 1
                    node_ids[target_file] = target_id

                    nodes.append({
                        "id": target_id,
                        "label": target_file,
                        "type": "file",
                        "is_code": target_file.startswith("src/"),
                        "is_doc": target_file.endswith(".md"),
                        "requires_human": alignment_map.is_human_required(target_file),
                    })

                # Create edge
                target_id = node_ids[target_file]
                edges.append({
                    "source": block_id,
                    "target": target_id,
                    "label": "aligned_with",
                    "anchor": target_anchor,
                })

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_files": len([n for n in nodes if n["type"] == "file"]),
            "total_blocks": len([n for n in nodes if n["type"] == "block"]),
            "total_alignments": len(edges),
            "code_files": len([n for n in nodes if n["type"] == "file" and n.get("is_code")]),
            "doc_files": len([n for n in nodes if n["type"] == "file" and n.get("is_doc")]),
            "human_required_docs": len([n for n in nodes if n["type"] == "file" and n.get("requires_human")]),
        },
    }


def generate_dot_graph(graph_data: dict[str, Any]) -> str:
    """Generate Graphviz DOT format output."""
    lines = ["digraph AlignmentMap {"]
    lines.append("  rankdir=LR;")
    lines.append("  node [shape=box];")
    lines.append("")

    # Group nodes by type
    code_nodes = []
    doc_nodes = []
    block_nodes = []

    for node in graph_data["nodes"]:
        if node["type"] == "block":
            block_nodes.append(node)
        elif node.get("is_code"):
            code_nodes.append(node)
        elif node.get("is_doc"):
            doc_nodes.append(node)

    # Code files subgraph
    if code_nodes:
        lines.append("  subgraph cluster_code {")
        lines.append('    label="Code Files";')
        lines.append("    style=filled;")
        lines.append("    color=lightblue;")
        for node in code_nodes:
            label = node["label"].replace('"', '\\"')
            lines.append(f'    {node["id"]} [label="{label}", shape=box, style=filled, fillcolor=white];')
        lines.append("  }")
        lines.append("")

    # Documentation subgraph
    if doc_nodes:
        lines.append("  subgraph cluster_docs {")
        lines.append('    label="Documentation";')
        lines.append("    style=filled;")
        lines.append("    color=lightgreen;")
        for node in doc_nodes:
            label = node["label"].replace('"', '\\"')
            color = "pink" if node.get("requires_human") else "white"
            lines.append(f'    {node["id"]} [label="{label}", shape=note, style=filled, fillcolor={color}];')
        lines.append("  }")
        lines.append("")

    # Blocks (nested under files)
    for node in block_nodes:
        label = f"{node['label']}\\n{node['lines']}"
        label = label.replace('"', '\\"')
        lines.append(f'  {node["id"]} [label="{label}", shape=ellipse, style=filled, fillcolor=lightyellow];')

        # Parent relationship
        if "parent" in node:
            lines.append(f'  {node["parent"]} -> {node["id"]} [style=dotted, arrowhead=none];')

    lines.append("")

    # Edges
    for edge in graph_data["edges"]:
        label = edge.get("anchor", "")
        if label:
            label = f'[label="#{label}"]'
        lines.append(f'  {edge["source"]} -> {edge["target"]} {label};')

    lines.append("}")

    return "\n".join(lines)


def generate_ascii_graph(graph_data: dict[str, Any], console: Console) -> str:
    """Generate ASCII tree visualization."""
    # Build a tree structure
    tree = Tree("[bold]Alignment Map[/bold]")

    # Stats branch
    stats = graph_data["stats"]
    stats_branch = tree.add("[cyan]Statistics[/cyan]")
    stats_branch.add(f"Files: {stats['total_files']} ({stats['code_files']} code, {stats['doc_files']} docs)")
    stats_branch.add(f"Blocks: {stats['total_blocks']}")
    stats_branch.add(f"Alignments: {stats['total_alignments']}")
    if stats['human_required_docs'] > 0:
        stats_branch.add(f"[red]Human-required docs: {stats['human_required_docs']}[/red]")

    # Build hierarchy
    files_branch = tree.add("[bold]Files and Alignments[/bold]")

    # Group nodes by file
    files = {}
    for node in graph_data["nodes"]:
        if node["type"] == "file":
            files[node["id"]] = {
                "node": node,
                "blocks": [],
            }

    for node in graph_data["nodes"]:
        if node["type"] == "block" and "parent" in node:
            files[node["parent"]]["blocks"].append(node)

    # Sort files by type (code first, then docs)
    sorted_files = sorted(
        files.values(),
        key=lambda f: (not f["node"].get("is_code", False), f["node"]["label"])
    )

    for file_data in sorted_files:
        file_node = file_data["node"]

        # Determine file style
        if file_node.get("is_code"):
            file_style = "cyan"
            icon = "📄"
        elif file_node.get("is_doc"):
            if file_node.get("requires_human"):
                file_style = "red"
                icon = "📕"
            else:
                file_style = "green"
                icon = "📗"
        else:
            file_style = "white"
            icon = "📁"

        file_branch = files_branch.add(f"{icon} [{file_style}]{file_node['label']}[/{file_style}]")

        # Add blocks
        for block in file_data["blocks"]:
            block_text = f"📦 {block['label']} [dim](lines {block['lines']})[/dim]"
            block_branch = file_branch.add(block_text)

            # Find alignments for this block
            alignments = []
            for edge in graph_data["edges"]:
                if edge["source"] == block["id"]:
                    # Find target node
                    target = next((n for n in graph_data["nodes"] if n["id"] == edge["target"]), None)
                    if target:
                        anchor = f"#{edge['anchor']}" if edge.get("anchor") else ""
                        alignments.append(f"{target['label']}{anchor}")

            if alignments:
                for aligned in alignments:
                    # Determine alignment style
                    if aligned.endswith(".md"):
                        align_style = "green"
                        align_icon = "→"
                    else:
                        align_style = "cyan"
                        align_icon = "↔"
                    block_branch.add(f"{align_icon} [{align_style}]{aligned}[/{align_style}]")

    # Print the tree
    console.print()
    console.print(tree)
    console.print()

    # Print legend
    legend_text = """[bold]Legend:[/bold]
📄 Code file
📗 Technical documentation
📕 Human-required documentation
📦 Code block
→  Alignment to documentation
↔  Code-to-code alignment"""

    console.print(Panel(legend_text, title="Legend", border_style="dim"))

    # Return string representation
    return "Graph visualization printed to console"