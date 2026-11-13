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


def test_step_directory_for_tool_names_lec_directories_after_the_engine():
    from chipcompiler.data import step_directory_for_tool

    assert step_directory_for_tool("postRouteLec", "kepler_formal") == "postRouteLec_kepler_formal"
    assert step_directory_for_tool("lec@CTS", "kepler_formal") == "lec@CTS_kepler_formal"
