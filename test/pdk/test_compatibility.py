import json
import subprocess
from unittest.mock import Mock

import pytest

from chipcompiler.pdk import compatibility
from chipcompiler.pdk.compatibility import Compatibility, ecc_compatible, runtime_issues
from chipcompiler.pdk.manifest import DescriptorError


def test_requirements_are_validated_and_ecc_release_is_checked():
    with pytest.raises(ValueError):
        Compatibility(ecc="not a version specifier")
    with pytest.raises(ValueError):
        Compatibility.model_validate({"distributions": {"unknown-tool": ">=1"}})
    with pytest.raises(DescriptorError, match="requires ECC"):
        ecc_compatible({"compatibility": {"ecc": ">=999"}})
    ecc_compatible({})


def test_only_selected_tools_are_probed(monkeypatch):
    version = Mock(return_value="0.1.0a7")
    monkeypatch.setattr(compatibility, "version", version)
    tools = {
        "compatibility": {"distributions": {"ecc-dreamplace": "==0.1.0a7"}, "sizer_vt_contract": 1}
    }
    assert runtime_issues(tools, ["Synthesis"]) == []
    version.assert_not_called()
    assert runtime_issues(tools, ["place"]) == []
    version.return_value = "0.1.0a6"
    assert "found 0.1.0a6" in runtime_issues(tools, ["place"])[0]


@pytest.mark.parametrize("response", ["valid", "old", "malformed", "array", "timeout"])
def test_sizer_contract_probe_rejects_unsupported_tools(monkeypatch, response):
    from chipcompiler.tools.ecc_sizer import utility

    monkeypatch.setattr(utility, "get_sizer_command", lambda: ["/local/Sizer"])
    payload = {"schema_version": 1, "tool": "ecc-sizer", "contracts": {"explicit_vt_groups": 1}}
    probe = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), ""))
    if response == "old":
        probe.side_effect = subprocess.CalledProcessError(1, ["/local/Sizer"])
    elif response == "malformed":
        probe.return_value.stdout = "not JSON"
    elif response == "array":
        probe.return_value.stdout = "[]"
    elif response == "timeout":
        probe.side_effect = subprocess.TimeoutExpired(["/local/Sizer"], 15)
    monkeypatch.setattr(compatibility.subprocess, "run", probe)
    issues = runtime_issues({"compatibility": {"sizer_vt_contract": 1}}, ["preplace"])
    assert bool(issues) == (response != "valid")
    assert probe.call_args.args[0] == ["/local/Sizer", "--ecc-capabilities"]
