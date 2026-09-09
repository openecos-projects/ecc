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
