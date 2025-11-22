"""Setup script to enable custom develop command for hook installation."""

import sys
from pathlib import Path

# Add src to path for imports during build
sys.path.insert(0, str(Path(__file__).parent / "src"))

from setuptools import setup

from alignment_map._install import DevelopCommand

setup(
    cmdclass={
        "develop": DevelopCommand,
    },
)

