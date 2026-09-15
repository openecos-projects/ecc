"""Cross-stage net population compatibility (spec §4.3, degraded per D-C).

Full ``MAPPED_COMPATIBLE`` verification needs a NetMapping contract that
the toolchain does not emit yet: CTS inserts clock-tree nets and neither
``place.map.json`` nor the route DB carries per-net data. Until such an
artifact exists the route side is conservatively INCOMPATIBLE and the
route-referencing ratios evaluate strictly to UNKNOWN; the same-stage
place ratios (one netlist, EXACT population) stay computable. QI then
degrades to the ``I_place`` ladder with downgraded evidence instead of
pretending a reconciled cross-stage identity.
"""

from dataclasses import dataclass, field

EXACT_COMPATIBLE = "EXACT_COMPATIBLE"
MAPPED_COMPATIBLE = "MAPPED_COMPATIBLE"
INCOMPATIBLE = "INCOMPATIBLE"


@dataclass(frozen=True)
class Compatibility:
    status: str
    assumptions: str = ""
    net_mapping: dict = field(default_factory=dict)

    def to_contract(self) -> dict:
        contract = {"status": self.status}
        if self.assumptions:
            contract["assumptions"] = self.assumptions
        if self.net_mapping:
            contract["net_mapping"] = dict(self.net_mapping)
        return contract


def evaluate_route_compatibility(*, cts_transformed: bool) -> Compatibility:
    """Classify the place→route population used by route-side ratios.

    ``cts_transformed`` is True when the CTS step completed and inserted
    physical clock-tree buffering (or its counts are unknown, which is
    treated conservatively as transformed).
    """
    if cts_transformed:
        return Compatibility(
            status=INCOMPATIBLE,
            assumptions=(
                "CTS inserted clock-tree nets and no verified net mapping "
                "exists yet, so route populations cannot be reconciled with "
                "placement; route-referencing inflation ratios stay UNKNOWN."
            ),
        )
    return Compatibility(
        status=EXACT_COMPATIBLE,
        assumptions=(
            "No CTS transformation is present; route and placement nets "
            "share one population (identity mapping)."
        ),
    )
