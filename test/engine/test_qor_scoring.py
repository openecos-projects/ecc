from chipcompiler.engine.qor_scoring import QorScoringMetric, score_metric, score_qor


def _metric(step, metric_id, value, dimension, direction="lower_is_better", **kwargs):
    return QorScoringMetric(
        step=step,
        metric_id=metric_id,
        value=value,
        dimension=dimension,
        direction=direction,
        scope="workspace",
        corner=None,
        project_role=kwargs.get("project_role", "final"),
        rating_score=kwargs.get("rating_score", True),
    )


def test_qor_scoring_selects_latest_area_and_combines_dimension_weights():
    result = score_qor(
        [
            _metric("Floor", "die_area", 300, "area_cost"),
            _metric("STA", "sta_setup_wns", -0.1, "timing", "higher_is_better"),
            _metric("Harden", "die_area", 1500, "area_cost"),
            _metric("DRC", "drc_count", 0, "routability_physical"),
        ]
    )

    assert result.area_scoring_step == "Harden"
    assert result.dimensions == {
        "timing": (50.0, 1),
        "routability_physical": (100.0, 1),
        "area_cost": (50.0, 1),
    }
    assert result.overall_score == 42.5


def test_qor_scoring_ignores_forward_version_dimensions_and_steps():
    result = score_qor(
        [
            _metric("future-step", "future_metric", 1, "future_dimension"),
            _metric("Harden", "die_area", 1500, "area_cost"),
        ]
    )

    assert result.dimensions == {"area_cost": (50.0, 1)}


def test_qor_scoring_uses_flow_order_for_area_step_when_provided():
    result = score_qor(
        [
            _metric("Harden", "die_area", 1500, "area_cost"),
            _metric("DRC", "die_area", 300, "area_cost"),
        ],
        flow_order=("STA", "DRC", "Harden"),
    )

    assert result.area_scoring_step == "Harden"
    assert result.dimensions == {"area_cost": (50.0, 1)}


def test_score_metric_matches_fail_threshold_formulas():
    slack = _metric("STA", "sta_setup_wns", -0.1, "timing", "higher_is_better")
    assert score_metric(slack) == 50.0
    assert score_metric(_metric("DRC", "drc_count", 0, "routability_physical")) == 100.0
    utilization = _metric("Harden", "core_utilization", 0.55, "area_cost", "target_range")
    assert score_metric(utilization) == 100.0
