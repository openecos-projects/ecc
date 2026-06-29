from chipcompiler.data import Workspace
from chipcompiler.engine.flow import EngineFlow


def test_engine_flow_missing_path_is_not_initialized():
    engine_flow = EngineFlow(Workspace())

    assert engine_flow.has_init() is False
