"""Evidence Completeness Index (spec §10.4).

IE is an internal engineering completeness index, not a probability.
The multiplicative composition implements a conjunctive requirement:
correlated extraction anomalies compound pessimistically on purpose so
that corrupt evidence downgrades confidence instead of averaging away.
Every zero-denominator condition evaluates to NOT_APPLICABLE, never to
division-by-zero or a fake perfect score.
"""

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
    return Evidence(
        index=index,
        state=_state(index),
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
    ws = inputs.value("sta_setup_wns")
    nvp = inputs.value("sta_setup_violation_count")
    if ws is not None and nvp is not None:
        checks.append((ws >= 0.0) == (nvp == 0))

    # C3: vias imply routed wirelength (one-way topological sanity).
    vias = inputs.value("route_via_count")
    rwl = inputs.value("route_wirelength")
    if vias is not None and rwl is not None:
        checks.append(not (vias > 0) or rwl > 0)

    if not checks:
        return None
    return sum(1.0 for passed in checks if passed) / len(checks)
