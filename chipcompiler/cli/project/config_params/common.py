from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigTarget:
    config_key: str
    json_path: tuple[str, ...]


@dataclass(frozen=True)
class ParamSchema:
    param: str
    group: str
    name: str
    type: str
    default: object
    applies: str
    description: str
    maps_to: str | dict | None = None
    config_target: ConfigTarget | None = None
    pdk_target: str | None = None
    range: tuple[float, float] | None = None
    choices: tuple[str, ...] | None = None
    unit: str | None = None
    example: str | None = None


_CONFIG_KEYS = {
    "cts": "CTS",
    "floorplan": "Floorplan",
    "routing": "route",
    "rcx": "RCX",
}


def config_param(
    param: str,
    config_key: str,
    json_path: tuple[str, ...],
    default: object,
    *,
    applies: str,
    description: str,
    type: str | None = None,
    range: tuple[float, float] | None = None,
    choices: tuple[str, ...] | None = None,
) -> ParamSchema:
    if type is None:
        type = _infer_type(default)
    group, _, name = param.rpartition(".")
    return ParamSchema(
        param=param,
        group=group.split(".", 1)[0],
        name=name,
        type=type,
        default=default,
        applies=applies,
        description=description,
        config_target=ConfigTarget(
            config_key=_CONFIG_KEYS.get(config_key, config_key),
            json_path=json_path,
        ),
        range=range,
        choices=choices,
    )


def _infer_type(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "list[str]"
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        return "list[int]"
    if isinstance(value, list) and all(isinstance(item, (int, float)) for item in value):
        return "list[float]"
    return "json"
