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

_NUMBERED_HEADING = re.compile(r"^## (?P<token>\d+(?:\.\d+)*)\.[ \t]*(?P<title>.*)$", re.MULTILINE)
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


def heading_entries(text: str) -> list[tuple[str, str]]:
    return [
        (match.group("token"), match.group("title").strip())
        for match in _NUMBERED_HEADING.finditer(text)
    ]


def heading_tokens(text: str) -> list[str]:
    return [token for token, _ in heading_entries(text)]


def table_of_contents(text: str) -> str:
    entries = heading_entries(text)
    width = max(len(token) for token, _ in entries)
    return "".join(f"  {token:<{width}}  {title}\n" for token, title in entries)


def slice_section(text: str, token: str) -> str:
    for match in _NUMBERED_HEADING.finditer(text):
        if match.group("token") != token:
            continue
        start = match.start()
        next_match = _ANY_HEADING.search(text, match.end())
        end = next_match.start() if next_match else len(text)
        return text[start:end]
    entries = heading_entries(text)
    width = max(len(token) for token, _ in entries)
    listing = "\n".join(f"  {token:<{width}}  {title}" for token, title in entries)
    raise SectionNotFoundError(f"no section {token}; available sections:\n{listing}")
