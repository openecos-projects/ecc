from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from chipcompiler.data.types import SkippableStepEnum, StepEnum

ValueTransform = Callable[[object], object]

#: ``applies`` of a parameter that holds for the whole workspace.
WORKSPACE_WIDE: Final = "all"
#: ``applies`` of a parameter that selects PDK files rather than a step's config.
PDK_SCOPE: Final = "pdk"
#: Flow step names an ``applies`` list may use (canonical spellings only).
FLOW_STEP_NAMES: Final = frozenset(
    {
        step.value
        for step in StepEnum
        if step not in {StepEnum.RTL2GDS, StepEnum.INIT, StepEnum.FLOORPLAN}
    }
    | {step.value for step in SkippableStepEnum}
)


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
    # ``applies`` parsed once (declaration order); see :attr:`steps`.
    _steps: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        steps = (
            ()
            if self.applies in (WORKSPACE_WIDE, PDK_SCOPE)
            else tuple(part.strip() for part in self.applies.split(","))
        )
        object.__setattr__(self, "_steps", steps)

    @property
    def has_direct_target(self) -> bool:
        """Whether the value lives only in a tool config (or PDK), with no workspace default.

        Stored (``maps_to``) and forked parameters always have an effective
        workspace value; only explicit direct parameters are worth listing.
        """
        direct_config = self.config_target is not None and self.maps_to is None and not self.fork
        return direct_config or self.pdk_target is not None

    @property
    def workspace_wide(self) -> bool:
        return self.applies == WORKSPACE_WIDE

    @property
    def steps(self) -> tuple[str, ...]:
        """The flow steps ``applies`` names, in declaration order.

        Empty for a workspace-wide or PDK parameter. Names are canonical flow
        step names; :meth:`applies_errors` rejects anything else.
        """
        return self._steps

    def applies_to(self, step: str) -> bool:
        """Whether *step* (a canonical flow step name) is one of :attr:`steps`."""
        return step in self.steps

    def listed_at(self, step: str, first_step: str) -> bool:
        """Whether the per-step view of *step* shows this parameter.

        Workspace-wide parameters are shown once, at the flow's *first_step*.
        """
        return self.applies_to(step) or (self.workspace_wide and step == first_step)

    def applies_errors(self) -> list[str]:
        unknown = [step for step in self.steps if step not in FLOW_STEP_NAMES]
        return [f"unknown flow step {step!r} in applies of {self.param}" for step in unknown]

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
