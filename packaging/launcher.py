"""PyInstaller entry point (absolute import so the frozen app runs the package normally)."""

import sys

from workagent.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
