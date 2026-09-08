"""Locate and load the bundled CLI guide documents."""

import sys
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

GUIDE_STEMS = {
    "config": "ecc-cli-config",
    "ug": "ecc-cli-ug",
    "tutorial": "ecc-cli-tutorial",
    "dev": "ecc-cli-dev",
}


class GuideNotFoundError(FileNotFoundError):
    pass


def guides_root() -> Traversable:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "docs"
    return resources.files("chipcompiler") / "docs"


def load_guide(topic: str, lang: str) -> bytes:
    name = f"{GUIDE_STEMS[topic]}.{lang}.md"
    path = guides_root() / name
    if not path.is_file():
        raise GuideNotFoundError(f"doc resource not found: {name}")
    return path.read_bytes()
