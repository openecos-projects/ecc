from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

ValueTransform = Callable[[object], object]


def flag_to_int(value: object) -> int:
    """Coerce a boolean-like flag (``True``, ``"on"``, ``"0"``...) to 0 or 1."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on"}:
            return 1
        if normalized in {"false", "no", "off", ""}:
            return 0
        try:
            return int(float(normalized))
        except ValueError:
            return 1
    return int(bool(value))


@dataclass(frozen=True)
class ConfigTarget:
    """One destination of a parameter inside a managed tool config JSON.

    ``to_config``/``to_parameter`` translate between the parameter value and
    the value stored in the config. ``element`` marks a target that carries
    one element of a list-valued parameter, so a ``[horizontal, vertical]``
    margin can fan out into per-side scalars and be read back as a list.
    """

    config_key: str
    json_path: tuple[str, ...]
    to_config: ValueTransform | None = None
    to_parameter: ValueTransform | None = None
    element: int | None = None

    def render(self, value: object) -> object:
        """The config value this target stores for a parameter *value*."""
        if self.element is not None:
            if (
                not isinstance(value, Sequence)
                or isinstance(value, str | bytes)
                or len(value) <= self.element
            ):
                raise ValueError(
                    f"{self.config_key}.{'.'.join(self.json_path)} needs element "
                    f"{self.element} of a list value, got {value!r}"
                )
            value = value[self.element]
        return self.to_config(value) if self.to_config is not None else value

    def parse(self, config_value: object) -> object:
        """The parameter value (or element) a stored config value represents."""
        return self.to_parameter(config_value) if self.to_parameter is not None else config_value


@dataclass(frozen=True)
class PdkVariant:
    """Default and allowed choices of a parameter for one PDK family."""

    default: object
    choices: tuple[str, ...] | None = None


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
    range: tuple[float, float | None] | None = None
    choices: tuple[str, ...] | None = None
    unit: str | None = None
    example: str | None = None
    output_only: bool = False
    # Further destinations of the same value; only valid beside ``config_target``.
    extra_config_targets: tuple[ConfigTarget, ...] = ()
    # Per-PDK-family overrides of ``default`` and ``choices`` (keys lower-case).
    pdk_variants: Mapping[str, PdkVariant] = field(default_factory=dict)
    # Fork the PDK-effective default out to every config target at each refresh,
    # for parameters whose shipped tool template is empty or ICS55-only.
    fork: bool = False

    @property
    def has_direct_target(self) -> bool:
        """Whether the value lives only in a tool config (or PDK), with no workspace default.

        Stored (``maps_to``) and forked parameters always have an effective
        workspace value; only explicit direct parameters are worth listing.
        """
        direct_config = self.config_target is not None and self.maps_to is None and not self.fork
        return direct_config or self.pdk_target is not None

    @property
    def config_targets(self) -> tuple[ConfigTarget, ...]:
        """Every config destination, the primary target first."""
        if self.config_target is None:
            return ()
        return (self.config_target, *self.extra_config_targets)

    def default_for(self, pdk: str | None) -> object:
        variant = self._variant(pdk)
        return self.default if variant is None else variant.default

    def choices_for(self, pdk: str | None) -> tuple[str, ...] | None:
        variant = self._variant(pdk)
        return self.choices if variant is None or variant.choices is None else variant.choices

    def _variant(self, pdk: str | None) -> PdkVariant | None:
        return self.pdk_variants.get(pdk.lower()) if pdk else None


def config_param(
    param: str,
    config_key: str,
    json_path: tuple[str, ...],
    default: object,
    *,
    applies: str,
    description: str,
    type: str | None = None,
    range: tuple[float, float | None] | None = None,
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
            config_key=config_key,
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
