"""Compatibility entry point for pycmkr CLI."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    root = Path(__file__).resolve().parent
    src_path = root / "src"
    if src_path.is_dir():
        sys.path.insert(0, str(src_path))


_ensure_src_on_path()

from pycmkr.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
