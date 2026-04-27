"""Shared pytest fixtures for bridge_core tests.

Adds the repo root to sys.path so `shared.contracts` imports resolve
when pytest is invoked from either the repo root or bridge-core/."""
from __future__ import annotations

import sys
from pathlib import Path

THIS = Path(__file__).resolve()
REPO_ROOT = THIS.parent.parent.parent  # .../kj-bridgedeck
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
