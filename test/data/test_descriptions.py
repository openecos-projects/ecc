import json
from pathlib import Path

from chipcompiler.data.config_params import CONFIG_PARAM_SCHEMAS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DREAMPLACE_PARAMETERS = (
    _REPO_ROOT / "chipcompiler/thirdparty/ecc-dreamplace/dreamplace/params.json"
)


def test_dreamplace_descriptions_match_upstream_metadata():
    metadata = json.loads(_DREAMPLACE_PARAMETERS.read_text(encoding="utf-8"))
    schemas = [
        schema
        for schema in CONFIG_PARAM_SCHEMAS
        if schema.config_target is not None and schema.config_target.config_key == "dreamplace"
    ]

    assert schemas
    for schema in schemas:
        target = schema.config_target
        assert target is not None
        (key,) = target.json_path
        assert schema.description == metadata[key]["description"]
