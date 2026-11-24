"""A workspace with the configs and flow the candidate materialization tests patch."""

import json
from pathlib import Path
from types import SimpleNamespace

from agent.data.candidate_artifacts import canonical_json_bytes, sha256_bytes
from chipcompiler.data.pdk import PDK
from test.flow_fixture import step_fields


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def rewrite_receipt(path: Path, receipt: dict) -> None:
    receipt["receipt_sha256"] = sha256_bytes(
        canonical_json_bytes(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
    )
    write_json(path, receipt)


def workspace(tmp_path: Path):
    tech_path = tmp_path / "pdk" / "tech.lef"
    tech_path.parent.mkdir(parents=True)
    tech_path.write_text(
        "UNITS\n  DATABASE MICRONS 1000 ;\nEND UNITS\nSITE core7\n  SIZE 0.2 BY 1.4 ;\nEND core7\n",
        encoding="utf-8",
    )
    cts_path = tmp_path / "config" / "cts_ecc.json"
    pl_path = tmp_path / "config" / "filler_ecc.json"
    write_json(
        cts_path,
        {
            "skew_bound": "0.08",
            "max_fanout": "32",
            "buffer_type": ["BUF_1"],
            "unrelated": {"keep": True},
        },
    )
    write_json(
        pl_path,
        {"-min_filler_width": 1},
    )
    write_json(
        tmp_path / "config" / "floorplan_ecc.json",
        {"Floorplan": {"Tap distance": 58}},
    )
    write_json(
        tmp_path / "config" / "dreamplace_ecc.json",
        {
            "target_density": 0.8,
            "stop_overflow": 0.1,
            "cell_padding_x": 0,
            "bndry_padding_x": 0,
            "bndry_padding_y": 0,
            "detailed_place_flag": 0,
            "num_threads": 8,
            "deterministic_flag": 1,
        },
    )
    write_json(
        tmp_path / "config" / "routing_ecc.json",
        {"RT": {"-bottom_routing_layer": "MET2", "-top_routing_layer": "MET5"}},
    )
    parameters_path = tmp_path / "home" / "params.toml"
    from chipcompiler.data.workspace.config import save_workspace_config

    assert save_workspace_config(
        tmp_path, {"core": {"utilitization": 0.6, "aspect_ratio": 1.0, "margin": [2, 2]}}
    )
    return SimpleNamespace(
        directory=str(tmp_path),
        config={
            "cts": cts_path,
            "floorplan": tmp_path / "config" / "floorplan_ecc.json",
            "dreamplace": tmp_path / "config" / "dreamplace_ecc.json",
            "legalization": pl_path,
            "filler": pl_path,
            "routing": tmp_path / "config" / "routing_ecc.json",
        },
        pdk=PDK(
            buffers=["BUF_1", "BUF_2"],
            fillers=["FILL_1", "FILL_2"],
            site_core="core7",
            tech=tech_path,
        ),
        parameters=SimpleNamespace(path=parameters_path),
        flow=SimpleNamespace(
            data={
                "schema_version": 3,
                "steps": [
                    {
                        "name": "floorplan",
                        "tool": "ecc",
                        **step_fields("floorplan", "ecc"),
                    },
                    {
                        "name": "placement",
                        "tool": "dreamplace",
                        **step_fields("placement", "dreamplace"),
                    },
                    {
                        "name": "cts",
                        "tool": "ecc",
                        **step_fields("cts", "ecc"),
                    },
                    {
                        "name": "legalization",
                        "tool": "dreamplace",
                        **step_fields("legalization", "dreamplace"),
                    },
                    {
                        "name": "routing",
                        "tool": "ecc",
                        **step_fields("routing", "ecc"),
                    },
                    {
                        "name": "filler",
                        "tool": "ecc",
                        **step_fields("filler", "ecc"),
                    },
                ],
            }
        ),
    )


def read_params(path: Path) -> dict:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))["params"]
