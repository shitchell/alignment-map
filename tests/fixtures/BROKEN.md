<!-- last_reviewed: 2019-01-01T00:00:00 -->
<!-- This file is intentionally broken for testing purposes -->

# Broken Documentation

This document has several intentional issues for testing the alignment-map tool.

## Broken Code

This section is supposed to align with `tests/fixtures/broken.py` but has an
intentionally old `last_reviewed` timestamp.

The alignment-map checker should:
1. Detect that this doc is stale
2. Print this section to the screen
3. Block the commit until `last_reviewed` is updated

## Nonexistent Reference

This section doesn't exist in the alignment map but is referenced.
This tests broken anchor detection.

## Missing Section

The alignment map might reference `#missing-section` which doesn't exist.
This tests the anchor extraction logic.

---

*This file exists solely for testing failure detection.*
