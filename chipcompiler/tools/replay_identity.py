"""Track observed object lifetimes across stable producer snapshots."""

import hashlib

ORIENTATIONS = {
    1: "R0",
    2: "R90",
    3: "R180",
    4: "R270",
    5: "MY",
    6: "MYR90",
    7: "MX",
    8: "MXR90",
    "N": "R0",
    "W": "R90",
    "S": "R180",
    "E": "R270",
    "FN": "MY",
    "FE": "MYR90",
    "FS": "MX",
    "FW": "MXR90",
}


class Identities:
    def __init__(self):
        self.active = {}
        self.births = {}

    def reference(self, key):
        if key in self.active:
            return self.active[key]
        return key if len(key) <= 128 else "shape:" + hashlib.sha256(key.encode()).hexdigest()

    def convert(self, incoming):
        result = {}
        for key, value in incoming.items():
            if value.get("kind") not in {"instance", "macro"}:
                # Full canonical shape strings made every delta/index repeat
                # the geometry. Hash the producer identity, including multiplicity.
                result[self.reference(key)] = value
                continue
            orientation = value.get("orient")
            # iDB enum codes and OpenDB/DEF names describe the same transforms.
            if orientation in ORIENTATIONS:
                value = {**value, "orient": ORIENTATIONS[orientation]}
            if key not in self.active:
                birth = self.births.get(key, 0)
                self.active[key] = key if birth == 0 else f"{key}#birth:{birth}"
            result[self.active[key]] = value
        return result

    def removed(self, removed):
        gone = set(removed)
        for raw, stable in list(self.active.items()):
            if stable in gone:
                del self.active[raw]
                self.births[raw] = self.births.get(raw, 0) + 1
