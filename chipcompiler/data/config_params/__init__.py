from .cts import SCHEMAS as CTS_SCHEMAS
from .dreamplace import SCHEMAS as DREAMPLACE_SCHEMAS
from .filler import SCHEMAS as FILLER_SCHEMAS
from .floorplan import SCHEMAS as FLOORPLAN_SCHEMAS
from .pdk import SCHEMAS as PDK_SCHEMAS
from .rcx import SCHEMAS as RCX_SCHEMAS
from .route import SCHEMAS as ROUTE_SCHEMAS
from .sta import SCHEMAS as STA_SCHEMAS

CONFIG_PARAM_SCHEMAS = (
    *CTS_SCHEMAS,
    *FLOORPLAN_SCHEMAS,
    *DREAMPLACE_SCHEMAS,
    *ROUTE_SCHEMAS,
    *FILLER_SCHEMAS,
    *RCX_SCHEMAS,
    *STA_SCHEMAS,
    *PDK_SCHEMAS,
)


def validate_config_registry() -> list[str]:
    seen: set[str] = set()
    errors = []
    for schema in CONFIG_PARAM_SCHEMAS:
        if schema.param in seen:
            errors.append(f"duplicate config parameter: {schema.param}")
        seen.add(schema.param)
        if schema.config_target is None and schema.pdk_target is None:
            errors.append(f"config parameter missing target: {schema.param}")
    return errors
