import pytest


@pytest.fixture(autouse=True)
def _step_worker_double(monkeypatch, request):
    if request.node.get_closest_marker("real_step_worker") is not None:
        return
    from chipcompiler.engine import step_execution
    from test.engine.step_execution_double import execute_in_process

    monkeypatch.setattr(step_execution, "_execute_in_worker", execute_in_process)
