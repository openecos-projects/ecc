from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .writers import file_sha256, write_parquet

SCHEMA_VERSION = "foundation-data-ecc-parquet-v1"
CONTRACT_NAME = "foundation_data/ecc"
STORAGE_FORMAT = "parquet+json_views"
logger = logging.getLogger("ecos.api.foundation")


@dataclass(frozen=True)
class TableSpec:
    name: str
    primary_key: tuple[str, ...]
    columns: tuple[str, ...]
    partition_fields: tuple[str, ...] = ()

    def arrow_schema(self):
        import pyarrow as pa

        return pa.schema(
            [pa.field(column, _arrow_type_for_column(column)) for column in self.columns]
        )


_STRING_COLUMNS = {
    "design_id",
    "pdk",
    "design_name",
    "top_module",
    "logical_source_hash",
    "tech_profile",
    "created_from_workspace",
    "run_id",
    "parameter_hash",
    "flow_hash",
    "tool_version_hash",
    "workspace_path",
    "status",
    "created_at",
    "stage_id",
    "stage_name",
    "tool",
    "state",
    "stage_dir",
    "artifact_id",
    "artifact_type",
    "relative_path",
    "sha256",
    "parser",
    "parser_version",
    "availability",
    "provenance_id",
    "target_table",
    "target_key",
    "target_field",
    "derived_from_artifact_ids",
    "source_section",
    "availability_code",
    "null_reason",
    "notes",
    "entity_type",
    "entity_key",
    "block_name",
    "block_payload",
    "source_schema_version",
    "source_doc",
    "source_field_path",
    "preserved_reason",
    "normalized_status",
    "future_normalization_plan",
    "layer_name",
    "routing_direction",
    "metadata",
    "via_name",
    "cut_layer",
    "lower_layer",
    "upper_layer",
    "master",
    "cell_class",
    "physical_class",
    "grid_id",
    "edge_position",
    "relation",
    "category",
    "channel",
    "tightness_class",
    "direction",
    "instance_key",
    "placement_status",
    "orientation",
    "overlap_patch_ids",
    "summary_json",
    "pin_key",
    "pin_kind",
    "pin_name",
    "full_name",
    "parent_master",
    "geometry_status",
    "electrical_json",
    "timing_json",
    "route_json",
    "net_key",
    "name",
    "use",
    "net_class",
    "terminal_role",
    "wire_segment_key",
    "row_id",
    "site",
    "violation_id",
    "native_type",
    "normalized_class",
    "rule",
    "bbox_json",
    "layer",
    "vertex_kind",
    "terminal_pin_key",
    "match_status",
    "edge_kind",
    "geometry_json",
    "wire_segment_refs",
    "path_id",
    "startpoint",
    "endpoint",
    "delay_type",
    "path_group",
    "path_length_summary",
    "from_pin_key",
    "to_pin_key",
    "transition",
    "edge_kind_source",
    "point",
    "payload_json",
    "metric_name",
    "metric_value",
    "source_artifact_id",
    "feature_availability_code",
    "label_source_artifact_id",
    "from_stage",
    "to_stage",
    "change_type",
    "old_value",
    "new_value",
}

_BOOL_COLUMNS = {
    "is_default",
    "is_sequential",
    "is_physical_only",
    "is_macro",
    "is_clock_related",
    "is_io",
    "is_macro_pin",
    "is_clock",
    "is_reset",
    "is_power_ground",
    "is_signal",
    "is_driver",
    "is_sink",
    "critical_path_flag",
    "is_primary",
}

_INT_COLUMNS = {
    "stage_order",
    "size_bytes",
    "source_index",
    "layer_index",
    "pin_count",
    "row",
    "col",
    "patch_id",
    "neighbor_patch_id",
    "segment_index",
    "vertex_id",
    "edge_id",
    "source_vertex_id",
    "target_vertex_id",
    "point_index",
    "node_id",
}


def _arrow_type_for_column(column: str):
    import pyarrow as pa

    if column in _STRING_COLUMNS:
        return pa.string()
    if column in _BOOL_COLUMNS:
        return pa.bool_()
    if (
        column in _INT_COLUMNS
        or column.endswith("_count")
        or column.endswith("_id")
        and column != "grid_id"
    ):
        return pa.int64()
    return pa.float64()


TABLE_SPECS: dict[str, TableSpec] = {
    "designs": TableSpec(
        "designs",
        ("design_id",),
        (
            "design_id",
            "pdk",
            "design_name",
            "top_module",
            "logical_source_hash",
            "tech_profile",
            "created_from_workspace",
        ),
    ),
    "runs": TableSpec(
        "runs",
        ("run_id",),
        (
            "design_id",
            "run_id",
            "parameter_hash",
            "flow_hash",
            "tool_version_hash",
            "workspace_path",
            "status",
            "created_at",
        ),
    ),
    "stages": TableSpec(
        "stages",
        ("stage_id",),
        (
            "design_id",
            "run_id",
            "stage_id",
            "stage_order",
            "stage_name",
            "tool",
            "state",
            "stage_dir",
            "runtime_s",
            "peak_memory_mb",
        ),
        ("run_id", "stage_name"),
    ),
    "artifacts": TableSpec(
        "artifacts",
        ("artifact_id",),
        (
            "artifact_id",
            "design_id",
            "run_id",
            "stage_id",
            "artifact_type",
            "relative_path",
            "sha256",
            "size_bytes",
            "parser",
            "parser_version",
            "availability",
        ),
        ("run_id", "stage_id"),
    ),
    "drc_violations": TableSpec(
        "drc_violations",
        ("design_id", "run_id", "stage_name", "violation_id"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "violation_id",
            "native_type",
            "normalized_class",
            "rule",
            "layer",
            "bbox_json",
            "count",
            "source_artifact_id",
            "source_index",
            "availability",
        ),
        ("run_id", "stage_name"),
    ),
    "placement_rows": TableSpec(
        "placement_rows",
        ("design_id", "run_id", "stage_name", "row_id"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "row_id",
            "site",
            "origin_x",
            "origin_y",
            "orientation",
            "count_x",
            "count_y",
            "step_x",
            "step_y",
            "availability",
        ),
        ("run_id", "stage_name"),
    ),
    "instance_row_refs": TableSpec(
        "instance_row_refs",
        ("design_id", "run_id", "stage_name", "instance_key", "row_id"),
        ("design_id", "run_id", "stage_name", "instance_key", "row_id", "relation", "availability"),
        ("run_id", "stage_name"),
    ),
    "clock_instance_refs": TableSpec(
        "clock_instance_refs",
        ("design_id", "run_id", "stage_name", "instance_key", "net_key", "pin_key"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "instance_key",
            "net_key",
            "pin_key",
            "patch_id",
            "availability",
        ),
        ("run_id", "stage_name"),
    ),
    "provenance": TableSpec(
        "provenance",
        ("provenance_id",),
        (
            "provenance_id",
            "target_table",
            "target_key",
            "target_field",
            "artifact_id",
            "derived_from_artifact_ids",
            "source_section",
            "source_index",
            "availability_code",
            "null_reason",
            "confidence",
            "notes",
        ),
    ),
    "semantic_blocks": TableSpec(
        "semantic_blocks",
        ("design_id", "run_id", "stage_name", "entity_type", "entity_key", "block_name"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "entity_type",
            "entity_key",
            "block_name",
            "block_payload",
            "source_schema_version",
            "source_doc",
            "source_field_path",
            "preserved_reason",
            "normalized_status",
            "future_normalization_plan",
            "target_table",
            "target_key",
        ),
    ),
    "tech_layers": TableSpec(
        "tech_layers",
        ("design_id", "layer_name"),
        (
            "design_id",
            "layer_name",
            "layer_index",
            "routing_direction",
            "pitch",
            "default_width",
            "metadata",
        ),
    ),
    "tech_vias": TableSpec(
        "tech_vias",
        ("design_id", "via_name"),
        (
            "design_id",
            "via_name",
            "cut_layer",
            "lower_layer",
            "upper_layer",
            "is_default",
            "metadata",
        ),
    ),
    "library_cells": TableSpec(
        "library_cells",
        ("design_id", "master"),
        (
            "design_id",
            "master",
            "cell_class",
            "physical_class",
            "width",
            "height",
            "area",
            "pin_count",
            "is_sequential",
            "is_physical_only",
            "metadata",
        ),
    ),
    "patches": TableSpec(
        "patches",
        ("design_id", "patch_id"),
        (
            "design_id",
            "grid_id",
            "patch_id",
            "row",
            "col",
            "bbox_llx",
            "bbox_lly",
            "bbox_urx",
            "bbox_ury",
            "center_x",
            "center_y",
            "width",
            "height",
            "area",
            "edge_position",
        ),
    ),
    "patch_neighbors": TableSpec(
        "patch_neighbors",
        ("design_id", "patch_id", "neighbor_patch_id", "relation"),
        ("design_id", "patch_id", "neighbor_patch_id", "relation"),
    ),
    "run_stage_patch_maps": TableSpec(
        "run_stage_patch_maps",
        ("design_id", "run_id", "stage_name", "patch_id", "category", "channel"),
        (
            "design_id",
            "run_id",
            "stage_id",
            "stage_name",
            "patch_id",
            "category",
            "channel",
            "value",
            "provenance_id",
        ),
        ("run_id", "stage_name"),
    ),
    "run_stage_patch_features": TableSpec(
        "run_stage_patch_features",
        ("design_id", "run_id", "stage_name", "patch_id"),
        (
            "design_id",
            "run_id",
            "stage_id",
            "stage_name",
            "patch_id",
            "cell_density",
            "macro_density",
            "pin_density",
            "net_density",
            "instance_count_center",
            "instance_count_overlap",
            "stdcell_count",
            "macro_count",
            "physical_only_count",
            "net_count_anchor",
            "net_count_overlap",
            "cross_patch_net_count",
            "high_fanout_net_count",
            "clock_net_count",
            "reset_net_count",
            "pg_net_count",
            "local_hpwl_sum",
            "local_hpwl_max",
            "local_hpwl_mean",
            "rudy_horizontal",
            "rudy_vertical",
            "rudy_union",
            "margin_horizontal",
            "margin_vertical",
            "egr_overflow_horizontal",
            "egr_overflow_vertical",
            "egr_overflow_union",
            "wire_length",
            "via_count",
            "critical_path_count",
            "worst_slack_min",
            "max_slew",
            "max_cap",
            "drc_count",
            "feature_availability_code",
            "provenance_id",
        ),
        ("run_id", "stage_name"),
    ),
    "run_patch_route_labels": TableSpec(
        "run_patch_route_labels",
        ("design_id", "run_id", "patch_id"),
        (
            "design_id",
            "run_id",
            "patch_id",
            "horizontal_capacity",
            "horizontal_demand",
            "horizontal_demand_capacity",
            "horizontal_utilization",
            "vertical_capacity",
            "vertical_demand",
            "vertical_demand_capacity",
            "vertical_utilization",
            "union_demand_capacity",
            "union_utilization",
            "tightness_class",
            "label_source_artifact_id",
            "availability_code",
        ),
    ),
    "run_patch_route_label_layers": TableSpec(
        "run_patch_route_label_layers",
        ("design_id", "run_id", "patch_id", "layer_name", "direction"),
        (
            "design_id",
            "run_id",
            "patch_id",
            "layer_name",
            "direction",
            "capacity",
            "demand",
            "demand_capacity",
            "utilization",
            "source_artifact_id",
        ),
    ),
    "patch_entity_refs": TableSpec(
        "patch_entity_refs",
        ("design_id", "run_id", "stage_name", "patch_id", "entity_type", "entity_key", "relation"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "patch_id",
            "entity_type",
            "entity_key",
            "relation",
            "weight",
            "is_primary",
        ),
        ("run_id", "stage_name"),
    ),
    "instances": TableSpec(
        "instances",
        ("design_id", "instance_key"),
        (
            "design_id",
            "instance_key",
            "master",
            "cell_class",
            "physical_class",
            "is_macro",
            "is_physical_only",
            "is_clock_related",
        ),
    ),
    "instance_stage_state": TableSpec(
        "instance_stage_state",
        ("design_id", "run_id", "stage_name", "instance_key"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "instance_key",
            "placement_status",
            "origin_x",
            "origin_y",
            "bbox_llx",
            "bbox_lly",
            "bbox_urx",
            "bbox_ury",
            "orientation",
            "patch_id",
            "overlap_patch_ids",
            "summary_json",
        ),
        ("run_id", "stage_name"),
    ),
    "pins": TableSpec(
        "pins",
        ("design_id", "pin_key"),
        (
            "design_id",
            "pin_key",
            "pin_kind",
            "instance_key",
            "pin_name",
            "full_name",
            "parent_master",
            "is_io",
            "is_macro_pin",
        ),
    ),
    "pin_stage_state": TableSpec(
        "pin_stage_state",
        ("design_id", "run_id", "stage_name", "pin_key"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "pin_key",
            "geometry_status",
            "center_x",
            "center_y",
            "patch_id",
            "overlap_patch_ids",
            "electrical_json",
            "timing_json",
            "route_json",
        ),
        ("run_id", "stage_name"),
    ),
    "nets": TableSpec(
        "nets",
        ("design_id", "net_key"),
        (
            "design_id",
            "net_key",
            "name",
            "use",
            "net_class",
            "is_clock",
            "is_reset",
            "is_power_ground",
            "is_signal",
        ),
    ),
    "net_terminals": TableSpec(
        "net_terminals",
        ("design_id", "run_id", "stage_name", "net_key", "pin_key"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "net_key",
            "pin_key",
            "terminal_role",
            "is_driver",
            "is_sink",
            "patch_id",
            "geometry_status",
            "critical_path_flag",
        ),
        ("run_id", "stage_name"),
    ),
    "wire_segments": TableSpec(
        "wire_segments",
        ("design_id", "run_id", "stage_name", "wire_segment_key"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "wire_segment_key",
            "net_key",
            "source_section",
            "segment_index",
            "layer",
            "start_x",
            "start_y",
            "end_x",
            "end_y",
            "bbox_json",
            "length",
            "direction",
            "via_name",
            "summary_json",
        ),
        ("run_id", "stage_name"),
    ),
    "wire_patch_intersections": TableSpec(
        "wire_patch_intersections",
        ("design_id", "run_id", "stage_name", "wire_segment_key", "patch_id"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "wire_segment_key",
            "patch_id",
            "intersect_length",
            "area_proxy",
            "layer",
            "direction",
            "is_primary",
            "capacity_contribution",
        ),
        ("run_id", "stage_name"),
    ),
    "routing_vertices": TableSpec(
        "routing_vertices",
        ("design_id", "run_id", "stage_name", "net_key", "vertex_id"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "net_key",
            "vertex_id",
            "x",
            "y",
            "layer",
            "vertex_kind",
            "patch_id",
            "terminal_pin_key",
            "match_status",
        ),
        ("run_id", "stage_name"),
    ),
    "routing_edges": TableSpec(
        "routing_edges",
        ("design_id", "run_id", "stage_name", "net_key", "edge_id"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "net_key",
            "edge_id",
            "source_vertex_id",
            "target_vertex_id",
            "edge_kind",
            "geometry_json",
            "layer",
            "length",
            "wire_segment_refs",
        ),
        ("run_id", "stage_name"),
    ),
    "timing_paths": TableSpec(
        "timing_paths",
        ("design_id", "run_id", "stage_name", "path_id"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "path_id",
            "startpoint",
            "endpoint",
            "delay_type",
            "slack",
            "arrival",
            "required",
            "path_group",
            "path_length_summary",
            "criticality",
        ),
        ("run_id", "stage_name"),
    ),
    "timing_path_points": TableSpec(
        "timing_path_points",
        ("design_id", "run_id", "stage_name", "path_id", "point_index"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "path_id",
            "point_index",
            "pin_key",
            "instance_key",
            "net_key",
            "x",
            "y",
            "patch_id",
            "arrival",
            "slew",
            "cap",
            "incr_delay",
        ),
        ("run_id", "stage_name"),
    ),
    "timing_edges": TableSpec(
        "timing_edges",
        ("design_id", "run_id", "stage_name", "path_id", "edge_id"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "path_id",
            "edge_id",
            "from_pin_key",
            "to_pin_key",
            "edge_delay",
            "transition",
            "net_key",
            "edge_kind_source",
        ),
        ("run_id", "stage_name"),
    ),
    "timing_wire_path_nodes": TableSpec(
        "timing_wire_path_nodes",
        ("design_id", "run_id", "stage_name", "path_id", "node_id"),
        (
            "design_id",
            "run_id",
            "stage_name",
            "path_id",
            "node_id",
            "point",
            "cap",
            "slew",
            "incr_delay",
            "match_status",
            "payload_json",
        ),
        ("run_id", "stage_name"),
    ),
    "stage_metrics": TableSpec(
        "stage_metrics",
        ("design_id", "run_id", "stage_name", "metric_name"),
        ("design_id", "run_id", "stage_name", "metric_name", "metric_value", "source_artifact_id"),
        ("run_id", "stage_name"),
    ),
    "stage_deltas": TableSpec(
        "stage_deltas",
        (
            "design_id",
            "run_id",
            "from_stage",
            "to_stage",
            "entity_type",
            "entity_key",
            "change_type",
            "metric_name",
        ),
        (
            "design_id",
            "run_id",
            "from_stage",
            "to_stage",
            "entity_type",
            "entity_key",
            "change_type",
            "metric_name",
            "old_value",
            "new_value",
            "delta_value",
            "provenance_id",
        ),
    ),
}


def schema_document() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_name": CONTRACT_NAME,
        "storage_format": STORAGE_FORMAT,
        "tables": {
            name: {
                "path": f"tables/{name}.parquet",
                "format": "parquet",
                "primary_key": list(spec.primary_key),
                "columns": list(spec.columns),
                "partition_fields": list(spec.partition_fields),
                "arrow_schema": [
                    {"name": field.name, "type": str(field.type)} for field in spec.arrow_schema()
                ],
            }
            for name, spec in TABLE_SPECS.items()
        },
    }


def _registry_entry_from_override(
    name: str, spec: TableSpec, override: Mapping[str, Any]
) -> dict[str, Any]:
    entry = dict(override)
    required = {"path", "format", "row_count", "sha256", "size_bytes"}
    missing = sorted(required - entry.keys())
    if missing:
        raise ValueError(
            f"registry override for skipped table {name} missing: {', '.join(missing)}"
        )
    entry["primary_key"] = list(spec.primary_key)
    entry["partition_fields"] = list(spec.partition_fields)
    return entry


def write_tables(
    foundation_dir: Path,
    tables: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    skip_tables: set[str] | frozenset[str] | None = None,
    registry_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    skip = frozenset(skip_tables or ())
    overrides = registry_overrides or {}
    registry: dict[str, Any] = {}
    for name, spec in TABLE_SPECS.items():
        if name in skip:
            if name not in overrides:
                raise ValueError(f"missing registry override for skipped table: {name}")
            registry[name] = _registry_entry_from_override(name, spec, overrides[name])
            logger.info(
                "foundation_table skipped name=%s path=%s row_count=%s",
                name,
                registry[name].get("path"),
                registry[name].get("row_count"),
            )
            continue
        table_path = foundation_dir / "tables" / f"{name}.parquet"
        start = time.monotonic()
        logger.info("foundation_table start name=%s path=%s", name, table_path)
        row_count = write_parquet(
            table_path, tables.get(name, ()), columns=spec.columns, schema=spec.arrow_schema()
        )
        elapsed = time.monotonic() - start
        registry[name] = {
            "path": f"tables/{name}.parquet",
            "format": "parquet",
            "row_count": row_count,
            "primary_key": list(spec.primary_key),
            "partition_fields": list(spec.partition_fields),
            "sha256": file_sha256(table_path),
            "size_bytes": table_path.stat().st_size,
        }
        logger.info(
            "foundation_table done name=%s row_count=%d size_bytes=%d elapsed=%.2fs",
            name,
            row_count,
            registry[name]["size_bytes"],
            elapsed,
        )
    return registry


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
