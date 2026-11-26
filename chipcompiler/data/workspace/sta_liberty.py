"""Select a PVT library group, optionally specialized to an extracted RC corner."""


def validate_liberty_groups(groups: list[dict]) -> None:
    temperatures = {}
    keys = set()
    for group in groups:
        corner = group["corner"]
        rc = group.get("rc_corner")
        if "rc_corner" in group and (not isinstance(rc, str) or not rc):
            raise ValueError("STA Liberty rc_corner must be a nonempty string")
        if (corner, rc) in keys:
            raise ValueError(f"Ambiguous STA Liberty groups for {corner}/{rc or '*'}")
        keys.add((corner, rc))
        temperature = group["temperature"]
        if corner in temperatures and temperatures[corner] != temperature:
            raise ValueError(f"STA Liberty groups for {corner} must use the same temperature")
        temperatures[corner] = temperature


def select_liberty_group(groups: list[dict], corner: str, rc_corner: str) -> dict | None:
    matching = [group for group in groups if group["corner"] == corner]
    exact = [group for group in matching if group.get("rc_corner") == rc_corner]
    selected = exact or [group for group in matching if "rc_corner" not in group]
    if len(selected) > 1:
        raise ValueError(f"Ambiguous STA Liberty groups for {corner}/{rc_corner}")
    return selected[0] if selected else None
