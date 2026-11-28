"""Evidence Completeness Index (spec §10.4).

IE is an internal engineering completeness index, not a probability.
The multiplicative composition implements a conjunctive requirement:
correlated extraction anomalies compound pessimistically on purpose so
that corrupt evidence downgrades confidence instead of averaging away.
Every zero-denominator condition evaluates to NOT_APPLICABLE, never to
division-by-zero or a fake perfect score.
"""

from chipcompiler.analysis.qor.feasibility import corner_slack_check
from chipcompiler.analysis.qor.models import Evidence

_HIGH = "HIGH"
_MODERATE = "MODERATE"
_LIMITED = "LIMITED"
_INSUFFICIENT = "INSUFFICIENT"
_NOT_VERIFIED = "NOT_VERIFIED"


def _ratio_or_none(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return max(0.0, min(1.0, numerator / denominator))


def evaluate_evidence(inputs, bundle) -> Evidence:
    integrity = _integrity(inputs)
    coverage = _coverage(inputs)
    consistency = _consistency(inputs, bundle)

    active = [
        component for component in (integrity, coverage, consistency) if component is not None
    ]
    if not active:
        return Evidence(
            index=None,
            state=_NOT_VERIFIED,
            integrity=integrity,
            coverage=coverage,
            consistency=consistency,
        )
    index = 100.0
    for component in active:
        index *= component
    state = _state(index)
    if inputs.sta_setup_only and state == _HIGH:
        state = _MODERATE
    return Evidence(
        index=index,
        state=state,
        integrity=integrity,
        coverage=coverage,
        consistency=consistency,
    )


def _state(index: float) -> str:
    if index >= 90.0:
        return _HIGH
    if index >= 70.0:
        return _MODERATE
    if index >= 50.0:
        return _LIMITED
    return _INSUFFICIENT


def _integrity(inputs):
    """Data integrity: payload parse health plus selector provenance (eq. 41)."""
    expected = len(inputs.analyzed_steps) + inputs.parse_failures
    if expected <= 0:
        return None
    failures = inputs.parse_failures + inputs.invalid_selector_count
    return max(0.0, min(1.0, 1.0 - failures / expected))


def _coverage(inputs):
    """Corner population: STA corners and RCX SPEF coverage (eq. 42)."""
    components = []
    sta = _ratio_or_none(_sta_loaded(inputs), inputs.sta_expected_corners)
    if sta is not None:
        components.append(sta)
    rcx = _ratio_or_none(inputs.rcx_spef_count, inputs.rcx_expected_spef)
    if rcx is not None:
        components.append(rcx)
    if not components:
        return None
    return sum(components) / len(components)


def _sta_loaded(inputs):
    expected = inputs.sta_expected_corners
    if expected is None:
        return None
    missing = inputs.value("sta_missing_corner_count")
    if missing is None:
        return None
    return expected - missing


def _consistency(inputs, bundle):
    """Semantic consistency checks C1-C3 (eq. 44-46)."""
    checks = []

    # C1: realized RWL >= HPWL baseline when populations are compatible.
    if bundle.compatibility.status != "INCOMPATIBLE":
        rwl = inputs.value("route_wirelength")
        hpwl = inputs.value("place_hpwl")
        if rwl is not None and hpwl is not None:
            checks.append(rwl >= hpwl)

    # C2: (WS >= 0) <=> (NVP == 0) under one scope — both metrics come
    # from the same STA payload over the same configured corners.
    ws_record = inputs.metrics.get("sta_setup_wns")
    nvp_record = inputs.metrics.get("sta_setup_violation_count")
    if (
        ws_record is not None
        and nvp_record is not None
        and ws_record.scope is not None
        and ws_record.scope == nvp_record.scope
        and ws_record.corner == nvp_record.corner
        and _population_compatible(ws_record.endpoint_population, nvp_record.endpoint_population)
    ):
        ws = ws_record.value
        nvp = nvp_record.value
        checks.append((ws >= 0.0) == (nvp == 0))

    # C2b: per-corner summaries are self-consistent and agree with the
    # aggregate STA metrics (same check that gates setup/hold feasibility).
    corner_checks = _corner_checks(inputs)
    checks.extend(corner_checks)

    # C3: vias imply routed wirelength (one-way topological sanity).
    vias = inputs.value("route_via_count")
    rwl = inputs.value("route_wirelength")
    if vias is not None and rwl is not None:
        checks.append(not (vias > 0) or rwl > 0)

    if not checks:
        return None
    return sum(1.0 for passed in checks if passed) / len(checks)


def _corner_checks(inputs) -> list:
    if not inputs.corners:
        return []
    checks = [
        (corner.setup_ws >= 0.0) == (corner.setup_nvp == 0)
        for corner in inputs.corners
        if corner.setup_nvp is not None
    ]
    checks.extend(
        (corner.hold_ws >= 0.0) == (corner.hold_nvp == 0)
        for corner in inputs.corners
        if corner.hold_ws is not None and corner.hold_nvp is not None
    )
    # Incomplete corner sets are already penalised by E_coverage.
    expected = inputs.sta_expected_corners
    if expected is not None and len(inputs.corners) < expected:
        return checks
    for metric_id, nvp_metric in (
        ("sta_setup_wns", "sta_setup_violation_count"),
        ("sta_hold_wns", "sta_hold_violation_count"),
    ):
        ws = inputs.value(metric_id)
        if ws is not None:
            checks.append(corner_slack_check(inputs, metric_id, nvp_metric, ws)[1] is None)
    return checks


def _population_compatible(left, right) -> bool:
    """C2 is applicable only when endpoint populations are comparable."""
    if left is None or right is None:
        return True
    return left == right
