from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExtractionResult:
    workspace_dir: Path
    foundation_dir: Path
    profile: str
    manifest: dict[str, Any]
    summary: dict[str, Any]
