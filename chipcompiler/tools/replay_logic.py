"""Keep the logical summary used by Replay; discard staging-only raw netlists."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from chipcompiler.tools.replay_storage import atomic_json


def summarize(document):
    modules = document.get("modules", {})
    candidates = [
        m for m in modules.values() if int(str(m.get("attributes", {}).get("top", "0")), 2)
    ]
    module = (
        candidates[0]
        if candidates
        else max(modules.values(), key=lambda m: len(m.get("cells", {})), default={})
    )
    cells = module.get("cells", {})
    types = Counter(cell["type"] for cell in cells.values())
    drivers, sinks = defaultdict(set), defaultdict(set)
    for cell in cells.values():
        for port, bits in cell.get("connections", {}).items():
            direction = cell.get("port_directions", {}).get(port)
            for bit in bits:
                if type(bit) is int:
                    if direction == "output":
                        drivers[bit].add(cell["type"])
                    elif direction == "input":
                        sinks[bit].add(cell["type"])
    connections = Counter(
        (source, target)
        for bit, sources in drivers.items()
        for source in sources
        for target in sinks[bit]
    )
    return {
        "cell_count": len(cells),
        "net_count": len(module.get("netnames", {})),
        "cell_types": dict(types),
        "connections": [
            {"source": source, "target": target, "count": count}
            for (source, target), count in sorted(connections.items())
        ],
    }


def collect_logical(directory: Path):
    capture = directory / "capture"
    events = sorted((capture / "logical").glob("*.event"))
    for sequence, event in enumerate(events):
        metadata = json.loads(event.read_text())
        source = event.with_suffix(".json")
        summary = summarize(json.loads(source.read_text()))
        folder = directory / f"subflows/logical-{sequence:03d}/overlays"
        folder.mkdir(parents=True, exist_ok=True)
        atomic_json(folder / "logic.json", summary)
        atomic_json(
            capture / f"logical-{sequence:03d}.json",
            {
                "sequence": sequence,
                "elapsed_ns": metadata["elapsed_ns"],
                "phase": metadata["phase"],
                "subflow": "run yosys",
                "state_domain": "analysis_complete"
                if sequence == len(events) - 1
                else "analysis_state",
                "objects": {},
                "logical": (folder / "logic.json").relative_to(directory).as_posix(),
                "metrics": {"cells": summary["cell_count"], "nets": summary["net_count"]},
            },
        )
