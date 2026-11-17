#!/usr/bin/env python

"""Inserted steps on a run's flow config, and project.json's synthesis LEC.

ecc.toml declares inserted steps (``[flow] insert_steps``); a project.json
range may end at one (``lec@synthesis``), and a project.json skip policy that
keeps ``lec`` runs the synthesis LEC. These helpers carry both onto the flow
config :mod:`effective_config` resolves.

Imported lazily by the command handlers, so module-level imports must stay
cheap (no chipcompiler.data imports here).
"""


def declared_insert_steps(cfg) -> list | None:
    """The declared [flow] insert_steps spelling; None when the key is absent."""
    if "flow.insert_steps" in getattr(cfg, "_explicit_keys", frozenset()):
        return cfg.flow_insert_steps
    return None


def attach_insert_steps(flow_config: dict | None, insert_steps: list | None) -> dict | None:
    """*flow_config* also inserting *insert_steps* (policy-only when it selects
    no steps), beside any its range implies (:func:`entry_flow_config`)."""
    if insert_steps is None:
        return flow_config
    flow_config = dict(flow_config or {})
    flow_config["insert_steps"] = [*(flow_config.get("insert_steps") or []), *insert_steps]
    return flow_config


def manifest_synthesis_lec(entry, cfg) -> list | None:
    """The synthesis LEC a project.json workspace entry keeps, as an insertion.

    A declared entry policy that does not skip ``lec`` runs it as
    ``lec@synthesis``; an undeclared policy skipped it by default, and an
    ecc.toml ``skip_steps`` replaces the entry's policy. None: no insertion.
    """
    from chipcompiler.data import StepEnum
    from chipcompiler.rtl2gds import inserted_step_name

    if entry is None or "flow.skip_steps" in getattr(cfg, "_explicit_keys", frozenset()):
        return None
    declared = getattr(entry, "skip_steps", None)
    if declared is None or any(str(name) == StepEnum.LEC.value for name in declared):
        return None
    return [inserted_step_name(StepEnum.LEC.value, StepEnum.SYNTHESIS.value)]


def entry_flow_config(entry) -> dict:
    """The run flow config of a project.json workspace range.

    A range bounded by an inserted LEC (``lec@synthesis``) is bounded by the
    step it checks and inserts that LEC.
    """
    from chipcompiler.rtl2gds import parse_inserted_step

    config: dict = {"start_step": entry.start_step, "end_step": entry.end_step}
    for key in ("start_step", "end_step"):
        parsed = parse_inserted_step(config[key])
        if parsed is None:
            continue
        inserted = config[key]
        config[key] = parsed[1]
        if inserted not in config.setdefault("insert_steps", []):
            config["insert_steps"].append(inserted)
    return config
