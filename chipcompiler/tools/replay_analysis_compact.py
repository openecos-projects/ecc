"""Replay display values reference existing geometry; reports stay in step output."""


def compact_analysis(views: list, unavailable: list) -> dict:
    nets, instances = {}, {}
    for view in views:
        if view["kind"] in {"ir", "em"}:
            # Solver mesh nodes/edges are genuine analysis locations, not native
            # wire rectangles. Keep their positions and plotted values only.
            for item in view["items"]:
                item["details"] = {
                    key: value for key, value in item.get("details", {}).items() if key == "layer"
                }
        if view["kind"] not in {"rcx", "power"}:
            continue
        is_net = view["kind"] == "rcx"
        names = nets if is_net else instances
        field = "net_ref" if is_net else "instance_ref"
        view["items"] = [
            {field: names.setdefault(item["label"], len(names)), "value": item["value"]}
            for item in view["items"]
        ]
    return {
        "schema": "ecos.replay.analysis.v2",
        "nets": list(nets),
        "instances": list(instances),
        "views": views,
        "unavailable": unavailable,
    }
