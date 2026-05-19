import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class WorkspaceCreateRequest:
    directory: str = ""
    pdk: str = ""
    pdk_root: str = ""
    parameters: dict = field(default_factory=dict)
    origin_def: str = ""
    origin_verilog: str = ""
    filelist: str = ""
    rtl_list: list[str] = field(default_factory=list)


def create_request_from_json(path: str) -> WorkspaceCreateRequest:
    data = _read_json_object(path)
    _resolve_request_paths(data, _input_json_base_dir(path))
    return WorkspaceCreateRequest(
        directory=data.get("directory", ""),
        pdk=data.get("pdk", ""),
        pdk_root=data.get("pdk_root", ""),
        parameters=data.get("parameters", {}),
        origin_def=data.get("origin_def", ""),
        origin_verilog=data.get("origin_verilog", ""),
        filelist=data.get("filelist", ""),
        rtl_list=_normalize_rtl_list(data.get("rtl_list", [])),
    )


def create_request_from_flags(
    directory: str | None = None,
    pdk: str | None = None,
    pdk_root: str | None = None,
    origin_def: str | None = None,
    origin_verilog: str | None = None,
    filelist: str | None = None,
    rtl: Sequence[str] | None = None,
    param_json: str | None = None,
) -> WorkspaceCreateRequest:
    parameters = {}
    if param_json:
        parameters = _read_json_object(param_json)

    return WorkspaceCreateRequest(
        directory=directory or "",
        pdk=pdk or "",
        pdk_root=pdk_root or "",
        parameters=parameters,
        origin_def=origin_def or "",
        origin_verilog=origin_verilog or "",
        filelist=filelist or "",
        rtl_list=_resolve_rtl_flags(rtl or []),
    )


def create_request(
    input_json: str | None = None,
    directory: str | None = None,
    pdk: str | None = None,
    pdk_root: str | None = None,
    origin_def: str | None = None,
    origin_verilog: str | None = None,
    filelist: str | None = None,
    rtl: Sequence[str] | None = None,
    param_json: str | None = None,
) -> WorkspaceCreateRequest:
    field_flags = [
        directory,
        pdk,
        pdk_root,
        origin_def,
        origin_verilog,
        filelist,
        rtl,
        param_json,
    ]
    if input_json is not None and any(bool(flag) for flag in field_flags):
        raise InputError("--input-json and field flags are mutually exclusive")
    if input_json is not None:
        return create_request_from_json(input_json)
    return create_request_from_flags(
        directory=directory,
        pdk=pdk,
        pdk_root=pdk_root,
        origin_def=origin_def,
        origin_verilog=origin_verilog,
        filelist=filelist,
        rtl=rtl,
        param_json=param_json,
    )


def missing_fields(data: dict, fields: Sequence[str]) -> list[str]:
    return [field for field in fields if not str(data.get(field, "")).strip()]


def normalize_rtl_list(rtl_list) -> list[str]:
    return _normalize_rtl_list(rtl_list)


def write_filelist(directory: str, rtl_paths: list[str]) -> str:
    os.makedirs(directory, exist_ok=True)
    filelist_path = os.path.join(directory, "filelist")
    with open(filelist_path, "w", encoding="utf-8") as f:
        for path in rtl_paths:
            if any(ch.isspace() for ch in path):
                f.write(f'"{path}"\n')
            else:
                f.write(f"{path}\n")
    return filelist_path


def _read_json_object(path: str) -> dict:
    try:
        if path == "-":
            raw = sys.stdin.read()
        else:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
    except OSError as exc:
        raise InputError(f"unreadable JSON file: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON input: {exc}") from exc

    if not isinstance(data, dict):
        raise InputError("JSON input must be an object")
    return data


def _normalize_rtl_list(rtl_list) -> list[str]:
    if not rtl_list:
        return []
    if isinstance(rtl_list, list):
        items = rtl_list
    elif isinstance(rtl_list, str):
        items = rtl_list.splitlines()
    else:
        items = [rtl_list]

    result = []
    seen = set()
    for item in items:
        path = str(item).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _resolve_rtl_flags(rtl_paths: Sequence[str]) -> list[str]:
    result = []
    for path in rtl_paths:
        expanded = os.path.expandvars(os.path.expanduser(str(path)))
        result.append(os.path.abspath(expanded))
    return result


def _resolve_request_path(path: str, base_dir: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(str(path)))
    if not expanded:
        return ""
    if os.path.isabs(expanded):
        return expanded
    return os.path.abspath(os.path.join(base_dir, expanded))


def _resolve_request_paths(data: dict, base_dir: str) -> None:
    for field_name in ("origin_def", "origin_verilog", "filelist"):
        path = data.get(field_name)
        if path:
            data[field_name] = _resolve_request_path(path, base_dir)

    filelist = data.get("filelist")
    if filelist:
        return

    rtl_list = data.get("rtl_list")
    if not rtl_list:
        return
    data["rtl_list"] = [
        _resolve_request_path(path, base_dir)
        for path in _normalize_rtl_list(rtl_list)
    ]


def _input_json_base_dir(path: str) -> str:
    if path == "-":
        return os.getcwd()
    return os.path.dirname(os.path.abspath(os.path.expanduser(path)))


class InputError(Exception):
    def __init__(self, message: str, response: str = "error"):
        super().__init__(message)
        self.response = response
