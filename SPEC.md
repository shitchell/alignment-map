---
last_reviewed: 2025-11-22T00:00:00
---

# Alignment Map — Specification

A tool for enforcing coherency between code and documentation through explicit mappings, automated review requirements, and git hook enforcement.

---

## Goals

1. **No unmapped code** — Every piece of code has documented alignment to relevant docs
2. **Forced review** — Code changes require reviewing aligned documentation
3. **Context in window** — Stale docs are printed to screen, guaranteeing they're seen
4. **Audit trail** — Every change is documented with timestamps and comments
5. **Hierarchical coherency** — Code traces through technical docs up to project identity
6. **LLM-friendly** — Clear, actionable error messages that LLMs can follow

---

## Core Concepts

### Alignment
A declared relationship between a code block and documentation (or other code). When one changes, the other must be reviewed.

### Block
A logical unit of code (class, function, module section) with defined line ranges that shares alignment requirements.

### Review
Acknowledgment that aligned documentation has been checked for coherency with code changes. Tracked via `last_reviewed` fields.

### Escalation
Some documents (identity, design principles) require human review. Others (technical docs) can be updated by LLMs.

---

## File Structure

```
project/
├── .alignment-map.yaml      # The alignment map
├── .alignment-map.lock      # Lock file for in-progress reviews (optional)
├── docs/
│   ├── IDENTITY.md          # Has last_reviewed field
│   ├── DESIGN_PRINCIPLES.md # Has last_reviewed field
│   └── ARCHITECTURE.md      # Has last_reviewed field
└── src/
    └── ...                  # Code with mapped blocks
```

### Project Root Detection

The tool determines the project root using the following priority:

1. **Explicit mapfile**: If `--mapfile` is provided, use its parent directory as the project root
2. **Reverse tree crawl**: Search upward from the current directory for `.alignment-map.yaml`
3. **Git fallback**: If no `.alignment-map.yaml` is found, fall back to the git repository root

This allows the tool to work in non-git environments or with custom map locations.

---

## `.alignment-map.yaml` Schema

```yaml
version: 1

# Document hierarchy for escalation rules
hierarchy:
  # Documents requiring human review for changes
  requires_human:
    - docs/IDENTITY.md
    - docs/DESIGN_PRINCIPLES.md

  # Documents LLMs can update alongside code
  technical:
    - docs/ARCHITECTURE.md
    - docs/**/*.md

# Code-to-doc and code-to-code mappings
mappings:
  - file: src/validate/validators/base.py
    blocks:
      - name: BaseValidator class
        lines: 15-89
        last_updated: 2024-01-15T10:30:00
        last_update_comment: "Added requires_context_types attribute"
        aligned_with:
          - docs/ARCHITECTURE.md#validators
          - docs/DESIGN_PRINCIPLES.md#11-granular-validators-and-remediators

      - name: validate method
        lines: 45-67
        last_updated: 2024-01-14T09:00:00
        last_update_comment: "Initial implementation"
        aligned_with:
          - docs/DESIGN_PRINCIPLES.md#3-rich-self-contained-problem-objects
          - src/validate/core/problem_types/base.py#ProblemType  # code-to-code

  - file: src/validate/core/problem_types/base.py
    blocks:
      - name: ProblemType base class
        id: ProblemType  # For code-to-code references
        lines: 10-75
        last_updated: 2024-01-13T14:00:00
        last_update_comment: "Added severity levels"
        aligned_with:
          - docs/ARCHITECTURE.md#problem-types

  - file: docs/ARCHITECTURE.md
    blocks:
      - name: Validators section
        id: validators
        lines: 120-180
        last_reviewed: 2024-01-15T10:30:00
        aligned_with:
          - docs/DESIGN_PRINCIPLES.md#11-granular-validators-and-remediators
          - docs/IDENTITY.md#simple-flexibility

      - name: Problem Types section
        id: problem-types
        lines: 182-220
        last_reviewed: 2024-01-13T14:00:00
        aligned_with:
          - docs/DESIGN_PRINCIPLES.md#3-rich-self-contained-problem-objects
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | Path to file relative to project root |
| `blocks` | array | Logical units within the file |
| `blocks[].name` | string | Human-readable description of the block |
| `blocks[].id` | string | Optional identifier for cross-references |
| `blocks[].lines` | string | Line range in format `start-end` |
| `blocks[].last_updated` | ISO 8601 | When this code block was last modified |
| `blocks[].last_update_comment` | string | Description of the last change |
| `blocks[].last_reviewed` | ISO 8601 | When aligned docs were last reviewed (for doc blocks) |
| `blocks[].aligned_with` | array | Paths to aligned docs/code with optional anchors |

---

## Document Format

Documents must include a `last_reviewed` field in YAML frontmatter or a special comment:

### Markdown with Frontmatter
```markdown
---
last_reviewed: 2024-01-15T10:30:00
---

# Architecture

...
```

### Or with HTML Comment
```markdown
<!-- last_reviewed: 2024-01-15T10:30:00 -->

# Architecture

...
```

---

## Git Hook Behavior

### Pre-commit Hook Flow

```
For each changed file in staged changes:
    │
    ├─ Is file in .alignment-map.yaml?
    │   │
    │   NO → BLOCK
    │   │    "File not in alignment map. Add mapping with aligned docs."
    │   │
    │   YES ↓
    │
    For each changed line in file:
        │
        ├─ Is line in a mapped block?
        │   │
        │   NO → BLOCK
        │   │    "Lines X-Y not mapped. Add or extend a block."
        │   │
        │   YES ↓
        │
        ├─ Is block's last_updated also being updated?
        │   │
        │   NO → BLOCK
        │   │    "Update last_updated and last_update_comment for block."
        │   │
        │   YES ↓
        │
        For each aligned doc/code:
            │
            ├─ Is it a document?
            │   │
            │   YES → Check document's last_reviewed
            │   │     │
            │   │     ├─ last_reviewed >= block's last_updated?
            │   │     │   → OK
            │   │     │
            │   │     └─ last_reviewed < block's last_updated?
            │   │         │
            │   │         ├─ Technical doc?
            │   │         │   → BLOCK: Print section, require last_reviewed update
            │   │         │
            │   │         └─ Identity/Design doc?
            │   │             → BLOCK: Print section, require human escalation
            │   │
            │   └─ Is it code?
            │       │
            │       Check aligned code block's last_updated
            │       │
            │       └─ If stale → BLOCK: Print code block, require review

All checks pass → ALLOW COMMIT
```

---

## CLI Commands

All commands support `--json` for structured output suitable for programmatic parsing.

All commands also support `--mapfile FILE` / `-m FILE` to specify the path to the alignment map directly. This allows the tool to work outside of git repositories and with custom map locations.

### `alignment-map check`

Run coherency checks on staged changes (what the git hook calls).

```bash
alignment-map check [--staged | --tracked | --all | --files FILE...] [--json] [--mapfile FILE]
```

Options:
- `--staged` - Check only staged changes (default, used by git hook)
- `--tracked` - Check all git-tracked files
- `--all` - Check all files in project directory
- `--files` - Check specific files

### `alignment-map map-lint`

Validate the alignment map itself and generate fixes:
- All referenced files exist
- All line ranges are valid
- All anchors resolve
- Auto-detects line drift using AST parsing

```bash
alignment-map map-lint [--apply] [--mapfile FILE]
```

Without `--apply`: Lints the map and writes suggested fixes to `.alignment-map.fixes`.
With `--apply`: Applies auto-fixes from the `.alignment-map.fixes` file and shows context for manual fixes.

Fixes are categorized as:
- **Auto-fixable**: Line drift, missing files without dependencies
- **Manual**: Overlapping blocks, missing anchors, items with dependencies

### `alignment-map block-add`

Add or modify a file/block mapping.

```bash
alignment-map block-add FILE --block NAME --lines START-END --aligned-with DOC [--comment COMMENT] [--mapfile FILE]
```

**Overlap handling:**

If the specified lines overlap with an existing block, the command errors with suggestions:

```
Error: Lines 25-40 overlap with existing block "MyClass" (lines 20-50)

Suggestion: Use --extend (new range is subset of existing)

Options:
  --extend     Extend existing block to include new lines
  --split      Split existing block at the boundary
  --replace    Replace existing block entirely

Rationale:
  --extend is suggested because lines 25-40 fall within the existing
  block 20-50. This likely means you're adding detail to an existing section.
```

**Requires `--aligned-with`:** The command refuses to add blocks without explicit alignment to prevent orphaned code.

### `alignment-map block-touch`

Update an existing block's metadata with smart line detection.

```bash
alignment-map block-touch FILE --name NAME --comment COMMENT [--mapfile FILE]
```

**What it does:**
1. Finds the existing block by name
2. Uses AST parsing to detect if the code has moved (line drift)
3. Updates `last_updated` timestamp and comment
4. Adjusts line numbers automatically if drift is detected

### `alignment-map block-suggest`

Suggest block boundaries for unmapped code.

```bash
alignment-map block-suggest [FILE] [--json] [--mapfile FILE]
```

**What it does:**
1. Attempts AST parsing (Python only initially) to find classes/functions
2. If AST parsing fails, falls back to suggesting grep patterns
3. Outputs suggested line ranges — never guesses doc alignments

**Example output (AST success):**
```
Unmapped code in src/validate/checker.py:

  Lines 37-85: function check_file_change()
  Lines 109-160: function check_aligned_document()

To add these blocks, run:
  alignment-map block-add src/validate/checker.py --block "check_file_change" --lines 37-85 --aligned-with <DOC>
```

**Example output (AST fallback):**
```
Unable to parse src/validate/checker.py (unsupported language or syntax error)

Suggested grep patterns to find logical blocks:
  grep -n "^def \|^class " src/validate/checker.py
  grep -n "^async def " src/validate/checker.py

## TODO: Add AST support for this language
```

### `alignment-map trace`

Print all context needed to review a file or specific line. Designed for LLM consumption — outputs everything inline so no searching is required.

```bash
alignment-map trace FILE[:LINE] [--json] [--mapfile FILE]
```

**Example:**
```bash
alignment-map trace src/validate/checker.py:45
```

**Outputs:**
1. The code block containing line 45
2. All aligned docs with their relevant sections printed inline
3. The full hierarchy up to identity
4. Current timestamps and staleness status
5. Specific instructions for what to review

This gives an LLM complete context in one command.

### `alignment-map review`

Pre-flight check showing what docs would need review if you modify a file.

```bash
alignment-map review FILE [--json] [--mapfile FILE]
```

**Outputs:**
1. All blocks in the file
2. Their aligned docs (with sections)
3. Current timestamps
4. What would need updating

Useful before starting work on a file.

### `alignment-map map-graph`

Visualize alignment relationships.

```bash
alignment-map map-graph [--format dot|ascii|json] [--mapfile FILE]
```

### `alignment-map hook-install`

Install the pre-commit git hook.

```bash
alignment-map hook-install [--mapfile FILE]
```

Creates `.git/hooks/pre-commit` that calls `alignment-map check --staged`.

---

## Error Messages

Error messages must be:
1. **Explicit** — Exact file paths and line numbers
2. **Actionable** — Tell exactly what to do
3. **Contextual** — Print relevant document sections

### Example: Unmapped File

```
ALIGNMENT CHECK FAILED

✗ Unmapped file: src/validate/validators/jira/new_validator.py

This file has no entry in .alignment-map.yaml

To add it, run:
  alignment-map block-add src/validate/validators/jira/new_validator.py --block "<name>" --lines 1-<end> --aligned-with <DOC>

Or manually add to .alignment-map.yaml:

  - file: src/validate/validators/jira/new_validator.py
    blocks:
      - name: <describe the block>
        lines: 1-<end line>
        last_updated: 2024-01-16T09:00:00Z
        last_update_comment: "Initial implementation"
        aligned_with:
          - docs/ARCHITECTURE.md#validators
```

### Example: Unmapped Lines

```
ALIGNMENT CHECK FAILED

✗ Unmapped lines in: src/validate/validators/base.py

  Lines 90-105 are not in any mapped block.

  Nearest block: "BaseValidator class" (lines 15-89)

To fix, either:
  • Extend the existing block: lines: 15-105
  • Add a new block for lines 90-105

Then update last_updated and last_update_comment.
```

### Example: Map Not Updated

```
ALIGNMENT CHECK FAILED

✗ Block not updated: src/validate/validators/base.py "validate method"

  You modified lines 45-67 but didn't update the alignment map.

Current entry:
  last_updated: 2024-01-14T09:00:00
  last_update_comment: "Initial implementation"

Update to:
  last_updated: 2024-01-16T09:00:00Z
  last_update_comment: "<describe your change>"
```

### Example: Stale Technical Doc

```
ALIGNMENT CHECK FAILED

✗ Stale document requires review

  Modified: src/validate/validators/base.py:45-67
  Block: "validate method"

  Aligned document needs review:
    docs/DESIGN_PRINCIPLES.md#3-rich-self-contained-problem-objects
    last_reviewed: 2024-01-10T00:00:00
    code last_updated: 2024-01-16T09:00:00

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
docs/DESIGN_PRINCIPLES.md — Section: #3-rich-self-contained-problem-objects
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 3. Rich, Self-Contained Problem Objects

**Principle:** Validators return rich objects (e.g., `FieldMissingFromCreateScreen`)
containing all specific IDs and data needed to understand the issue. They are not
just error strings or codes.

**Rationale:** Remediators should not have to re-discover data. By packaging the
field ID, screen ID, project key, and relevant URLs into the problem object, the
remediator has everything needed to act immediately.

**Upholds:**
- [Actionability](./IDENTITY.md#actionability)
- [Philosophy: Stateless and Deterministic](./IDENTITY.md#stateless-and-deterministic)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

To proceed:
  • Review the above section
  • If changes are needed, update the document
  • Update last_reviewed in the document's frontmatter:

    ---
    last_reviewed: 2024-01-16T09:00:00Z
    ---
```

### Example: Human Escalation Required

```
ALIGNMENT CHECK FAILED

⚠️  HUMAN REVIEW REQUIRED

  Modified: src/validate/validators/base.py:45-67
  Block: "validate method"

  This change affects a document requiring human review:
    docs/IDENTITY.md#actionability
    last_reviewed: 2024-01-05T00:00:00

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
docs/IDENTITY.md — Section: #actionability
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Actionability
Problems must include everything needed to fix them. A validator should never
report "something is wrong" — it should report exactly what, where, and provide
all information required to fix it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This document cannot be modified without human approval.

To proceed:
  • Have a human review this change
  • Human updates last_reviewed in docs/IDENTITY.md
  • Or human approves skip in commit message:
    git commit -m "... [human-reviewed: identity alignment verified]"
```

---

## Fuzzy Line Matching

When validating or updating line numbers, the tool should:

1. Parse the file for named symbols (classes, functions)
2. Match block names to symbols using fuzzy matching
3. Allow configurable tolerance (default: ±10 lines)

```yaml
# .alignment-map.yaml
settings:
  line_tolerance: 10  # Lines can shift by this much before warning
  fuzzy_match: true   # Match block names to code symbols
```

---

## Installation

### Development Install (Auto-installs Hook)

```bash
# Install with dev dependencies - hook is auto-installed
pip install -e ".[dev]"

# The hook is automatically installed when running setup.py develop
python setup.py develop
```

### Manual Hook Installation

```bash
# Install the pre-commit hook manually
alignment-map hook-install [--mapfile FILE]

# This creates .git/hooks/pre-commit that calls alignment-map check --staged
# If --mapfile is specified, the hook will use that path for the alignment map
```

### Manual Check

```bash
# Check before committing
alignment-map check --staged

# Check entire project
alignment-map check --all
```

---

## Configuration

### `.alignment-map.yaml` Settings Section

```yaml
settings:
  # Line number tolerance for fuzzy matching
  line_tolerance: 10

  # Enable fuzzy matching of block names to code symbols
  fuzzy_match: true

  # Files to ignore (globs) - exempt from alignment mapping
  ignore:
    - "**/*.test.py"
    - "**/fixtures/**"

  # Also skip files matching .gitignore patterns (default: true)
  respect_gitignore: true

  # Require all code files to be mapped
  require_complete_coverage: true

  # Custom escalation message
  escalation_message: "Tag @tech-lead in PR for review"
```

| Setting | Default | Description |
|---------|---------|-------------|
| `line_tolerance` | `10` | Lines can shift by this much before warning |
| `fuzzy_match` | `true` | Match block names to code symbols |
| `ignore` | `[]` | Glob patterns for files exempt from alignment mapping |
| `respect_gitignore` | `true` | Also skip files matching .gitignore patterns |
| `require_complete_coverage` | `false` | Require all code files to be mapped |

---

## Integration with CI/CD

```yaml
# .github/workflows/alignment-check.yml
name: Alignment Check

on: [push, pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install alignment-map
        run: pip install alignment-map
      - name: Check alignment
        run: alignment-map check --all
      - name: Validate map
        run: alignment-map validate
```

---

## Future Enhancements

1. **IDE integration** — Show alignment relationships in editor
2. **Auto-update timestamps** — Option to auto-update `last_updated` on save
3. **Diff-aware printing** — Only print the parts of sections that seem relevant to the change
4. **AI-assisted review** — Suggest whether doc updates are needed based on change analysis
5. **Metrics** — Track alignment coverage, review frequency, staleness

---

## Philosophy

This tool embodies the principle that **coherency requires enforcement**. Comments suggesting review get ignored. Blocking commits with printed context guarantees the information is seen.

The goal is not to slow down development, but to ensure that every change is made with full awareness of its context and implications. The small overhead of updating timestamps and reviewing printed sections pays dividends in reduced drift and improved understanding.

---

*This specification should trace back to the project's [Identity](../../docs/IDENTITY.md) principles of documentation as first-class and explicit over magic.*
