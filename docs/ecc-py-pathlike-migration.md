# ecc_py PathLike migration notes

Behavioral compatibility notes for the `os.PathLike` adoption in the
`ecc_py` bindings and the `chipcompiler.tools.ecc` wrapper. This document
is intentionally version-neutral; versioned release metadata is maintained
separately.

## Compatibility matrix

| Input | Behavior |
| --- | --- |
| `str` | Supported, unchanged from before the migration. |
| `os.PathLike` | Newly supported on all 73 path parameters (69 scalars + 4 lists) across the 11 binding modules. Passed through to the bindings unchanged; no `str()` coercion in the wrapper. |
| `None` | Native for optional path parameters (forwarded as `None`). `TypeError` for required path parameters, raised by the binding. |
| `""` | Preserved as unset: for optional parameters `None` ≡ omitted ≡ `""`. |
| `bytes` | Incidental caster behavior (accepted by pybind11's `std::string` caster); unsupported, do not rely on it. |
| Platform | Linux-only wheels (`manylinux_2_34` via CI, auditwheel-repaired). |
| Python | `>=3.11` (both the `ecc` package and `ecc-tools-bin`). |

## Removed wrapper methods (30)

30 `ECCToolsModule` wrapper methods were removed. They were internal
wrapper surface with no production callers, and every one of them called an
upstream binding that is disabled or absent in `ecc_py`
(`runMP`/`runRef` commented out in `py_register_imp.cpp`, the `py_vec`
module excluded from the build, the rest never registered in `ecc_py`).
If upstream re-enables a binding, re-add the corresponding wrapper in
pass-through form (path arguments forwarded unchanged).

Removed: `build_connection_map`, `build_macro_connection_map`,
`build_rc_tree_from_flat_data`, `destroy_pl`, `generate_vectors`,
`get_timing_instance_graph`, `get_timing_wire_graph`,
`get_wire_timing_power_data`, `init_pl`, `layout_graph`, `layout_patchs`,
`placer_run_dp`, `placer_run_gp`, `placer_run_lg`, `placer_run_mp`, `pnp`,
`read_pg_spef`, `read_vcd_cpp`, `report_ir_drop`, `report_power`,
`report_power_cpp`, `run_ai_placement`, `run_incremental_flow`,
`run_macro_placement`, `run_refinement`, `run_timing_opt_setup`, `run_to`,
`update_and_get_all_pin_timings`, `vectors_nets_patterns_to_def`,
`vectors_nets_to_def`.

Retained pending legacy-runner cleanup (4): `run_placement`,
`run_legalize`, `run_timing_opt_drv`, `run_timing_opt_hold`. These are
referenced by the legacy runner flow (`chipcompiler/tools/ecc/runner.py`);
their upstream bindings are absent, so those legacy steps already fail at
runtime today — a pre-existing condition, out of scope for this migration.
Delete these wrapper methods together with the legacy dispatch when the
flow owners retire it.

## config_dict boundary

Unchanged. `config_dict` remains `std::map<std::string, std::string>` at
the binding boundary; the two `path_text` conversions in
`chipcompiler/tools/ecc/module.py` (the `-temp_directory_path` values built
in `run_timing` and `write_timing_model` for `init_sta`) remain because
that boundary is string-typed.

## Rollback plan

Generic rollback, two options:

1. Revert this three-part series — the ecc-tools integration (submodule
   pointer and wheel pin), the wrapper pass-through migration, and the
   dead-method deletion — and repin the previous `ecc-tools-bin` wheel
   release.
2. Fix forward in the next `ecc-tools-bin` wheel release.
