"""CLI parameter-output expectations from the production catalog."""

import pytest

from chipcompiler.data.parameter_schema import list_schemas


@pytest.fixture
def semantic_parameter_ids():
    return [schema.param for schema in list_schemas() if not schema.has_direct_target]


@pytest.fixture
def synthesis_parameter_ids():
    return [schema.param for schema in list_schemas() if schema.applies in {"synthesis", "all"}]
