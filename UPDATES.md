# Planned Updates for Alignment-Map

This document outlines the planned CLI restructuring discussed with the user. The next Claude session should implement these changes.

---

## Instructions for Next Claude

### Required Reading

Before implementing, read and understand:

1. **All source files**: `src/alignment_map/*.py` (11 files)
2. **Specification**: `SPEC.md` - full schema and workflow
3. **Project context**: `CLAUDE.md` - architecture overview and design principles
4. **Tests**: `tests/*.py` - understand current test coverage
5. **This file**: Understand the rationale for each change

### Key Philosophy

The tool's core principle: **"Comments suggesting review get ignored. Blocking commits with printed context guarantees the information is seen."**

All changes should reinforce this. When in doubt, print more context.

---

## Command Restructuring

### Overview of Changes

| Old Command | New Command | Change Type |
|-------------|-------------|-------------|
| `update` | `block-add` | Rename + refine |
| (new) | `block-touch` | New command |
| `suggest` | `block-suggest` | Rename |
| `check` | `check` | Keep |
| `validate` | `map-lint` | Rename + enhance |
| `update-lines` | (removed) | Merged into `map-lint --apply` |
| `review` | (removed) | Merged into `trace` |
| `trace` | `trace` | Keep + enhance |
| `graph` | `map-graph` | Rename |
| `install-hook` | `hook-install` | Rename |

### Final Command List

```
alignment-map --help
Commands:
  block-add       Add new block mapping
  block-suggest   Suggest block boundaries
  block-touch     Update existing block
  check           Check staged changes
  hook-install    Install git hook
  map-graph       Visualize relationships
  map-lint        Validate map file
  trace           Print context for file/line
```

---

## Detailed Command Specifications

### 1. `block-add` (was `update`)

**Purpose**: Add a new block to the alignment map

**Usage**:
```bash
alignment-map block-add FILE --name NAME --lines START-END --aligned-with DOC [--comment COMMENT]
```

**Behavior**:
- If lines overlap with existing blocks, error with suggestions:
  - `--extend` - Extend existing block
  - `--split` - Split existing block
  - `--replace` - Replace existing block
- After successful add, **print trace output** showing:
  - The code block (actual lines from file)
  - Aligned document sections
  - Instruction to review alignment

**Rationale**: Clear verb for adding new mappings. Suffix pattern groups block operations together in help output.

**Implementation**: Modify `cli.py` and `update.py`. Add trace printing after successful operations.

---

### 2. `block-touch` (new command)

**Purpose**: Update an existing block's metadata with smart line detection

**Usage**:
```bash
alignment-map block-touch FILE --name NAME --comment "Description of change"
```

**Behavior**:
1. Find the block by name in the map
2. Use AST/fuzzy matching to find where the code moved
3. Update `lines` if they changed
4. Update `last_updated` timestamp
5. Update `last_update_comment`
6. **Error only if new lines overlap with another block**
7. After success, **print trace output**

**Rationale**: This is the common workflow after `check` fails. The current `update` requires re-specifying everything; `block-touch` is streamlined for "I modified this block, update the map."

**Implementation**:
- Create new `touch.py` module
- Implement smart line detection using AST (reuse logic from `suggest.py`)
- Add to CLI

---

### 3. `block-suggest` (was `suggest`)

**Purpose**: Suggest block boundaries for unmapped code

**Usage**:
```bash
alignment-map block-suggest [FILE] [--json]
```

**Behavior**: No change to functionality, just rename.

**Rationale**: Groups with other block operations.

**Implementation**: Rename in `cli.py`.

---

### 4. `check` (unchanged)

**Purpose**: Check staged changes against alignment rules

**Usage**:
```bash
alignment-map check [--staged | --all | --files FILE...]
```

**Rationale**: High-frequency command (git hook), keep short and unprefixed.

---

### 5. `map-lint` (was `validate`)

**Purpose**: Validate the alignment map file itself

**Usage**:
```bash
alignment-map map-lint [--apply]
```

**Behavior**:

Without `--apply`:
1. Check all referenced files exist
2. Check all line ranges are valid
3. Check all anchors resolve
4. If issues found, write suggested fixes to `.alignment-map.fixes`
5. Print summary and path to fixes file

With `--apply`:
1. **Only runs if `.alignment-map.fixes` exists**
2. Apply the fixes from that file
3. Delete the fixes file after applying
4. Print what was fixed

**Fixes file format** (`.alignment-map.fixes`):
```yaml
generated: 2024-01-16T10:30:00
fixes:
  - file: src/module.py
    block: MyClass
    issue: line_drift
    old_lines: 10-50
    new_lines: 15-55
    confidence: high

  - file: src/other.py
    block: helper_function
    issue: missing_file
    action: remove_block
```

**Rationale**:
- "Lint" is clearer than "validate" (validates the map, not alignment)
- Terraform-style plan/apply pattern ensures user reviews before auto-fixing
- Absorbs `update-lines` functionality

**Implementation**:
- Rename command in `cli.py`
- Add fixes file generation to current validation logic
- Implement `--apply` to read and apply fixes
- Add smart line detection for `line_drift` fixes

---

### 6. `trace` (enhanced)

**Purpose**: Print all context needed to review a file/line

**Usage**:
```bash
alignment-map trace FILE[:LINE] [--json]
```

**Changes**:
- Absorb `review` command functionality
- When FILE specified without LINE, show impact summary for all blocks
- Remove time estimates (they were arbitrary guesses)

**Rationale**: `review` was nearly identical to `trace`. One command is simpler.

**Implementation**:
- Remove `review.py` and its CLI command
- Ensure `trace.py` handles FILE without LINE gracefully
- Remove `estimate_review_impact` logic

---

### 7. `map-graph` (was `graph`)

**Purpose**: Visualize alignment relationships

**Usage**:
```bash
alignment-map map-graph [--format dot|ascii|json]
```

**Rationale**: Clarifies it's graphing the map structure.

**Implementation**: Rename in `cli.py`.

---

### 8. `hook-install` (was `install-hook`)

**Purpose**: Install the pre-commit git hook

**Usage**:
```bash
alignment-map hook-install
```

**Rationale**: Follows `<noun>-<verb>` pattern for consistency with other prefixed commands.

**Implementation**: Rename in `cli.py`.

---

## Print Trace After Block Modifications

**Critical UX improvement**: After any `block-add` or `block-touch` operation, print:

1. **The code block** - actual lines from the file
2. **Aligned document sections** - content from linked docs
3. **Instruction** - remind user to review and update docs if needed

Example output:
```
✓ Added block 'MyClass' (lines 10-50) to src/module.py

━━━ Code Block ━━━
10│ class MyClass:
11│     """A sample class."""
12│     def __init__(self):
...
50│         return self.value

━━━ Aligned Documents ━━━
docs/ARCHITECTURE.md#my-class
  last_reviewed: 2024-01-15T10:30:00

  ## My Class

  This section describes MyClass and its responsibilities.
  It should be kept in sync with the implementation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Review the above to ensure alignment. If docs need updating,
modify them and update their last_reviewed timestamps.
```

**Implementation**:
- Create helper function to print this format
- Call from `block-add` and `block-touch` after successful operations
- Reuse logic from `trace.py` for section extraction

---

## Files to Modify

| File | Changes |
|------|---------|
| `cli.py` | Rename all commands, update signatures, add `block-touch` |
| `update.py` | Rename to support `block-add`, add trace printing |
| `touch.py` | **New file** - implement `block-touch` with smart line detection |
| `suggest.py` | Minor - command rename |
| `trace.py` | Absorb `review` functionality, enhance for full-file trace |
| `review.py` | **Delete** - merged into trace |
| `graph.py` | Minor - command rename |
| `parser.py` | May need enhancements for fixes file parsing |
| `output.py` | Add helper for post-modification trace output |

---

## Test Updates

All tests in `tests/test_commands.py` will need updating for new command names.

Add new tests for:
- `block-touch` with smart line detection
- `block-touch` overlap detection
- `map-lint` fixes file generation
- `map-lint --apply` behavior
- Post-modification trace output

---

## Migration Notes

- Old command names should produce helpful error messages pointing to new names
- Update `SPEC.md` with new command structure
- Update `README.md` quick start examples
- Update `CLAUDE.md` if needed

---

## Summary

The restructuring achieves:
1. **Clearer terminology** - `lint` vs `validate`, grouped prefixes
2. **Better workflow** - `block-touch` for common "update timestamp" operation
3. **Forced review** - Terraform-style plan/apply for auto-fixes
4. **Context guarantee** - Print trace after every block modification
5. **Simpler CLI** - Merged redundant `review` into `trace`

All changes reinforce the core philosophy: **print context to guarantee it's seen**.
