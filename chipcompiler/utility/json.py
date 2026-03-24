#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import json
import os


def json_read(file_path: str) -> dict:
    """
    Read a JSON file and return its content as a dictionary.
    """
    data = {}
    if os.path.isfile(file_path) is False:
        return data

    try:
        if file_path.endswith('.gz'):
            import gzip
            with gzip.open(file_path, 'rt') as f:
                data = json.load(f)
        else:
            with open(file_path, 'r') as f:
                data = json.load(f)
    except Exception as e:
        return data

    return data


def json_write(file_path: str, data: dict = {}, indent=4) -> bool:
    """
    Write a dictionary to a JSON file.
    """
    try:
        if file_path.endswith('.gz'):
            import gzip
            with gzip.open(file_path, 'wt') as f:
                json.dump(data, f, indent=indent)
        else:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=indent)
        return True
    except Exception as e:
        return False

def dict_to_str(d, indent=0):
    """
    Render nested dictionaries as ASCII tables for log output.

    - Scalar values and simple lists are rendered as a two-column key/value table.
    - Nested dictionaries become titled sections.
    - Lists of dictionaries become row tables with an index column.
    """
    def _render_dict_block(mapping: dict, lines: list[str], base_indent: int, depth: int,
                           title: str | None, is_root: bool = False) -> None:
        current_indent = base_indent + depth
    
        if title is not None:
            if lines and lines[-1] != '':
                lines.append('')
            lines.append(f"{'  ' * current_indent}[{title}]")
    
        pending_rows = []
        child_depth = depth if is_root else depth + 1
    
        for key, value in mapping.items():
            if isinstance(value, dict):
                _flush_key_value_rows(lines, pending_rows, current_indent)
                _render_dict_block(
                    value,
                    lines,
                    base_indent=base_indent,
                    depth=child_depth,
                    title=str(key),
                    is_root=False,
                )
                continue
    
            if isinstance(value, list) and not _is_inline_list(value):
                _flush_key_value_rows(lines, pending_rows, current_indent)
                _render_list_block(
                    value,
                    lines,
                    base_indent=base_indent,
                    depth=child_depth,
                    title=str(key),
                )
                continue
    
            pending_rows.append([str(key), _format_inline_value(value)])
    
        _flush_key_value_rows(lines, pending_rows, current_indent)
    
    
    def _render_list_block(values: list, lines: list[str], base_indent: int, depth: int,
                           title: str) -> None:
        current_indent = base_indent + depth
    
        if lines and lines[-1] != '':
            lines.append('')
        lines.append(f"{'  ' * current_indent}[{title}]")
    
        if not values:
            _append_table(lines, _build_table(['#', 'Value'], [['-', '[]']], current_indent))
            return
    
        if all(isinstance(item, dict) for item in values):
            headers = _collect_headers(values)
            rows = []
            for index, item in enumerate(values, start=1):
                rows.append([str(index)] + [_format_inline_value(item.get(header, '')) for header in headers])
            _append_table(lines, _build_table(['#'] + headers, rows, current_indent))
            return
    
        rows = [[str(index), _format_inline_value(item)] for index, item in enumerate(values, start=1)]
        _append_table(lines, _build_table(['#', 'Value'], rows, current_indent))
    
    
    def _flush_key_value_rows(lines: list[str], rows: list[list[str]], indent: int) -> None:
        if not rows:
            return
    
        _append_table(lines, _build_table(['Key', 'Value'], rows, indent))
        rows.clear()
    
    
    def _append_table(lines: list[str], table_lines: list[str]) -> None:
        if not table_lines:
            return
    
        if lines and lines[-1] != '' and not lines[-1].lstrip().startswith('['):
            lines.append('')
        lines.extend(table_lines)
    
    
    def _build_table(headers: list[str], rows: list[list[str]], indent: int) -> list[str]:
        string_rows = [[_normalize_cell(cell) for cell in row] for row in rows]
        widths = [len(str(header)) for header in headers]
    
        for row in string_rows:
            for index, cell in enumerate(row):
                widths[index] = max(widths[index], len(cell))
    
        prefix = '  ' * indent
        border = prefix + '+-' + '-+-'.join('-' * width for width in widths) + '-+'
        header_line = prefix + '| ' + ' | '.join(str(header).ljust(widths[index]) for index, header in enumerate(headers)) + ' |'
    
        table_lines = [border, header_line, border]
        for row in string_rows:
            table_lines.append(prefix + '| ' + ' | '.join(cell.ljust(widths[index]) for index, cell in enumerate(row)) + ' |')
        table_lines.append(border)
        return table_lines
    
    
    def _collect_headers(items: list[dict]) -> list[str]:
        headers = []
        seen = set()
        for item in items:
            for key in item.keys():
                key_str = str(key)
                if key_str not in seen:
                    seen.add(key_str)
                    headers.append(key_str)
        return headers
    
    
    def _is_inline_list(values: list) -> bool:
        return all(not isinstance(item, (dict, list)) for item in values)
    
    
    def _format_inline_value(value) -> str:
        if value is None:
            return ''
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            formatted_items = []
            for item in value:
                if isinstance(item, (dict, list)):
                    formatted_items.append(json.dumps(item, ensure_ascii=False, sort_keys=False))
                else:
                    formatted_items.append(_format_inline_value(item))
            return '[' + ', '.join(formatted_items) + ']'
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, sort_keys=False)
        return str(value)
    
    
    def _normalize_cell(value) -> str:
        return str(value).replace('\n', '\\n')
    
    if not isinstance(d, dict):
        return _format_inline_value(d)

    lines = []
    _render_dict_block(d, lines, base_indent=indent, depth=0, title=None, is_root=True)
    return '\n'.join(lines)
