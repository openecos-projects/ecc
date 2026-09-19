import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agent.methods import agent_method_names
from agent.requests import (
    CandidateRerunRequest,
    CandidateResumeRequest,
    parse_agent_request_model,
)
from agent.server import AgentRuntimeServer
from chipcompiler.runtime.requests import RequestValidationError
from chipcompiler.runtime.transport import ContentLengthDecoder, encode_content_length_frame
from chipcompiler.runtime.workspace_api import WorkspaceRuntimeApi

CONTEXT_SHA256 = "sha256:" + "a" * 64
PARAMETER_CARD_SHA256 = "sha256:" + "b" * 64


PUBLIC_CANDIDATE_METHODS = (
    "workspace.extract_foundation",
    "candidate.capabilities",
    "candidate.rerun",
    "candidate.resume",
)
REMOVED_PUBLIC_METHODS = (
    "agent.runtime_preflight",
    "candidate.export_capabilities",
    "candidate.bind_input",
    "candidate.materialize",
)


def test_agent_methods_keep_the_public_candidate_rpc_names():
    assert agent_method_names() == PUBLIC_CANDIDATE_METHODS


def test_agent_runtime_server_registers_isolated_methods():
    server = AgentRuntimeServer()

    assert set(agent_method_names()).issubset(server.capabilities)
    assert not set(REMOVED_PUBLIC_METHODS) & set(server.capabilities)


def test_agent_runtime_server_prepares_agent_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.server.prepare_agent_runtime_environment",
        lambda: calls.append(True),
    )

    AgentRuntimeServer()

    assert calls == [True]


def test_agent_runtime_server_uses_generic_workspace_api_for_ordinary_flow():
    server = AgentRuntimeServer()

    assert type(server.api) is WorkspaceRuntimeApi


def test_candidate_execution_builds_agent_engine_flow(monkeypatch):
    flow = SimpleNamespace()
    monkeypatch.setattr(
        "agent.workspace_api.build_agent_flow_for_workspace",
        lambda _workspace, **_kwargs: flow,
    )
    server = AgentRuntimeServer()

    result = server.agent_api._build_flow(SimpleNamespace())

    assert result is flow


def test_agent_request_normalizes_camel_case_fields():
    request = parse_agent_request_model(
        CandidateRerunRequest,
        {
            "workspaceId": "workspace-1",
            "targetStep": "place",
            "endStep": "CTS",
            "candidateId": "candidate-1",
            "patch": [],
            "executionScope": "full_flow",
            "idempotencyKey": "episode-1.intervention-1",
            "contextSha256": CONTEXT_SHA256,
            "parameterCardSha256": PARAMETER_CARD_SHA256,
            "seed": 17,
            "expectedWorkspaceRevision": 17,
            "parentCandidateRootRef": ".agent/candidates/candidate-0",
        },
    )

    assert request == CandidateRerunRequest(
        workspace_id="workspace-1",
        target_step="place",
        end_step="CTS",
        candidate_id="candidate-1",
        patch=[],
        execution_scope="full_flow",
        idempotency_key="episode-1.intervention-1",
        context_sha256=CONTEXT_SHA256,
        parameter_card_sha256=PARAMETER_CARD_SHA256,
        seed=17,
        expected_workspace_revision=17,
        parent_candidate_root_ref=".agent/candidates/candidate-0",
    )


def test_candidate_rerun_request_requires_context_hash():
    with pytest.raises(RequestValidationError, match="missing required field: context_sha256"):
        parse_agent_request_model(
            CandidateRerunRequest,
            {
                "workspaceId": "workspace-1",
                "targetStep": "place",
                "endStep": "Harden",
                "candidateId": "candidate-1",
                "patch": [{"knob_id": "place.target_density", "value": 0.6}],
                "executionScope": "full_flow",
                "idempotencyKey": "episode-1.intervention-1",
            },
        )


def test_candidate_resume_request_accepts_only_execution_binding_fields():
    request = parse_agent_request_model(
        CandidateResumeRequest,
        {
            "workspaceId": "workspace-1",
            "candidateId": "candidate-1",
            "idempotencyKey": "episode-1.resume-1",
            "contextSha256": CONTEXT_SHA256,
            "parameterCardSha256": PARAMETER_CARD_SHA256,
            "seed": 17,
            "expectedWorkspaceRevision": 17,
        },
    )

    assert request == CandidateResumeRequest(
        workspace_id="workspace-1",
        candidate_id="candidate-1",
        idempotency_key="episode-1.resume-1",
        context_sha256=CONTEXT_SHA256,
        parameter_card_sha256=PARAMETER_CARD_SHA256,
        seed=17,
        expected_workspace_revision=17,
    )


@pytest.mark.parametrize("extra", ["targetStep", "path", "patch", "command"])
def test_candidate_resume_request_rejects_execution_authority_fields(extra):
    params = {
        "workspaceId": "workspace-1",
        "candidateId": "candidate-1",
        "idempotencyKey": "episode-1.resume-1",
        "contextSha256": CONTEXT_SHA256,
        "seed": 17,
        extra: "untrusted",
    }

    with pytest.raises(RequestValidationError, match="unknown field"):
        parse_agent_request_model(CandidateResumeRequest, params)


def test_candidate_rerun_request_requires_seed():
    with pytest.raises(RequestValidationError, match="missing required field: seed"):
        parse_agent_request_model(
            CandidateRerunRequest,
            {
                "workspaceId": "workspace-1",
                "targetStep": "place",
                "endStep": "Harden",
                "candidateId": "candidate-1",
                "patch": [{"knob_id": "place.target_density", "value": 0.6}],
                "executionScope": "full_flow",
                "idempotencyKey": "episode-1.intervention-1",
                "contextSha256": CONTEXT_SHA256,
                "parameterCardSha256": PARAMETER_CARD_SHA256,
            },
        )


def test_agent_request_rejects_duplicate_aliases():
    with pytest.raises(RequestValidationError, match="duplicate field: workspace_id"):
        parse_agent_request_model(
            CandidateRerunRequest,
            {
                "workspaceId": "workspace-1",
                "workspace_id": "workspace-1",
                "targetStep": "place",
                "endStep": "place",
                "candidateId": "candidate-1",
                "patch": [],
                "executionScope": "single_step",
            },
        )


def test_candidate_rerun_rejects_a_multi_knob_patch_as_an_invalid_request():
    server = AgentRuntimeServer()

    response = json.loads(
        server.dispatch(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "candidate.rerun",
                    "id": 1,
                    "params": {
                        "workspaceId": "workspace-1",
                        "targetStep": "place",
                        "endStep": "Harden",
                        "candidateId": "candidate-1",
                        "patch": [
                            {"knob_id": "place.target_density", "value": 0.6},
                            {"knob_id": "place.routability_opt", "value": True},
                        ],
                        "executionScope": "full_flow",
                        "idempotencyKey": "episode-1.intervention-1",
                        "contextSha256": CONTEXT_SHA256,
                        "parameterCardSha256": PARAMETER_CARD_SHA256,
                        "seed": 17,
                    },
                }
            )
        )
    )

    assert response["error"] == {
        "code": -32602,
        "message": "invalid_request",
        "data": {"message": "candidate rerun requires exactly one patch item"},
    }


def test_ecc_rpc_serve_advertises_candidate_methods():
    def request(method: str, request_id: int, params: dict | None = None) -> bytes:
        payload = {"jsonrpc": "2.0", "method": method, "id": request_id}
        if params is not None:
            payload["params"] = params
        return encode_content_length_frame(json.dumps(payload, separators=(",", ":")))

    completed = subprocess.run(
        [sys.executable, "-m", "chipcompiler.cli.main", "rpc", "serve", "--stdio"],
        input=request("rpc.hello", 1, {"version": 1}) + request("rpc.shutdown", 2),
        capture_output=True,
        check=False,
    )
    decoder = ContentLengthDecoder()
    responses = [json.loads(message) for message in decoder.feed(completed.stdout)]
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    capabilities = responses[0]["result"]["capabilities"]

    for method_name in PUBLIC_CANDIDATE_METHODS:
        assert method_name in capabilities
    for method_name in REMOVED_PUBLIC_METHODS:
        assert method_name not in capabilities
