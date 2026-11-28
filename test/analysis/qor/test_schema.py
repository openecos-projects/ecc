from chipcompiler.analysis.qor import build_qor_analysis
from chipcompiler.analysis.qor.schema import validate_report
from test.analysis.qor.helpers import gcd_corners, gcd_metrics, make_inputs


class TestSchemaParity:
    def test_assembled_report_validates(self):
        from unittest import mock

        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        with mock.patch(
            "chipcompiler.analysis.qor.load_workspace_qor_inputs",
            lambda workspace: inputs,
        ):
            analysis = build_qor_analysis(workspace=None)
        assert validate_report(analysis.to_dict()) == []
        assert analysis.to_dict()["power"] == {
            "total_uw": None,
            "budget_uw": None,
            "source_path": None,
            "source_kind": None,
            "corner": None,
        }

    def test_supplementary_features_are_published_and_validated(self):
        from unittest import mock

        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        with mock.patch(
            "chipcompiler.analysis.qor.load_workspace_qor_inputs",
            lambda workspace: inputs,
        ):
            payload = build_qor_analysis(workspace=None).to_dict()
        ids = {feature["feature_id"] for feature in payload["supplementary_features"]}
        assert {"F_PL_EGR_OVERFLOW_GCELL_FRAC", "F_STA_SETUP_TNS", "F_STA_HOLD_HEADROOM"} <= ids
        payload["supplementary_features"][0]["value"] = float("nan")
        assert any("supplementary" in error for error in validate_report(payload))

    def test_missing_required_key_is_detected(self):
        from unittest import mock

        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        with mock.patch(
            "chipcompiler.analysis.qor.load_workspace_qor_inputs",
            lambda workspace: inputs,
        ):
            payload = build_qor_analysis(workspace=None).to_dict()
        del payload["evidence"]
        errors = validate_report(payload)
        assert any("evidence" in error for error in errors)

    def test_out_of_range_score_is_detected(self):
        from unittest import mock

        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        with mock.patch(
            "chipcompiler.analysis.qor.load_workspace_qor_inputs",
            lambda workspace: inputs,
        ):
            payload = build_qor_analysis(workspace=None).to_dict()
        payload["scalar_summary"]["score"] = 150.0
        errors = validate_report(payload)
        assert any("score out of range" in error for error in errors)

    def test_coverage_fields_are_optional_and_validated(self):
        from unittest import mock

        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        with mock.patch(
            "chipcompiler.analysis.qor.load_workspace_qor_inputs",
            lambda workspace: inputs,
        ):
            payload = build_qor_analysis(workspace=None).to_dict()
        assert payload["scalar_summary"]["band_provisional"] is True
        assert validate_report(payload) == []
        del payload["scalar_summary"]["coverage"]
        del payload["scalar_summary"]["band_provisional"]
        assert validate_report(payload) == []  # pre-coverage reports stay valid
        payload["scalar_summary"]["coverage"] = 1.5
        payload["scalar_summary"]["band_provisional"] = "yes"
        errors = validate_report(payload)
        assert any("coverage out of range" in error for error in errors)
        assert any("band_provisional" in error for error in errors)

    def test_malformed_nested_blocks_return_errors_without_raising(self):
        from unittest import mock

        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        with mock.patch(
            "chipcompiler.analysis.qor.load_workspace_qor_inputs",
            lambda workspace: inputs,
        ):
            payload = build_qor_analysis(workspace=None).to_dict()
        payload["feasibility"] = None
        assert validate_report(payload)

        payload["feasibility"] = {"status": "PASS", "gates": []}
        payload["diagnoses"] = [{"diagnosis_id": "broken", "interventions": [None]}]
        assert validate_report(payload)

    def test_invalid_gate_state_is_detected(self):
        from unittest import mock

        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        with mock.patch(
            "chipcompiler.analysis.qor.load_workspace_qor_inputs",
            lambda workspace: inputs,
        ):
            payload = build_qor_analysis(workspace=None).to_dict()
        payload["feasibility"]["gates"][0]["state"] = "maybe"
        errors = validate_report(payload)
        assert any("gate state invalid" in error for error in errors)

    def test_invalid_power_observation_is_detected(self):
        from unittest import mock

        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        with mock.patch(
            "chipcompiler.analysis.qor.load_workspace_qor_inputs",
            lambda workspace: inputs,
        ):
            payload = build_qor_analysis(workspace=None).to_dict()
        payload["power"]["source_kind"] = "estimated"
        errors = validate_report(payload)
        assert any("power.source_kind invalid" in error for error in errors)
