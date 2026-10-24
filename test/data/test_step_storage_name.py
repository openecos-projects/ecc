from chipcompiler.data import SkippableStepEnum, StepEnum, step_storage_name


def test_step_storage_name_sanitizes_sizer_timing_opt():
    assert step_storage_name(SkippableStepEnum.TIMING_OPT.value, "sizer") == "timing_optimization"
    assert step_storage_name(SkippableStepEnum.TIMING_OPT.value, "Sizer") == "timing_optimization"
    assert step_storage_name(StepEnum.FLOORPLAN.value, "ecc") == StepEnum.FLOORPLAN.value


def test_step_directory_for_tool_uses_the_storage_stem_for_sizer():
    from chipcompiler.data import step_directory_for_tool

    assert (
        step_directory_for_tool(SkippableStepEnum.TIMING_OPT.value, "sizer")
        == "timing_optimization_sizer"
    )


def test_step_directory_for_tool_keeps_legacy_lec_directories():
    from chipcompiler.data import step_directory_for_tool

    assert step_directory_for_tool("lec", "yosys_lec") == "lec_yosys_lec"
    assert step_directory_for_tool("postRouteLec", "yosys_lec") == "postRouteLec_yosys_lec"
    assert step_directory_for_tool("lec", "lec_dual") == "lec_dual"
    assert step_directory_for_tool("postRouteLec", "lec_dual") == "postRouteLec_dual"
    assert step_directory_for_tool("lec", "kepler_formal") == "lec_kepler_formal"
