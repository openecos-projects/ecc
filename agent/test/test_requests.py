import json
import subprocess
import sys

import pytest

from agent.methods import agent_method_names
from agent.requests import CandidateRerunRequest, CandidateResumeRequest, parse_agent_request_model
from agent.server import AgentRuntimeServer
from chipcompiler.runtime.requests import RequestValidationError
from chipcompiler.runtime.transport import ContentLengthDecoder, encode_content_length_frame

CONTEXT_SHA256 = "sha256:" + "a" * 64


def test_agent_methods_keep_the_original_rpc_names():
    assert agent_method_names() == (
        "workspace.extract_foundation",
        "candidate.export_capabilities",
        "candidate.bind_input",
        "candidate.materialize",
        "candidate.rerun",
        "candidate.resume",
    )


def test_agent_runtime_server_registers_isolated_methods():
    server = AgentRuntimeServer()

    assert set(agent_method_names()).issubset(server.capabilities)


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
            "seed": 17,
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
        seed=17,
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
            "seed": 17,
        },
    )

    assert request == CandidateResumeRequest(
        workspace_id="workspace-1",
        candidate_id="candidate-1",
        idempotency_key="episode-1.resume-1",
        context_sha256=CONTEXT_SHA256,
        seed=17,
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


def test_agent_rpc_cli_is_explicitly_opt_in():
    def request(method: str, request_id: int, params: dict | None = None) -> bytes:
        payload = {"jsonrpc": "2.0", "method": method, "id": request_id}
        if params is not None:
            payload["params"] = params
        return encode_content_length_frame(json.dumps(payload, separators=(",", ":")))

    def capabilities(*, agent_enabled: bool) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "chipcompiler.cli.main",
            "rpc",
            "serve",
            "--stdio",
        ]
        if agent_enabled:
            command.append("--agent")
        completed = subprocess.run(
            command,
            input=request("rpc.hello", 1, {"version": 1}) + request("rpc.shutdown", 2),
            capture_output=True,
            check=False,
        )
        decoder = ContentLengthDecoder()
        responses = [json.loads(message) for message in decoder.feed(completed.stdout)]
        assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
        return responses[0]["result"]["capabilities"]

    assert "candidate.rerun" not in capabilities(agent_enabled=False)
    assert "candidate.rerun" in capabilities(agent_enabled=True)
