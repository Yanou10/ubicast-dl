"""Permet `python -m ubicast_dl`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
