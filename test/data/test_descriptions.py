import json
from pathlib import Path

from chipcompiler.data.config_params import CONFIG_PARAM_SCHEMAS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DREAMPLACE_PARAMETERS = (
    _REPO_ROOT / "chipcompiler/thirdparty/ecc-dreamplace/dreamplace/params.json"
)
# These ECC flow-controller controls are translated by the ECC builders and are
# not declared in upstream Params metadata. Keep the set explicit so unknown
# fields still fail.
_ECC_OWNED_DREAMPLACE_PARAMETERS = {
    "buffering_candidate_strategy",
    "diff_buffering_coefficients",
    "diff_buffering_rounds",
    "diff_buffering_selection_fraction",
    "diff_optimization_flows",
    "diff_optimization_mode",
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
