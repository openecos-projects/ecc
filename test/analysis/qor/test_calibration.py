import pytest

from chipcompiler.analysis.qor.calibration import (
    CalibrationError,
    clamp01,
    psi_cost,
    psi_target,
)


class TestPsiCost:
    def test_preferred_plateau_gives_full_credit(self):
        # Approaching the geometric lower bound is never penalized.
        assert psi_cost(1.05, 1.25, 1.75) == 1.0
        assert psi_cost(1.20, 1.25, 1.75) == 1.0
        assert psi_cost(1.25, 1.25, 1.75) == 1.0

    def test_linear_penalty_slope(self):
        assert psi_cost(1.50, 1.25, 1.75) == pytest.approx(0.5)
        assert psi_cost(1.75, 1.25, 1.75) == 0.0

    def test_beyond_failure_is_clamped_to_zero(self):
        assert psi_cost(2.5, 1.25, 1.75) == 0.0

    def test_monotone_non_increasing(self):
        scores = [psi_cost(x / 100.0, 1.25, 1.75) for x in range(100, 200, 5)]
        assert scores == sorted(scores, reverse=True)

    def test_invalid_thresholds_rejected(self):
        with pytest.raises(CalibrationError):
            psi_cost(1.0, 1.75, 1.25)


class TestPsiTarget:
    def test_target_interval_full_credit(self):
        assert psi_target(0.52, 0.45, 0.70, 0.85) == 1.0
        assert psi_target(0.45, 0.45, 0.70, 0.85) == 1.0
        assert psi_target(0.70, 0.45, 0.70, 0.85) == 1.0

    def test_under_allocation_penalized(self):
        assert psi_target(0.225, 0.45, 0.70, 0.85) == pytest.approx(0.5)

    def test_over_allocation_penalized(self):
        assert psi_target(0.85, 0.45, 0.70, 0.85) == 0.0
        assert psi_target(0.775, 0.45, 0.70, 0.85) == pytest.approx(0.5)

    def test_strict_positivity_required(self):
        with pytest.raises(CalibrationError):
            psi_target(0.1, 0.0, 0.7, 0.85)


class TestClamp01:
    def test_clamps(self):
        assert clamp01(-0.5) == 0.0
        assert clamp01(0.25) == 0.25
        assert clamp01(1.5) == 1.0
