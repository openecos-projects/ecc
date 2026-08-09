from types import SimpleNamespace

from chipcompiler.data import StepEnum
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


class FakeLogger:
    def __init__(self):
        self.info_messages = []
        self.warning_messages = []

    def info(self, message):
        self.info_messages.append(message)

    def warning(self, message):
        self.warning_messages.append(message)


def test_engine_db_skips_synthesis_without_a_failure_warning(monkeypatch):
    logger = FakeLogger()
    workspace = SimpleNamespace(logger=logger)
    db_engine = EngineDB(workspace=workspace)
    create_calls = []

    monkeypatch.setattr("chipcompiler.tools.load_eda_module", lambda _name: object())
    monkeypatch.setattr(
        "chipcompiler.tools.ecc.create_db_engine",
        lambda *_args: create_calls.append(True),
    )

    assert db_engine.create_db_engine(SimpleNamespace(name=StepEnum.SYNTHESIS.value)) is False
    assert create_calls == []
    assert logger.warning_messages == []


def test_engine_db_warns_when_a_physical_step_cannot_initialize(monkeypatch):
    logger = FakeLogger()
    workspace = SimpleNamespace(logger=logger)
    db_engine = EngineDB(workspace=workspace)

    monkeypatch.setattr("chipcompiler.tools.load_eda_module", lambda _name: object())
    monkeypatch.setattr("chipcompiler.tools.ecc.create_db_engine", lambda *_args: None)

    step = SimpleNamespace(name=StepEnum.FLOORPLAN.value)
    assert db_engine.create_db_engine(step) is False
    assert logger.warning_messages == [
        f"ecc db initialize failed for step {StepEnum.FLOORPLAN.value}."
    ]
