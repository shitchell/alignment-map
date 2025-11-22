---
last_reviewed: 2025-11-22T00:00:00
---

# Alignment Map

Enforce coherency between code and documentation through explicit mappings and git hook enforcement.

## Overview

Alignment Map ensures that when code changes, related documentation is reviewed. It:

1. **Maps code blocks to docs** — Declare which docs each piece of code aligns with
2. **Blocks commits** — Until the alignment map is updated and docs are reviewed
3. **Prints context** — Shows relevant doc sections so reviewers (human or LLM) have full context
4. **Enforces hierarchy** — Escalates identity/design doc changes to human review

## Quick Start

```bash
# Install with dev dependencies (auto-installs git hook)
pip install -e ".[dev]"

# Or install and manually setup hook
pip install -e .
alignment-map hook-install

# Create initial alignment map
touch .alignment-map.yaml
```

## Configuration

Create `.alignment-map.yaml` in your project root:

```yaml
version: 1

hierarchy:
  requires_human:
    - docs/IDENTITY.md
    - docs/DESIGN_PRINCIPLES.md
  technical:
    - docs/ARCHITECTURE.md
    - docs/**/*.md

mappings:
  - file: src/mymodule/core.py
    blocks:
      - name: MyClass definition
        lines: 10-50
        last_updated: 2024-01-15T10:30:00
        last_update_comment: "Added new method"
        aligned_with:
          - docs/ARCHITECTURE.md#core-module
```

## Document Format

Documents must include `last_reviewed` in YAML frontmatter:

```markdown
---
last_reviewed: 2024-01-15T10:30:00
---

# Architecture

...
```

## Commands

```bash
# Check staged changes (run by git hook)
alignment-map check --staged

# Validate the alignment map
alignment-map map-lint

# Apply auto-fixes from map-lint
alignment-map map-lint --apply

# Add or update a block mapping
alignment-map block-add src/file.py --block "MyClass" --lines 10-50 --aligned-with SPEC.md#section

# Update existing block metadata with smart line detection
alignment-map block-touch src/file.py --name "MyClass" --comment "Description of change"

# Suggest blocks for unmapped code
alignment-map block-suggest src/file.py

# Visualize relationships
alignment-map map-graph

# Print context for a file/line location
alignment-map trace src/file.py:45
```

## How It Works

When you try to commit:

1. **Check coverage** — All changed lines must be in mapped blocks
2. **Check map updated** — Block's `last_updated` must be current
3. **Check doc review** — Aligned docs' `last_reviewed` must be ≥ `last_updated`
4. **Print sections** — Stale doc sections are printed to screen
5. **Block or pass** — Commit proceeds only when all checks pass

## Philosophy

This tool embodies the principle that **coherency requires enforcement**. Comments suggesting review get ignored. Blocking commits with printed context guarantees the information is seen and considered.

## See Also

- [Full Specification](./SPEC.md)
