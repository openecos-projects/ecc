"""Routing transitions preserve physical context and revision-local overlays."""

import json

from chipcompiler.tools.replay import atomic_json, publish


def test_routing_state_replaces_process_layers_and_preserves_power(tmp_path):
    base = {
        "die": {"kind": "die", "bbox": [0, 0, 100, 100]},
        "power": {"kind": "wire", "net_kind": "power", "bbox": [0, 0, 2, 100]},
        "cell": {"kind": "instance", "bbox": [4, 4, 8, 8]},
    }
    wire = {"kind": "wire", "bbox": [0, 0, 20, 1]}
    overlay = {"kind": "route_congestion", "bbox": [0, 0, 10, 10], "capacity": 0, "blocked": True}
    states = [base, {"net1": wire, "grid": overlay}, {"net1": wire}, base]
    for i, objects in enumerate(states):
        atomic_json(
            tmp_path / f"attempts/a/capture/{i}.json",
            {
                "sequence": i,
                "elapsed_ns": i,
                "phase": "routing",
                "subflow": "run routing",
                "scope": "full" if i in (0, 3) else "routing",
                "objects": objects,
                "state_domain": "native_committed" if i == 3 else "algorithm_state",
            },
        )
    publish(tmp_path, "a", "routing", "ecc", 3)
    directory = tmp_path / "attempts/a"
    manifest = json.loads((directory / "manifest.json").read_text())
    scene = {}
    snapshots = []
    for frame in manifest["frames"]:
        data = json.loads((directory / frame["path"]).read_text())
        if data["checkpoint"]:
            scene = base.copy() if data.get("base_checkpoint") == 0 else {}
        for key in data["remove"]:
            scene.pop(key, None)
        scene.update(data["upsert"])
        snapshots.append(scene.copy())
    assert snapshots == [
        base,
        {**base, "net1": wire, "grid": overlay},
        {**base, "net1": wire},
        base,
    ]


def test_native_transport_patch_removes_previous_overlay_and_restores_routing(tmp_path):
    base = {"power": {"kind": "pdn", "bbox": [0, 0, 2, 100]}}
    wire = {"kind": "wire", "bbox": [0, 0, 20, 1]}
    changed = {"kind": "wire", "bbox": [0, 0, 30, 1]}
    violation = {"kind": "route_violation", "bbox": [1, 1, 2, 2], "name": "short"}
    inputs = [
        ("full", base, []),
        ("routing", {"wire:a": wire, "marker": violation}, []),
        ("patch", {"wire:b": changed}, ["wire:a", "marker"]),
        ("patch", {"wire:a": wire, "marker": violation}, ["wire:b"]),
        ("full", {**base, "wire:a": wire}, []),
    ]
    for i, (scope, objects, removed) in enumerate(inputs):
        atomic_json(
            tmp_path / f"attempts/a/capture/{i}.json",
            {
                "sequence": i,
                "elapsed_ns": i,
                "phase": "route",
                "subflow": "run routing",
                "scope": scope,
                "objects": objects,
                "remove": removed,
                "state_domain": "native_committed" if i == 4 else "algorithm_state",
            },
        )
    publish(tmp_path, "a", "routing", "ecc", 4)
    directory = tmp_path / "attempts/a"
    manifest = json.loads((directory / "manifest.json").read_text())
    scene = {}
    snapshots = []
    for frame in manifest["frames"]:
        data = json.loads((directory / frame["path"]).read_text())
        if data["checkpoint"]:
            scene = base.copy() if data.get("base_checkpoint") == 0 else {}
        for key in data["remove"]:
            scene.pop(key, None)
        scene.update(data["upsert"])
        snapshots.append(scene.copy())
    assert snapshots == [
        base,
        {**base, "wire:a": wire, "marker": violation},
        {**base, "wire:b": changed},
        {**base, "wire:a": wire, "marker": violation},
        {**base, "wire:a": wire},
    ]
