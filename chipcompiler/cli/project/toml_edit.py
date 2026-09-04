"""Text-level ecc.toml editing shared by the param and pdk handlers.

Edits preserve the surrounding file layout (comments, ordering, indentation)
so repeated `param set`/`pdk set-root` calls do not churn the config file.
"""

import re

_TABLE_HEADER_RE = re.compile(r"^[ \t]*\[([^\]]+)\][ \t]*(?:#.*)?$", re.MULTILINE)


def find_table_span(text: str, table_name: str) -> tuple[int, int] | None:
    """Return (body_start, body_end) for a TOML table, or None."""
    for m in _TABLE_HEADER_RE.finditer(text):
        if m.group(1).strip() == table_name:
            header_end = m.end()
            nl = text.find("\n", header_end)
            body_start = len(text) if nl == -1 else nl + 1
            next_header = _TABLE_HEADER_RE.search(text, body_start)
            body_end = next_header.start() if next_header else len(text)
            return body_start, body_end
    return None


def _extend_multiline_value(text: str, match_end: int) -> int:
    """Extend match end past continuation lines for multiline TOML values.

    After matching `key = ...` on one line, consume subsequent lines if the
    value has unclosed brackets (arrays or inline tables).
    """
    line_start = text.rfind("\n", 0, match_end) + 1
    matched_line = text[line_start:match_end]

    depth = 0
    eq_pos = matched_line.find("=")
    if eq_pos >= 0:
        for ch in matched_line[eq_pos + 1 :]:
            if ch in ("[", "{"):
                depth += 1
            elif ch in ("]", "}"):
                depth -= 1

    if depth <= 0:
        return match_end

    pos = match_end
    while pos < len(text) and depth > 0:
        ch = text[pos]
        if ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth -= 1
        pos += 1

    while pos < len(text) and text[pos] in (" ", "\t"):
        pos += 1
    if pos < len(text) and text[pos] == "\n":
        pos += 1

    return pos


def format_toml_value(val: object) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(val, (list, tuple)):
        items = ", ".join(format_toml_value(v) for v in val)
        return f"[{items}]"
    if isinstance(val, dict):
        items = ", ".join(f'"{key}" = {format_toml_value(value)}' for key, value in val.items())
        return f"{{{items}}}"
    return str(val)


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
    key_pattern = re.compile(rf"^(\s*){re.escape(name)}\s*=[^\n]*$", re.MULTILINE)
    key_match = key_pattern.search(section_body)

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
    key_pattern = re.compile(rf"^\s*{re.escape(name)}\s*=[^\n]*\n?", re.MULTILINE)
    key_match = key_pattern.search(section_body)
    if not key_match:
        return None

    end = _extend_multiline_value(section_body, key_match.end())
    # Consume trailing newline after multiline value
    if section_body[end : end + 1] == "\n":
        end += 1
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
    span = find_table_span(text, "pdk")
    if span is None:
        return text.rstrip("\n") + f'\n\n[pdk]\nroot = "{value}"\n'

    body_start, body_end = span
    section = text[body_start:body_end]
    key_pattern = re.compile(r"^(\s*)root\s*=[^\n]*$", re.MULTILINE)
    key_match = key_pattern.search(section)
    if key_match:
        new_section = (
            section[: key_match.start()]
            + f'{key_match.group(1)}root = "{value}"'
            + section[key_match.end() :]
        )
    else:
        new_section = f'root = "{value}"\n' + section
    return text[:body_start] + new_section + text[body_end:]
