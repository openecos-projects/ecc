"""Text-level ecc.toml editing shared by the param and pdk handlers.

Edits preserve the surrounding file layout (comments, ordering, indentation)
so repeated `param set`/`pdk set-root` calls do not churn the config file.
"""

import re

_TABLE_HEADER_RE = re.compile(r"^[ \t]*\[([^\]]+)\][ \t]*(?:#.*)?$", re.MULTILINE)


def _mask_strings_and_comments(text: str) -> str:
    """Return a same-length text with string and comment contents blanked.

    Table-header discovery must not mistake bracket text inside a multiline
    string for a real ``[table]`` header; masking preserves every index and
    newline so matches map back onto the original text.
    """
    chars = list(text)
    pos = 0
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch == "#":
            nl = text.find("\n", pos)
            end = n if nl == -1 else nl
            for i in range(pos, end):
                chars[i] = " "
            pos = end
            continue
        if ch in ('"', "'"):
            triple = text[pos : pos + 3]
            if triple in ('"""', "'''"):
                end = pos + 3
                while end < n:
                    if text.startswith(triple, end):
                        end += 3
                        break
                    end += 1
            else:
                end = pos + 1
                while end < n:
                    if ch == '"' and text.startswith("\\", end):
                        end += 2
                        continue
                    if text[end] == ch:
                        end += 1
                        break
                    end += 1
            for i in range(pos, min(end, n)):
                if chars[i] != "\n":
                    chars[i] = " "
            pos = max(end, pos + 1)
            continue
        pos += 1
    return "".join(chars)


def find_table_span(text: str, table_name: str) -> tuple[int, int] | None:
    """Return (body_start, body_end) for a TOML table, or None."""
    masked = _mask_strings_and_comments(text)
    for m in _TABLE_HEADER_RE.finditer(masked):
        if m.group(1).strip() == table_name:
            header_end = m.end()
            nl = text.find("\n", header_end)
            body_start = len(text) if nl == -1 else nl + 1
            next_header = _TABLE_HEADER_RE.search(masked, body_start)
            body_end = next_header.start() if next_header else len(text)
            return body_start, body_end
    return None


def _skip_string(segment: str, start: int) -> int:
    """Return the index just past the TOML string starting at segment[start]."""
    quote = segment[start]
    if segment[start : start + 3] in ('"""', "'''"):
        end = start + 3
        while end < len(segment):
            if quote == '"' and segment.startswith("\\", end):
                end += 2
                continue
            if segment.startswith(segment[start : start + 3], end):
                return end + 3
            end += 1
        return len(segment)
    end = start + 1
    while end < len(segment):
        if quote == '"' and segment[end] == "\\":
            end += 2
            continue
        if segment[end] == quote:
            return end + 1
        end += 1
    return len(segment)


def _toml_code_depth(segment: str) -> int:
    """Net []/{} depth of a TOML fragment, skipping strings and comments.

    Bracket characters inside quoted strings, triple-quoted strings, or
    comments are content, not structure: counting them would make a value
    like "alu[rev" look multiline and swallow following keys.
    """
    depth = 0
    i = 0
    while i < len(segment):
        ch = segment[i]
        if ch == "#":
            nl = segment.find("\n", i)
            if nl == -1:
                break
            i = nl + 1
        elif ch in ('"', "'"):
            i = _skip_string(segment, i)
        elif ch in "[{":
            depth += 1
            i += 1
        elif ch in "]}":
            depth -= 1
            i += 1
        else:
            i += 1
    return depth


def _extend_multiline_value(text: str, match_end: int) -> int:
    """Return the end of the (possibly multiline) TOML value at the match.

    A small tokenizer walks the value from its line start: multiline basic
    and literal strings (``\"\"\"...\"\"\"`` / ``'''...'''``), bracket
    collections, escapes, and comments each terminate the value correctly.
    The naive first-line match would leave the tail of a multiline string
    behind as unparsable text.
    """
    pos = text.rfind("\n", 0, match_end) + 1
    n = len(text)
    depth = 0
    state = None  # None, or the opening quote: '"' | "'" | '"""' | "'''"
    while pos < n:
        ch = text[pos]
        if state in ('"', "'"):
            if ch == "\\" and state == '"':
                pos += 2
                continue
            if ch == state:
                state = None
            pos += 1
            continue
        if state in ('"""', "'''"):
            if text.startswith(state, pos):
                state = None
                pos += 3
            else:
                pos += 1
            continue
        if ch == "#":
            # A comment ends the value only at the top level; inside a
            # bracket collection it decorates the line and the collection
            # continues on the next line.
            if depth <= 0:
                nl = text.find("\n", pos)
                if nl == -1:
                    return n
                return nl + 1
            nl = text.find("\n", pos)
            if nl == -1:
                return n
            pos = nl + 1
            continue
        if ch in ('"', "'"):
            triple = text[pos : pos + 3]
            if triple in ('"""', "'''"):
                state = triple
                pos += 3
            else:
                state = ch
                pos += 1
            continue
        if ch == "\n" and depth <= 0:
            # Inside a bracket collection a line break is insignificant; at
            # the top level the value ends with this physical line.
            return pos + 1
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        pos += 1
    return n


_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def format_toml_value(val: object) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        out = []
        for ch in val:
            escaped = _ESCAPES.get(ch)
            if escaped:
                out.append(escaped)
            elif ord(ch) < 0x20 or ch == "\x7f":
                out.append(f"\\u{ord(ch):04X}")
            else:
                out.append(ch)
        return f'"{"".join(out)}"'
    if isinstance(val, (list, tuple)):
        items = ", ".join(format_toml_value(v) for v in val)
        return f"[{items}]"
    if isinstance(val, dict):
        items = ", ".join(
            f"{format_toml_value(str(key))} = {format_toml_value(value)}"
            for key, value in val.items()
        )
        return f"{{{items}}}"
    raise ValueError(f"value has no TOML representation: {val!r}")


# TODO: Move ecc.toml parameter editing into chipcompiler.data.project_config_edit
# or the future EccTomlConfig owner. CLI should only call the edit operation and
# translate its result into command records.
def set_scoped_key(text: str, target_table: str, name: str, value: object) -> str:
    value_str = format_toml_value(value)

    span = find_table_span(text, target_table)
    if span is None:
        params_span = find_table_span(text, "params")
        if params_span is None:
            return text.rstrip() + f"\n\n[{target_table}]\n{name} = {value_str}\n"
        body_start, body_end = params_span
        insert = f"\n\n[{target_table}]\n{name} = {value_str}"
        next_header = _TABLE_HEADER_RE.search(text, body_start)
        if next_header:
            pos = next_header.start()
            return text[:pos] + insert + "\n" + text[pos:]
        return text + insert + "\n"

    body_start, body_end = span
    section_body = text[body_start:body_end]
    # Match assignments on the masked body: key-like text inside a multiline
    # string must never be edited as if it were a real assignment.
    masked_body = _mask_strings_and_comments(section_body)
    key_pattern = re.compile(rf"^(\s*){re.escape(name)}\s*=[^\n]*$", re.MULTILINE)
    key_match = key_pattern.search(masked_body)

    if key_match:
        indent = key_match.group(1)
        end = _extend_multiline_value(section_body, key_match.end())
        new_line = f"{indent}{name} = {value_str}"
        if end > key_match.end():
            new_line += "\n"
        new_body = section_body[: key_match.start()] + new_line + section_body[end:]
        return text[:body_start] + new_body + text[body_end:]
    else:
        insert = f"{name} = {value_str}\n"
        return text[:body_start] + insert + text[body_start:]


def remove_scoped_key(text: str, target_table: str, name: str) -> str | None:
    span = find_table_span(text, target_table)
    if span is None:
        return None

    body_start, body_end = span
    section_body = text[body_start:body_end]
    # Match only the value's first line; _extend_multiline_value walks to the
    # true end of a multiline value, including its terminating newline.
    # Assignments are located on the masked body (see set_scoped_key).
    masked_body = _mask_strings_and_comments(section_body)
    key_pattern = re.compile(rf"^\s*{re.escape(name)}\s*=[^\n]*$", re.MULTILINE)
    key_match = key_pattern.search(masked_body)
    if not key_match:
        return None

    end = _extend_multiline_value(section_body, key_match.end())
    new_body = section_body[: key_match.start()] + section_body[end:]
    remaining_keys = [line for line in new_body.strip().split("\n") if line.strip()]
    if not remaining_keys:
        header_match = None
        for m in _TABLE_HEADER_RE.finditer(text):
            if m.group(1).strip() == target_table:
                header_match = m
                break
        if header_match is None:
            return None
        header_start = header_match.start()
        result = text[:header_start].rstrip("\n") + "\n" + text[body_end:].lstrip("\n")
        return result if result.strip() else None
    else:
        return text[:body_start] + new_body + text[body_end:]


def set_pdk_root(text: str, value: str) -> str:
    """Set `root = "<value>"` under the existing [pdk] table, preserving layout."""
    value_str = format_toml_value(value)
    span = find_table_span(text, "pdk")
    if span is None:
        return text.rstrip("\n") + f"\n\n[pdk]\nroot = {value_str}\n"

    body_start, body_end = span
    section = text[body_start:body_end]
    masked_section = _mask_strings_and_comments(section)
    key_pattern = re.compile(r"^(\s*)root\s*=[^\n]*$", re.MULTILINE)
    key_match = key_pattern.search(masked_section)
    if key_match:
        # Same value-range logic as set_scoped_key: a multiline value must
        # be replaced whole, never leaving its tail behind.
        end = _extend_multiline_value(section, key_match.end())
        indent = key_match.group(1)
        new_line = f"{indent}root = {value_str}"
        if end > key_match.end():
            new_line += "\n"
        new_section = section[: key_match.start()] + new_line + section[end:]
    else:
        new_section = f"root = {value_str}\n" + section
    return text[:body_start] + new_section + text[body_end:]
