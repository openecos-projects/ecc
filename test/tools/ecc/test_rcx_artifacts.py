import errno
import shutil
from pathlib import Path

import pytest

from chipcompiler.data import EccData, EccOutput, EccStep, StepEnum, Workspace
from chipcompiler.tools.ecc import rcx_artifacts


class FakeLogger:
    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []

    def info(self, message, *args):
        self.infos.append((message, args))

    def warning(self, message, *args):
        self.warnings.append((message, args))

    def error(self, message, *args):
        self.errors.append((message, args))


def test_copy_rcx_spef_outputs_publishes_to_step_output_dir(tmp_path):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    source_path = data_dir / "spef_writer" / "gcd_Cworst_125C.spef"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("*SPEF\n", encoding="utf-8")
    spef_outputs = [data_dir / source_path.name]
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=spef_outputs),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is True

    destination = output_dir / source_path.name
    assert destination.read_text(encoding="utf-8") == "*SPEF\n"
    assert not (data_dir / source_path.name).exists()
    assert step.output.spef is spef_outputs
    assert step.output.spef == [destination]


def test_copy_rcx_spef_outputs_fails_when_declared_spef_source_is_missing(tmp_path):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    spef_writer = data_dir / "spef_writer"
    spef_writer.mkdir(parents=True)
    (spef_writer / "present.spef").write_text("*SPEF\n", encoding="utf-8")
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=[output_dir / "missing.spef"]),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is False
    assert not (output_dir / "missing.spef").exists()
    assert not (output_dir / "present.spef").exists()
    assert step.output.spef == [output_dir / "missing.spef"]


def test_copy_rcx_spef_outputs_fails_when_source_spef_is_zero_byte(tmp_path):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    spef_writer = data_dir / "spef_writer"
    spef_writer.mkdir(parents=True)
    (spef_writer / "empty.spef").write_text("", encoding="utf-8")
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=[output_dir / "empty.spef"]),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is False
    assert not (output_dir / "empty.spef").exists()
    assert step.output.spef == [output_dir / "empty.spef"]


def test_copy_rcx_spef_outputs_fails_and_keeps_stale_destination_when_source_missing(tmp_path):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    spef_writer = data_dir / "spef_writer"
    spef_writer.mkdir(parents=True)
    (spef_writer / "good.spef").write_text("*SPEF\nfresh\n", encoding="utf-8")
    stale_destination = output_dir / "missing.spef"
    output_dir.mkdir(parents=True)
    stale_destination.write_text("*SPEF\nstale\n", encoding="utf-8")
    spef_outputs = [output_dir / "good.spef", stale_destination]
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=spef_outputs),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is False

    assert stale_destination.read_text(encoding="utf-8") == "*SPEF\nstale\n"
    assert not (output_dir / "good.spef").exists()
    assert step.output.spef is spef_outputs
    assert step.output.spef == [output_dir / "good.spef", stale_destination]


def test_copy_rcx_spef_outputs_fails_without_partial_copy_when_one_source_is_empty(tmp_path):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    spef_writer = data_dir / "spef_writer"
    spef_writer.mkdir(parents=True)
    (spef_writer / "good.spef").write_text("*SPEF\n", encoding="utf-8")
    (spef_writer / "empty.spef").write_text("", encoding="utf-8")
    spef_outputs = [output_dir / "good.spef", output_dir / "empty.spef"]
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=spef_outputs),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is False

    assert not (output_dir / "good.spef").exists()
    assert not (output_dir / "empty.spef").exists()
    assert step.output.spef is spef_outputs
    assert step.output.spef == [output_dir / "good.spef", output_dir / "empty.spef"]


@pytest.mark.parametrize("partial_content", ["", "*SPEF\ntrunc"])
def test_copy_rcx_spef_outputs_cleans_partial_publication_when_a_copy_fails(
    tmp_path, monkeypatch, partial_content
):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    spef_writer = data_dir / "spef_writer"
    spef_writer.mkdir(parents=True)
    (spef_writer / "a.spef").write_text("*SPEF\na\n", encoding="utf-8")
    (spef_writer / "b.spef").write_text("*SPEF\nb\n", encoding="utf-8")
    spef_outputs = [output_dir / "a.spef", output_dir / "b.spef"]
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=spef_outputs),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())
    real_copy2 = shutil.copy2

    def fail_second_copy(source, destination, **kwargs):
        destination = Path(destination)
        if destination.name == ".b.spef.tmp":
            destination.write_text(partial_content, encoding="utf-8")
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_copy2(source, destination, **kwargs)

    monkeypatch.setattr(rcx_artifacts.shutil, "copy2", fail_second_copy)

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is False

    assert not (output_dir / "a.spef").exists()
    assert not (output_dir / "b.spef").exists()
    assert step.output.spef is spef_outputs
    assert step.output.spef == [output_dir / "a.spef", output_dir / "b.spef"]


@pytest.mark.parametrize("second_write", ["zero-byte", "skipped"])
def test_copy_rcx_spef_outputs_cleans_partial_publication_when_validation_fails(
    tmp_path, monkeypatch, second_write
):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    spef_writer = data_dir / "spef_writer"
    spef_writer.mkdir(parents=True)
    (spef_writer / "a.spef").write_text("*SPEF\na\n", encoding="utf-8")
    (spef_writer / "b.spef").write_text("*SPEF\nb\n", encoding="utf-8")
    spef_outputs = [output_dir / "a.spef", output_dir / "b.spef"]
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=spef_outputs),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())

    def copy_with_invalid_second(source, destination, **_kwargs):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.name == ".b.spef.tmp" and second_write == "zero-byte":
            destination.write_text("", encoding="utf-8")
        elif destination.name == ".a.spef.tmp":
            destination.write_text("*SPEF\na\n", encoding="utf-8")

    monkeypatch.setattr(rcx_artifacts.shutil, "copy2", copy_with_invalid_second)

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is False

    assert not (output_dir / "a.spef").exists()
    assert not (output_dir / "b.spef").exists()
    assert step.output.spef is spef_outputs
    assert step.output.spef == [output_dir / "a.spef", output_dir / "b.spef"]


def test_copy_rcx_spef_outputs_restores_previous_spef_when_a_later_copy_fails(
    tmp_path, monkeypatch
):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    spef_writer = data_dir / "spef_writer"
    spef_writer.mkdir(parents=True)
    (spef_writer / "a.spef").write_text("*SPEF\nfresh a\n", encoding="utf-8")
    (spef_writer / "b.spef").write_text("*SPEF\nfresh b\n", encoding="utf-8")
    output_dir.mkdir(parents=True)
    previous_a = output_dir / "a.spef"
    previous_a.write_text("*SPEF\nprevious a\n", encoding="utf-8")
    spef_outputs = [output_dir / "a.spef", output_dir / "b.spef"]
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=spef_outputs),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())
    real_copy2 = shutil.copy2

    def fail_second_copy(source, destination, **kwargs):
        destination = Path(destination)
        if destination.name == ".b.spef.tmp":
            destination.write_text("*SPEF\ntrunc", encoding="utf-8")
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_copy2(source, destination, **kwargs)

    monkeypatch.setattr(rcx_artifacts.shutil, "copy2", fail_second_copy)

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is False

    assert previous_a.read_text(encoding="utf-8") == "*SPEF\nprevious a\n"
    assert not (output_dir / "b.spef").exists()
    assert list(output_dir.iterdir()) == [previous_a]
    assert step.output.spef is spef_outputs
    assert step.output.spef == [output_dir / "a.spef", output_dir / "b.spef"]


def test_copy_rcx_spef_outputs_removes_backups_after_successful_republish(tmp_path):
    data_dir = tmp_path / "RCX_ecc" / "data"
    output_dir = tmp_path / "RCX_ecc" / "output"
    spef_writer = data_dir / "spef_writer"
    spef_writer.mkdir(parents=True)
    (spef_writer / "a.spef").write_text("*SPEF\nfresh a\n", encoding="utf-8")
    (spef_writer / "b.spef").write_text("*SPEF\nfresh b\n", encoding="utf-8")
    output_dir.mkdir(parents=True)
    (output_dir / "a.spef").write_text("*SPEF\nprevious a\n", encoding="utf-8")
    (output_dir / "b.spef").write_text("*SPEF\nprevious b\n", encoding="utf-8")
    spef_outputs = [output_dir / "a.spef", output_dir / "b.spef"]
    step = EccStep(
        name=StepEnum.RCX.value,
        data=EccData(dir=data_dir),
        output=EccOutput(dir=output_dir, spef=spef_outputs),
    )
    workspace = Workspace(directory=tmp_path, logger=FakeLogger())

    assert rcx_artifacts.copy_rcx_spef_outputs(workspace, step) is True

    assert (output_dir / "a.spef").read_text(encoding="utf-8") == "*SPEF\nfresh a\n"
    assert (output_dir / "b.spef").read_text(encoding="utf-8") == "*SPEF\nfresh b\n"
    assert sorted(path.name for path in output_dir.iterdir()) == ["a.spef", "b.spef"]
    assert step.output.spef is spef_outputs
    assert step.output.spef == [output_dir / "a.spef", output_dir / "b.spef"]
