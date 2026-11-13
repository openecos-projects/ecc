"""The ``req.json`` and ``rsp.json`` files in a step directory.

The flow writes a step's request to ``req.json`` before the step runs; the
step's worker writes its response to ``rsp.json`` when it finishes. Steps
exchange data through these two files rather than through the shared flow
ledger. Both are validated strictly on read and replaced atomically on write.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

from chipcompiler.data.handshake.messages import (
    DesignFiles,
    ResponseStatus,
    StepInputs,
    StepRequest,
    StepResponse,
    UpstreamResponse,
)
from chipcompiler.data.step import is_step_directory_name
from chipcompiler.data.types import AnalysisData, DesignData, DesignState, flow_step_policy
from chipcompiler.utility.file import write_text_atomic

REQ_FILE: Final = "req.json"
RSP_FILE: Final = "rsp.json"
SCHEMA_VERSION: Final = 1


class HandshakeError(ValueError):
    """A ``req.json`` or ``rsp.json`` that cannot be trusted."""


def write_request(request: StepRequest) -> Path:
    path = request.directory / REQ_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, _dumps(_request_json(request)))
    return path


def load_request(step_directory: Path) -> StepRequest:
    """The request in *step_directory*; a missing or invalid file raises."""
    data = _load(step_directory / REQ_FILE)
    if data is None:
        raise HandshakeError(f"{step_directory / REQ_FILE} is missing")
    return _request_from_json(data)


def write_response(step_directory: Path, response: StepResponse) -> Path:
    path = step_directory / RSP_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, _dumps(_response_json(response)))
    return path


def load_response(step_directory: Path) -> StepResponse | None:
    """The response in *step_directory*; None before the step has answered."""
    data = _load(step_directory / RSP_FILE)
    return None if data is None else _response_from_json(data)


def clear_response(step_directory: Path) -> None:
    """Remove a previous response so a crashed run cannot leave it behind."""
    (step_directory / RSP_FILE).unlink(missing_ok=True)


# --- JSON shape -------------------------------------------------------------


def _dumps(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2) + "\n"


def _load(path: Path) -> Mapping[str, object] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        parsed: object = json.loads(text)
    except ValueError as exc:
        raise HandshakeError(f"{path} is not valid JSON: {exc}") from None
    data = _table(parsed, str(path))
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise HandshakeError(f"{path} has unsupported schema_version {version!r}")
    return data


def _path_json(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _design_json(design: DesignFiles) -> dict[str, object]:
    return {
        "def": _path_json(design.def_),
        "verilog": _path_json(design.verilog),
        "db": _path_json(design.db),
    }


def _link_json(source: UpstreamResponse) -> dict[str, object]:
    return {"step_directory": source.step_directory, "attempt_id": source.attempt_id}


def _optional_link_json(source: UpstreamResponse | None) -> dict[str, object] | None:
    return None if source is None else _link_json(source)


def _upstream_json(upstream: Mapping[DesignData, UpstreamResponse]) -> dict[str, object]:
    return {str(item): _link_json(source) for item, source in sorted(upstream.items())}


def _request_json(request: StepRequest) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "workspace_directory": str(request.workspace_directory),
        "step": request.step,
        "tool": request.tool,
        "step_directory": request.step_directory,
        "attempt_id": request.attempt_id,
        "inputs": {
            "design": _design_json(request.inputs.design),
            "golden_verilog": _path_json(request.inputs.golden_verilog),
            "spef": [str(path) for path in request.inputs.spef],
        },
        "design_source": _optional_link_json(request.design_source),
        "upstream": _upstream_json(request.upstream),
        "final_step": request.final_step,
        "layout_image": request.layout_image,
    }


def _response_json(response: StepResponse) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "step": response.step,
        "tool": response.tool,
        "attempt_id": response.attempt_id,
        "status": str(response.status),
        "design": _design_json(response.design),
        "design_states": sorted(str(state) for state in response.design_states),
        "outputs": {
            str(item): [str(path) for path in paths]
            for item, paths in sorted(response.outputs.items())
        },
        "design_source": _optional_link_json(response.design_source),
        "upstream": _upstream_json(response.upstream),
        "warnings": sorted(str(item) for item in response.warnings),
    }


# --- strict readers ---------------------------------------------------------


def _field(data: Mapping[str, object], key: str) -> object:
    if key not in data:
        raise HandshakeError(f"missing field {key!r}")
    return data[key]


def _text(data: Mapping[str, object], key: str) -> str:
    value = _field(data, key)
    if not isinstance(value, str) or not value:
        raise HandshakeError(f"{key!r} must be a non-empty string")
    return value


def _flag(data: Mapping[str, object], key: str) -> bool:
    value = _field(data, key)
    if not isinstance(value, bool):
        raise HandshakeError(f"{key!r} must be true or false")
    return value


def _table(value: object, key: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise HandshakeError(f"{key!r} must be a JSON object")
    return cast("dict[str, object]", value)  # JSON object keys are always strings.


def _strings(value: object, key: str) -> list[str]:
    if not isinstance(value, list):
        raise HandshakeError(f"{key!r} must be a list of non-empty strings")
    items: list[str] = []
    for item in cast("list[object]", value):
        if not isinstance(item, str) or not item:
            raise HandshakeError(f"{key!r} must be a list of non-empty strings")
        items.append(item)
    return items


def _optional_path(data: Mapping[str, object], key: str) -> Path | None:
    value = _field(data, key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise HandshakeError(f"{key!r} must be a path or null")
    return Path(value)


def _step(data: Mapping[str, object]) -> str:
    step = _text(data, "step")
    try:
        flow_step_policy(step)
    except ValueError as exc:
        raise HandshakeError(str(exc)) from None
    return step


def _step_directory(data: Mapping[str, object]) -> str:
    name = _text(data, "step_directory")
    if not is_step_directory_name(name):
        raise HandshakeError(f"'step_directory' must be a single directory name: {name!r}")
    return name


def _design_data(name: str) -> DesignData:
    try:
        return DesignState(name)
    except ValueError:
        pass
    try:
        return AnalysisData(name)
    except ValueError:
        raise HandshakeError(f"unknown design data {name!r}") from None


def _design_files(value: object) -> DesignFiles:
    data = _table(value, "design")
    return DesignFiles(
        def_=_optional_path(data, "def"),
        verilog=_optional_path(data, "verilog"),
        db=_optional_path(data, "db"),
    )


def _link(value: object, key: str) -> UpstreamResponse:
    data = _table(value, key)
    attempt_id = _field(data, "attempt_id")
    if attempt_id is not None and (not isinstance(attempt_id, str) or not attempt_id):
        raise HandshakeError(f"'{key}.attempt_id' must be a non-empty string or null")
    return UpstreamResponse(step_directory=_step_directory(data), attempt_id=attempt_id)


def _optional_link(data: Mapping[str, object], key: str) -> UpstreamResponse | None:
    value = _field(data, key)
    return None if value is None else _link(value, key)


def _upstream(value: object) -> Mapping[DesignData, UpstreamResponse]:
    upstream = {
        _design_data(name): _link(source, f"upstream.{name}")
        for name, source in _table(value, "upstream").items()
    }
    return MappingProxyType(upstream)


def _request_from_json(data: Mapping[str, object]) -> StepRequest:
    workspace_directory = Path(_text(data, "workspace_directory"))
    if not workspace_directory.is_absolute():
        raise HandshakeError(f"'workspace_directory' must be absolute: {workspace_directory}")
    inputs = _table(_field(data, "inputs"), "inputs")
    return StepRequest(
        workspace_directory=workspace_directory,
        step=_step(data),
        tool=_text(data, "tool"),
        step_directory=_step_directory(data),
        attempt_id=_text(data, "attempt_id"),
        inputs=StepInputs(
            design=_design_files(_field(inputs, "design")),
            golden_verilog=_optional_path(inputs, "golden_verilog"),
            spef=tuple(Path(path) for path in _strings(_field(inputs, "spef"), "spef")),
        ),
        design_source=_optional_link(data, "design_source"),
        upstream=_upstream(_field(data, "upstream")),
        final_step=_flag(data, "final_step"),
        layout_image=_flag(data, "layout_image"),
    )


def _response_from_json(data: Mapping[str, object]) -> StepResponse:
    try:
        status = ResponseStatus(_text(data, "status"))
    except ValueError as exc:
        raise HandshakeError(f"invalid 'status': {exc}") from None
    states: set[DesignState] = set()
    for name in _strings(_field(data, "design_states"), "design_states"):
        state = _design_data(name)
        if not isinstance(state, DesignState):
            raise HandshakeError(f"{name!r} is analysis data, not a design state")
        states.add(state)
    outputs: dict[AnalysisData, tuple[Path, ...]] = {}
    for name, paths in _table(_field(data, "outputs"), "outputs").items():
        item = _design_data(name)
        if not isinstance(item, AnalysisData):
            raise HandshakeError(f"{name!r} is a design state, not analysis data")
        outputs[item] = tuple(Path(path) for path in _strings(paths, f"outputs.{name}"))
    return StepResponse(
        step=_step(data),
        tool=_text(data, "tool"),
        attempt_id=_text(data, "attempt_id"),
        status=status,
        design=_design_files(_field(data, "design")),
        design_states=frozenset(states),
        outputs=MappingProxyType(outputs),
        design_source=_optional_link(data, "design_source"),
        upstream=_upstream(_field(data, "upstream")),
        warnings=frozenset(
            _design_data(name) for name in _strings(_field(data, "warnings"), "warnings")
        ),
    )
