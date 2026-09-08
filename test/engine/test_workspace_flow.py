from chipcompiler.engine.workspace_flow import build_flow_for_workspace


def test_build_flow_requires_committed_flow(tmp_path):
    from chipcompiler.data import Workspace

    workspace = Workspace(directory=tmp_path)

    try:
        build_flow_for_workspace(workspace, create_step_workspaces=False)
    except ValueError as error:
        assert str(error) == "Workspace has no committed Flow"
    else:
        raise AssertionError("missing committed Flow was accepted")
