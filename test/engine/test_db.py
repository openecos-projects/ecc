from chipcompiler.engine.db import EngineDB


class FakeEccModule:
    def __init__(self):
        self.ecc = object()
        self.calls = []

    def close(self):
        self.calls.append("close")

    def exit(self):
        raise AssertionError("EngineDB.close must not terminate the host process")


def test_engine_db_close_calls_non_terminating_close_and_clears_module():
    ecc_module = FakeEccModule()
    engine_db = EngineDB(workspace=None, ecc_module=ecc_module)

    engine_db.close()

    assert ecc_module.calls == ["close"]
    assert engine_db.ecc_module is None
    assert not engine_db.has_init()


def test_engine_db_close_is_idempotent():
    ecc_module = FakeEccModule()
    engine_db = EngineDB(workspace=None, ecc_module=ecc_module)

    engine_db.close()
    engine_db.close()

    assert ecc_module.calls == ["close"]
    assert engine_db.ecc_module is None
