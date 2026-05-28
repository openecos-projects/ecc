import os

_STEP_CONFIG_FILES = {
    ("floorplan", "ecc"): ("flow_config.json", "db_default_config.json", "fp_default_config.json"),
    (
        "fixfanout",
        "ecc",
    ): ("flow_config.json", "db_default_config.json", "no_default_config_fixfanout.json"),
    ("placement", "ecc"): ("flow_config.json", "db_default_config.json", "pl_default_config.json"),
    ("cts", "ecc"): ("flow_config.json", "db_default_config.json", "cts_default_config.json"),
    ("routing", "ecc"): ("flow_config.json", "db_default_config.json", "rt_default_config.json"),
    ("drc", "ecc"): ("flow_config.json", "db_default_config.json", "drc_default_config.json"),
    ("legalization", "ecc"): (
        "flow_config.json",
        "db_default_config.json",
        "pl_default_config.json",
    ),
    ("filler", "ecc"): ("flow_config.json", "db_default_config.json", "pl_default_config.json"),
    ("pnp", "ecc"): ("flow_config.json", "db_default_config.json", "pnp_default_config.json"),
    ("optdrv", "ecc"): ("flow_config.json", "db_default_config.json", "to_default_config_drv.json"),
    ("opthold", "ecc"): (
        "flow_config.json",
        "db_default_config.json",
        "to_default_config_hold.json",
    ),
    ("optsetup", "ecc"): (
        "flow_config.json",
        "db_default_config.json",
        "to_default_config_setup.json",
    ),
    ("rcx", "ecc"): ("flow_config.json", "db_default_config.json", "rcx.json"),
    ("sta", "ecc"): ("flow_config.json", "db_default_config.json", "rcx.json"),
    ("placement", "dreamplace"): ("dreamplace.json",),
    ("legalization", "dreamplace"): ("dreamplace.json",),
}


def workspace_config_files(run_dir: str, step_token: str, tool: str | None) -> list[str]:
    filenames = _STEP_CONFIG_FILES.get((step_token, (tool or "").lower()), ())
    config_dir = os.path.join(run_dir, "config")
    return [
        os.path.join(config_dir, name)
        for name in filenames
        if os.path.isfile(os.path.join(config_dir, name))
    ]
