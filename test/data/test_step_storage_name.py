from chipcompiler.data import SkippableStepEnum, StepEnum, step_storage_name


def test_step_storage_name_sanitizes_sizer_timing_opt():
    assert step_storage_name(SkippableStepEnum.TIMING_OPT.value, "sizer") == "timing_optimization"
    assert step_storage_name(SkippableStepEnum.TIMING_OPT.value, "Sizer") == "timing_optimization"
    assert step_storage_name(StepEnum.FLOORPLAN.value, "ecc") == StepEnum.FLOORPLAN.value
