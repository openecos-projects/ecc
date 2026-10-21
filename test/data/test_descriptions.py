import json
from pathlib import Path

from chipcompiler.data.config_params import CONFIG_PARAM_SCHEMAS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DREAMPLACE_PARAMETERS = (
    _REPO_ROOT / "chipcompiler/thirdparty/ecc-dreamplace/dreamplace/params.json"
)
# These stage controls are translated by ECC's diff-sizing builder, not declared
# in upstream Params metadata. Keep the set explicit so unknown fields still fail.
_ECC_OWNED_DREAMPLACE_PARAMETERS = {
    "diff_sizing_continuous_steps",
    "diff_sizing_coefficients",
}


def test_canonical_dreamplace_descriptions_match_upstream_metadata():
    metadata = json.loads(_DREAMPLACE_PARAMETERS.read_text(encoding="utf-8"))
    schemas = [
        schema
        for schema in CONFIG_PARAM_SCHEMAS
        if schema.config_target is not None
        and schema.config_target.config_key == "dreamplace"
        and schema.name == schema.config_target.json_path[-1]
    ]

    assert schemas
    descriptions = {}
    for schema in schemas:
        target = schema.config_target
        assert target is not None
        (key,) = target.json_path
        descriptions[key] = schema.description

    assert descriptions.keys() - metadata.keys() == _ECC_OWNED_DREAMPLACE_PARAMETERS
    upstream_keys = descriptions.keys() - _ECC_OWNED_DREAMPLACE_PARAMETERS
    assert {key: descriptions[key] for key in upstream_keys} == {
        key: metadata[key]["description"] for key in upstream_keys
    }
