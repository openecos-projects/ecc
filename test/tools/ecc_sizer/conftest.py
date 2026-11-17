"""Keep native IO probing out of Sizer orchestration tests."""

import json
from unittest.mock import Mock

import pytest

from chipcompiler.tools.ecc import runner
from chipcompiler.tools.ecc.module import ECCToolsModule


@pytest.fixture(autouse=True)
def timing_probe(monkeypatch):
    module = Mock(spec=ECCToolsModule)

    def export(json_path):
        json_path.write_text(json.dumps({"Instances": {"iopads": {"num": 0}}}))
        return True

    module.feature_sammry.side_effect = export
    monkeypatch.setattr(runner, "create_db_engine", lambda *_args: module)
