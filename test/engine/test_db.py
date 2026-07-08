from types import SimpleNamespace

from chipcompiler.engine.db import EngineDB


def test_engine_db_close_calls_native_exit_and_clears_module():
    calls = []
    ecc_module = SimpleNamespace(ecc=object(), exit=lambda: calls.append("exit"))
    engine_db = EngineDB(workspace=None, ecc_module=ecc_module)

    engine_db.close()

    assert calls == ["exit"]
    assert engine_db.ecc_module is None
    assert not engine_db.has_init()


def test_engine_db_close_is_idempotent():
    calls = []
    ecc_module = SimpleNamespace(ecc=object(), exit=lambda: calls.append("exit"))
    engine_db = EngineDB(workspace=None, ecc_module=ecc_module)

    engine_db.close()
    engine_db.close()

    assert calls == ["exit"]
    assert engine_db.ecc_module is None
