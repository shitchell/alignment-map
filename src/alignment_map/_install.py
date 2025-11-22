"""Custom install commands to auto-install git hook."""

import subprocess
import sys
from pathlib import Path

from setuptools.command.develop import develop  # type: ignore[import-untyped]


def install_git_hook() -> None:
    """Install the alignment-map git hook if in a git repo."""
    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return  # Not in a git repo

        # Run alignment-map hook-install
        subprocess.run(
            [sys.executable, "-m", "alignment_map.cli", "hook-install"],
            check=False,  # Don't fail install if hook fails
        )
        print("Alignment map git hook installed")
    except Exception as e:
        print(f"Warning: Could not install git hook: {e}")


class DevelopCommand(develop):  # type: ignore[misc]
    """Custom develop command that installs git hook."""

    def run(self) -> None:
        super().run()
        install_git_hook()
