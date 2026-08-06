import pytest

from agent.methods import agent_method_names
from agent.requests import CandidateRerunRequest, parse_agent_request_model
from agent.server import AgentRuntimeServer
from chipcompiler.runtime.requests import RequestValidationError


def test_agent_methods_keep_the_original_rpc_names():
    assert agent_method_names() == (
        "workspace.extract_foundation",
        "candidate.export_capabilities",
        "candidate.bind_input",
        "candidate.materialize",
        "candidate.rerun",
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
        },
    )

    assert request == CandidateRerunRequest(
        workspace_id="workspace-1",
        target_step="place",
        end_step="CTS",
        candidate_id="candidate-1",
        patch=[],
        execution_scope="full_flow",
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
