"""Locate, slice, and load the bundled CLI guide documents."""

import re
import sys
from pathlib import Path

GUIDE_STEMS = {
    "config": "ecc-cli-config",
    "ug": "ecc-cli-ug",
    "tutorial": "ecc-cli-tutorial",
    "dev": "ecc-cli-dev",
}

_NUMBERED_HEADING = re.compile(r"^## (?P<token>\d+(?:\.\d+)*)\.", re.MULTILINE)
_ANY_HEADING = re.compile(r"^## ", re.MULTILINE)


class GuideNotFoundError(FileNotFoundError):
    pass


class SectionNotFoundError(LookupError):
    pass


def guides_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "docs"
    import chipcompiler

    return Path(chipcompiler.__file__).resolve().parent.parent / "docs"


def load_guide(topic: str, lang: str) -> bytes:
    name = f"{GUIDE_STEMS[topic]}.{lang}.md"
    path = guides_root() / name
    if not path.is_file():
        raise GuideNotFoundError(f"doc resource not found: {name}")
    return path.read_bytes()


def heading_tokens(text: str) -> list[str]:
    return [match.group("token") for match in _NUMBERED_HEADING.finditer(text)]


def slice_section(text: str, token: str) -> str:
    for match in _NUMBERED_HEADING.finditer(text):
        if match.group("token") != token:
            continue
        start = match.start()
        next_match = _ANY_HEADING.search(text, match.end())
        end = next_match.start() if next_match else len(text)
        return text[start:end]
    available = " ".join(heading_tokens(text))
    raise SectionNotFoundError(f"no section {token}; available sections: {available}")
