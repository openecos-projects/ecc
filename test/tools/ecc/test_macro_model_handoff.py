from unittest.mock import Mock

import pytest

from chipcompiler.tools.ecc.module import ECCToolsModule


def test_model_pair_is_extracted_once_and_published_without_losing_hold(tmp_path):
    native = Mock()
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = native
    raw = tmp_path / "work/timing_characterizer"

    def extract():
        raw.mkdir(parents=True)
        (raw / "core_max.lib").write_text("setup model")
        (raw / "core_min.lib").write_text("hold model")

    native.extract_lib.side_effect = extract
    output = tmp_path / "output"
    module.write_timing_model(
        output / "core.lib",
        output_min_lib_path=output / "core_min.lib",
        output_dir=tmp_path / "work",
        design_name="core",
        lib_paths=["std.lib", "child_max.lib"],
        min_lib_paths=["child_min.lib"],
    )
    native.lib_init.assert_called_once_with(lib_paths=["std.lib", "child_max.lib", "child_min.lib"])
    native.init_sta.assert_called_once_with(
        config="",
        config_dict={"-temp_directory_path": str(tmp_path / "work")},
        min_lib_paths=["child_min.lib"],
    )
    native.extract_lib.assert_called_once()
    native.destroy_sta.assert_called_once()
    assert {path.name: path.read_text() for path in output.iterdir()} == {
        "core.lib": "setup model",
        "core_min.lib": "hold model",
    }


@pytest.mark.parametrize("content", [None, ""])
def test_missing_min_model_cannot_publish_a_successful_pair(tmp_path, content):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = Mock()
    raw = tmp_path / "work/timing_characterizer"
    raw.mkdir(parents=True)
    (raw / "core_max.lib").write_text("setup model")
    if content is not None:
        (raw / "core_min.lib").write_text(content)
    with pytest.raises(RuntimeError, match="missing or empty"):
        module.write_timing_model(
            tmp_path / "out/core.lib",
            output_min_lib_path=tmp_path / "out/core_min.lib",
            output_dir=tmp_path / "work",
            design_name="core",
        )
    assert list((tmp_path / "out").glob("*.lib")) == []
    module.ecc.destroy_sta.assert_called_once()
