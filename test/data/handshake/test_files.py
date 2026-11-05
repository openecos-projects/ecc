"""req.json / rsp.json round-trip and are rejected when they cannot be trusted."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from chipcompiler.data.handshake import (
    REQ_FILE,
    RSP_FILE,
    DesignFiles,
    HandshakeError,
    ResponseStatus,
    StepInputs,
    StepRequest,
    StepResponse,
    UpstreamResponse,
    clear_response,
    load_request,
    load_response,
    write_request,
    write_response,
)
from chipcompiler.data.types import AnalysisData, DesignState


def _request(workspace: Path) -> StepRequest:
    return StepRequest(
        workspace_directory=workspace,
        step="sta",
        tool="ecc",
        step_directory="sta_ecc",
        attempt_id="attempt-sta",
        inputs=StepInputs(
            design=DesignFiles(
                def_=workspace / "filler_ecc/output/gcd_filler.def.gz",
                verilog=workspace / "filler_ecc/output/gcd_filler.v.gz",
                db=workspace / "filler_ecc/output/db",
            ),
            spef=(workspace / "RCX_ecc/output/gcd_rcworst_25C.spef",),
        ),
        design_source=UpstreamResponse("filler_ecc", "attempt-filler"),
        upstream={
            DesignState.FILLED: UpstreamResponse("filler_ecc", "attempt-filler"),
            AnalysisData.PARASITICS: UpstreamResponse("RCX_ecc", "attempt-rcx"),
        },
        final_step=False,
        layout_image=True,
    )


def _response(workspace: Path) -> StepResponse:
    return StepResponse(
        step="RCX",
        tool="ecc",
        attempt_id="attempt-rcx",
        status=ResponseStatus.SUCCESS,
        design=DesignFiles(def_=workspace / "RCX_ecc/output/gcd_RCX.def.gz"),
        design_states=frozenset({DesignState.ROUTED, DesignState.FILLED}),
        outputs={AnalysisData.PARASITICS: (workspace / "RCX_ecc/output/gcd_rcworst_25C.spef",)},
        design_source=UpstreamResponse("filler_ecc", "attempt-filler"),
        upstream={DesignState.FILLED: UpstreamResponse("filler_ecc", "attempt-filler")},
        warnings=frozenset({DesignState.CLOCK_TREE}),
    )


def _rewrite(path: Path, **changes) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_request_round_trips(tmp_path):
    request = _request(tmp_path)

    write_request(request)

    assert load_request(tmp_path / "sta_ecc") == request


def test_response_round_trips(tmp_path):
    response = _response(tmp_path)

    write_response(tmp_path, response)

    assert load_response(tmp_path) == response


def test_step_without_response_has_not_answered(tmp_path):
    assert load_response(tmp_path) is None


def test_cleared_response_is_gone(tmp_path):
    write_response(tmp_path, _response(tmp_path))

    clear_response(tmp_path)

    assert load_response(tmp_path) is None


def test_missing_request_is_rejected(tmp_path):
    with pytest.raises(HandshakeError, match="missing"):
        load_request(tmp_path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"workspace_directory": "relative/ws"}, "absolute"),
        ({"step_directory": "../sta_ecc"}, "single directory name"),
        ({"step_directory": ".."}, "single directory name"),
        ({"step": "Spin"}, "no flow policy registered"),
        ({"final_step": "no"}, "true or false"),
        ({"upstream": {"timing": {"step_directory": "sta_ecc", "attempt_id": "a"}}}, "unknown"),
        ({"attempt_id": ""}, "non-empty string"),
        ({"design_source": {"step_directory": "../filler_ecc", "attempt_id": None}}, "single"),
        ({"design_source": {"step_directory": "filler_ecc", "attempt_id": 3}}, "string or null"),
    ],
)
def test_untrusted_request_is_rejected(tmp_path, changes, message):
    path = write_request(_request(tmp_path))
    _rewrite(path, **changes)

    with pytest.raises(HandshakeError, match=message):
        load_request(tmp_path / "sta_ecc")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "done"}, "status"),
        ({"design_states": ["parasitics"]}, "not a design state"),
        ({"outputs": {"routed": []}}, "not analysis data"),
        ({"warnings": [""]}, "non-empty strings"),
    ],
)
def test_untrusted_response_is_rejected(tmp_path, changes, message):
    path = write_response(tmp_path, _response(tmp_path))
    _rewrite(path, **changes)

    with pytest.raises(HandshakeError, match=message):
        load_response(tmp_path)


def test_corrupt_file_is_rejected(tmp_path):
    (tmp_path / RSP_FILE).write_text("{not json", encoding="utf-8")
    (tmp_path / REQ_FILE).write_text("[]", encoding="utf-8")

    with pytest.raises(HandshakeError, match="not valid JSON"):
        load_response(tmp_path)
    with pytest.raises(HandshakeError, match="JSON object"):
        load_request(tmp_path)


def test_a_declared_design_has_no_design_source(tmp_path):
    request = replace(_request(tmp_path), design_source=None)

    write_request(request)

    assert load_request(tmp_path / "sta_ecc").design_source is None
