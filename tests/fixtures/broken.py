"""Intentionally broken code for testing alignment-map.

This file has several intentional issues:
1. It's mapped with a very old last_updated (2020-01-01)
2. Its aligned doc (BROKEN.md) has even older last_reviewed (2019-01-01)
3. Some code below is intentionally outside mapped blocks

The alignment-map checker should detect these issues and fail appropriately.
"""


class BrokenClass:
    """A class with intentionally stale alignment."""

    def __init__(self) -> None:
        """Initialize the broken class."""
        self.broken = True
        self.reason = "Testing alignment-map failure detection"

    def break_things(self) -> str:
        """Return a message about being broken."""
        return f"I am broken: {self.reason}"

    def get_status(self) -> bool:
        """Get the broken status."""
        return self.broken


# This code is outside the mapped block (lines 1-30)
# It should trigger an UNMAPPED_LINES failure when changed

class UnmappedClass:
    """This class is not in any mapped block."""

    def __init__(self) -> None:
        """Initialize unmapped class."""
        self.mapped = False

    def do_unmapped_things(self) -> None:
        """Do things that aren't tracked."""
        print("I'm not being tracked!")


def unmapped_function() -> str:
    """A function that's not in the alignment map.

    Changing this should trigger an unmapped lines error.
    """
    return "unmapped"
