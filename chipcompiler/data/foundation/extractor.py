from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import logging
import math
import re
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from .grid.canonical_grid import build_gcell_patch_grid, build_patch_grid, resize_nearest
from .parsers.def_parser import DefData, DefNet, DefTrack, DefWire, parse_def
from .parsers.drc_parser import parse_drc_artifacts
from .parsers.gcell import parse_gcell_info
from .parsers.lef_parser import LefLayer, LefMacro, LefVia, parse_lef_libraries
from .parsers.map_csv import read_numeric_csv, shape
from .parsers.route_native_demand_capacity import parse_route_native_demand_capacity_artifacts
from .parsers.rt_log import parse_rt_log
from .parsers.sta_parser import parse_sta_artifacts
from .schema import ExtractionResult
from .table_contract import (
    CONTRACT_NAME,
    SCHEMA_VERSION,
    STORAGE_FORMAT,
    json_value,
    schema_document,
    write_tables,
)
from .writers import write_json, write_jsonl

FOUNDATION_REL = Path("foundation_data") / "ecc"
_SUPPORTED_PROFILE = "iccd_full_v1"
_ROUTE_COMPLETION_MODES = {"full_route", "space_router_label"}
_STAGE_DIR_OVERRIDES = {
    ("place", "dreamplace"): "place_dreamplace",
    ("legalization", "dreamplace"): "legalization_dreamplace",
}
_ENTITY_NAMES = ("instances", "nets", "pins", "wires", "routing_graphs", "timing_paths", "patches")
_TECH_REQUIRED_TABLES = {"tech_layers": "layers", "tech_vias": "vias", "library_cells": "cells"}
_ATTRIBUTION_INPUT_TABLES = (
    "drc_violations",
    "wire_segments",
    "run_stage_patch_features",
    "instance_stage_state",
    "pin_stage_state",
    "placement_rows",
    "instance_row_refs",
    "clock_instance_refs",
)
_ATTRIBUTION_RULE_VERSIONS = {
    "C1": "clock_placement_attribution.v1",
    "R1": "route_local.v1",
    "R3": "congestion_or_pin_access.v1",
    "D1": "native_drc_wire_via_open_short.v1",
    "D2": "native_drc_overlap_site_row.v1",
}
_ATTRIBUTION_SEED_ID_LIMIT = 32
_BASE_DELTA_STATIC_TABLES = frozenset(
    {
        "designs",
        "tech_layers",
        "tech_vias",
        "library_cells",
        "patches",
        "patch_neighbors",
    }
)
_DENSITY_MAP_KEY_ORDER = (
    "allcell_density",
    "macro_density",
    "stdcell_density",
    "allcell_pin_density",
    "macro_pin_density",
    "stdcell_pin_density",
    "allnet_density",
    "local_net_density",
    "global_net_density",
)
MapMatrix = list[list[float]]
StageMaps = dict[str, dict[str, MapMatrix]]
CanonicalMaps = dict[str, StageMaps]
logger = logging.getLogger("ecos.api.foundation")
T = TypeVar("T")


@dataclass(frozen=True)
class StageInfo:
    name: str
    tool: str
    state: str
    directory: Path


@dataclass(frozen=True)
class _PatchGridLookup:
    patches_by_coord: dict[tuple[int, int], dict[str, Any]]
    patches_by_id: dict[int, dict[str, Any]]
    row_bounds: list[tuple[float, float]]
    col_bounds: list[tuple[float, float]]
    rectangular: bool
    uniform: bool
    row_origin: float | None
    col_origin: float | None
    row_step: float | None
    col_step: float | None


_PATCH_GRID_LOOKUP_CACHE: dict[tuple[int, int, int, int], _PatchGridLookup | None] = {}


def _normalize_route_completion_mode(value: object) -> str:
    mode = str(value or "full_route").strip() or "full_route"
    if mode not in _ROUTE_COMPLETION_MODES:
        allowed = ", ".join(sorted(_ROUTE_COMPLETION_MODES))
        raise ValueError(f"route_completion_mode must be one of: {allowed}")
    return mode


def _normalize_route_detail_level(value: object) -> str:
    level = str(value or "full").strip() or "full"
    if level not in {"full", "labels_only"}:
        raise ValueError("route_detail_level must be one of: full, labels_only")
    return level


class FoundationExtractor:
    """Post-run foundation-data extractor for ECOS/ECC workspaces.

    The extractor intentionally reads existing workspace artifacts and writes a
    versioned, sharded JSON/JSONL contract under ``foundation_data/ecc``. It does
    not mutate flow outputs or require re-running any EDA step.
    """

    def __init__(self, workspace_dir: str | Path, *, profile: str = _SUPPORTED_PROFILE) -> None:
        if profile != _SUPPORTED_PROFILE:
            raise ValueError(f"unsupported foundation profile: {profile}")
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.profile = profile
        self.foundation_dir = self.workspace_dir / FOUNDATION_REL
        self._quality: dict[str, Any] = {"availability": {}, "null_reason": {}, "warnings": []}
        self._raw_refs: list[dict[str, Any]] = []
        self._raw_ref_by_stage_type_key: dict[tuple[str, str, str], str] = {}
        self._exact_gcell_map_keys: set[tuple[str, str, str]] = set()
        self._lef_macros: dict[str, LefMacro] = {}
        self._lef_layers: dict[str, LefLayer] = {}
        self._lef_vias: dict[str, LefVia] = {}
        self._tech_records: dict[str, list[dict[str, Any]]] = {
            "layers": [],
            "vias": [],
            "cells": [],
        }
        self._source_signature_cache: list[str] | None = None

    def extract(
        self,
        *,
        force: bool = False,
        stages: Any = "all",
        include_raw_refs: bool = True,
        export_legacy_debug: bool = False,
        scope: str = "full",
        base_manifest_path: str | None = None,
        route_completion_mode: str = "full_route",
        materialize_audit_tables: bool = True,
        route_detail_level: str = "full",
    ) -> ExtractionResult:
        extract_start = time.monotonic()
        del force  # The current post-run extractor is deterministic and always rewrites outputs.
        scope = str(scope or "full").strip()
        if scope not in {"full", "design_base", "variant_delta"}:
            raise ValueError("scope must be one of: full, design_base, variant_delta")
        if scope == "variant_delta" and not base_manifest_path:
            raise ValueError("scope=variant_delta requires base_manifest_path")
        route_completion_mode = _normalize_route_completion_mode(route_completion_mode)
        materialize_audit_tables = bool(materialize_audit_tables)
        route_detail_level = _normalize_route_detail_level(route_detail_level)
        self._source_signature_cache = None
        if self.foundation_dir.exists():
            shutil.rmtree(self.foundation_dir)
        logger.info(
            "foundation_extract start workspace=%s profile=%s scope=%s "
            "stages=%s include_raw_refs=%s",
            self.workspace_dir,
            self.profile,
            scope,
            stages,
            include_raw_refs,
        )
        flow = self._run_logged_stage(
            "read_flow", lambda: self._read_json(self.workspace_dir / "home" / "flow.json")
        )
        parameters = self._run_logged_stage(
            "read_parameters",
            lambda: self._read_json(self.workspace_dir / "home" / "parameters.json"),
        )
        self._lef_macros = self._run_logged_stage(
            "load_lef", lambda: self._load_lef_macros(parameters)
        )
        selected_stages = self._filter_stages(self._stage_infos(flow), stages)
        logger.info(
            "foundation_extract selected_stages workspace=%s stages=%s",
            self.workspace_dir,
            ",".join(stage.name for stage in selected_stages),
        )
        options = {
            "stages": [stage.name for stage in selected_stages],
            "include_raw_refs": bool(include_raw_refs),
            "export_legacy_debug": bool(export_legacy_debug),
            "route_completion_mode": route_completion_mode,
            "materialize_audit_tables": materialize_audit_tables,
            "route_detail_level": route_detail_level,
        }
        if scope != "full":
            options["scope"] = scope
        if base_manifest_path:
            options["base_manifest_path"] = str(base_manifest_path)
        self._legacy_debug_enabled = bool(export_legacy_debug)
        self._vector_records: dict[str, dict[str, list[dict[str, Any]]]] = {
            entity: {} for entity in _ENTITY_NAMES
        }
        def_data = self._run_logged_stage(
            "collect_def_data", lambda: self._collect_def_data(selected_stages)
        )
        rt_logs = self._run_logged_stage(
            "collect_rt_logs", lambda: self._collect_rt_logs(selected_stages)
        )
        sta_reports = self._run_logged_stage(
            "collect_sta_reports", lambda: self._collect_sta_reports(selected_stages)
        )
        drc_reports = self._run_logged_stage(
            "collect_drc_reports", lambda: self._collect_drc_reports(selected_stages)
        )
        raw_maps = self._run_logged_stage(
            "collect_raw_maps", lambda: self._collect_raw_maps(selected_stages)
        )
        self._run_logged_stage(
            "merge_egr_demand_capacity_maps",
            lambda: self._merge_egr_demand_capacity_maps(raw_maps, selected_stages),
        )
        die_bbox = self._run_logged_stage(
            "discover_die_bbox",
            lambda: self._discover_die_bbox(selected_stages)
            or self._discover_def_die_bbox(def_data),
        )
        canonical_grid = self._run_logged_stage(
            "build_canonical_grid",
            lambda: self._build_canonical_grid(raw_maps, die_bbox, selected_stages),
        )
        canonical_maps = self._run_logged_stage(
            "write_maps",
            lambda: self._write_maps(raw_maps, canonical_grid, selected_stages, def_data),
        )
        self._run_logged_stage(
            "ensure_floorplan_maps",
            lambda: self._ensure_floorplan_maps(
                selected_stages, canonical_grid, canonical_maps, def_data
            ),
        )
        self._run_logged_stage(
            "ensure_floorplan_specific_maps",
            lambda: self._ensure_floorplan_specific_maps(
                selected_stages, canonical_grid, canonical_maps, def_data
            ),
        )
        if export_legacy_debug:
            self._run_logged_stage(
                "write_indexed_maps",
                lambda: self._write_indexed_maps(canonical_maps, canonical_grid),
            )
        route_stage = next((stage for stage in selected_stages if stage.name == "route"), None)
        native_demand_capacity = self._run_logged_stage(
            "parse_route_native_demand_capacity",
            lambda: parse_route_native_demand_capacity_artifacts(
                route_stage.directory, canonical_grid
            )
            if route_stage
            else {"available": False, "labels": []},
        )
        labels = self._run_logged_stage(
            "write_labels",
            lambda: self._write_labels(
                native_demand_capacity.get("labels", []),
                export_legacy_debug=export_legacy_debug,
            ),
        )
        self._run_logged_stage(
            "write_tech", lambda: self._write_tech(def_data, rt_logs, selected_stages)
        )
        entity_counts = self._run_logged_stage(
            "write_vectors",
            lambda: self._write_vectors(
                selected_stages,
                canonical_grid,
                canonical_maps,
                def_data,
                labels,
                sta_reports,
                drc_reports,
                export_legacy_debug=export_legacy_debug,
            ),
        )
        self._run_logged_stage(
            "record_wire_quality", lambda: self._record_wire_quality(selected_stages)
        )
        self._run_logged_stage(
            "record_patch_quality",
            lambda: self._record_patch_quality(selected_stages, canonical_grid),
        )
        public_labels = {key: value for key, value in labels.items() if not key.startswith("_")}
        stage_index = self._run_logged_stage(
            "build_stage_index", lambda: self._build_stage_index(selected_stages)
        )
        metrics = self._run_logged_stage(
            "collect_metrics", lambda: self._collect_metrics(selected_stages)
        )
        summary_parameters = self._run_logged_stage(
            "build_summary_parameters",
            lambda: self._build_summary_parameters(parameters, selected_stages, def_data),
        )
        summary = self._run_logged_stage(
            "build_summary",
            lambda: self._build_summary(
                flow,
                summary_parameters,
                selected_stages,
                metrics,
                entity_counts,
                public_labels,
                def_data,
                sta_reports,
                drc_reports,
            ),
        )
        table_rows = self._run_logged_stage(
            "build_table_rows",
            lambda: self._build_table_rows(
                flow=flow,
                parameters=summary_parameters,
                stages=selected_stages,
                canonical_grid=canonical_grid,
                canonical_maps=canonical_maps,
                labels=labels,
                metrics=metrics,
                drc_reports=drc_reports,
                def_data=def_data,
                skip_tables=_BASE_DELTA_STATIC_TABLES if scope == "variant_delta" else frozenset(),
                materialize_audit_tables=materialize_audit_tables,
                route_detail_level=route_detail_level,
            ),
        )
        base_tables = (
            self._load_base_manifest_tables(base_manifest_path) if scope == "variant_delta" else {}
        )
        skip_tables = _BASE_DELTA_STATIC_TABLES if scope == "variant_delta" else frozenset()
        missing_static_tables = sorted(skip_tables - base_tables.keys())
        if missing_static_tables:
            raise ValueError(
                "base manifest missing static foundation tables: "
                + ", ".join(missing_static_tables)
            )
        table_registry = self._run_logged_stage(
            "write_tables",
            lambda: write_tables(
                self.foundation_dir,
                table_rows,
                skip_tables=skip_tables,
                registry_overrides={name: base_tables[name] for name in skip_tables},
            ),
        )
        table_registry = self._with_base_delta_sources(
            table_registry,
            scope=scope,
            base_manifest_path=base_manifest_path,
            base_tables=base_tables,
        )
        schema = schema_document()
        manifest = self._run_logged_stage(
            "build_manifest",
            lambda: self._build_manifest(
                selected_stages,
                raw_maps,
                summary,
                options=options,
                table_registry=table_registry,
                table_rows=table_rows,
            ),
        )
        self._quality["tables"] = {
            name: {"row_count": meta["row_count"], "path": meta["path"]}
            for name, meta in table_registry.items()
        }
        tech_materialization_errors = self._run_logged_stage(
            "record_tech_materialization_quality",
            lambda: self._record_tech_materialization_quality(table_registry),
        )
        self._quality["legacy_outputs"] = {
            "vectors_default_enabled": bool(export_legacy_debug),
            "maps_default_enabled": bool(export_legacy_debug),
            "jsonl_export": "explicit_debug_export_only",
        }

        self._run_logged_stage(
            "write_canonical_grid",
            lambda: write_json(self.foundation_dir / "canonical_grid.json", canonical_grid),
        )
        self._run_logged_stage(
            "write_stage_index",
            lambda: write_json(self.foundation_dir / "stage_index.json", stage_index),
        )
        self._run_logged_stage(
            "write_summary", lambda: write_json(self.foundation_dir / "summary.json", summary)
        )
        self._run_logged_stage(
            "write_schema", lambda: write_json(self.foundation_dir / "schema.json", schema)
        )
        self._run_logged_stage(
            "write_migration_report",
            lambda: write_json(
                self.foundation_dir / "migration_report.json", self._build_migration_report()
            ),
        )
        if include_raw_refs:
            self._run_logged_stage(
                "write_raw_refs",
                lambda: write_json(
                    self.foundation_dir / "raw_refs" / "artifacts.json",
                    {"artifacts": self._raw_refs},
                ),
            )
        self._run_logged_stage(
            "write_quality", lambda: write_json(self.foundation_dir / "quality.json", self._quality)
        )
        if tech_materialization_errors:
            raise RuntimeError(
                "foundation tech materialization failed: " + "; ".join(tech_materialization_errors)
            )
        self._run_logged_stage(
            "write_manifest", lambda: write_json(self.foundation_dir / "manifest.json", manifest)
        )
        self._run_logged_stage(
            "write_views",
            lambda: self._write_views(
                summary,
                metrics,
                stage_index,
                public_labels,
                manifest=manifest,
                drc_violation_rows=table_rows.get("drc_violations", ()),
                include_raw_refs=bool(include_raw_refs),
                route_completion_mode=route_completion_mode,
                route_detail_level=route_detail_level,
            ),
        )
        if not export_legacy_debug:
            self._run_logged_stage(
                "remove_legacy_default_outputs", self._remove_legacy_default_outputs
            )

        logger.info(
            "foundation_extract done workspace=%s profile=%s scope=%s elapsed=%.2fs",
            self.workspace_dir,
            self.profile,
            scope,
            time.monotonic() - extract_start,
        )

        return ExtractionResult(
            workspace_dir=self.workspace_dir,
            foundation_dir=self.foundation_dir,
            profile=self.profile,
            manifest=manifest,
            summary=summary,
        )

    def _run_logged_stage(self, name: str, func: Callable[[], T]) -> T:
        start = time.monotonic()
        logger.info("foundation_stage start name=%s workspace=%s", name, self.workspace_dir)
        try:
            result = func()
        except Exception:
            logger.exception(
                "foundation_stage error name=%s workspace=%s elapsed=%.2fs",
                name,
                self.workspace_dir,
                time.monotonic() - start,
            )
            raise
        logger.info(
            "foundation_stage done name=%s workspace=%s elapsed=%.2fs",
            name,
            self.workspace_dir,
            time.monotonic() - start,
        )
        return result

    def _load_base_manifest_tables(self, base_manifest_path: str | None) -> dict[str, Any]:
        if not base_manifest_path:
            return {}
        path = Path(base_manifest_path)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"base manifest not found: {path}") from exc
        tables = manifest.get("tables")
        if not isinstance(tables, dict):
            raise ValueError(f"base manifest missing tables object: {path}")
        return tables

    def _with_base_delta_sources(
        self,
        table_registry: dict[str, Any],
        *,
        scope: str,
        base_manifest_path: str | None,
        base_tables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del base_manifest_path
        if scope == "full":
            return table_registry
        updated: dict[str, Any] = {}
        for name, meta in table_registry.items():
            if scope == "variant_delta" and name in _BASE_DELTA_STATIC_TABLES:
                meta = dict((base_tables or {})[name])
                source_root = "design_base"
            else:
                source_root = "design_base" if scope == "design_base" else "variant_delta"
            updated[name] = {
                **meta,
                "sources": [{"root": source_root, "path": meta["path"]}],
            }
        return updated

    def _stage_infos(self, flow: dict[str, Any]) -> list[StageInfo]:
        stages = []
        for item in flow.get("steps", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            tool = str(item.get("tool", "")).strip()
            if not name or not tool:
                continue
            directory = self.workspace_dir / _STAGE_DIR_OVERRIDES.get(
                (name, tool), f"{name}_{tool}"
            )
            stages.append(
                StageInfo(
                    name=name, tool=tool, state=str(item.get("state", "")), directory=directory
                )
            )
        return stages

    @staticmethod
    def _filter_stages(stages: list[StageInfo], requested: Any) -> list[StageInfo]:
        if requested is None:
            return stages
        if isinstance(requested, str):
            normalized = requested.strip()
            if not normalized or normalized.lower() == "all":
                return stages
            requested_names = [item.strip() for item in normalized.split(",") if item.strip()]
        elif isinstance(requested, list | tuple | set):
            requested_names = [str(item).strip() for item in requested if str(item).strip()]
        else:
            raise ValueError("stages must be 'all', a stage name, or a list of stage names")
        if not requested_names:
            return stages
        by_name = {stage.name: stage for stage in stages}
        unknown = [name for name in requested_names if name not in by_name]
        if unknown:
            raise ValueError(f"unknown foundation extraction stage: {', '.join(unknown)}")
        return [by_name[name] for name in requested_names]

    def _load_lef_macros(self, parameters: dict[str, Any]) -> dict[str, LefMacro]:
        pdk_root = parameters.get("PDK Root") or parameters.get("pdk_root")
        if not pdk_root:
            self._mark("tech", "lef", "missing", "missing_pdk_root")
            return {}
        root = Path(str(pdk_root)).expanduser()
        if not root.is_absolute():
            root = (self.workspace_dir / root).resolve()
        if not root.exists():
            self._mark("tech", "lef", "missing", "missing_pdk_root")
            return {}
        paths = sorted([*root.rglob("*.lef"), *root.rglob("*.tlef")])
        library = parse_lef_libraries(paths)
        self._lef_layers = library.layers
        self._lef_vias = library.vias
        self._quality.setdefault("tech", {})["lef_macro_count"] = len(library.macros)
        self._quality.setdefault("tech", {})["lef_layer_count"] = len(library.layers)
        self._quality.setdefault("tech", {})["lef_via_count"] = len(library.vias)
        has_lef_data = bool(library.macros or library.layers or library.vias)
        self._mark(
            "tech",
            "lef",
            "available" if has_lef_data else "missing",
            "" if has_lef_data else "missing_lef_records",
        )
        return library.macros

    def _collect_def_data(self, stages: list[StageInfo]) -> dict[str, DefData]:
        out: dict[str, DefData] = {}
        for stage in stages:
            candidates = sorted((stage.directory / "output").glob("*.def")) + sorted(
                (stage.directory / "output").glob("*.def.gz")
            )
            if not candidates:
                self._mark("defs", stage.name, "missing", "missing_def_output")
                continue
            try:
                parsed = parse_def(candidates[0])
            except (
                Exception
            ) as exc:  # pragma: no cover - defensive boundary around external artifacts
                self._mark("defs", stage.name, "missing", f"def_parse_error:{exc}")
                continue
            out[stage.name] = parsed
            self._mark("defs", stage.name, "available")
            self._record_raw_ref(
                stage,
                candidates[0],
                "def",
                {"nets": len(parsed.nets), "wires": sum(len(net.wires) for net in parsed.nets)},
            )
        return out

    def _collect_rt_logs(self, stages: list[StageInfo]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for stage in stages:
            candidates = sorted((stage.directory / "data" / "rt").rglob("rt.log")) + sorted(
                (stage.directory / "log").glob("*.log")
            )
            parsed = (
                parse_rt_log(candidates[0])
                if candidates
                else {"available": False, "layers": [], "totals": {}}
            )
            if parsed.get("available"):
                out[stage.name] = parsed
                self._mark("rt_log", stage.name, "available")
                self._record_raw_ref(
                    stage, Path(parsed["source"]), "rt_log", {"totals": parsed.get("totals", {})}
                )
            else:
                self._mark("rt_log", stage.name, "missing", "missing_rt_log")
        return out

    def _collect_sta_reports(self, stages: list[StageInfo]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for stage in stages:
            parsed = parse_sta_artifacts(stage.directory)
            if parsed.get("available"):
                out[stage.name] = parsed
                self._mark("sta", stage.name, "available")
                source = Path(str(parsed.get("source", "")))
                if source.exists():
                    self._record_raw_ref(
                        stage, source, "sta_report_json", {"paths": len(parsed.get("records", []))}
                    )
                for wire_source in parsed.get("wire_path_sources", []):
                    wire_path = Path(str(wire_source))
                    if wire_path.exists():
                        self._record_raw_ref(stage, wire_path, "sta_wire_path", {})
            else:
                self._mark("sta", stage.name, "missing", "missing_sta_report")
        return out

    def _collect_drc_reports(self, stages: list[StageInfo]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for stage in stages:
            parsed = parse_drc_artifacts(stage.directory)
            if parsed.get("available"):
                out[stage.name] = parsed
                self._mark("drc", stage.name, "available")
                source = Path(str(parsed.get("source", "")))
                if source.exists():
                    self._record_raw_ref(
                        stage, source, "drc_violation_map", {"count": parsed.get("count", 0)}
                    )
            else:
                self._mark("drc", stage.name, "missing", "missing_drc_artifacts")
        return out

    def _collect_raw_maps(
        self, stages: list[StageInfo]
    ) -> dict[str, dict[str, dict[str, list[list[float]]]]]:
        out: dict[str, dict[str, dict[str, list[list[float]]]]] = {}
        for stage in stages:
            stage_maps: dict[str, dict[str, list[list[float]]]] = {}
            feature_dir = stage.directory / "feature"
            for csv_path in sorted(feature_dir.rglob("*.csv")):
                matrix = read_numeric_csv(csv_path)
                if not matrix:
                    continue
                category, key = self._classify_map(csv_path)
                if category == "ignored" or (
                    category == "congestion" and stage.name not in {"place", "CTS"}
                ):
                    continue
                exact_gcell_map = "gcell_patch_map" in csv_path.parts
                if exact_gcell_map:
                    self._exact_gcell_map_keys.add((stage.name, category, key))
                if (
                    key in stage_maps.setdefault(category, {})
                    and not exact_gcell_map
                    and (stage.name, category, key) in self._exact_gcell_map_keys
                ):
                    continue
                stage_maps[category][key] = matrix
                self._record_raw_ref(
                    stage,
                    csv_path,
                    "gcell_patch_map_csv" if exact_gcell_map else "map_csv",
                    {
                        "category": category,
                        "key": key,
                        "shape": shape(matrix),
                        "grid_source": "irt_gcell_info" if exact_gcell_map else "tool_default",
                    },
                )
            if stage_maps:
                out[stage.name] = stage_maps
                self._quality.setdefault("availability", {}).setdefault("maps", {})[stage.name] = (
                    "available"
                )
            else:
                self._quality.setdefault("availability", {}).setdefault("maps", {})[stage.name] = (
                    "missing"
                )
        return out

    def _merge_egr_demand_capacity_maps(
        self,
        raw_maps: dict[str, dict[str, dict[str, list[list[float]]]]],
        stages: list[StageInfo],
    ) -> None:
        for stage in stages:
            if stage.name not in {"place", "CTS"}:
                continue
            existing = raw_maps.get(stage.name, {}).get("congestion", {})
            if existing.get("union"):
                continue
            maps, source_paths = _egr_demand_capacity_maps_from_stage(stage.directory)
            if not maps:
                continue
            raw_maps.setdefault(stage.name, {})["congestion"] = maps
            self._quality.setdefault("availability", {}).setdefault("maps", {})[stage.name] = (
                "available"
            )
            for source_path in source_paths:
                self._record_raw_ref(
                    stage,
                    source_path,
                    "egr_demand_capacity_map_csv",
                    {"category": "congestion", "grid_source": "irt_early_router"},
                )

    @staticmethod
    def _classify_map(path: Path) -> tuple[str, str]:
        name = path.stem.lower()
        direction = "union"
        for candidate in ("horizontal", "vertical", "union"):
            if candidate in name:
                direction = candidate
                break
        if "egr" in name and "overflow" in name:
            return "congestion", direction
        if "rudy" in name:
            if "lut" in name:
                return "ignored", name
            return "rudy", f"rudy_{direction}"
        if "margin" in name:
            return "margin", direction
        if "density" in name:
            return "density", name
        return "other", name

    def _discover_die_bbox(self, stages: list[StageInfo]) -> dict[str, float] | None:
        for stage in stages:
            for layout_path in sorted((stage.directory / "output").glob("*.json")):
                payload = self._read_json(layout_path)
                bbox = self._die_bbox_from_layout(payload)
                if bbox is not None:
                    return bbox
        return None

    @staticmethod
    def _discover_def_die_bbox(def_data: dict[str, DefData]) -> dict[str, float] | None:
        for parsed in def_data.values():
            if parsed.diearea:
                return parsed.diearea
        return None

    @staticmethod
    def _die_bbox_from_layout(payload: dict[str, Any]) -> dict[str, float] | None:
        diearea = payload.get("diearea") if isinstance(payload, dict) else None
        path = diearea.get("path") if isinstance(diearea, dict) else None
        if not isinstance(path, list) or not path:
            return None
        xs: list[float] = []
        ys: list[float] = []
        for point in path:
            if isinstance(point, list | tuple) and len(point) >= 2:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
        if not xs or not ys:
            return None
        return {"llx": min(xs), "lly": min(ys), "urx": max(xs), "ury": max(ys)}

    def _build_canonical_grid(
        self,
        raw_maps: dict[str, dict[str, dict[str, list[list[float]]]]],
        die_bbox: dict[str, float] | None,
        stages: list[StageInfo],
    ) -> dict:
        gcell = self._discover_gcell_info(stages)
        if gcell:
            path, cells = gcell
            with contextlib.suppress(StopIteration, ValueError):
                self._record_raw_ref(
                    next(stage for stage in stages if path.is_relative_to(stage.directory)),
                    path,
                    "irt_gcell_info",
                    {"cells": len(cells)},
                )
            self._mark("grid", "canonical", "available")
            return build_gcell_patch_grid(
                cells,
                source=str(path.relative_to(self.workspace_dir))
                if path.is_relative_to(self.workspace_dir)
                else str(path),
            )
        rows = 1
        cols = 1
        for stage_maps in raw_maps.values():
            for category_maps in stage_maps.values():
                for matrix in category_maps.values():
                    src_rows, src_cols = shape(matrix)
                    rows = max(rows, src_rows)
                    cols = max(cols, src_cols)
        self._mark("grid", "canonical", "available")
        return build_patch_grid(rows, cols, die_bbox)

    def _discover_gcell_info(
        self, stages: list[StageInfo]
    ) -> tuple[Path, list[dict[str, Any]]] | None:
        candidates: list[Path] = []
        for preferred in ("route", "CTS", "place"):
            candidates.extend(
                stage.directory
                / "data"
                / "rt"
                / "rt_temp_directory"
                / "early_router"
                / "gcell.info"
                for stage in stages
                if stage.name == preferred
            )
        candidates.extend(
            stage.directory / "data" / "rt" / "rt_temp_directory" / "early_router" / "gcell.info"
            for stage in stages
        )
        for path in candidates:
            if not path.exists():
                continue
            cells = parse_gcell_info(path)
            if cells:
                return path, cells
        return None

    def _write_maps(
        self,
        raw_maps: dict[str, dict[str, dict[str, list[list[float]]]]],
        canonical_grid: dict,
        stages: list[StageInfo],
        def_data: dict[str, DefData],
    ) -> dict[str, dict[str, dict[str, list[list[float]]]]]:
        rows = int(canonical_grid["rows"])
        cols = int(canonical_grid["cols"])
        stages_by_name = {stage.name: stage for stage in stages}
        canonical: dict[str, dict[str, dict[str, list[list[float]]]]] = {}
        for stage, stage_maps in raw_maps.items():
            for category, category_maps in stage_maps.items():
                normalized = self._canonicalize_maps_for_grid(
                    category,
                    category_maps,
                    canonical_grid,
                    stages_by_name.get(stage),
                    def_data.get(stage),
                    rows,
                    cols,
                )
                canonical.setdefault(stage, {})[category] = normalized
        return canonical

    def _canonicalize_maps_for_grid(
        self,
        category: str,
        category_maps: dict[str, list[list[float]]],
        canonical_grid: dict,
        stage: StageInfo | None,
        parsed_def: DefData | None,
        rows: int,
        cols: int,
    ) -> dict[str, list[list[float]]]:
        if category == "congestion":
            for key, matrix in category_maps.items():
                src_shape = shape(matrix)
                if src_shape != (rows, cols):
                    self._quality.setdefault("warnings", []).append(
                        f"congestion map {stage.name if stage else 'unknown'}:{key} "
                        f"shape {src_shape} does not match canonical gcell grid {(rows, cols)}; "
                        "kept raw without resize"
                    )
            return {
                key: [[float(value) for value in row] for row in matrix]
                for key, matrix in category_maps.items()
            }
        if (
            canonical_grid.get("grid_source") == "irt_gcell_info"
            and stage is not None
            and category in {"density", "rudy", "margin"}
        ):
            exact_maps = {
                key: [[float(value) for value in row] for row in matrix]
                for key, matrix in category_maps.items()
                if (stage.name, category, key) in self._exact_gcell_map_keys
                and shape(matrix) == (rows, cols)
            }
            missing_maps = {
                key: matrix for key, matrix in category_maps.items() if key not in exact_maps
            }
            if missing_maps:
                self._quality.setdefault("warnings", []).append(
                    f"exact ecc-tools gcell patch maps missing for "
                    f"{stage.name}:{category}:{sorted(missing_maps)}; "
                    "omitted approximate Python recomputation"
                )
            if category == "density":
                exact_maps = _strip_stage_prefix_from_density_maps(exact_maps, stage.name)
                _rebuild_allcell_maps(exact_maps)
            return exact_maps
        resized = {key: resize_nearest(matrix, rows, cols) for key, matrix in category_maps.items()}
        if category == "density" and stage is not None:
            return _strip_stage_prefix_from_density_maps(resized, stage.name)
        return resized

    def _ensure_floorplan_maps(
        self,
        stages: list[StageInfo],
        canonical_grid: dict,
        canonical_maps: CanonicalMaps,
        def_data: dict[str, DefData],
    ) -> None:
        stage = next((item for item in stages if item.name == "Floorplan"), None)
        if stage is None or canonical_maps.get("Floorplan"):
            return
        zero_density = _zero_density_maps(canonical_grid)
        if not zero_density:
            return
        canonical_maps["Floorplan"] = {"density": zero_density}
        self._quality.setdefault("availability", {}).setdefault("maps", {})["Floorplan"] = (
            "available"
        )
        self._quality.get("null_reason", {}).get("maps", {}).pop("Floorplan", None)

    def _ensure_floorplan_specific_maps(
        self,
        stages: list[StageInfo],
        canonical_grid: dict,
        canonical_maps: CanonicalMaps,
        def_data: dict[str, DefData],
    ) -> None:
        stage = next((item for item in stages if item.name == "Floorplan"), None)
        parsed_def = def_data.get("Floorplan")
        if stage is None or parsed_def is None:
            return
        layout_physical_only_cells = self._floorplan_physical_only_cells_from_layout(stage)
        maps = _floorplan_specific_patch_maps(
            parsed_def, canonical_grid, layout_physical_only_cells
        )
        if not maps:
            return
        canonical_maps.setdefault("Floorplan", {})["floorplan"] = maps
        self._record_raw_ref(
            stage,
            parsed_def.path,
            "floorplan_specific_def_maps",
            {
                "category": "floorplan",
                "keys": list(maps),
                "grid_source": canonical_grid.get("grid_source"),
            },
        )
        self._quality.setdefault("availability", {}).setdefault("maps", {})["Floorplan"] = (
            "available"
        )
        self._quality.get("null_reason", {}).get("maps", {}).pop("Floorplan", None)

    def _floorplan_physical_only_cells_from_layout(self, stage: StageInfo) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for layout_path in sorted((stage.directory / "output").glob("*.json")):
            payload = self._read_json(layout_path)
            if not isinstance(payload.get("data"), list):
                continue
            for item in payload.get("data", []):
                if not isinstance(item, dict) or item.get("type") != "group":
                    continue
                name = str(item.get("struct name") or "")
                if not _is_physical_only_cell_name(name, ""):
                    continue
                bbox = self._bbox_from_children(item.get("children", []))
                if bbox is None:
                    continue
                llx, lly, urx, ury = bbox
                out.append({"llx": llx, "lly": lly, "urx": urx, "ury": ury})
            if out:
                self._record_raw_ref(
                    stage, layout_path, "floorplan_physical_only_layout_json", {"count": len(out)}
                )
                break
        return out

    def _write_indexed_maps(self, canonical_maps: CanonicalMaps, canonical_grid: dict) -> None:
        for stage, stage_maps in canonical_maps.items():
            for category, category_maps in stage_maps.items():
                payload = {
                    "stage": stage,
                    "category": category,
                    "grid": {
                        "source": canonical_grid.get("grid_source"),
                        "rows": int(canonical_grid.get("rows", 0)),
                        "cols": int(canonical_grid.get("cols", 0)),
                    },
                    "maps": {
                        key: {"values": _matrix_to_patch_values(matrix, canonical_grid)}
                        for key, matrix in category_maps.items()
                    },
                }
                write_json(self.foundation_dir / "maps" / stage / f"{category}.json", payload)

    def _write_tech(
        self,
        def_data: dict[str, DefData],
        rt_logs: dict[str, dict[str, Any]],
        stages: list[StageInfo],
    ) -> None:
        stage_names = [stage.name for stage in stages]
        stage_order = {stage.name: idx for idx, stage in enumerate(stages)}
        layer_items: dict[str, dict[str, Any]] = {}
        cell_items: dict[str, dict[str, Any]] = {}
        via_items: dict[str, dict[str, Any]] = {}
        pin_names_by_master: dict[str, set[str]] = {}
        pin_layers_by_master: dict[str, set[str]] = {}
        pin_clock_by_master: dict[str, set[str]] = {}
        pin_pg_by_master: dict[str, set[str]] = {}

        for stage_name, parsed in def_data.items():
            for track in parsed.tracks:
                item = layer_items.setdefault(track.layer, _empty_layer_item(track.layer))
                item["track_axes"].append(
                    {
                        "axis": track.axis,
                        "start": track.start,
                        "count": track.count,
                        "step": track.step,
                        "stage": stage_name,
                    }
                )
                item["stage_sources"].setdefault(stage_name, set()).add("def_tracks")
                item["source_refs_def"].append(
                    {
                        "path": _workspace_relative_path(parsed.path, self.workspace_dir),
                        "stage": stage_name,
                        "section": "TRACKS",
                        "layer": track.layer,
                    }
                )
            for component in parsed.components:
                master = str(component["master"])
                cell = cell_items.setdefault(
                    master,
                    {
                        "name": master,
                        "stage_instance_counts": {},
                        "source_refs_def": [],
                        "bbox_sizes": [],
                    },
                )
                cell["stage_instance_counts"][stage_name] = (
                    cell["stage_instance_counts"].get(stage_name, 0) + 1
                )
                cell["source_refs_def"].append(
                    {
                        "path": _workspace_relative_path(parsed.path, self.workspace_dir),
                        "stage": stage_name,
                        "section": "COMPONENTS",
                        "master": master,
                    }
                )
            component_master_by_name = {
                str(component.get("name")): str(component.get("master"))
                for component in parsed.components
            }
            for pin in parsed.pins:
                for pin_shape in pin.get("shapes", []) or []:
                    layer = pin_shape.get("layer")
                    if layer:
                        layer_items.setdefault(str(layer), _empty_layer_item(str(layer)))[
                            "stage_sources"
                        ].setdefault(stage_name, set()).add("def_pin_layers")
            for net in parsed.nets:
                for pin in net.pins:
                    master = component_master_by_name.get(str(pin.get("instance")))
                    if not master:
                        continue
                    pin_name = str(pin.get("pin_name"))
                    pin_names_by_master.setdefault(master, set()).add(pin_name)
                    if _is_clock_pin_name(pin_name):
                        pin_clock_by_master.setdefault(master, set()).add(pin_name)
                    if _is_power_ground_pin_name(pin_name):
                        pin_pg_by_master.setdefault(master, set()).add(pin_name)
                for wire in net.wires:
                    if wire.layer:
                        layer_items.setdefault(wire.layer, _empty_layer_item(wire.layer))[
                            "stage_sources"
                        ].setdefault(stage_name, set()).add("def_routed_wires")
                    if wire.via:
                        via = via_items.setdefault(
                            wire.via, _empty_via_item(wire.via, source="def_routed_wires")
                        )
                        via["usage_count"] = int(via.get("usage_count", 0)) + 1
                        via["stage_usage_counts"][stage_name] = (
                            via["stage_usage_counts"].get(stage_name, 0) + 1
                        )
                        via["stage_sources"].setdefault(stage_name, set()).add("def_routed_wires")
                        via["source_refs_def"].append(
                            {
                                "path": _workspace_relative_path(parsed.path, self.workspace_dir),
                                "stage": stage_name,
                                "section": "NETS" if not net.special else "SPECIALNETS",
                                "via": wire.via,
                            }
                        )
                        inferred_layers = _infer_via_stack_layers_from_name(wire.via, layer_items)
                        if inferred_layers and not via.get("layers"):
                            via["layers"] = inferred_layers
                            via["stack_source"] = "heuristic_from_name"
            for via in parsed.vias:
                name = str(via.get("name"))
                item = via_items.setdefault(name, _empty_via_item(name, source="def_vias"))
                item["source"] = (
                    "def_vias" if item.get("source") != "def_routed_wires" else item.get("source")
                )
                if via.get("layers"):
                    item["layers"] = list(via.get("layers") or [])
                    item["stack_source"] = "def_via_layers"
                if via.get("rects_by_layer"):
                    item["rects_by_layer"] = via.get("rects_by_layer") or {}
                item["stage_definition_counts"][stage_name] = (
                    item["stage_definition_counts"].get(stage_name, 0) + 1
                )
                item["stage_sources"].setdefault(stage_name, set()).add("def_vias")
                item["source_refs_def"].append(
                    {
                        "path": _workspace_relative_path(parsed.path, self.workspace_dir),
                        "stage": stage_name,
                        "section": "VIAS",
                        "via": name,
                    }
                )
                for layer in item.get("layers") or []:
                    layer_items.setdefault(str(layer), _empty_layer_item(str(layer)))[
                        "stage_sources"
                    ].setdefault(stage_name, set()).add("def_vias")

        for stage_name, parsed in rt_logs.items():
            for layer in parsed.get("layers", []):
                name = str(layer.get("name"))
                item = layer_items.setdefault(name, _empty_layer_item(name))
                item["preferred_direction"] = _normalize_direction(layer.get("preferred_direction"))
                item["order"] = layer.get("order")
                item["stage_sources"].setdefault(stage_name, set()).add("rt_log")
                item["source_refs_rt_log"].append(
                    {
                        "path": _workspace_relative_path(parsed.get("source"), self.workspace_dir),
                        "parser": "rt_log",
                        "stage": stage_name,
                    }
                )

        for name, lef_layer in self._lef_layers.items():
            item = layer_items.setdefault(name, _empty_layer_item(name))
            item["lef_layer"] = lef_layer
            item["stage_sources"].setdefault("library", set()).add("lef_layer")
        for name, lef_via in self._lef_vias.items():
            item = via_items.setdefault(name, _empty_via_item(name, source="lef_via"))
            if lef_via.layers:
                item["layers"] = list(lef_via.layers)
                item["stack_source"] = "lef_via_layers"
            if lef_via.rects_by_layer:
                item["rects_by_layer"] = lef_via.rects_by_layer
            item["lef_via"] = lef_via
            item["stage_sources"].setdefault("library", set()).add("lef_via")

        layer_records = self._tech_layer_records(layer_items, stage_names)
        layer_direction_by_name = {
            record["name"]: record["routing_properties"].get("preferred_direction")
            for record in layer_records
        }
        layer_order_by_name = {
            record["name"]: record["identity"].get("order") for record in layer_records
        }
        cell_records = self._tech_cell_records(
            cell_items,
            pin_names_by_master,
            pin_layers_by_master,
            pin_clock_by_master,
            pin_pg_by_master,
            stage_names,
            stage_order,
        )
        via_records = self._tech_via_records(
            via_items, layer_direction_by_name, layer_order_by_name, stage_names
        )
        routing_layer_count = sum(
            1 for record in layer_records if record["identity"].get("is_routing_layer")
        )
        cut_layer_count = sum(
            1 for record in layer_records if record["identity"].get("is_cut_layer")
        )
        source_coverage = {
            "def_tracks": any(parsed.tracks for parsed in def_data.values()),
            "rt_log_layers": any(parsed.get("layers") for parsed in rt_logs.values()),
            "def_components": any(parsed.components for parsed in def_data.values()),
            "def_vias": any(
                parsed.vias or any(wire.via for net in parsed.nets for wire in net.wires)
                for parsed in def_data.values()
            ),
            "lef": bool(self._lef_macros or self._lef_layers or self._lef_vias),
            "liberty": False,
        }
        self._tech_records = {
            "layers": layer_records,
            "cells": cell_records,
            "vias": via_records,
        }
        tech_summary = {
            "schema_version": "iccd_full_v1.tech.v1",
            "profile": self.profile,
            "source_coverage": source_coverage,
            "counts": {
                "layer_count": len(layer_records),
                "routing_layer_count": routing_layer_count,
                "cut_layer_count": cut_layer_count,
                "cell_count": len(cell_records),
                "via_count": len(via_records),
                "stage_count": len(stages),
            },
            "canonical_grid_ref": "foundation_data/ecc/canonical_grid.json",
            "milestones": {
                "m1": "available"
                if any(
                    source_coverage[key]
                    for key in ("def_tracks", "rt_log_layers", "def_components", "def_vias")
                )
                else "missing",
                "m2": "available" if source_coverage["lef"] else "planned",
                "liberty": "reserved_not_parsed",
            },
            "quality_flags": [],
            "source_refs": {"lef": None, "liberty": None},
        }
        write_json(self.foundation_dir / "tech_summary.json", tech_summary)
        if self._legacy_debug_enabled:
            write_json(self.foundation_dir / "vectors" / "tech" / "layers.json", layer_records)
            write_json(self.foundation_dir / "vectors" / "tech" / "cells.json", cell_records)
            write_json(self.foundation_dir / "vectors" / "tech" / "vias.json", via_records)
            write_json(self.foundation_dir / "vectors" / "tech" / "tech_summary.json", tech_summary)
        self._mark(
            "tech",
            "layers",
            "available" if layer_records else "missing",
            "" if layer_records else "missing_def_or_rt_layers",
        )
        self._mark(
            "tech",
            "cells",
            "available" if cell_records else "missing",
            "" if cell_records else "missing_def_components",
        )
        self._mark(
            "tech",
            "vias",
            "available" if via_records else "missing",
            "" if via_records else "missing_def_vias",
        )

    def _tech_layer_records(
        self, layer_items: dict[str, dict[str, Any]], stage_names: list[str]
    ) -> list[dict[str, Any]]:
        records = []
        for idx, item in enumerate(
            sorted(
                layer_items.values(),
                key=lambda value: (_layer_order_sort_key(value), str(value.get("name"))),
            )
        ):
            name = str(item["name"])
            lef_layer = item.get("lef_layer")
            layer_type = _layer_type(name, lef_layer)
            is_routing = layer_type == "routing"
            is_cut = layer_type == "cut"
            axes = _unique_dicts(
                item.get("track_axes", []), keys=("axis", "start", "count", "step", "stage")
            )
            track_count_by_axis: dict[str, int] = {}
            steps_by_axis: dict[str, list[float]] = {}
            for axis in axes:
                axis_name = str(axis.get("axis"))
                track_count_by_axis[axis_name] = max(
                    track_count_by_axis.get(axis_name, 0), int(axis.get("count") or 0)
                )
                if axis.get("step") is not None:
                    steps_by_axis.setdefault(axis_name, []).append(float(axis["step"]))
            preferred_direction = (
                _normalize_direction(item.get("preferred_direction"))
                or _normalize_direction(getattr(lef_layer, "direction", None))
                or ("unknown" if is_routing else None)
            )
            pitch = _layer_pitch_from_tracks(preferred_direction, steps_by_axis) or getattr(
                lef_layer, "pitch", None
            )
            order = (
                item.get("order") if item.get("order") is not None else _layer_order_from_name(name)
            )
            estimated_track_count = _estimated_track_count(preferred_direction, track_count_by_axis)
            estimated_capacity = (
                (estimated_track_count / pitch)
                if estimated_track_count is not None and pitch not in (None, 0)
                else estimated_track_count
            )
            stage_sources = _stage_sources(item.get("stage_sources", {}), stage_names)
            available_stages = sorted([stage for stage in stage_names if stage_sources.get(stage)])
            null_reason = {
                "source_refs_liberty": "liberty_reserved_not_parsed",
                "patch_capacity_ref": "stored_in_patch_vectors_or_not_available",
            }
            if getattr(lef_layer, "width", None) is None:
                null_reason["routing_properties_width"] = (
                    "lef_not_parsed_in_m1" if lef_layer is None else "missing_lef_layer_width"
                )
            if getattr(lef_layer, "spacing", None) is None:
                null_reason["routing_properties_spacing"] = (
                    "lef_not_parsed_in_m1" if lef_layer is None else "missing_lef_layer_spacing"
                )
            if pitch is None:
                null_reason["routing_properties_pitch"] = "missing_def_track_step"
            record = {
                "id": idx,
                "name": name,
                "identity": {
                    "layer_key": name,
                    "name": name,
                    "layer_type": layer_type,
                    "order": order,
                    "is_routing_layer": is_routing,
                    "is_cut_layer": is_cut,
                    "classification_source": "lef_layer_type"
                    if lef_layer and getattr(lef_layer, "layer_type", None)
                    else "rt_log"
                    if item.get("source_refs_rt_log")
                    else "heuristic_name_rule",
                },
                "routing_properties": {
                    "preferred_direction": preferred_direction,
                    "pitch": pitch,
                    "track_axes": axes,
                    "track_count_by_axis": track_count_by_axis,
                    "width": getattr(lef_layer, "width", None),
                    "spacing": getattr(lef_layer, "spacing", None),
                    "source": _join_sources(
                        [
                            "def_tracks" if axes else None,
                            "rt_log" if item.get("source_refs_rt_log") else None,
                            "lef_layer" if lef_layer else None,
                        ]
                    ),
                },
                "capacity_summary": {
                    "estimated_track_count": estimated_track_count,
                    "estimated_capacity": estimated_capacity,
                    "capacity_formula": "estimated_track_count / pitch"
                    if estimated_track_count is not None and pitch not in (None, 0)
                    else "track_count_proxy_from_def_tracks"
                    if estimated_track_count is not None
                    else None,
                    "stage_track_variants": _stage_track_variants(axes),
                    "patch_capacity_ref": (
                        "foundation_data/ecc/vectors/patches/route.jsonl:"
                        "native_demand_capacity_by_layer"
                        if is_routing
                        else None
                    ),
                },
                "stage_metadata": {
                    "available_stages": available_stages,
                    "missing_stages": [
                        stage for stage in stage_names if stage not in available_stages
                    ],
                    "stage_sources": stage_sources,
                    "stage_track_variants": _stage_track_variants(axes),
                },
                "source_refs": {
                    "def": _unique_dicts(
                        item.get("source_refs_def", []), keys=("path", "section", "stage", "layer")
                    ),
                    "rt_log": _unique_dicts(
                        item.get("source_refs_rt_log", []), keys=("path", "parser", "stage")
                    ),
                    "lef": _workspace_relative_path(
                        getattr(lef_layer, "source", None), self.workspace_dir
                    )
                    if lef_layer and getattr(lef_layer, "source", None)
                    else None,
                    "liberty": None,
                    "derived_from_vectors": None,
                },
                "null_reason": null_reason,
            }
            records.append(record)
        return records

    def _tech_cell_records(
        self,
        cell_items: dict[str, dict[str, Any]],
        pin_names_by_master: dict[str, set[str]],
        pin_layers_by_master: dict[str, set[str]],
        pin_clock_by_master: dict[str, set[str]],
        pin_pg_by_master: dict[str, set[str]],
        stage_names: list[str],
        stage_order: dict[str, int],
    ) -> list[dict[str, Any]]:
        records = []
        for idx, item in enumerate(
            sorted(cell_items.values(), key=lambda value: str(value.get("name")))
        ):
            name = str(item["name"])
            lef_macro = self._lef_macros.get(name)
            stage_counts = dict(
                sorted(
                    item.get("stage_instance_counts", {}).items(),
                    key=lambda pair: stage_order.get(pair[0], 999),
                )
            )
            available_stages = list(stage_counts)
            physical_class = _physical_class_from_lef_or_name(name, lef_macro)
            cell_class = _cell_class(name, name)
            is_physical_only = physical_class == "physical_only"
            is_macro = physical_class == "macro"
            size = getattr(lef_macro, "size", None) if lef_macro else None
            pin_names = set(pin_names_by_master.get(name, set()))
            pin_layers = set(pin_layers_by_master.get(name, set()))
            pin_shape_count = None
            signal_pin_count = None
            pg_pin_count = None
            clock_pin_count = None
            pin_summary_source = "def_net_terminals" if pin_names else "missing"
            if lef_macro is not None:
                pin_names = set(lef_macro.pins)
                pin_layers = {
                    str(shape.get("layer"))
                    for pin in lef_macro.pins.values()
                    for shape in pin.shapes
                    if shape.get("layer")
                }
                pin_shape_count = sum(len(pin.shapes) for pin in lef_macro.pins.values())
                pg_pin_count = sum(
                    1
                    for pin in lef_macro.pins.values()
                    if _is_power_ground_pin_name(pin.name)
                    or str(pin.use or "").upper() in {"POWER", "GROUND"}
                )
                clock_pin_count = sum(
                    1 for pin in lef_macro.pins.values() if _is_clock_pin_name(pin.name)
                )
                signal_pin_count = max(len(lef_macro.pins) - pg_pin_count, 0)
                pin_summary_source = "lef_macro_pins"
            else:
                pg_pin_count = len(pin_pg_by_master.get(name, set())) if pin_names else None
                clock_pin_count = len(pin_clock_by_master.get(name, set())) if pin_names else None
                signal_pin_count = (
                    max(len(pin_names) - (pg_pin_count or 0), 0) if pin_names else None
                )
            null_reason = {"source_refs_liberty": "liberty_reserved_not_parsed"}
            if size is None:
                null_reason["physical_properties_width"] = "lef_not_parsed_and_no_bbox_estimate"
                null_reason["physical_properties_height"] = "lef_not_parsed_and_no_bbox_estimate"
            if not pin_layers:
                null_reason["pin_summary_pin_layers"] = (
                    "lef_not_parsed_in_m1" if lef_macro is None else "missing_lef_pin_layers"
                )
            record = {
                "id": idx,
                "name": name,
                "identity": {
                    "cell_key": name,
                    "name": name,
                    "library": _library_from_lef_source(getattr(lef_macro, "source", None))
                    if lef_macro
                    else None,
                    "site": getattr(lef_macro, "site", None) if lef_macro else None,
                    "is_macro": is_macro,
                    "is_physical_only": is_physical_only,
                    "classification_source": "lef_macro_class"
                    if lef_macro and getattr(lef_macro, "macro_class", None)
                    else "heuristic_name_rule",
                },
                "classification": {
                    "cell_class": cell_class,
                    "physical_class": physical_class,
                    "is_clock_related": _is_clock_related(name, name),
                    "is_buffer_like": _is_buffer_like_cell_name(name, name),
                    "source": "lef_macro_class"
                    if lef_macro and getattr(lef_macro, "macro_class", None)
                    else "heuristic_name_rule",
                },
                "physical_properties": {
                    "width": size.get("width") if isinstance(size, dict) else None,
                    "height": size.get("height") if isinstance(size, dict) else None,
                    "area": (size.get("width") * size.get("height"))
                    if isinstance(size, dict)
                    and size.get("width") is not None
                    and size.get("height") is not None
                    else None,
                    "size_source": "lef_macro_size" if isinstance(size, dict) else "missing",
                    "observed_bbox_stats": None,
                },
                "pin_summary": {
                    "pin_count": len(pin_names) if pin_names else None,
                    "signal_pin_count": signal_pin_count,
                    "clock_pin_count": clock_pin_count,
                    "power_ground_pin_count": pg_pin_count,
                    "pin_layers": sorted(pin_layers),
                    "pin_shape_count": pin_shape_count,
                    "summary_source": pin_summary_source,
                },
                "usage_summary": {
                    "instance_count": sum(stage_counts.values()),
                    "stage_instance_counts": stage_counts,
                    "first_seen_stage": min(
                        stage_counts, key=lambda stage: stage_order.get(stage, 999)
                    )
                    if stage_counts
                    else None,
                    "route_only_usage": False,
                },
                "stage_metadata": {
                    "available_stages": available_stages,
                    "missing_stages": [
                        stage for stage in stage_names if stage not in available_stages
                    ],
                    "stage_instance_counts": stage_counts,
                },
                "source_refs": {
                    "def": _unique_dicts(
                        item.get("source_refs_def", []), keys=("path", "section", "stage", "master")
                    ),
                    "lef": _workspace_relative_path(
                        getattr(lef_macro, "source", None), self.workspace_dir
                    )
                    if lef_macro and getattr(lef_macro, "source", None)
                    else None,
                    "liberty": None,
                    "derived_from_vectors": None,
                },
                "null_reason": null_reason,
            }
            records.append(record)
        return records

    def _tech_via_records(
        self,
        via_items: dict[str, dict[str, Any]],
        layer_direction_by_name: dict[str, str | None],
        layer_order_by_name: dict[str, Any],
        stage_names: list[str],
    ) -> list[dict[str, Any]]:
        records = []
        for idx, item in enumerate(
            sorted(via_items.values(), key=lambda value: str(value.get("name")))
        ):
            name = str(item["name"])
            layers = list(item.get("layers") or [])
            if not layers:
                layers = _infer_via_stack_layers_from_name(
                    name, {layer: {} for layer in layer_direction_by_name}
                )
            layer_stack = _via_layer_stack(
                layers,
                layer_order_by_name,
                item.get("stack_source") or ("heuristic_from_name" if layers else "missing"),
            )
            rects_by_layer = item.get("rects_by_layer") or {}
            geometry = _via_geometry(layer_stack, rects_by_layer)
            usage_counts = dict(
                sorted(
                    item.get("stage_usage_counts", {}).items(),
                    key=lambda pair: stage_names.index(pair[0]) if pair[0] in stage_names else 999,
                )
            )
            stage_sources = _stage_sources(item.get("stage_sources", {}), stage_names)
            available_stages = sorted(
                [
                    stage
                    for stage in stage_names
                    if stage_sources.get(stage) or usage_counts.get(stage)
                ]
            )
            bottom_direction = layer_direction_by_name.get(layer_stack.get("bottom_layer"))
            top_direction = layer_direction_by_name.get(layer_stack.get("top_layer"))
            route_only_usage = bool(usage_counts)
            null_reason = {"source_refs_liberty": "liberty_reserved_not_parsed"}
            if geometry["geometry_status"] in {"name_only", "missing"}:
                null_reason["geometry_bottom_rect"] = "via_geometry_not_available_from_def"
                null_reason["geometry_cut_rect"] = "via_geometry_not_available_from_def"
                null_reason["geometry_top_rect"] = "via_geometry_not_available_from_def"
            if not usage_counts:
                null_reason["usage_summary_stage_usage_counts"] = "route_usage_not_computed"
            record = {
                "id": idx,
                "name": name,
                "identity": {
                    "via_key": name,
                    "name": name,
                    "via_type": "fixed"
                    if item.get("source") == "def_vias"
                    or item.get("stack_source") in {"def_via_layers", "lef_via_layers"}
                    else "routed_wire_reference"
                    if item.get("source") == "def_routed_wires"
                    else "unknown",
                    "classification_source": item.get("source") or "heuristic_name_rule",
                },
                "layer_stack": layer_stack,
                "geometry": geometry,
                "routing_properties": {
                    "bottom_direction": bottom_direction,
                    "top_direction": top_direction,
                    "is_direction_change": (bottom_direction != top_direction)
                    if bottom_direction and top_direction
                    else None,
                },
                "usage_summary": {
                    "stage_usage_counts": usage_counts,
                    "total_usage_count": sum(usage_counts.values()),
                    "route_only_usage": route_only_usage,
                    "usage_source": "def_routed_wires" if usage_counts else "not_computed",
                },
                "stage_metadata": {
                    "available_stages": available_stages,
                    "missing_stages": [
                        stage for stage in stage_names if stage not in available_stages
                    ],
                    "stage_sources": stage_sources,
                    "stage_usage_counts": usage_counts,
                },
                "source_refs": {
                    "def": _unique_dicts(
                        item.get("source_refs_def", []), keys=("path", "section", "stage", "via")
                    ),
                    "lef": _workspace_relative_path(
                        getattr(item.get("lef_via"), "source", None), self.workspace_dir
                    )
                    if item.get("lef_via")
                    else None,
                    "liberty": None,
                    "derived_from_vectors": None,
                },
                "null_reason": null_reason,
            }
            records.append(record)
        return records

    def _write_vectors(
        self,
        stages: list[StageInfo],
        canonical_grid: dict,
        canonical_maps: dict,
        def_data: dict[str, DefData],
        labels: dict[str, Any],
        sta_reports: dict[str, dict[str, Any]],
        drc_reports: dict[str, dict[str, Any]],
        *,
        export_legacy_debug: bool,
    ) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {entity: {} for entity in _ENTITY_NAMES}
        native_demand_capacity_by_patch = {
            item["patch_id"]: item
            for item in labels.get("_route_native_demand_capacity_records", [])
        }
        stage_order = [stage.name for stage in stages]
        instances_by_stage: dict[str, list[dict[str, Any]]] = {}
        for stage in stages:
            stage_start = time.monotonic()
            logger.info(
                "foundation_vectors instances_start stage=%s workspace=%s",
                stage.name,
                self.workspace_dir,
            )
            instances_by_stage[stage.name] = self._parse_instances(
                stage,
                def_data.get(stage.name),
                canonical_grid,
                canonical_maps.get(stage.name, {}),
            )
            logger.info(
                "foundation_vectors instances_done stage=%s count=%d elapsed=%.2fs workspace=%s",
                stage.name,
                len(instances_by_stage[stage.name]),
                time.monotonic() - stage_start,
                self.workspace_dir,
            )
        _attach_progressive_metadata(stages, instances_by_stage)
        for stage in stages:
            stage_start = time.monotonic()
            logger.info(
                "foundation_vectors stage_start stage=%s workspace=%s",
                stage.name,
                self.workspace_dir,
            )
            parsed_def = def_data.get(stage.name)
            instances = instances_by_stage.get(stage.name, [])
            pins = self._pin_records(
                stage,
                parsed_def,
                instances,
                canonical_grid,
                canonical_maps.get(stage.name, {}),
                sta_reports.get(stage.name),
                drc_reports.get(stage.name)
                or (drc_reports.get("drc") if stage.name == "route" else None),
            )
            nets = self._net_records(
                stage,
                parsed_def,
                pins,
                canonical_grid,
                canonical_maps.get(stage.name, {}),
                sta_reports.get(stage.name),
            )
            wires = self._wire_records(
                stage,
                parsed_def,
                canonical_grid,
                canonical_maps.get(stage.name, {}),
                nets,
                native_demand_capacity_by_patch if stage.name == "route" else {},
                drc_reports.get(stage.name)
                or (drc_reports.get("drc") if stage.name == "route" else None),
            )
            routing_graphs = self._routing_graph_records(
                stage, parsed_def, canonical_grid, pins, nets
            )
            timing_paths = self._timing_path_records(
                stage,
                sta_reports.get(stage.name),
                instances,
                pins,
                parsed_def,
                canonical_grid,
                canonical_maps.get(stage.name, {}),
            )
            self._vector_records["instances"][stage.name] = instances
            if export_legacy_debug:
                counts["instances"][stage.name] = write_jsonl(
                    self.foundation_dir / "vectors" / "instances" / f"{stage.name}.jsonl",
                    instances,
                    sort_keys=False,
                )
            else:
                counts["instances"][stage.name] = len(instances)
            stage_vectors = {
                "nets": nets,
                "pins": pins,
                "wires": wires,
                "routing_graphs": routing_graphs,
                "timing_paths": timing_paths,
            }
            for entity, records in stage_vectors.items():
                self._vector_records[entity][stage.name] = records
                if export_legacy_debug:
                    counts[entity][stage.name] = write_jsonl(
                        self.foundation_dir / "vectors" / entity / f"{stage.name}.jsonl",
                        records,
                        sort_keys=entity
                        not in (
                            "pins",
                            "timing_paths",
                            "nets",
                            "wires",
                            "routing_graphs",
                            "patches",
                        ),
                    )
                else:
                    counts[entity][stage.name] = len(records)
                if entity == "routing_graphs" and stage.name != "route" and not records:
                    status = (
                        "optional_post_route_snapshot"
                        if stage.name in {"drc", "filler"}
                        else "not_available_before_route"
                    )
                    self._quality.setdefault("availability", {}).setdefault(entity, {})[
                        stage.name
                    ] = status
                    self._quality.setdefault("null_reason", {}).setdefault(entity, {})[
                        stage.name
                    ] = status
                elif (
                    entity == "routing_graphs"
                    and self._quality.get("availability", {}).get(entity, {}).get(stage.name)
                    == "direct_table_stream_from_wire_segments"
                ):
                    continue
                else:
                    self._mark(
                        entity,
                        stage.name,
                        "available" if records else "missing",
                        "" if records else f"missing_{entity}_source",
                    )
            patches = self._patch_records(
                stage.name,
                canonical_grid,
                canonical_maps.get(stage.name, {}),
                instances,
                nets,
                pins,
                wires,
                native_demand_capacity_by_patch if stage.name == "route" else {},
                timing_paths,
                drc_reports.get(stage.name),
                parsed_def,
                stage_order,
            )
            self._vector_records["patches"][stage.name] = patches
            if export_legacy_debug:
                counts["patches"][stage.name] = write_jsonl(
                    self.foundation_dir / "vectors" / "patches" / f"{stage.name}.jsonl",
                    patches,
                    sort_keys=False,
                )
            else:
                counts["patches"][stage.name] = len(patches)
            self._mark(
                "patches",
                stage.name,
                "available" if patches else "missing",
                "" if patches else "missing_canonical_grid",
            )
            logger.info(
                "foundation_vectors stage_done stage=%s instances=%d pins=%d nets=%d "
                "wires=%d routing_graphs=%d timing_paths=%d patches=%d "
                "elapsed=%.2fs workspace=%s",
                stage.name,
                len(instances),
                len(pins),
                len(nets),
                len(wires),
                len(routing_graphs),
                len(timing_paths),
                len(patches),
                time.monotonic() - stage_start,
                self.workspace_dir,
            )
        if export_legacy_debug:
            _attach_patch_progressive_metadata(stages, self.foundation_dir / "vectors" / "patches")
            _attach_net_progressive_metadata(stages, self.foundation_dir / "vectors" / "nets")
            _attach_pin_progressive_metadata(stages, self.foundation_dir / "vectors" / "pins")
            _attach_wire_progressive_metadata(stages, self.foundation_dir / "vectors" / "wires")
            self._reload_legacy_vector_records(stages)
        else:
            _attach_patch_progressive_metadata_in_memory(stages, self._vector_records["patches"])
            _attach_net_progressive_metadata_in_memory(stages, self._vector_records["nets"])
            _attach_pin_progressive_metadata_in_memory(stages, self._vector_records["pins"])
            _attach_wire_progressive_metadata_in_memory(stages, self._vector_records["wires"])
        return counts

    def _parse_instances(
        self,
        stage: StageInfo,
        parsed_def: DefData | None,
        canonical_grid: dict | None = None,
        stage_maps: dict[str, dict[str, list[list[float]]]] | None = None,
    ) -> list[dict[str, Any]]:
        if self._should_use_def_instance_fast_path(stage, parsed_def):
            records = self._instance_records_from_def(
                stage, parsed_def, canonical_grid or {}, stage_maps or {}
            )
            self._quality.setdefault("availability", {}).setdefault("instances", {})[stage.name] = (
                "available" if records else "missing"
            )
            if records:
                _attach_connectivity_summaries(records, parsed_def)
                return records
        records: list[dict[str, Any]] = []
        components_by_name = {
            _component_lookup_key(component.get("name")): component
            for component in (parsed_def.components if parsed_def else [])
            if component.get("name")
        }
        for layout_path in sorted((stage.directory / "output").glob("*.json")):
            payload = self._read_json(layout_path)
            if not isinstance(payload.get("data"), list):
                continue
            self._record_raw_ref(stage, layout_path, "layout_json", {})
            for index, item in enumerate(payload.get("data", [])):
                if not isinstance(item, dict) or item.get("type") != "group":
                    continue
                name = str(item.get("struct name") or f"instance_{index}")
                instance_key = _instance_key_from_layout_name(name)
                component = components_by_name.get(
                    _component_lookup_key(instance_key)
                ) or components_by_name.get(_component_lookup_key(name))
                record = self._instance_record_from_layout(
                    stage, layout_path, name, instance_key, item, component
                )
                if record is None:
                    continue
                _attach_patch_anchor(record, canonical_grid or {}, stage_maps or {})
                records.append(_ordered_instance_record(record, len(records)))
            if records:
                break
        self._quality.setdefault("availability", {}).setdefault("instances", {})[stage.name] = (
            "available" if records else "missing"
        )
        if parsed_def:
            _attach_connectivity_summaries(records, parsed_def)
        if not records:
            self._quality.setdefault("null_reason", {}).setdefault("instances", {})[stage.name] = (
                "missing_layout_json_instances"
            )
        return records

    def _should_use_def_instance_fast_path(
        self, stage: StageInfo, parsed_def: DefData | None
    ) -> bool:
        if not parsed_def or not parsed_def.components:
            return False
        if not self._lef_macros:
            return False
        layout_paths = sorted((stage.directory / "output").glob("*.json"))
        if not layout_paths:
            return True
        # KLayout JSON can be hundreds of MB on real ICCD workspaces.  When LEF
        # sizes are available, DEF components preserve placement semantics for
        # instance anchors without paying that JSON parse cost.
        return any(path.stat().st_size > 50 * 1024 * 1024 for path in layout_paths if path.exists())

    def _instance_records_from_def(
        self,
        stage: StageInfo,
        parsed_def: DefData,
        canonical_grid: dict,
        stage_maps: dict[str, dict[str, list[list[float]]]],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for component in parsed_def.components:
            record = self._instance_record_from_component(stage, parsed_def, component)
            _attach_patch_anchor(record, canonical_grid, stage_maps)
            records.append(_ordered_instance_record(record, len(records)))
        if records:
            self._record_raw_ref(stage, parsed_def.path, "def_components", {"count": len(records)})
        return records

    def _instance_record_from_component(
        self,
        stage: StageInfo,
        parsed_def: DefData,
        component: dict[str, Any],
    ) -> dict[str, Any]:
        name = str(component.get("name") or "")
        master = str(component.get("master") or "")
        origin = component.get("origin") if isinstance(component.get("origin"), dict) else None
        orientation = component.get("orientation")
        physical_class = _physical_class(master, name)
        is_macro = physical_class == "macro"
        is_physical_only = _is_physical_only_cell_name(name, master)
        bbox = _component_bbox_from_def(component, self._lef_macros.get(master), parsed_def.units)
        null_reason: dict[str, str] = {}
        if bbox is None:
            null_reason["physical_state_bbox"] = "missing_lef_macro_size"
        if orientation is None:
            null_reason["physical_state_orientation"] = "def_component_missing_orientation"
        center = (
            None
            if bbox is None
            else {"x": (bbox["llx"] + bbox["urx"]) / 2.0, "y": (bbox["lly"] + bbox["ury"]) / 2.0}
        )
        width = None if bbox is None else bbox["urx"] - bbox["llx"]
        height = None if bbox is None else bbox["ury"] - bbox["lly"]
        return {
            "stage": stage.name,
            "name": name,
            "source": _workspace_relative_path(parsed_def.path, self.workspace_dir),
            "identity": {
                "instance_key": name,
                "master": master or None,
                "cell_class": _cell_class(master, name),
                "physical_class": physical_class,
                "is_macro": is_macro,
                "is_physical_only": is_physical_only,
                "is_clock_related": _is_clock_related(master, name),
                "classification_source": "heuristic_name_rule",
            },
            "physical_state": {
                "placement_status": "placed" if origin and bbox is not None else "unplaced",
                "origin": {"x": float(origin["x"]), "y": float(origin["y"])} if origin else None,
                "bbox": bbox,
                "center": center,
                "width": width,
                "height": height,
                "area": None if width is None or height is None else max(0.0, width * height),
                "orientation": orientation,
                "patch_id": None,
                "overlap_patch_ids": [],
            },
            "connectivity_summary": {},
            "patch_anchor": {},
            "progressive_metadata": {},
            "clock_tree": None,
            "route_analysis": None,
            "null_reason": null_reason,
        }

    def _instance_record_from_layout(
        self,
        stage: StageInfo,
        layout_path: Path,
        name: str,
        instance_key: str,
        item: dict[str, Any],
        component: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        raw_bbox = self._bbox_from_children(item.get("children", []))
        origin = component.get("origin") if isinstance(component, dict) else None
        has_origin = isinstance(origin, dict)
        master = str(component.get("master") or "") if isinstance(component, dict) else None
        orientation = component.get("orientation") if isinstance(component, dict) else None
        physical_class = _physical_class(master or "", name)
        is_macro = physical_class == "macro"
        is_physical_only = _is_physical_only_cell_name(name, master or "")
        null_reason: dict[str, str] = {}
        bbox: dict[str, float] | None = None
        if raw_bbox is not None:
            llx, lly, urx, ury = raw_bbox
            if urx > llx and ury > lly:
                bbox = {"llx": llx, "lly": lly, "urx": urx, "ury": ury}
        if bbox is None and has_origin and is_macro:
            x = float(origin.get("x", 0.0))
            y = float(origin.get("y", 0.0))
            bbox = {"llx": x, "lly": y, "urx": x, "ury": y}
        if bbox is None and not has_origin and raw_bbox is None:
            return None
        if bbox is None:
            null_reason["physical_state_bbox"] = "not_available_before_placement"
        if not master:
            null_reason["identity_master"] = (
                "def_component_missing_master" if component else "missing_def_component"
            )
        if orientation is None:
            null_reason["physical_state_orientation"] = (
                "def_component_missing_orientation" if component else "missing_def_component"
            )
        center = (
            None
            if bbox is None
            else {"x": (bbox["llx"] + bbox["urx"]) / 2.0, "y": (bbox["lly"] + bbox["ury"]) / 2.0}
        )
        width = None if bbox is None else bbox["urx"] - bbox["llx"]
        height = None if bbox is None else bbox["ury"] - bbox["lly"]
        placement_status = "placed" if has_origin and bbox is not None else "unplaced"
        return {
            "stage": stage.name,
            "name": name,
            "source": str(layout_path.relative_to(self.workspace_dir)),
            "identity": {
                "instance_key": instance_key,
                "master": master or None,
                "cell_class": _cell_class(master or "", name),
                "physical_class": physical_class,
                "is_macro": is_macro,
                "is_physical_only": is_physical_only,
                "is_clock_related": _is_clock_related(master or "", name),
                "classification_source": "heuristic_name_rule",
            },
            "physical_state": {
                "placement_status": placement_status,
                "origin": {"x": float(origin["x"]), "y": float(origin["y"])}
                if has_origin
                else None,
                "bbox": bbox,
                "center": center,
                "width": width,
                "height": height,
                "area": None if width is None or height is None else max(0.0, width * height),
                "orientation": orientation,
                "patch_id": None,
                "overlap_patch_ids": [],
            },
            "connectivity_summary": {},
            "patch_anchor": {},
            "progressive_metadata": {},
            "clock_tree": None,
            "route_analysis": None,
            "null_reason": null_reason,
        }

    def _net_records(
        self,
        stage: StageInfo,
        parsed_def: DefData | None,
        pins: list[dict[str, Any]],
        canonical_grid: dict,
        stage_maps: dict[str, dict[str, MapMatrix]],
        sta_report: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not parsed_def:
            return []
        route_label_demand_capacity_by_patch = (
            _route_label_demand_capacity_by_patch(stage.directory, canonical_grid)
            if stage.name == "route"
            else {}
        )
        pins_by_net: dict[str, list[dict[str, Any]]] = {}
        for pin in pins:
            net_name = str(pin.get("identity", {}).get("net") or "")
            if net_name:
                pins_by_net.setdefault(net_name, []).append(pin)
        records = []
        for idx, net in enumerate(parsed_def.nets):
            net_pins = pins_by_net.get(net.name, [])
            records.append(
                _ordered_net_record(
                    _build_net_record(
                        stage,
                        parsed_def,
                        net,
                        idx,
                        net_pins,
                        canonical_grid,
                        stage_maps,
                        sta_report,
                        route_label_demand_capacity_by_patch,
                    ),
                    idx,
                )
            )
        return records

    def _pin_records(
        self,
        stage: StageInfo,
        parsed_def: DefData | None,
        instances: list[dict[str, Any]],
        canonical_grid: dict,
        stage_maps: dict[str, dict[str, list[list[float]]]],
        sta_report: dict[str, Any] | None,
        drc_report: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not parsed_def:
            return []
        return _pin_records_for_stage(
            stage,
            parsed_def,
            instances,
            canonical_grid,
            stage_maps,
            sta_report,
            self.workspace_dir,
            self._lef_macros,
            drc_report,
        )

    def _wire_records(
        self,
        stage: StageInfo,
        parsed_def: DefData | None,
        canonical_grid: dict,
        stage_maps: dict[str, dict[str, MapMatrix]],
        nets: list[dict[str, Any]],
        native_demand_capacity_by_patch: dict[int, dict[str, Any]] | None = None,
        drc_report: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not parsed_def:
            return []
        records: list[dict[str, Any]] = []
        net_records = {str(record.get("net_key")): record for record in nets}
        net_contexts = {
            net.name: _wire_net_context(net, net_records.get(net.name)) for net in parsed_def.nets
        }
        total_wire_count = sum(len(item.wires) for item in parsed_def.nets)
        large_design_route = stage.name == "route" and total_wire_count > 1000
        if large_design_route:
            self._quality["large_design_observed"] = {
                "enabled": True,
                "route_wire_count": total_wire_count,
                "policy": "source_backed_tables_preserved",
            }
        tech_layers = {
            str(item.get("name")): item
            for item in self._tech_records.get("layers", [])
            if item.get("name") is not None
        }
        tech_vias = {
            str(item.get("name")): item
            for item in self._tech_records.get("vias", [])
            if item.get("name") is not None
        }
        net_segment_index: dict[str, int] = {}
        for net in parsed_def.nets:
            for wire in net.wires:
                segment_index = net_segment_index.get(net.name, 0)
                net_segment_index[net.name] = segment_index + 1
                records.append(
                    _ordered_wire_record(
                        _build_wire_record(
                            stage,
                            parsed_def,
                            net,
                            wire,
                            len(records),
                            segment_index,
                            canonical_grid,
                            stage_maps,
                            net_records.get(net.name),
                            native_demand_capacity_by_patch or {},
                            drc_report,
                            tech_layers,
                            tech_vias,
                            net_contexts.get(net.name),
                            large_design_route=large_design_route,
                        )
                    )
                )
        return records

    def _routing_graph_records(
        self,
        stage: StageInfo,
        parsed_def: DefData | None,
        canonical_grid: dict,
        pins: list[dict[str, Any]],
        nets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not parsed_def:
            return []
        if stage.name != "route":
            self._quality.setdefault("availability", {}).setdefault("routing_graphs", {})[
                stage.name
            ] = "not_available_before_route"
            self._quality.setdefault("null_reason", {}).setdefault("routing_graphs", {})[
                stage.name
            ] = "not_available_before_route"
            return []
        if sum(len(net.wires) for net in parsed_def.nets) > 1000:
            self._quality.setdefault("routing_graph_observed", {})[stage.name] = {
                "route_wire_count": sum(len(net.wires) for net in parsed_def.nets),
                "policy": "direct_table_stream_from_wire_segments",
            }
            self._quality.setdefault("availability", {}).setdefault("routing_graphs", {})[
                stage.name
            ] = "direct_table_stream_from_wire_segments"
            self._quality.setdefault("null_reason", {}).setdefault("routing_graphs", {})[
                stage.name
            ] = "legacy_nested_graph_skipped_large_route"
            return []
        net_records = {str(record.get("net_key")): record for record in nets}
        pins_by_net: dict[str, list[dict[str, Any]]] = {}
        for pin in pins:
            net_name = str(pin.get("identity", {}).get("net") or "")
            if net_name:
                pins_by_net.setdefault(net_name, []).append(pin)
        records = []
        for def_net_index, net in enumerate(parsed_def.nets):
            if not net.wires:
                continue
            records.append(
                _ordered_routing_graph_record(
                    _build_routing_graph_record(
                        stage,
                        parsed_def,
                        net,
                        len(records),
                        def_net_index,
                        canonical_grid,
                        pins_by_net.get(net.name, []),
                        net_records.get(net.name),
                    )
                )
            )
        return records

    def _timing_path_records(
        self,
        stage: StageInfo,
        sta_report: dict[str, Any] | None,
        instances: list[dict[str, Any]],
        pins: list[dict[str, Any]],
        parsed_def: DefData | None,
        canonical_grid: dict,
        stage_maps: dict[str, dict[str, MapMatrix]],
    ) -> list[dict[str, Any]]:
        if not sta_report:
            return []
        records = []
        instance_by_key = {
            str(record.get("identity", {}).get("instance_key")): record for record in instances
        }
        pin_by_key = {str(record.get("pin_key")): record for record in pins}
        net_by_pin_pair = _net_lookup_by_pin_pair(parsed_def)
        for idx, item in enumerate(sta_report.get("records", [])):
            record = {**item, "id": idx, "stage": stage.name}
            source = record.get("source")
            record["source"] = self._workspace_relative_string(source) if source else None
            refs = (
                record.get("source_refs", {}) if isinstance(record.get("source_refs"), dict) else {}
            )
            for ref in (refs.get("sta_report"), refs.get("wire_path")):
                if isinstance(ref, dict) and ref.get("path"):
                    ref["path"] = self._workspace_relative_string(ref.get("path"))
            record = _enrich_timing_path_record(
                record, instance_by_key, pin_by_key, net_by_pin_pair, canonical_grid, stage_maps
            )
            path_key = _timing_path_key(stage.name, record)
            record["path_key"] = path_key
            record["identity"]["path_key"] = path_key
            records.append(_ordered_timing_path_record(record, idx))
        _attach_timing_progressive_metadata(
            stage.name, records, self.foundation_dir / "vectors" / "timing_paths"
        )
        return records

    def _workspace_relative_string(self, value: Any) -> str:
        try:
            return str(Path(str(value)).relative_to(self.workspace_dir))
        except ValueError:
            return str(value)

    @staticmethod
    def _bbox_from_children(children: Any) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        if not isinstance(children, list):
            return None
        for child in children:
            if not isinstance(child, dict) or child.get("type") != "box":
                continue
            if int(child.get("layer", -1)) != 0:
                continue
            for point in child.get("path", []):
                if isinstance(point, list | tuple) and len(point) >= 2:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    @staticmethod
    def _patch_records(
        stage: str,
        canonical_grid: dict,
        stage_maps: dict[str, dict[str, list[list[float]]]],
        instances: list[dict[str, Any]],
        nets: list[dict[str, Any]],
        pins: list[dict[str, Any]],
        wires: list[dict[str, Any]],
        native_demand_capacity_by_patch: dict[int, dict[str, Any]],
        timing_paths: list[dict[str, Any]],
        drc_report: dict[str, Any] | None,
        parsed_def: DefData | None,
        stage_order: list[str],
    ) -> list[dict[str, Any]]:
        records = []
        density_maps = stage_maps.get("density", {})
        floorplan_maps = stage_maps.get("floorplan", {})
        congestion_maps = stage_maps.get("congestion", {})
        rudy_maps = stage_maps.get("rudy", {})
        margin_maps = stage_maps.get("margin", {})
        rows = int(canonical_grid.get("rows") or 0)
        cols = int(canonical_grid.get("cols") or 0)
        die_bbox = canonical_grid.get("die_bbox")
        patch_count = len(canonical_grid.get("patches", []))
        stage_index = stage_order.index(stage) if stage in stage_order else None
        prev_stage = (
            stage_order[stage_index - 1]
            if isinstance(stage_index, int) and stage_index > 0
            else None
        )
        def_source = _workspace_relative_from_parsed_def(parsed_def) if parsed_def else None

        def _index_by_primary(
            items: list[dict[str, Any]], primary_getter
        ) -> dict[int, list[dict[str, Any]]]:
            out: dict[int, list[dict[str, Any]]] = {}
            for item in items:
                patch_id = primary_getter(item)
                if patch_id is None:
                    continue
                out.setdefault(int(patch_id), []).append(item)
            return out

        def _index_by_many(
            items: list[dict[str, Any]], ids_getter
        ) -> dict[int, list[dict[str, Any]]]:
            out: dict[int, list[dict[str, Any]]] = {}
            for item in items:
                for patch_id in ids_getter(item) or []:
                    if patch_id is None:
                        continue
                    out.setdefault(int(patch_id), []).append(item)
            return out

        instances_by_primary = _index_by_primary(
            instances,
            lambda item: item.get("patch_anchor", {}).get("primary_patch_id")
            if item.get("patch_anchor", {}).get("primary_patch_id") is not None
            else item.get("physical_state", {}).get("patch_id"),
        )
        instances_by_overlap = _index_by_many(
            instances,
            lambda item: item.get("patch_anchor", {}).get("overlap_patch_ids")
            or item.get("physical_state", {}).get("overlap_patch_ids")
            or [],
        )
        pins_by_primary = _index_by_primary(
            pins, lambda item: item.get("patch_anchor", {}).get("primary_patch_id")
        )
        pins_by_overlap = _index_by_many(
            pins,
            lambda item: item.get("patch_anchor", {}).get("overlap_patch_ids")
            or item.get("geometry", {}).get("overlap_patch_ids")
            or [],
        )
        wires_by_overlap = _index_by_many(
            wires, lambda item: item.get("patch_anchor", {}).get("overlap_patch_ids") or []
        )
        nets_by_primary = _index_by_primary(
            nets, lambda item: item.get("patch_anchor", {}).get("primary_patch_id")
        )
        nets_by_overlap = _index_by_many(
            nets, lambda item: item.get("geometry_proxy", {}).get("patch_ids") or []
        )
        timing_by_patch = _index_by_many(timing_paths, _timing_path_patch_ids)
        timing_electrical_by_patch = _timing_electrical_contexts_by_patch(timing_paths, stage=stage)

        for patch in canonical_grid.get("patches", []):
            patch_id = int(patch["patch_id"])
            row = int(patch["row"])
            col = int(patch["col"])
            bbox = patch["bbox"]
            center = _bbox_center(bbox)
            patch_instances = instances_by_primary.get(patch_id, [])
            overlap_instances = instances_by_overlap.get(patch_id, [])
            patch_pins = pins_by_primary.get(patch_id, [])
            overlap_pins = pins_by_overlap.get(patch_id, [])
            patch_wires = wires_by_overlap.get(patch_id, [])
            patch_nets = nets_by_primary.get(patch_id, [])
            overlap_nets = nets_by_overlap.get(patch_id, [])
            patch_timing_paths = timing_by_patch.get(patch_id, [])
            wire_length_by_layer: dict[str, float] = {}
            wire_length = 0.0
            for wire in patch_wires:
                layer = str(wire.get("geometry", {}).get("layer") or wire.get("layer"))
                length = _wire_length_for_patch(wire, patch_id)
                wire_length += length
                wire_length_by_layer[layer] = wire_length_by_layer.get(layer, 0.0) + length
            native_demand_capacity = native_demand_capacity_by_patch.get(patch_id, {})
            patch_drc = _drc_for_patch(drc_report, bbox)
            route_label = _demand_capacity_label(native_demand_capacity)
            native_route_oracle = _route_native_demand_capacity_oracle(route_label)
            route_oracle = None
            if stage == "route":
                route_oracle = {
                    "feature_role": "route_only_oracle",
                    "available_for_training_input": False,
                    "route_only_oracle": True,
                    "wire_length": wire_length,
                    "wire_length_by_layer": wire_length_by_layer,
                    "via_count": sum(
                        1
                        for wire in patch_wires
                        if wire.get("identity", {}).get("segment_kind") == "via"
                    ),
                    "native_demand_capacity": native_route_oracle,
                    "source": route_label.get("source") or "routed_def_reconstruction",
                }
            neighbor_ids = _neighbor_patch_ids(row, col, rows, cols)
            adjacent_ids = _adjacent_patch_ids(row, col, rows, cols)
            stdcell_instances = [
                item
                for item in overlap_instances
                if item.get("identity", {}).get("physical_class") == "stdcell"
            ]
            macro_instances = [
                item
                for item in overlap_instances
                if item.get("identity", {}).get("physical_class") == "macro"
            ]
            physical_only_instances = [
                item
                for item in overlap_instances
                if item.get("identity", {}).get("physical_class") == "physical_only"
            ]
            stdcell_area = _instance_overlap_area(stdcell_instances, bbox)
            macro_area = _instance_overlap_area(macro_instances, bbox)
            instance_area = _instance_overlap_area(overlap_instances, bbox)
            pin_density = _value_from_named_map(density_maps, "allcell_pin_density", row, col)
            if pin_density is None:
                pin_density = _value_from_named_map(density_maps, "pin_density", row, col)
            net_density = _value_from_named_map(density_maps, "allnet_density", row, col)
            if net_density is None:
                net_density = _value_from_named_map(density_maps, "net_density", row, col)
            pg_net_count = _matrix_value(floorplan_maps.get("pg_net_count"), row, col)
            rudy_union = _value_from_named_map(rudy_maps, "rudy_union", row, col)
            egr_horizontal = _matrix_value(congestion_maps.get("horizontal"), row, col)
            egr_vertical = _matrix_value(congestion_maps.get("vertical"), row, col)
            egr_union = _matrix_value(congestion_maps.get("union"), row, col)
            window_cell_values = [
                _value_from_patch_id(canonical_grid, density_maps, "allcell_density", item)
                for item in neighbor_ids
            ]
            window_pin_density_values = [
                _value_from_patch_id(canonical_grid, density_maps, "allcell_pin_density", item)
                for item in neighbor_ids
            ]
            if not any(value is not None for value in window_pin_density_values):
                window_pin_density_values = [
                    _value_from_patch_id(canonical_grid, density_maps, "pin_density", item)
                    for item in neighbor_ids
                ]
            window_rudy_values = [
                _value_from_patch_id(canonical_grid, rudy_maps, "rudy_union", item)
                for item in neighbor_ids
            ]
            window_egr_values = [
                _matrix_value_for_patch_id(canonical_grid, congestion_maps.get("union"), item)
                for item in neighbor_ids
            ]
            timing_context, electrical_context = timing_electrical_by_patch.get(
                patch_id,
                (
                    _timing_for_scoped_patch_paths([], patch_id, stage),
                    _electrical_for_scoped_patch_paths([], patch_id, stage),
                ),
            )
            drc_context = {
                "feature_role": "route_or_drc_analysis",
                "available_for_training_input": False,
                "availability": patch_drc.get(
                    "availability", "available" if patch_drc.get("count") is not None else "missing"
                ),
                "count": patch_drc.get("count"),
                "by_type": patch_drc.get("by_type", {}),
                "by_layer": patch_drc.get("by_layer", {}),
                "unlocalized_count": patch_drc.get("unlocalized_count"),
                "source": "drc_artifacts" if patch_drc.get("availability") != "missing" else None,
            }
            is_progressive_input_stage = stage in {"Floorplan", "place", "CTS"}
            input_available = is_progressive_input_stage
            if not input_available:
                timing_context["available_for_training_input"] = False
                electrical_context["available_for_training_input"] = False
            input_blocks = [
                "local_density",
                "local_connectivity",
                "pre_route_estimators",
                "neighbor_context",
                "entity_refs",
            ]
            if timing_context.get("available_for_training_input"):
                input_blocks.append("timing_context")
            if electrical_context.get("available_for_training_input"):
                input_blocks.append("electrical_context")
            null_reason = _patch_null_reason(
                stage,
                density_maps,
                rudy_maps,
                congestion_maps,
                timing_context,
                electrical_context,
                route_oracle,
                native_demand_capacity,
                drc_context,
            )
            record = {
                "id": patch_id,
                "stage": stage,
                "patch_key": f"patch:{patch_id}",
                "source": "canonical_grid.json",
                "identity": {
                    "patch_id": patch_id,
                    "row": row,
                    "col": col,
                    "grid_rows": rows,
                    "grid_cols": cols,
                    "grid_source": canonical_grid.get("grid_source"),
                    "grid_patch_count": patch_count,
                },
                "geometry": {
                    "bbox": bbox,
                    "center": center,
                    "width": float(bbox["urx"]) - float(bbox["llx"]),
                    "height": float(bbox["ury"]) - float(bbox["lly"]),
                    "area": _bbox_area(bbox),
                    "die_bbox": die_bbox,
                    "distance_to_die_boundary": _distance_to_die_boundary(bbox, die_bbox),
                    "edge_position": _edge_position(row, col, rows, cols),
                },
                "local_density": {
                    "feature_role": "progressive_input",
                    "available_for_training_input": input_available,
                    "instance_count_center": len(patch_instances),
                    "instance_count_overlap": len(overlap_instances),
                    "stdcell_count_center": sum(
                        1
                        for item in patch_instances
                        if item.get("identity", {}).get("physical_class") == "stdcell"
                    ),
                    "macro_count_overlap": len(macro_instances),
                    "physical_only_count_overlap": len(physical_only_instances),
                    "stdcell_area_overlap": stdcell_area,
                    "macro_area_overlap": macro_area,
                    "instance_area_overlap": instance_area,
                    "cell_density": _value_from_named_map(
                        density_maps, "allcell_density", row, col
                    ),
                    "macro_density": _value_from_named_map(density_maps, "macro_density", row, col),
                    "pin_count_anchor": len(patch_pins),
                    "pin_count_overlap": len(overlap_pins),
                    "pin_density": pin_density,
                    "net_density": net_density,
                    "wire_length": wire_length,
                    "wire_length_by_layer": wire_length_by_layer,
                    "via_count": sum(
                        1
                        for wire in patch_wires
                        if wire.get("identity", {}).get("segment_kind") == "via"
                    ),
                    "source": "maps_and_vectors",
                },
                "local_connectivity": {
                    "feature_role": "progressive_input",
                    "available_for_training_input": input_available,
                    "net_count_anchor": len(patch_nets),
                    "net_count_overlap": len(overlap_nets),
                    "cross_patch_net_count": sum(
                        1
                        for net in overlap_nets
                        if net.get("connectivity_summary", {}).get("cross_patch")
                    ),
                    "entering_net_count": sum(
                        1
                        for net in overlap_nets
                        if patch_id != net.get("patch_anchor", {}).get("primary_patch_id")
                    ),
                    "leaving_net_count": sum(
                        1
                        for net in patch_nets
                        if net.get("connectivity_summary", {}).get("cross_patch")
                    ),
                    "internal_net_count": sum(
                        1
                        for net in patch_nets
                        if not net.get("connectivity_summary", {}).get("cross_patch")
                    ),
                    "high_fanout_net_count": sum(
                        1
                        for net in overlap_nets
                        if int(net.get("connectivity_summary", {}).get("fanout") or 0) >= 8
                    ),
                    "clock_net_count": sum(
                        1 for net in overlap_nets if net.get("identity", {}).get("is_clock")
                    ),
                    "reset_net_count": sum(
                        1 for net in overlap_nets if net.get("identity", {}).get("is_reset")
                    ),
                    "pg_net_count": _pg_net_count_for_patch(pg_net_count, overlap_nets),
                    "signal_net_count": sum(
                        1 for net in overlap_nets if net.get("identity", {}).get("is_signal")
                    ),
                    "local_hpwl_sum": _sum_optional(
                        net.get("geometry_proxy", {}).get("hpwl") for net in patch_nets
                    ),
                    "local_hpwl_max": _max_optional(
                        net.get("geometry_proxy", {}).get("hpwl") for net in patch_nets
                    ),
                    "local_hpwl_mean": _mean_optional(
                        net.get("geometry_proxy", {}).get("hpwl") for net in patch_nets
                    ),
                    "source": f"vectors/nets/{stage}.jsonl",
                },
                "pre_route_estimators": {
                    "feature_role": "progressive_input",
                    "available_for_training_input": input_available,
                    "rudy_horizontal": _value_from_named_map(
                        rudy_maps, "rudy_horizontal", row, col
                    ),
                    "rudy_vertical": _value_from_named_map(rudy_maps, "rudy_vertical", row, col),
                    "rudy_union": rudy_union,
                    "egr_overflow_horizontal": egr_horizontal,
                    "egr_overflow_vertical": egr_vertical,
                    "egr_overflow_union": egr_union,
                    "margin_horizontal": _matrix_value(margin_maps.get("horizontal"), row, col),
                    "margin_vertical": _matrix_value(margin_maps.get("vertical"), row, col),
                    "source": "canonical_maps",
                },
                "neighbor_context": {
                    "feature_role": "progressive_input",
                    "available_for_training_input": input_available,
                    "adjacent_patch_ids": adjacent_ids,
                    "window_3x3_patch_ids": neighbor_ids,
                    "window_3x3_valid_count": len(neighbor_ids),
                    "edge_position": _edge_position(row, col, rows, cols),
                    "window_3x3_cell_density_mean": _mean_optional(window_cell_values),
                    "window_3x3_pin_density_sum": _sum_optional(window_pin_density_values),
                    "window_3x3_pin_count_sum": sum(
                        len(pins_by_primary.get(item, [])) for item in neighbor_ids
                    ),
                    "window_3x3_rudy_max": _max_optional(window_rudy_values),
                    "window_3x3_egr_overflow_max": _max_optional(window_egr_values),
                    "source": f"vectors/patches/{stage}.jsonl",
                },
                "entity_refs": {
                    "anchor_semantics": "primary_patch_or_center",
                    "overlap_semantics": "bbox_or_segment_intersection",
                    "instance_count": len(patch_instances),
                    "instance_overlap_count": len(overlap_instances),
                    "pin_count": len(patch_pins),
                    "pin_overlap_count": len(overlap_pins),
                    "net_count": len(patch_nets),
                    "net_overlap_count": len(overlap_nets),
                    "wire_count": len(patch_wires),
                    "timing_path_count": len(patch_timing_paths),
                    "drc_count": patch_drc.get("count"),
                    "sample_instance_keys": [
                        item.get("identity", {}).get("instance_key")
                        for item in patch_instances[:32]
                    ],
                    "sample_pin_keys": [item.get("pin_key") for item in patch_pins[:32]],
                    "sample_net_keys": [item.get("net_key") for item in patch_nets[:32]],
                    "sample_wire_ids": [item.get("wire_key") for item in patch_wires[:32]],
                    "sample_timing_path_ids": [item.get("id") for item in patch_timing_paths[:32]],
                    "sample_drc_ids": [],
                    "refs_truncated": any(
                        count > 32
                        for count in (
                            len(patch_instances),
                            len(patch_pins),
                            len(patch_nets),
                            len(patch_wires),
                            len(patch_timing_paths),
                        )
                    ),
                    "ref_limit": 32,
                },
                "timing_context": timing_context,
                "electrical_context": electrical_context,
                "route_oracle": route_oracle,
                "label_refs": {
                    "route_patch_overflow": None,
                    "route_native_demand_capacity": (
                        f"labels/route_native_demand_capacity.jsonl#patch_id={patch_id}"
                        if native_demand_capacity
                        else None
                    ),
                    "route_reconstructed_congestion": None,
                    "label_source_status": "available" if native_demand_capacity else "missing",
                },
                "drc_context": drc_context,
                "progressive_metadata": {
                    "available_from": "Floorplan" if stage_order else stage,
                    "grid_stable_across_stages": True,
                    "stage_order_index": stage_index,
                    "is_progressive_input_stage": is_progressive_input_stage,
                    "is_route_oracle_stage": stage == "route",
                    "input_blocks": input_blocks if is_progressive_input_stage else [],
                    "oracle_blocks": ["route_oracle"] if stage == "route" else [],
                    "prev_stage": prev_stage,
                    "density_delta_from_prev_stage": None,
                    "pin_count_delta_from_prev_stage": None,
                    "rudy_delta_from_prev_stage": None,
                    "egr_overflow_delta_from_prev_stage": None,
                },
                "source_refs": {
                    "canonical_grid": "canonical_grid.json",
                    "stage_def": def_source,
                    "density_maps": f"maps/{stage}/density.json" if density_maps else None,
                    "rudy_maps": f"maps/{stage}/rudy.json" if rudy_maps else None,
                    "egr_maps": f"maps/{stage}/congestion.json" if congestion_maps else None,
                    "instances": f"vectors/instances/{stage}.jsonl",
                    "pins": f"vectors/pins/{stage}.jsonl",
                    "nets": f"vectors/nets/{stage}.jsonl",
                    "wires": f"vectors/wires/{stage}.jsonl",
                    "timing_paths": f"vectors/timing_paths/{stage}.jsonl",
                    "route": def_source if stage == "route" else None,
                    "drc": "drc_artifacts"
                    if drc_context.get("availability") == "available"
                    else None,
                    "route_label_definition": (
                        "route_oracle.native_demand_capacity."
                        "union_demand_capacity=max("
                        "horizontal_demand_capacity,vertical_demand_capacity); "
                        "union_utilization=max(horizontal_utilization,vertical_utilization); "
                        "tightness_class={over_capacity,near_capacity,relaxed,unknown}"
                        if stage == "route" and native_demand_capacity
                        else None
                    ),
                },
                "null_reason": null_reason,
            }
            records.append(record)
        return records

    def _write_labels(
        self, native_demand_capacity: list[dict[str, Any]], *, export_legacy_debug: bool
    ) -> dict[str, Any]:
        if export_legacy_debug:
            write_jsonl(
                self.foundation_dir / "labels" / "route_native_demand_capacity.jsonl",
                native_demand_capacity,
            )
        self._mark(
            "labels",
            "route_native_demand_capacity",
            "available" if native_demand_capacity else "missing",
            ""
            if native_demand_capacity
            else "missing_irt_space_router_native_demand_capacity_artifact",
        )
        return {
            "route_native_demand_capacity_count": len(native_demand_capacity),
            "_route_native_demand_capacity_records": native_demand_capacity,
        }

    def _build_stage_index(self, stages: list[StageInfo]) -> dict[str, Any]:
        index = {"stages": []}
        for stage in stages:
            entry = {
                "name": stage.name,
                "tool": stage.tool,
                "state": stage.state,
                "directory": str(stage.directory.relative_to(self.workspace_dir))
                if stage.directory.exists()
                else str(stage.directory),
            }
            for folder in ("output", "feature", "analysis", "report", "data"):
                root = stage.directory / folder
                entry[folder] = (
                    sorted(
                        str(path.relative_to(self.workspace_dir))
                        for path in root.rglob("*")
                        if path.is_file()
                    )
                    if root.exists()
                    else []
                )
            index["stages"].append(entry)
        return index

    def _collect_metrics(self, stages: list[StageInfo]) -> dict[str, Any]:
        metrics = {}
        for stage in stages:
            stage_metrics: dict[str, Any] = {}
            for path in sorted((stage.directory / "analysis").glob("*.json")):
                stage_metrics[path.name] = self._read_json(path)
                self._record_raw_ref(stage, path, "metrics_json", {})
            feature_metrics = self._collect_feature_metric_files(stage)
            if feature_metrics:
                stage_metrics["features"] = feature_metrics
            metrics[stage.name] = stage_metrics
        return metrics

    def _collect_feature_metric_files(self, stage: StageInfo) -> dict[str, Any]:
        feature_metrics = {}
        for path in sorted((stage.directory / "feature").glob("*.json")):
            payload = self._read_json(path)
            if not payload:
                continue
            feature_metrics[path.name] = payload
            self._record_raw_ref(stage, path, "feature_summary_json", {})
        return feature_metrics

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _build_summary(
        self,
        flow: dict,
        parameters: dict,
        stages: list[StageInfo],
        metrics: dict,
        entity_counts: dict,
        labels: dict,
        def_data: dict[str, DefData],
        sta_reports: dict[str, dict[str, Any]],
        drc_reports: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        ppa_metrics = self._build_ppa_metrics(
            metrics, stages, labels, def_data, sta_reports, drc_reports
        )
        return {
            "workspace": str(self.workspace_dir),
            "flow": _summary_flow(flow, stages),
            "parameters": parameters,
            "stage_count": len(stages),
            "metrics": ppa_metrics,
            "entity_counts": entity_counts,
            "labels": labels,
        }

    def _build_summary_parameters(
        self, parameters: dict[str, Any], stages: list[StageInfo], def_data: dict[str, DefData]
    ) -> dict[str, Any]:
        del def_data
        normalized = self._engineer_settable_parameters(parameters)
        normalized["control_knobs"] = self._collect_control_knobs(stages)
        return normalized

    @staticmethod
    def _engineer_settable_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
        normalized = json.loads(json.dumps(parameters))
        normalized.pop("PDK Root", None)
        normalized.pop("Die", None)
        core = normalized.get("Core")
        if isinstance(core, dict):
            allowed_core = {
                key: core[key] for key in ("Utilitization", "Margin", "Aspect ratio") if key in core
            }
            if allowed_core:
                normalized["Core"] = allowed_core
            else:
                normalized.pop("Core", None)
        return normalized

    def _collect_control_knobs(self, stages: list[StageInfo]) -> dict[str, Any]:
        knobs: dict[str, Any] = {"source": "effective_tool_flow_configs"}
        floorplan = self._first_config_values(
            stages, "fp_default_config.json", {"tap_distance": ("Floorplan", "Tap distance")}
        )
        if floorplan:
            knobs["floorplan"] = floorplan
        dreamplace = self._first_config_values(
            [stage for stage in stages if stage.tool == "dreamplace"],
            "dreamplace.json",
            {
                "num_bins_x": ("num_bins_x",),
                "num_bins_y": ("num_bins_y",),
                "global_place_stages": ("global_place_stages",),
                "density_weight": ("density_weight",),
                "random_seed": ("random_seed",),
                "route_num_bins_x": ("route_num_bins_x",),
                "route_num_bins_y": ("route_num_bins_y",),
                "unit_horizontal_capacity": ("unit_horizontal_capacity",),
                "unit_vertical_capacity": ("unit_vertical_capacity",),
                "max_route_opt_adjust_rate": ("max_route_opt_adjust_rate",),
            },
        )
        if dreamplace:
            knobs["dreamplace"] = dreamplace
        fix_fanout = self._first_config_values(
            [stage for stage in stages if stage.name == "fixFanout"],
            "no_default_config_fixfanout.json",
            {"insert_buffer": ("insert_buffer",)},
        )
        if fix_fanout:
            knobs["fix_fanout"] = fix_fanout
        cts = self._first_config_values(
            [stage for stage in stages if stage.name == "CTS"],
            "cts_default_config.json",
            {
                "router_type": ("router_type",),
                "cluster_type": ("cluster_type",),
                "skew_bound": ("skew_bound",),
                "max_buf_tran": ("max_buf_tran",),
                "max_sink_tran": ("max_sink_tran",),
                "max_cap": ("max_cap",),
                "routing_layer": ("routing_layer",),
                "buffer_type": ("buffer_type",),
                "root_buffer_type": ("root_buffer_type",),
            },
        )
        if cts:
            knobs["cts"] = cts
        route = self._first_config_values(
            [stage for stage in stages if stage.name == "route"],
            "rt_default_config.json",
            {
                "thread_number": ("RT", "-thread_number"),
                "enable_timing": ("RT", "-enable_timing"),
            },
        )
        if route:
            knobs["route"] = route
        return knobs

    def _build_ppa_metrics(
        self,
        metrics: dict[str, Any],
        stages: list[StageInfo],
        labels: dict[str, Any],
        def_data: dict[str, DefData],
        sta_reports: dict[str, dict[str, Any]],
        drc_reports: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        del labels
        ppa_metrics: dict[str, Any] = {}
        for stage in stages:
            stage_metrics: dict[str, Any] = {}
            for payload in metrics.get(stage.name, {}).values():
                if isinstance(payload, dict):
                    stage_metrics.update(_extract_ppa_metric_values(payload))
            parsed_def = def_data.get(stage.name)
            if parsed_def:
                scale = _def_unit_scale(parsed_def)
                stage_metrics.update(
                    {
                        "die_area": _bbox_area(
                            _scale_bbox(parsed_def.diearea, scale) if parsed_def.diearea else None
                        ),
                        "wire_count": sum(len(net.wires) for net in parsed_def.nets),
                        "wire_length": sum(
                            wire.length for net in parsed_def.nets for wire in net.wires
                        )
                        * scale,
                        "via_count": sum(
                            1 for net in parsed_def.nets for wire in net.wires if wire.via
                        ),
                    }
                )
            sta_report = sta_reports.get(stage.name)
            if sta_report:
                slacks = [
                    _to_float(
                        record.get("path_timing", {}).get("slack")
                        if isinstance(record.get("path_timing"), dict)
                        else record.get("slack")
                    )
                    for record in sta_report.get("records", [])
                    if isinstance(record, dict)
                ]
                slacks = [value for value in slacks if value is not None]
                if slacks:
                    stage_metrics["worst_slack"] = min(slacks)
            drc_report = drc_reports.get(stage.name)
            if drc_report:
                stage_metrics["drc_violation_count"] = drc_report.get("count", 0)
            route_feature_metrics = _extract_route_ppa_metrics(
                metrics.get(stage.name, {}).get("features", {})
            )
            if route_feature_metrics:
                stage_metrics.update(route_feature_metrics)
            ppa_metrics[stage.name] = {
                key: value for key, value in stage_metrics.items() if value is not None
            }
        return ppa_metrics

    def _first_config_values(
        self, stages: list[StageInfo], filename: str, paths: dict[str, tuple[str, ...]]
    ) -> dict[str, Any]:
        for stage in stages:
            config_path = stage.directory / "config" / filename
            payload = self._read_json(config_path)
            if not payload:
                continue
            values = {name: _get_nested(payload, path) for name, path in paths.items()}
            return {name: value for name, value in values.items() if value is not None}
        return {}

    def _build_table_rows(
        self,
        *,
        flow: dict[str, Any],
        parameters: dict[str, Any],
        stages: list[StageInfo],
        canonical_grid: dict[str, Any],
        canonical_maps: CanonicalMaps,
        labels: dict[str, Any],
        metrics: dict[str, Any],
        drc_reports: dict[str, dict[str, Any]] | None = None,
        def_data: dict[str, DefData] | None = None,
        skip_tables: frozenset[str] | set[str] | None = None,
        materialize_audit_tables: bool = True,
        route_detail_level: str = "full",
    ) -> dict[str, list[dict[str, Any]] | Iterable[dict[str, Any]]]:
        skip = frozenset(skip_tables or ())
        design_name = str(parameters.get("Design") or parameters.get("design") or "unknown")
        top_module = str(
            parameters.get("Top module") or parameters.get("top_module") or design_name
        )
        pdk = str(parameters.get("PDK") or parameters.get("pdk") or "unknown")
        logical_source_hash = _stable_digest({"pdk": pdk, "design": design_name, "top": top_module})
        design_id = _stable_id("design", pdk, design_name, top_module, logical_source_hash)
        run_id = _stable_id("run", design_id, parameters, self._source_signature())
        stage_ids = {
            stage.name: _stage_id(run_id, index, stage.name) for index, stage in enumerate(stages)
        }
        flow_steps = _stage_flow_step_by_name(flow)
        tables: dict[str, list[dict[str, Any]] | Iterable[dict[str, Any]]] = {}
        design_rows = [
            {
                "design_id": design_id,
                "pdk": pdk,
                "design_name": design_name,
                "top_module": top_module,
                "logical_source_hash": logical_source_hash,
                "tech_profile": str(parameters.get("tech_profile") or pdk),
                "created_from_workspace": str(self.workspace_dir),
            }
        ]
        if "designs" not in skip:
            tables["designs"] = design_rows
        instance_stage_state = self._instance_stage_state_rows(design_id, run_id, stages)
        placement_rows = self._placement_row_rows(design_id, run_id, def_data or {})
        tables.update(
            {
                "runs": [
                    {
                        "design_id": design_id,
                        "run_id": run_id,
                        "parameter_hash": _stable_digest(parameters),
                        "flow_hash": _stable_digest(flow.get("steps", [])),
                        "tool_version_hash": _stable_digest(self._source_signature()),
                        "workspace_path": str(self.workspace_dir),
                        "status": _overall_status(stages),
                        "created_at": None,
                    }
                ],
                "stages": [
                    {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_id": stage_ids[stage.name],
                        "stage_order": index,
                        "stage_name": stage.name,
                        "tool": stage.tool,
                        "state": stage.state,
                        "stage_dir": _relative_or_string(stage.directory, self.workspace_dir),
                        "runtime_s": _runtime_to_seconds(
                            flow_steps.get(stage.name, {}).get("runtime")
                        ),
                        "peak_memory_mb": _to_float(
                            flow_steps.get(stage.name, {}).get("peak memory (mb)")
                        ),
                    }
                    for index, stage in enumerate(stages)
                ],
                "artifacts": self._artifact_table_rows(
                    design_id, run_id, stage_ids, labels, metrics
                ),
                "drc_violations": self._drc_violation_rows(design_id, run_id, drc_reports or {}),
                "provenance": [],
                "semantic_blocks": self._semantic_block_rows(design_id, run_id, stages)
                if materialize_audit_tables
                else [],
                "run_stage_patch_maps": self._patch_map_rows(
                    design_id, run_id, stage_ids, canonical_grid, canonical_maps
                ),
                "run_stage_patch_features": self._patch_feature_rows(
                    design_id,
                    run_id,
                    stage_ids,
                    stages,
                    route_detail_level=route_detail_level,
                ),
                "run_patch_route_labels": self._route_label_rows(design_id, run_id, labels),
                "run_patch_route_label_layers": self._route_label_layer_rows(
                    design_id, run_id, labels
                ),
                "patch_entity_refs": self._patch_entity_ref_rows(design_id, run_id, stages)
                if materialize_audit_tables
                else [],
                "instances": self._instance_rows(design_id, stages),
                "instance_stage_state": instance_stage_state,
                "placement_rows": placement_rows,
                "instance_row_refs": _instance_row_ref_rows(instance_stage_state, placement_rows),
                "clock_instance_refs": [],
                "pins": self._pin_rows(design_id, stages),
                "pin_stage_state": self._pin_stage_state_rows(design_id, run_id, stages),
                "nets": self._net_rows(design_id, stages),
                "net_terminals": self._net_terminal_rows(design_id, run_id, stages),
                "wire_segments": []
                if route_detail_level == "labels_only"
                else self._wire_segment_rows(design_id, run_id, stages),
                "wire_patch_intersections": []
                if route_detail_level == "labels_only"
                else self._wire_patch_intersection_rows(design_id, run_id, stages),
                "routing_vertices": []
                if route_detail_level == "labels_only"
                else self._routing_vertex_rows(design_id, run_id, stages),
                "routing_edges": []
                if route_detail_level == "labels_only"
                else self._routing_edge_rows(design_id, run_id, stages),
                "timing_paths": self._timing_path_rows(design_id, run_id, stages),
                "timing_path_points": self._timing_path_point_rows(design_id, run_id, stages),
                "timing_edges": self._timing_edge_rows(design_id, run_id, stages),
                "timing_wire_path_nodes": self._timing_wire_path_node_rows(
                    design_id, run_id, stages
                ),
                "stage_metrics": self._stage_metric_rows(design_id, run_id, metrics),
                "stage_deltas": self._stage_delta_rows(design_id, run_id, stages),
            }
        )
        if "patches" not in skip:
            tables["patches"] = self._patch_table_rows(design_id, canonical_grid)
        if "patch_neighbors" not in skip:
            tables["patch_neighbors"] = self._patch_neighbor_rows(design_id, canonical_grid)
        if "tech_layers" not in skip:
            tables["tech_layers"] = list(self._tech_layer_rows(design_id))
        if "tech_vias" not in skip:
            tables["tech_vias"] = list(self._tech_via_rows(design_id))
        if "library_cells" not in skip:
            tables["library_cells"] = list(self._library_cell_rows(design_id))
        for table_name in (
            "run_stage_patch_maps",
            "run_stage_patch_features",
            "stage_deltas",
            "semantic_blocks",
        ):
            if not isinstance(tables[table_name], list):
                tables[table_name] = list(tables[table_name])
        if materialize_audit_tables:
            tables["provenance"] = self._provenance_rows(
                {
                    "run_stage_patch_maps": tables["run_stage_patch_maps"],
                    "run_stage_patch_features": tables["run_stage_patch_features"],
                    "stage_deltas": tables["stage_deltas"],
                    "semantic_blocks": tables["semantic_blocks"],
                    "drc_violations": tables["drc_violations"],
                }
            )
        tables["_manifest_design_row"] = design_rows
        return tables

    def _drc_violation_rows(
        self,
        design_id: str,
        run_id: str,
        drc_reports: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = []
        for stage_name, report in sorted(drc_reports.items()):
            for violation in report.get("violations", []):
                source_index = _to_int_or_none(violation.get("id"))
                native_type = str(violation.get("type") or "unknown")
                bbox = violation.get("bbox")
                layer = violation.get("layer")
                source = str(violation.get("source") or report.get("source") or "")
                availability = "available" if bbox and layer else "partial"
                rows.append(
                    {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage_name,
                        "violation_id": _stable_id(
                            "drc_violation", run_id, stage_name, source_index
                        ),
                        "native_type": native_type,
                        "normalized_class": (
                            "short" if native_type.casefold() == "short" else "other"
                        ),
                        "rule": violation.get("rule"),
                        "layer": layer,
                        "bbox_json": json_value(bbox) if bbox else None,
                        "count": _to_int_or_none(violation.get("count")) or 1,
                        "source_artifact_id": _source_artifact_id(source) if source else None,
                        "source_index": source_index,
                        "availability": availability,
                    }
                )
        return rows

    def _placement_row_rows(
        self,
        design_id: str,
        run_id: str,
        def_data: dict[str, DefData],
    ) -> list[dict[str, Any]]:
        rows = []
        for stage_name, parsed in sorted(def_data.items()):
            for row in parsed.rows:
                rows.append(
                    {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage_name,
                        "row_id": _stable_id("placement_row", run_id, stage_name, row.name),
                        "site": row.site,
                        "origin_x": row.x,
                        "origin_y": row.y,
                        "orientation": row.orient,
                        "count_x": row.count_x,
                        "count_y": row.count_y,
                        "step_x": row.step_x,
                        "step_y": row.step_y,
                        "availability": "available",
                    }
                )
        return rows

    def _artifact_table_rows(
        self,
        design_id: str,
        run_id: str,
        stage_ids: dict[str, str],
        labels: dict[str, Any],
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows = []
        seen: set[str] = set()
        for ref in self._raw_refs:
            rel_path = str(ref.get("path") or "")
            if not rel_path or rel_path in seen:
                continue
            seen.add(rel_path)
            path = self.workspace_dir / rel_path
            stage_name = str(ref.get("stage") or "")
            rows.append(
                {
                    "artifact_id": _stable_id("artifact", rel_path),
                    "design_id": design_id,
                    "run_id": run_id,
                    "stage_id": stage_ids.get(stage_name),
                    "artifact_type": str(ref.get("type") or "unknown"),
                    "relative_path": rel_path,
                    "sha256": _file_digest(path),
                    "size_bytes": path.stat().st_size if path.exists() else None,
                    "parser": "FoundationExtractor",
                    "parser_version": SCHEMA_VERSION,
                    "availability": "available" if path.exists() else "missing",
                }
            )
        for rel_path in ("home/flow.json", "home/parameters.json"):
            if rel_path in seen:
                continue
            path = self.workspace_dir / rel_path
            rows.append(
                {
                    "artifact_id": _stable_id("artifact", rel_path),
                    "design_id": design_id,
                    "run_id": run_id,
                    "stage_id": None,
                    "artifact_type": "workspace_metadata",
                    "relative_path": rel_path,
                    "sha256": _file_digest(path),
                    "size_bytes": path.stat().st_size if path.exists() else None,
                    "parser": "FoundationExtractor",
                    "parser_version": SCHEMA_VERSION,
                    "availability": "available" if path.exists() else "missing",
                }
            )
        for label in labels.get("_route_native_demand_capacity_records", []):
            rel_path = _workspace_relative_path(
                (label.get("source_artifacts") or {}).get("route_native_demand_capacity"),
                self.workspace_dir,
            )
            if not rel_path or rel_path in seen:
                continue
            seen.add(rel_path)
            path = self.workspace_dir / rel_path
            rows.append(
                {
                    "artifact_id": _source_artifact_id(rel_path),
                    "design_id": design_id,
                    "run_id": run_id,
                    "stage_id": stage_ids.get("route"),
                    "artifact_type": "route_native_demand_capacity",
                    "relative_path": rel_path,
                    "sha256": _file_digest(path),
                    "size_bytes": path.stat().st_size if path.exists() else None,
                    "parser": "route_native_demand_capacity",
                    "parser_version": SCHEMA_VERSION,
                    "availability": "available" if path.exists() else "derived_or_missing_raw",
                }
            )
        metric_artifact_ids: set[str] = set()
        for stage_name, stage_metrics in metrics.items():
            for metric_name in stage_metrics:
                rel_path = _metric_artifact_relative_path(stage_name, metric_name)
                artifact_id = _stable_id("metric", stage_name, metric_name)
                if not rel_path or artifact_id in metric_artifact_ids:
                    continue
                metric_artifact_ids.add(artifact_id)
                path = self.workspace_dir / rel_path
                rows.append(
                    {
                        "artifact_id": artifact_id,
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_id": stage_ids.get(stage_name),
                        "artifact_type": "stage_metric_bundle"
                        if metric_name == "features"
                        else "metrics_json",
                        "relative_path": rel_path,
                        "sha256": _file_digest(path),
                        "size_bytes": path.stat().st_size if path.exists() else None,
                        "parser": "FoundationExtractor",
                        "parser_version": SCHEMA_VERSION,
                        "availability": "available" if path.exists() else "derived_bundle",
                    }
                )
        return rows

    def _provenance_rows(
        self, tables: dict[str, list[dict[str, Any]] | Iterable[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {
            "foundation_contract": {
                "provenance_id": "foundation_contract",
                "target_table": "*",
                "target_key": "*",
                "target_field": "*",
                "artifact_id": None,
                "source_section": "foundation_extractor",
                "source_index": None,
                "availability_code": "available",
                "null_reason": None,
                "confidence": 1.0,
                "notes": (
                    "Parquet contract generated from normalized foundation-data table builders."
                ),
            }
        }

        def add(
            provenance_id: Any,
            *,
            target_table: str,
            target_key: Any = "*",
            target_field: str = "*",
            artifact_id: Any = None,
            derived_from_artifact_ids: list[str] | None = None,
            source_section: str = "foundation_extractor",
            source_index: Any = None,
            availability_code: str = "available",
            null_reason: Any = None,
            confidence: float = 1.0,
            notes: str = "",
        ) -> None:
            if not provenance_id:
                return
            key = str(provenance_id)
            rows.setdefault(
                key,
                {
                    "provenance_id": key,
                    "target_table": target_table,
                    "target_key": str(target_key),
                    "target_field": target_field,
                    "artifact_id": artifact_id,
                    "derived_from_artifact_ids": json_value(
                        sorted(set(derived_from_artifact_ids or []))
                    ),
                    "source_section": source_section,
                    "source_index": source_index,
                    "availability_code": availability_code,
                    "null_reason": None if null_reason is None else str(null_reason),
                    "confidence": float(confidence),
                    "notes": notes,
                },
            )

        for table_name in ("run_stage_patch_maps", "run_stage_patch_features", "stage_deltas"):
            for row in tables.get(table_name, ()):
                artifact_ids = self._row_artifact_ids_for_provenance(table_name, row)
                add(
                    row.get("provenance_id"),
                    target_table=table_name,
                    target_key=_provenance_target_key(row),
                    target_field="*",
                    artifact_id=artifact_ids[0] if len(artifact_ids) == 1 else None,
                    derived_from_artifact_ids=artifact_ids,
                    source_section=table_name,
                    availability_code=str(row.get("feature_availability_code") or "available"),
                    notes="Generated from normalized table row provenance.",
                )
        for row in tables.get("semantic_blocks", ()):
            add(
                _stable_id(
                    "semantic_block",
                    row.get("stage_name"),
                    row.get("entity_type"),
                    row.get("entity_key"),
                    row.get("block_name"),
                ),
                target_table="semantic_blocks",
                target_key=_provenance_target_key(row),
                target_field=str(row.get("block_name") or "*"),
                source_section=str(row.get("source_doc") or "legacy_schema_migration"),
                availability_code="available",
                notes=str(row.get("preserved_reason") or "Preserved semantic block."),
            )
        for row in tables.get("drc_violations", ()):
            add(
                _stable_id("provenance", "drc_violation", row.get("violation_id")),
                target_table="drc_violations",
                target_key=row.get("violation_id"),
                artifact_id=row.get("source_artifact_id"),
                source_section="drc_violation_map",
                source_index=row.get("source_index"),
                availability_code=str(row.get("availability") or "missing"),
                notes="Parsed from a native DRC violation record.",
            )
        return list(rows.values())

    def _row_artifact_ids_for_provenance(self, table_name: str, row: dict[str, Any]) -> list[str]:
        if table_name == "run_stage_patch_maps":
            rel_path = self._map_source_path(
                str(row.get("stage_name") or ""),
                str(row.get("category") or ""),
                str(row.get("channel") or ""),
            )
            return [_source_artifact_id(rel_path)] if rel_path else []
        if table_name == "run_stage_patch_features":
            stage_name = str(row.get("stage_name") or "")
            artifact_ids = []
            for rel_path in self._stage_feature_source_paths(stage_name):
                artifact_ids.append(_source_artifact_id(rel_path))
            return sorted(set(artifact_ids))
        if table_name == "stage_deltas":
            rel_path = self._entity_stage_source_path(
                str(row.get("to_stage") or ""), str(row.get("entity_type") or "")
            )
            return [_source_artifact_id(rel_path)] if rel_path else []
        return []

    def _map_source_path(self, stage_name: str, category: str, channel: str) -> str | None:
        preferred_types = (
            "gcell_patch_map_csv",
            "egr_demand_capacity_map_csv",
            "map_csv",
            "floorplan_specific_def_maps",
        )
        candidate_keys = [channel]
        if category == "congestion" and channel in {"horizontal", "vertical", "union"}:
            candidate_keys.append(f"{channel}_overflow")
        for artifact_type in preferred_types:
            for key in candidate_keys:
                rel_path = self._raw_ref_by_stage_type_key.get((stage_name, artifact_type, key))
                if rel_path:
                    return rel_path
        return self._fallback_existing_artifact_path(stage_name)

    def _stage_feature_source_paths(self, stage_name: str) -> list[str]:
        paths = []
        for ref in self._raw_refs:
            if ref.get("stage") == stage_name and ref.get("type") in {
                "gcell_patch_map_csv",
                "egr_demand_capacity_map_csv",
                "map_csv",
                "def",
                "sta_report_json",
                "drc_violation_map",
            }:
                paths.append(str(ref.get("path")))
        if not paths:
            fallback = self._fallback_existing_artifact_path(stage_name)
            if fallback:
                paths.append(fallback)
        return [path for path in paths if path]

    def _entity_stage_source_path(self, stage_name: str, entity_type: str) -> str | None:
        for ref in self._raw_refs:
            if ref.get("stage") == stage_name and ref.get("type") == "def":
                return str(ref.get("path"))
        if entity_type == "timing_path":
            for ref in self._raw_refs:
                if ref.get("stage") == stage_name and ref.get("type") == "sta_report_json":
                    return str(ref.get("path"))
        return self._fallback_existing_artifact_path(stage_name)

    def _fallback_existing_artifact_path(self, stage_name: str) -> str | None:
        stage_dir = _stage_directory_name(stage_name)
        prefixes = (
            f"{stage_dir}/output/",
            f"{stage_dir}/data/",
            f"{stage_dir}/analysis/",
            f"{stage_dir}/feature/",
        )
        for ref in self._raw_refs:
            rel_path = str(ref.get("path") or "")
            if rel_path.startswith(prefixes):
                return rel_path
        return None

    def _reload_legacy_vector_records(self, stages: list[StageInfo]) -> None:
        for entity in _ENTITY_NAMES:
            for stage in stages:
                self._vector_records[entity][stage.name] = _read_jsonl_records(
                    self.foundation_dir / "vectors" / entity / f"{stage.name}.jsonl"
                )

    def _records_for_stage(self, entity: str, stage_name: str) -> list[dict[str, Any]]:
        records = self._vector_records.get(entity, {}).get(stage_name)
        if records is not None:
            return records
        return _read_jsonl_records(self.foundation_dir / "vectors" / entity / f"{stage_name}.jsonl")

    def _semantic_block_sources(
        self, stage_name: str
    ) -> tuple[tuple[str, str, list[dict[str, Any]]], ...]:
        return (
            ("patch", "patch_key", self._records_for_stage("patches", stage_name)),
            ("instance", "name", self._records_for_stage("instances", stage_name)),
            ("pin", "pin_key", self._records_for_stage("pins", stage_name)),
            ("net", "net_key", self._records_for_stage("nets", stage_name)),
            ("wire_segment", "wire_key", self._records_for_stage("wires", stage_name)),
            ("routing_graph", "graph_key", self._records_for_stage("routing_graphs", stage_name)),
            ("timing_path", "path_key", self._records_for_stage("timing_paths", stage_name)),
        )

    def _semantic_block_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        block_names = ("source_refs", "null_reason", "progressive_metadata")
        for stage in stages:
            for entity_type, key_field, records in self._semantic_block_sources(stage.name):
                for record in records:
                    entity_key = str(record.get(key_field) or record.get("id"))
                    for block_name in block_names:
                        payload = record.get(block_name)
                        if payload is None:
                            continue
                        landing = _semantic_block_landing(entity_type, block_name)
                        source_doc = _semantic_block_source_doc(entity_type)
                        yield {
                            "design_id": design_id,
                            "run_id": run_id,
                            "stage_name": stage.name,
                            "entity_type": entity_type,
                            "entity_key": entity_key,
                            "block_name": block_name,
                            "block_payload": json_value(
                                _semantic_block_payload(
                                    payload, entity_type, block_name, stage.name
                                )
                            ),
                            "source_schema_version": "legacy_jsonl_iccd_full_v1",
                            "source_doc": source_doc,
                            "source_field_path": f"{source_doc}:{block_name}",
                            "preserved_reason": (
                                "Preserved legacy nested semantics during parquet normalization."
                            ),
                            "normalized_status": landing["normalized_status"],
                            "future_normalization_plan": landing["future_normalization_plan"],
                            "target_table": landing["target_table"],
                            "target_key": landing["target_key"],
                        }

    @staticmethod
    def _build_migration_report() -> dict[str, Any]:
        source_docs = [
            "canonical_grid.md",
            "labels_route_native_demand_capacity.md",
            "maps.md",
            "meta_manifest.md",
            "quality.md",
            "raw_refs.md",
            "vec_instance.md",
            "vec_nets.md",
            "vec_patches.md",
            "vec_pins.md",
            "vec_routing_graph.md",
            "vec_tech.md",
            "vec_timing_paths.md",
            "vec_wires.md",
            "views_agent.md",
            "views_ml.md",
        ]
        return {
            "contract_name": CONTRACT_NAME,
            "schema_version": SCHEMA_VERSION,
            "source_docs_dir": "ecos/agent/docs/foundatio_data",
            "source_docs": source_docs,
            "information_families": {
                "canonical_grid": {
                    "status": "preserved_as_table",
                    "target": ["patches", "patch_neighbors"],
                },
                "stage_maps": {
                    "status": "preserved_as_table",
                    "target": ["run_stage_patch_maps", "run_stage_patch_features"],
                },
                "patch_features": {
                    "status": "preserved_as_table",
                    "target": ["patches", "run_stage_patch_features", "patch_entity_refs"],
                },
                "pin_connectivity_timing_route": {
                    "status": "preserved_as_table",
                    "target": ["pins", "pin_stage_state", "patch_entity_refs"],
                },
                "net_connectivity_terminals": {
                    "status": "preserved_as_table",
                    "target": ["nets", "net_terminals"],
                },
                "wire_route_attribution": {
                    "status": "preserved_as_table",
                    "target": ["wire_segments", "wire_patch_intersections"],
                },
                "routing_graph_topology": {
                    "status": "preserved_as_table",
                    "target": ["routing_vertices", "routing_edges"],
                },
                "timing_paths": {
                    "status": "preserved_as_table",
                    "target": [
                        "timing_paths",
                        "timing_path_points",
                        "timing_edges",
                        "timing_wire_path_nodes",
                    ],
                },
                "route_native_labels": {
                    "status": "preserved_as_table",
                    "target": ["run_patch_route_labels", "run_patch_route_label_layers"],
                },
                "tech_library": {
                    "status": "preserved_as_table",
                    "target": ["tech_layers", "tech_vias", "library_cells"],
                },
                "source_refs_null_reason": {
                    "status": "preserved_as_semantic_block",
                    "target": ["provenance", "semantic_blocks"],
                },
                "agent_views": {"status": "preserved_as_view", "target": ["views/agent"]},
                "ml_views_leakage_policy": {
                    "status": "preserved_as_view",
                    "target": ["views/ml/task_views.json"],
                },
            },
            "semantic_block_policy": {
                "allowed_status": [
                    "preserved_only",
                    "side_table",
                    "strong_typed",
                    "deprecated_with_reason",
                ],
                "preserved_only_requires_future_normalization_plan": True,
            },
            "field_migration_checklist": _field_migration_checklist(),
        }

    @staticmethod
    def _patch_table_rows(design_id: str, canonical_grid: dict[str, Any]) -> list[dict[str, Any]]:
        rows = int(canonical_grid.get("rows") or 0)
        cols = int(canonical_grid.get("cols") or 0)
        out = []
        for patch in canonical_grid.get("patches", []):
            bbox = patch.get("bbox") or {}
            llx = float(bbox.get("llx") or 0.0)
            lly = float(bbox.get("lly") or 0.0)
            urx = float(bbox.get("urx") or 0.0)
            ury = float(bbox.get("ury") or 0.0)
            row = int(patch.get("row") or 0)
            col = int(patch.get("col") or 0)
            out.append(
                {
                    "design_id": design_id,
                    "grid_id": str(canonical_grid.get("grid_source") or "canonical_grid"),
                    "patch_id": int(patch.get("patch_id") or 0),
                    "row": row,
                    "col": col,
                    "bbox_llx": llx,
                    "bbox_lly": lly,
                    "bbox_urx": urx,
                    "bbox_ury": ury,
                    "center_x": (llx + urx) / 2.0,
                    "center_y": (lly + ury) / 2.0,
                    "width": urx - llx,
                    "height": ury - lly,
                    "area": max(0.0, urx - llx) * max(0.0, ury - lly),
                    "edge_position": _edge_position(row, col, rows, cols),
                }
            )
        return out

    @staticmethod
    def _patch_neighbor_rows(
        design_id: str, canonical_grid: dict[str, Any]
    ) -> list[dict[str, Any]]:
        rows = int(canonical_grid.get("rows") or 0)
        cols = int(canonical_grid.get("cols") or 0)
        out = []
        for patch in canonical_grid.get("patches", []):
            patch_id = int(patch.get("patch_id") or 0)
            row = int(patch.get("row") or 0)
            col = int(patch.get("col") or 0)
            for neighbor_id in _adjacent_patch_ids(row, col, rows, cols):
                out.append(
                    {
                        "design_id": design_id,
                        "patch_id": patch_id,
                        "neighbor_patch_id": int(neighbor_id),
                        "relation": "adjacent_4",
                    }
                )
            for neighbor_id in _neighbor_patch_ids(row, col, rows, cols):
                if neighbor_id == patch_id:
                    continue
                out.append(
                    {
                        "design_id": design_id,
                        "patch_id": patch_id,
                        "neighbor_patch_id": int(neighbor_id),
                        "relation": "window_3x3",
                    }
                )
        return out

    @staticmethod
    def _patch_map_rows(
        design_id: str,
        run_id: str,
        stage_ids: dict[str, str],
        canonical_grid: dict[str, Any],
        canonical_maps: CanonicalMaps,
    ) -> Iterable[dict[str, Any]]:
        for stage_name, stage_maps in canonical_maps.items():
            for category, channels in stage_maps.items():
                for channel, matrix in channels.items():
                    for patch in canonical_grid.get("patches", []):
                        row = int(patch.get("row") or 0)
                        col = int(patch.get("col") or 0)
                        value = _matrix_value(matrix, row, col)
                        if value is None:
                            continue
                        yield {
                            "design_id": design_id,
                            "run_id": run_id,
                            "stage_id": stage_ids.get(stage_name),
                            "stage_name": stage_name,
                            "patch_id": int(patch.get("patch_id") or 0),
                            "category": category,
                            "channel": channel,
                            "value": value,
                            "provenance_id": _stable_id("map", stage_name, category, channel),
                        }

    def _patch_feature_rows(
        self,
        design_id: str,
        run_id: str,
        stage_ids: dict[str, str],
        stages: list[StageInfo],
        *,
        route_detail_level: str = "full",
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for record in self._records_for_stage("patches", stage.name):
                density = record.get("local_density") or {}
                connectivity = record.get("local_connectivity") or {}
                estimators = record.get("pre_route_estimators") or {}
                timing = record.get("timing_context") or {}
                drc = record.get("drc_context") or {}
                oracle = record.get("route_oracle") or {}
                if route_detail_level == "labels_only":
                    oracle = {}
                yield {
                    "design_id": design_id,
                    "run_id": run_id,
                    "stage_id": stage_ids.get(stage.name),
                    "stage_name": stage.name,
                    "patch_id": _patch_id_from_record(record),
                    "cell_density": density.get("cell_density"),
                    "macro_density": density.get("macro_density"),
                    "pin_density": density.get("pin_density"),
                    "net_density": density.get("net_density"),
                    "instance_count_center": density.get("instance_count_center"),
                    "instance_count_overlap": density.get("instance_count_overlap"),
                    "stdcell_count": density.get("stdcell_count_center")
                    or density.get("stdcell_count_overlap"),
                    "macro_count": density.get("macro_count_overlap")
                    or density.get("macro_count_center"),
                    "physical_only_count": density.get("physical_only_count_overlap"),
                    "net_count_anchor": connectivity.get("net_count_anchor"),
                    "net_count_overlap": connectivity.get("net_count_overlap"),
                    "cross_patch_net_count": connectivity.get("cross_patch_net_count"),
                    "high_fanout_net_count": connectivity.get("high_fanout_net_count"),
                    "clock_net_count": connectivity.get("clock_net_count"),
                    "reset_net_count": connectivity.get("reset_net_count"),
                    "pg_net_count": connectivity.get("pg_net_count"),
                    "local_hpwl_sum": connectivity.get("local_hpwl_sum"),
                    "local_hpwl_max": connectivity.get("local_hpwl_max"),
                    "local_hpwl_mean": connectivity.get("local_hpwl_mean"),
                    "rudy_horizontal": estimators.get("rudy_horizontal"),
                    "rudy_vertical": estimators.get("rudy_vertical"),
                    "rudy_union": estimators.get("rudy_union"),
                    "margin_horizontal": estimators.get("margin_horizontal"),
                    "margin_vertical": estimators.get("margin_vertical"),
                    "egr_overflow_horizontal": estimators.get("egr_overflow_horizontal"),
                    "egr_overflow_vertical": estimators.get("egr_overflow_vertical"),
                    "egr_overflow_union": estimators.get("egr_overflow_union"),
                    "wire_length": density.get("wire_length") or oracle.get("wire_length"),
                    "via_count": density.get("via_count") or oracle.get("via_count"),
                    "critical_path_count": timing.get("critical_path_count"),
                    "worst_slack_min": timing.get("worst_slack_min"),
                    "max_slew": timing.get("max_slew"),
                    "max_cap": timing.get("max_cap"),
                    "drc_count": drc.get("count"),
                    "feature_availability_code": "available",
                    "provenance_id": _stable_id(
                        "patch_features", stage.name, record.get("patch_key")
                    ),
                }

    @staticmethod
    def _route_label_rows(
        design_id: str, run_id: str, labels: dict[str, Any]
    ) -> list[dict[str, Any]]:
        out = []
        for label in labels.get("_route_native_demand_capacity_records", []):
            route_label = _demand_capacity_label(label)
            oracle = _route_native_demand_capacity_oracle(route_label)
            out.append(
                {
                    "design_id": design_id,
                    "run_id": run_id,
                    "patch_id": int(label.get("patch_id") or 0),
                    "horizontal_capacity": oracle.get("horizontal_capacity"),
                    "horizontal_demand": oracle.get("horizontal_demand"),
                    "horizontal_demand_capacity": oracle.get("horizontal_demand_capacity"),
                    "horizontal_utilization": oracle.get("horizontal_utilization"),
                    "vertical_capacity": oracle.get("vertical_capacity"),
                    "vertical_demand": oracle.get("vertical_demand"),
                    "vertical_demand_capacity": oracle.get("vertical_demand_capacity"),
                    "vertical_utilization": oracle.get("vertical_utilization"),
                    "union_demand_capacity": oracle.get("union_demand_capacity"),
                    "union_utilization": oracle.get("union_utilization"),
                    "tightness_class": oracle.get("tightness_class"),
                    "label_source_artifact_id": _source_artifact_id(
                        (label.get("source_artifacts") or {}).get("route_native_demand_capacity")
                    ),
                    "availability_code": "available" if label else "missing",
                }
            )
        return out

    @staticmethod
    def _route_label_layer_rows(
        design_id: str, run_id: str, labels: dict[str, Any]
    ) -> list[dict[str, Any]]:
        out = []
        for label in labels.get("_route_native_demand_capacity_records", []):
            patch_id = int(label.get("patch_id") or 0)
            source_artifact_id = _source_artifact_id(
                (label.get("source_artifacts") or {}).get("route_native_demand_capacity")
            )
            for layer_name, by_direction in (label.get("by_layer") or {}).items():
                for direction in ("horizontal", "vertical"):
                    demand = by_direction.get(f"{direction}_demand")
                    capacity = by_direction.get(f"{direction}_capacity")
                    demand_capacity = by_direction.get(f"{direction}_demand_capacity")
                    if demand_capacity is None and demand is not None and capacity is not None:
                        demand_capacity = float(demand or 0.0) - float(capacity or 0.0)
                    out.append(
                        {
                            "design_id": design_id,
                            "run_id": run_id,
                            "patch_id": patch_id,
                            "layer_name": str(layer_name),
                            "direction": direction,
                            "capacity": capacity,
                            "demand": demand,
                            "demand_capacity": demand_capacity,
                            "utilization": _safe_ratio(demand, capacity),
                            "source_artifact_id": source_artifact_id,
                        }
                    )
        return out

    @staticmethod
    def _stage_metric_rows(
        design_id: str, run_id: str, metrics: dict[str, Any]
    ) -> list[dict[str, Any]]:
        out = []
        for stage_name, stage_metrics in metrics.items():
            for metric_name, metric_value in stage_metrics.items():
                out.append(
                    {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage_name,
                        "metric_name": metric_name,
                        "metric_value": json_value(metric_value),
                        "source_artifact_id": _stable_id("metric", stage_name, metric_name),
                    }
                )
        return out

    def _tech_layer_rows(self, design_id: str) -> Iterable[dict[str, Any]]:
        for record in self._tech_records.get("layers", []):
            identity = record.get("identity") or {}
            routing = record.get("routing_properties") or {}
            yield {
                "design_id": design_id,
                "layer_name": str(record.get("name") or identity.get("name")),
                "layer_index": identity.get("order"),
                "routing_direction": routing.get("preferred_direction"),
                "pitch": routing.get("pitch"),
                "default_width": routing.get("width"),
                "metadata": json_value(record),
            }

    def _tech_via_rows(self, design_id: str) -> Iterable[dict[str, Any]]:
        for record in self._tech_records.get("vias", []):
            stack = record.get("layer_stack") or {}
            yield {
                "design_id": design_id,
                "via_name": str(
                    record.get("name") or (record.get("identity") or {}).get("via_key")
                ),
                "cut_layer": stack.get("cut_layer"),
                "lower_layer": stack.get("bottom_layer"),
                "upper_layer": stack.get("top_layer"),
                "is_default": (record.get("identity") or {}).get("via_type") == "default",
                "metadata": json_value(record),
            }

    def _library_cell_rows(self, design_id: str) -> Iterable[dict[str, Any]]:
        for record in self._tech_records.get("cells", []):
            classification = record.get("classification") or {}
            physical = record.get("physical_properties") or {}
            pins = record.get("pin_summary") or {}
            yield {
                "design_id": design_id,
                "master": str(record.get("name") or (record.get("identity") or {}).get("cell_key")),
                "cell_class": classification.get("cell_class"),
                "physical_class": classification.get("physical_class"),
                "width": physical.get("width"),
                "height": physical.get("height"),
                "area": physical.get("area"),
                "pin_count": pins.get("pin_count"),
                "is_sequential": classification.get("cell_class") == "sequential",
                "is_physical_only": (record.get("identity") or {}).get("is_physical_only"),
                "metadata": json_value(record),
            }

    def _patch_entity_ref_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for entity, key_field, records in (
                ("instance", "name", self._records_for_stage("instances", stage.name)),
                ("pin", "pin_key", self._records_for_stage("pins", stage.name)),
                ("net", "net_key", self._records_for_stage("nets", stage.name)),
                ("wire_segment", "wire_key", self._records_for_stage("wires", stage.name)),
                ("timing_path", "path_key", self._records_for_stage("timing_paths", stage.name)),
            ):
                for record in records:
                    anchor = record.get("patch_anchor") or {}
                    geometry = record.get("geometry") or record.get("geometry_proxy") or {}
                    primary = anchor.get("primary_patch_id") or geometry.get("patch_id")
                    patch_ids = (
                        anchor.get("overlap_patch_ids")
                        or geometry.get("overlap_patch_ids")
                        or geometry.get("patch_ids")
                        or []
                    )
                    if primary is not None and primary not in patch_ids:
                        patch_ids = [primary, *patch_ids]
                    for patch_id in patch_ids:
                        yield {
                            "design_id": design_id,
                            "run_id": run_id,
                            "stage_name": stage.name,
                            "patch_id": int(patch_id),
                            "entity_type": entity,
                            "entity_key": str(record.get(key_field) or record.get("id")),
                            "relation": "primary" if patch_id == primary else "overlap",
                            "weight": None,
                            "is_primary": patch_id == primary,
                        }

    def _instance_rows(self, design_id: str, stages: list[StageInfo]) -> list[dict[str, Any]]:
        by_key = {}
        for stage in stages:
            for record in self._records_for_stage("instances", stage.name):
                identity = record.get("identity") or {}
                key = str(identity.get("instance_key") or record.get("name"))
                by_key.setdefault(
                    key,
                    {
                        "design_id": design_id,
                        "instance_key": key,
                        "master": identity.get("master"),
                        "cell_class": identity.get("cell_class"),
                        "physical_class": identity.get("physical_class"),
                        "is_macro": identity.get("is_macro"),
                        "is_physical_only": identity.get("is_physical_only"),
                        "is_clock_related": identity.get("is_clock_related"),
                    },
                )
        return list(by_key.values())

    def _instance_stage_state_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> list[dict[str, Any]]:
        out = []
        for stage in stages:
            for record in self._records_for_stage("instances", stage.name):
                identity = record.get("identity") or {}
                state = record.get("physical_state") or {}
                bbox = state.get("bbox") or {}
                origin = state.get("origin") or {}
                out.append(
                    {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage.name,
                        "instance_key": str(identity.get("instance_key") or record.get("name")),
                        "placement_status": state.get("placement_status"),
                        "origin_x": origin.get("x"),
                        "origin_y": origin.get("y"),
                        "bbox_llx": bbox.get("llx"),
                        "bbox_lly": bbox.get("lly"),
                        "bbox_urx": bbox.get("urx"),
                        "bbox_ury": bbox.get("ury"),
                        "orientation": state.get("orientation"),
                        "patch_id": state.get("patch_id")
                        or (record.get("patch_anchor") or {}).get("primary_patch_id"),
                        "overlap_patch_ids": json_value(state.get("overlap_patch_ids") or []),
                        "summary_json": json_value(record),
                    }
                )
        return out

    def _pin_rows(self, design_id: str, stages: list[StageInfo]) -> list[dict[str, Any]]:
        by_key = {}
        for stage in stages:
            for record in self._records_for_stage("pins", stage.name):
                identity = record.get("identity") or {}
                key = str(record.get("pin_key") or identity.get("pin_key"))
                by_key.setdefault(
                    key,
                    {
                        "design_id": design_id,
                        "pin_key": key,
                        "pin_kind": identity.get("pin_kind"),
                        "instance_key": identity.get("parent_instance_key"),
                        "pin_name": identity.get("pin_name"),
                        "full_name": identity.get("full_name"),
                        "parent_master": identity.get("parent_master"),
                        "is_io": identity.get("is_io"),
                        "is_macro_pin": identity.get("is_macro_pin"),
                    },
                )
        return list(by_key.values())

    def _pin_stage_state_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> list[dict[str, Any]]:
        out = []
        for stage in stages:
            for record in self._records_for_stage("pins", stage.name):
                geometry = record.get("geometry") or {}
                center = geometry.get("center") or {}
                out.append(
                    {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage.name,
                        "pin_key": str(
                            record.get("pin_key") or (record.get("identity") or {}).get("pin_key")
                        ),
                        "geometry_status": geometry.get("geometry_status"),
                        "center_x": center.get("x"),
                        "center_y": center.get("y"),
                        "patch_id": geometry.get("patch_id")
                        or (record.get("patch_anchor") or {}).get("primary_patch_id"),
                        "overlap_patch_ids": json_value(geometry.get("overlap_patch_ids") or []),
                        "electrical_json": json_value(record.get("electrical_context") or {}),
                        "timing_json": json_value(record.get("timing_context") or {}),
                        "route_json": json_value(record.get("route_context") or {}),
                    }
                )
        return out

    def _net_rows(self, design_id: str, stages: list[StageInfo]) -> list[dict[str, Any]]:
        by_key = {}
        for stage in stages:
            for record in self._records_for_stage("nets", stage.name):
                identity = record.get("identity") or {}
                key = str(record.get("net_key") or identity.get("net_key"))
                by_key.setdefault(
                    key,
                    {
                        "design_id": design_id,
                        "net_key": key,
                        "name": record.get("name") or identity.get("name"),
                        "use": identity.get("use"),
                        "net_class": identity.get("net_class"),
                        "is_clock": identity.get("is_clock"),
                        "is_reset": identity.get("is_reset"),
                        "is_power_ground": identity.get("is_power_ground"),
                        "is_signal": identity.get("is_signal"),
                    },
                )
        return list(by_key.values())

    def _net_terminal_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> list[dict[str, Any]]:
        out = []
        for stage in stages:
            for record in self._records_for_stage("nets", stage.name):
                net_key = str(
                    record.get("net_key") or (record.get("identity") or {}).get("net_key")
                )
                for terminal in record.get("terminal_refs") or []:
                    role = str(terminal.get("role") or terminal.get("terminal_role") or "")
                    out.append(
                        {
                            "design_id": design_id,
                            "run_id": run_id,
                            "stage_name": stage.name,
                            "net_key": net_key,
                            "pin_key": str(
                                terminal.get("pin_key")
                                or terminal.get("full_name")
                                or terminal.get("name")
                            ),
                            "terminal_role": role,
                            "is_driver": role.lower() == "driver",
                            "is_sink": role.lower() == "sink",
                            "patch_id": terminal.get("patch_id"),
                            "geometry_status": terminal.get("geometry_status"),
                            "critical_path_flag": terminal.get("critical_path_flag"),
                        }
                    )
        return out

    def _wire_segment_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for record in self._records_for_stage("wires", stage.name):
                identity = record.get("identity") or {}
                geometry = record.get("geometry") or {}
                start = geometry.get("start") or {}
                end = geometry.get("end") or {}
                yield {
                    "design_id": design_id,
                    "run_id": run_id,
                    "stage_name": stage.name,
                    "wire_segment_key": str(record.get("wire_key") or identity.get("wire_key")),
                    "net_key": identity.get("net_key"),
                    "source_section": identity.get("source_section"),
                    "segment_index": identity.get("segment_index"),
                    "layer": geometry.get("layer"),
                    "start_x": start.get("x"),
                    "start_y": start.get("y"),
                    "end_x": end.get("x"),
                    "end_y": end.get("y"),
                    "bbox_json": json_value(geometry.get("bbox") or {}),
                    "length": geometry.get("length"),
                    "direction": geometry.get("direction"),
                    "via_name": (record.get("via_context") or {}).get("via_name"),
                    "summary_json": json_value(_wire_segment_summary(record)),
                }

    def _wire_patch_intersection_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for record in self._records_for_stage("wires", stage.name):
                key = str(record.get("wire_key") or (record.get("identity") or {}).get("wire_key"))
                for item in record.get("patch_intersections") or []:
                    yield {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage.name,
                        "wire_segment_key": key,
                        "patch_id": int(item.get("patch_id") or 0),
                        "intersect_length": item.get("intersect_length") or item.get("length"),
                        "area_proxy": item.get("area_proxy"),
                        "layer": item.get("layer") or (record.get("geometry") or {}).get("layer"),
                        "direction": item.get("direction")
                        or (record.get("geometry") or {}).get("direction"),
                        "is_primary": item.get("is_primary"),
                        "capacity_contribution": item.get("capacity_contribution"),
                    }

    def _routing_vertex_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            graphs = self._records_for_stage("routing_graphs", stage.name)
            if not graphs and self._uses_direct_routing_graph_tables(stage.name):
                yield from self._routing_vertex_rows_from_wires(design_id, run_id, stage)
                continue
            for graph in graphs:
                net_key = str(graph.get("net_key") or (graph.get("identity") or {}).get("net_key"))
                for vertex in graph.get("vertices") or []:
                    yield {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage.name,
                        "net_key": net_key,
                        "vertex_id": int(vertex.get("vertex_id") or vertex.get("id") or 0),
                        "x": vertex.get("x") or (vertex.get("point") or {}).get("x"),
                        "y": vertex.get("y") or (vertex.get("point") or {}).get("y"),
                        "layer": vertex.get("layer"),
                        "vertex_kind": vertex.get("vertex_kind") or vertex.get("kind"),
                        "patch_id": vertex.get("patch_id"),
                        "terminal_pin_key": vertex.get("terminal_pin_key") or vertex.get("pin_key"),
                        "match_status": vertex.get("match_status"),
                    }

    def _routing_edge_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            graphs = self._records_for_stage("routing_graphs", stage.name)
            if not graphs and self._uses_direct_routing_graph_tables(stage.name):
                yield from self._routing_edge_rows_from_wires(design_id, run_id, stage)
                continue
            for graph in graphs:
                net_key = str(graph.get("net_key") or (graph.get("identity") or {}).get("net_key"))
                for edge in graph.get("edges") or []:
                    yield {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage.name,
                        "net_key": net_key,
                        "edge_id": int(edge.get("edge_id") or edge.get("id") or 0),
                        "source_vertex_id": edge.get("source_vertex_id")
                        or edge.get("src")
                        or edge.get("source"),
                        "target_vertex_id": edge.get("target_vertex_id")
                        or edge.get("dst")
                        or edge.get("target"),
                        "edge_kind": edge.get("edge_kind") or edge.get("kind"),
                        "geometry_json": json_value(edge.get("geometry") or {}),
                        "layer": edge.get("layer"),
                        "length": edge.get("length"),
                        "wire_segment_refs": json_value(edge.get("wire_segment_refs") or []),
                    }

    def _uses_direct_routing_graph_tables(self, stage_name: str) -> bool:
        return (
            self._quality.get("availability", {}).get("routing_graphs", {}).get(stage_name)
            == "direct_table_stream_from_wire_segments"
        )

    def _routing_vertex_rows_from_wires(
        self, design_id: str, run_id: str, stage: StageInfo
    ) -> Iterable[dict[str, Any]]:
        for index, record in enumerate(self._records_for_stage("wires", stage.name)):
            identity = record.get("identity") or {}
            geometry = record.get("geometry") or {}
            patch_anchor = record.get("patch_anchor") or {}
            net_key = str(identity.get("net_key") or "")
            for offset, endpoint_name in enumerate(("start", "end")):
                point = geometry.get(endpoint_name) or {}
                yield {
                    "design_id": design_id,
                    "run_id": run_id,
                    "stage_name": stage.name,
                    "net_key": net_key,
                    "vertex_id": index * 2 + offset,
                    "x": point.get("x"),
                    "y": point.get("y"),
                    "layer": geometry.get("layer"),
                    "vertex_kind": "wire_endpoint",
                    "patch_id": patch_anchor.get("primary_patch_id"),
                    "terminal_pin_key": None,
                    "match_status": "direct_from_wire_segment",
                }

    def _routing_edge_rows_from_wires(
        self, design_id: str, run_id: str, stage: StageInfo
    ) -> Iterable[dict[str, Any]]:
        for index, record in enumerate(self._records_for_stage("wires", stage.name)):
            identity = record.get("identity") or {}
            geometry = record.get("geometry") or {}
            wire_key = str(record.get("wire_key") or identity.get("wire_key") or f"wire:{index}")
            yield {
                "design_id": design_id,
                "run_id": run_id,
                "stage_name": stage.name,
                "net_key": str(identity.get("net_key") or ""),
                "edge_id": index,
                "source_vertex_id": index * 2,
                "target_vertex_id": index * 2 + 1,
                "edge_kind": "via_transition"
                if identity.get("segment_kind") == "via"
                else "wire_segment",
                "geometry_json": json_value(geometry),
                "layer": geometry.get("layer"),
                "length": geometry.get("length"),
                "wire_segment_refs": json_value([wire_key]),
            }

    def _timing_path_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for record in self._records_for_stage("timing_paths", stage.name):
                timing = record.get("path_timing") or {}
                endpoints = record.get("endpoints") or {}
                yield {
                    "design_id": design_id,
                    "run_id": run_id,
                    "stage_name": stage.name,
                    "path_id": str(record.get("path_key") or record.get("id")),
                    "startpoint": json_value(endpoints.get("startpoint") or {}),
                    "endpoint": json_value(endpoints.get("endpoint") or {}),
                    "delay_type": (record.get("analysis_context") or {}).get("delay_type")
                    or (record.get("identity") or {}).get("delay_type"),
                    "slack": timing.get("slack"),
                    "arrival": timing.get("arrival"),
                    "required": timing.get("path_required"),
                    "path_group": (record.get("identity") or {}).get("clock_group"),
                    "path_length_summary": json_value(record.get("path_spatial") or {}),
                    "criticality": timing.get("normalized_criticality"),
                }

    def _timing_path_point_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for record in self._records_for_stage("timing_paths", stage.name):
                path_id = str(record.get("path_key") or record.get("id"))
                for index, point in enumerate(record.get("path_points") or []):
                    center = point.get("center") or {}
                    yield {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage.name,
                        "path_id": path_id,
                        "point_index": int(point.get("point_index") or index),
                        "pin_key": point.get("pin_key"),
                        "instance_key": point.get("instance_key"),
                        "net_key": point.get("net_key"),
                        "x": center.get("x") or point.get("x"),
                        "y": center.get("y") or point.get("y"),
                        "patch_id": point.get("patch_id"),
                        "arrival": point.get("arrival"),
                        "slew": point.get("slew"),
                        "cap": point.get("cap"),
                        "incr_delay": point.get("incr_delay"),
                    }

    def _timing_edge_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for record in self._records_for_stage("timing_paths", stage.name):
                path_id = str(record.get("path_key") or record.get("id"))
                for index, edge in enumerate(record.get("timing_edges") or []):
                    yield {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage.name,
                        "path_id": path_id,
                        "edge_id": int(edge.get("edge_id") or index),
                        "from_pin_key": edge.get("from_pin_key"),
                        "to_pin_key": edge.get("to_pin_key"),
                        "edge_delay": edge.get("edge_delay"),
                        "transition": edge.get("transition"),
                        "net_key": edge.get("net_key"),
                        "edge_kind_source": edge.get("edge_kind_source") or edge.get("source"),
                    }

    def _timing_wire_path_node_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for record in self._records_for_stage("timing_paths", stage.name):
                path_id = str(record.get("path_key") or record.get("id"))
                for index, node in enumerate(record.get("wire_path_nodes") or []):
                    yield {
                        "design_id": design_id,
                        "run_id": run_id,
                        "stage_name": stage.name,
                        "path_id": path_id,
                        "node_id": int(node.get("node_id") or index),
                        "point": node.get("point") or node.get("Point"),
                        "cap": node.get("cap") or node.get("Capacitance"),
                        "slew": node.get("slew"),
                        "incr_delay": node.get("incr_delay") or node.get("Incr"),
                        "match_status": node.get("match_status"),
                        "payload_json": json_value(node),
                    }

    def _stage_delta_rows(
        self, design_id: str, run_id: str, stages: list[StageInfo]
    ) -> Iterable[dict[str, Any]]:
        for stage in stages:
            for entity, key_field, records in (
                ("instance", "name", self._records_for_stage("instances", stage.name)),
                ("pin", "pin_key", self._records_for_stage("pins", stage.name)),
                ("net", "net_key", self._records_for_stage("nets", stage.name)),
                ("patch", "patch_key", self._records_for_stage("patches", stage.name)),
                ("timing_path", "path_key", self._records_for_stage("timing_paths", stage.name)),
            ):
                for record in records:
                    progressive = record.get("progressive_metadata") or {}
                    prev_stage = progressive.get("prev_stage")
                    if not prev_stage and (
                        entity == "timing_path"
                        or progressive.get("exists_in_prev_stage") is not None
                    ):
                        prev_stage = _previous_stage_name(stages, stage.name)
                    if not prev_stage:
                        continue
                    entity_key = str(record.get(key_field) or record.get("id"))
                    emitted = False
                    for metric_name, (change_type, value) in self._progressive_delta_metrics(
                        progressive
                    ).items():
                        yield {
                            "design_id": design_id,
                            "run_id": run_id,
                            "from_stage": prev_stage,
                            "to_stage": stage.name,
                            "entity_type": entity,
                            "entity_key": entity_key,
                            "change_type": change_type,
                            "metric_name": metric_name,
                            "old_value": None,
                            "new_value": None if value is None else str(value),
                            "delta_value": value,
                            "provenance_id": _stable_id(
                                "stage_delta", stage.name, entity, entity_key, metric_name
                            ),
                        }
                        emitted = True
                    if not emitted:
                        yield {
                            "design_id": design_id,
                            "run_id": run_id,
                            "from_stage": prev_stage,
                            "to_stage": stage.name,
                            "entity_type": entity,
                            "entity_key": entity_key,
                            "change_type": "state_changed"
                            if progressive.get("exists_in_prev_stage") is False
                            else "metadata_changed",
                            "metric_name": "available_from",
                            "old_value": None,
                            "new_value": str(
                                progressive.get("available_from")
                                or progressive.get("created_stage")
                                or stage.name
                            ),
                            "delta_value": None,
                            "provenance_id": _stable_id(
                                "stage_delta", stage.name, entity, entity_key, "available_from"
                            ),
                        }

    @staticmethod
    def _progressive_delta_metrics(
        progressive: dict[str, Any],
    ) -> dict[str, tuple[str, float | None]]:
        metrics: dict[str, tuple[str, float | None]] = {}
        for key, value in progressive.items():
            if key.endswith("_delta_from_prev_stage"):
                numeric = _to_float(value)
                if numeric is not None:
                    metrics[key] = ("metric_changed", numeric)
            elif key in {"moved_from_prev_stage", "is_new_routed_geometry"} and value is True:
                metrics[key] = ("moved", None)
            elif key in {"dx_from_prev_stage", "dy_from_prev_stage"}:
                numeric = _to_float(value)
                if numeric is not None and numeric != 0.0:
                    metrics[key] = ("moved", numeric)
            elif key in {"geometry_changed_from_prev_stage"} and value is True:
                metrics[key] = ("geometry_changed", None)
            elif key in {
                "net_changed_from_prev_stage",
                "terminal_count_changed_from_prev_stage",
                "patch_span_delta_from_prev_stage",
            }:
                numeric = _to_float(value)
                if value is True or (numeric is not None and numeric != 0.0):
                    metrics[key] = ("connectivity_changed", numeric)
            elif key in {
                "slack_delta_from_prev_stage",
                "delay_delta_from_prev_stage",
                "rank_delta_from_prev_stage",
                "endpoint_best_slack_delta_from_prev_stage",
            }:
                numeric = _to_float(value)
                if numeric is not None:
                    metrics[key] = ("timing_changed", numeric)
        return metrics

    def _remove_legacy_default_outputs(self) -> None:
        for name in ("vectors", "maps", "labels"):
            path = self.foundation_dir / name
            if path.exists():
                shutil.rmtree(path)

    def _record_tech_materialization_quality(self, table_registry: dict[str, Any]) -> list[str]:
        tech_quality = self._quality.setdefault("tech", {})
        tech_quality["source_counts"] = {
            "lef_layers": len(self._lef_layers),
            "lef_vias": len(self._lef_vias),
            "lef_macros": len(self._lef_macros),
            "record_layers": len(self._tech_records.get("layers", [])),
            "record_vias": len(self._tech_records.get("vias", [])),
            "record_cells": len(self._tech_records.get("cells", [])),
        }
        tech_quality["materialization_counts"] = {
            table_name: int((table_registry.get(table_name) or {}).get("row_count") or 0)
            for table_name in _TECH_REQUIRED_TABLES
        }
        errors = self._tech_materialization_errors(tech_quality)
        if errors:
            self._quality.setdefault("warnings", []).extend(errors)
        return errors

    def _tech_materialization_errors(self, tech_quality: dict[str, Any]) -> list[str]:
        availability = self._quality.get("availability", {}).get("tech", {})
        source_counts = tech_quality.get("source_counts", {})
        materialization_counts = tech_quality.get("materialization_counts", {})
        errors = []
        for table_name, record_key in _TECH_REQUIRED_TABLES.items():
            row_count = int(materialization_counts.get(table_name) or 0)
            source_key = f"record_{record_key}"
            source_count = int(source_counts.get(source_key) or 0)
            source_available = availability.get(record_key) == "available" or source_count > 0
            if source_available and row_count == 0:
                errors.append(
                    f"{table_name}: source_available=True, {source_key}={source_count}, row_count=0"
                )
        return errors

    def _build_manifest(
        self,
        stages: list[StageInfo],
        raw_maps: dict,
        summary: dict,
        *,
        options: dict[str, Any],
        table_registry: dict[str, Any],
        table_rows: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        del stages, raw_maps, summary
        design_row = (table_rows.get("designs") or table_rows.get("_manifest_design_row") or [{}])[
            0
        ]
        run_row = (table_rows.get("runs") or [{}])[0]
        stage_rows = table_rows.get("stages") or []
        artifacts = {
            "summary": str((self.foundation_dir / "summary.json").relative_to(self.workspace_dir)),
            "stage_index": str(
                (self.foundation_dir / "stage_index.json").relative_to(self.workspace_dir)
            ),
            "canonical_grid": str(
                (self.foundation_dir / "canonical_grid.json").relative_to(self.workspace_dir)
            ),
            "quality": str((self.foundation_dir / "quality.json").relative_to(self.workspace_dir)),
            "schema": str((self.foundation_dir / "schema.json").relative_to(self.workspace_dir)),
            "ml_view": str(
                (self.foundation_dir / "views" / "ml" / "dataset_index.json").relative_to(
                    self.workspace_dir
                )
            ),
            "agent_view": str(
                (self.foundation_dir / "views" / "agent" / "run_summary.json").relative_to(
                    self.workspace_dir
                )
            ),
        }
        if options.get("include_raw_refs"):
            artifacts["raw_refs"] = str(
                (self.foundation_dir / "raw_refs" / "artifacts.json").relative_to(
                    self.workspace_dir
                )
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "contract_name": CONTRACT_NAME,
            "storage_format": STORAGE_FORMAT,
            "route_completion_mode": options.get("route_completion_mode", "full_route"),
            **(
                {
                    "storage_layout": "base_delta_v1",
                    "base_manifest_path": options.get("base_manifest_path"),
                }
                if options.get("scope") in {"design_base", "variant_delta"}
                else {}
            ),
            "options": options,
            "workspace": str(self.workspace_dir),
            "source_workspace": str(self.workspace_dir),
            "design_id": design_row.get("design_id"),
            "run_id": run_row.get("run_id"),
            "stages": [
                {
                    "stage_id": row.get("stage_id"),
                    "stage_order": row.get("stage_order"),
                    "stage_name": row.get("stage_name"),
                    "tool": row.get("tool"),
                    "state": row.get("state"),
                }
                for row in stage_rows
            ],
            "created_at": datetime.now(UTC).isoformat(),
            "generated_by": {
                "extractor": "chipcompiler.data.foundation.FoundationExtractor",
                "profile": self.profile,
                "schema_version": SCHEMA_VERSION,
                "parser_versions": {"foundation_contract": SCHEMA_VERSION},
            },
            "sources": self._source_signature(),
            "schema": "foundation_data/ecc/schema.json",
            "migration_report": "foundation_data/ecc/migration_report.json",
            "tables": table_registry,
            "views": {
                "agent_run_summary": "foundation_data/ecc/views/agent/run_summary.json",
                "agent_qor_snapshot": "foundation_data/ecc/views/agent/qor_snapshot.json",
                "agent_evidence_index": "foundation_data/ecc/views/agent/evidence_index.json",
                "agent_attribution_inputs": (
                    "foundation_data/ecc/views/agent/attribution_inputs.v1.json"
                ),
                "ml_dataset_index": "foundation_data/ecc/views/ml/dataset_index.json",
                "ml_task_views": "foundation_data/ecc/views/ml/task_views.json",
                "ml_progressive_patch_dataset": (
                    "foundation_data/ecc/views/ml/progressive_patch_dataset.json"
                ),
            },
            "artifacts": artifacts,
        }

    def _record_patch_quality(
        self, stages: list[StageInfo], canonical_grid: dict[str, Any]
    ) -> None:
        patch_quality: dict[str, Any] = {
            "rows_by_stage": {},
            "schema_coverage_by_stage": {},
            "pre_route_estimators_availability_by_stage": {},
            "route_label_availability": {"available": 0, "missing": 0, "partial": 0},
            "route_oracle_tightness_class_distribution": {
                "over_capacity": 0,
                "near_capacity": 0,
                "relaxed": 0,
                "unknown": 0,
            },
            "refs_truncated_count_by_stage": {},
            "timing_context_availability_by_stage": {},
            "electrical_context_availability_by_stage": {},
            "drc_context_availability_by_stage": {},
            "null_reason_topk": [],
        }
        null_reasons: dict[str, int] = {}
        required_top = (
            "id",
            "stage",
            "patch_key",
            "source",
            "identity",
            "geometry",
            "local_density",
            "local_connectivity",
            "pre_route_estimators",
            "neighbor_context",
            "entity_refs",
            "timing_context",
            "electrical_context",
            "route_oracle",
            "label_refs",
            "drc_context",
            "progressive_metadata",
            "source_refs",
            "null_reason",
        )
        expected_rows = int(canonical_grid.get("rows") or 0) * int(canonical_grid.get("cols") or 0)
        for stage in stages:
            records = self._records_for_stage("patches", stage.name)
            patch_quality["rows_by_stage"][stage.name] = len(records)
            complete_records = sum(
                1 for record in records if all(key in record for key in required_top)
            )
            patch_quality["schema_coverage_by_stage"][stage.name] = {
                "expected_rows": expected_rows,
                "complete_records": complete_records,
                "missing_records": max(0, expected_rows - len(records)),
            }
            patch_quality["pre_route_estimators_availability_by_stage"][stage.name] = (
                _pre_route_availability_counts(records)
            )
            patch_quality["refs_truncated_count_by_stage"][stage.name] = sum(
                1 for record in records if record.get("entity_refs", {}).get("refs_truncated")
            )
            patch_quality["timing_context_availability_by_stage"][stage.name] = (
                _block_availability_counts(records, "timing_context")
            )
            patch_quality["electrical_context_availability_by_stage"][stage.name] = (
                _block_availability_counts(records, "electrical_context")
            )
            patch_quality["drc_context_availability_by_stage"][stage.name] = (
                _block_availability_counts(records, "drc_context")
            )
            for record in records:
                if stage.name == "route":
                    label_status = (
                        record.get("label_refs", {}).get("label_source_status") or "missing"
                    )
                    if label_status not in patch_quality["route_label_availability"]:
                        patch_quality["route_label_availability"][label_status] = 0
                    patch_quality["route_label_availability"][label_status] += 1
                    tightness = (record.get("route_oracle") or {}).get(
                        "native_demand_capacity", {}
                    ).get("tightness_class") or "unknown"
                    if tightness not in patch_quality["route_oracle_tightness_class_distribution"]:
                        patch_quality["route_oracle_tightness_class_distribution"][tightness] = 0
                    patch_quality["route_oracle_tightness_class_distribution"][tightness] += 1
                for key, value in (record.get("null_reason") or {}).items():
                    reason = f"{key}={value}"
                    null_reasons[reason] = null_reasons.get(reason, 0) + 1
        patch_quality["null_reason_topk"] = [
            {"reason": reason, "count": count}
            for reason, count in sorted(null_reasons.items(), key=lambda item: (-item[1], item[0]))[
                :10
            ]
        ]
        self._quality["patches"] = patch_quality

    def _record_wire_quality(self, stages: list[StageInfo]) -> None:
        wire_quality: dict[str, Any] = {}
        required_top = (
            "id",
            "stage",
            "wire_key",
            "source",
            "identity",
            "geometry",
            "layer_context",
            "track_context",
            "capacity_context",
            "patch_anchor",
            "patch_intersections",
            "net_context",
            "endpoint_context",
            "timing_context",
            "route_context",
            "via_context",
            "progressive_metadata",
            "source_refs",
            "null_reason",
        )
        for stage in stages:
            records = self._records_for_stage("wires", stage.name)
            record_count = len(records)
            route_context_count = sum(
                1 for record in records if isinstance(record.get("route_context"), dict)
            )
            route_context_source: dict[str, int] = {}
            for record in records:
                source = (
                    (record.get("route_context") or {}).get("source")
                    if isinstance(record.get("route_context"), dict)
                    else None
                )
                if source:
                    route_context_source[str(source)] = route_context_source.get(str(source), 0) + 1
            wire_quality[stage.name] = {
                "record_count": record_count,
                "signal_wire_count": sum(
                    1
                    for record in records
                    if record.get("identity", {}).get("wire_class") == "signal"
                ),
                "special_wire_count": sum(
                    1 for record in records if record.get("identity", {}).get("is_special")
                ),
                "via_count": sum(
                    1
                    for record in records
                    if record.get("identity", {}).get("segment_kind") == "via"
                ),
                "missing_width_count": sum(
                    1 for record in records if record.get("geometry", {}).get("width") is None
                ),
                "schema_complete_count": sum(
                    1 for record in records if all(key in record for key in required_top)
                ),
                "patch_intersection_coverage": (
                    sum(1 for record in records if record.get("patch_intersections")) / record_count
                )
                if record_count
                else 0.0,
                "route_context_coverage": (route_context_count / record_count)
                if record_count
                else 0.0,
                "capacity_context_coverage": (
                    sum(
                        1
                        for record in records
                        if record.get("capacity_context", {}).get("available")
                    )
                    / record_count
                )
                if record_count
                else 0.0,
                "endpoint_context_coverage": (
                    sum(
                        1
                        for record in records
                        if record.get("endpoint_context", {}).get("available")
                    )
                    / record_count
                )
                if record_count
                else 0.0,
                "timing_context_coverage": (
                    sum(
                        1 for record in records if record.get("timing_context", {}).get("available")
                    )
                    / record_count
                )
                if record_count
                else 0.0,
                "route_context_source": route_context_source,
                "missing_reason_counts": _null_reason_counts(records),
            }
        self._quality["wires"] = wire_quality

    def _compute_source_signature(self) -> list[str]:
        paths = [
            self.workspace_dir / "home" / "flow.json",
            self.workspace_dir / "home" / "parameters.json",
        ]
        for stage_dir in self.workspace_dir.glob("*_*"):
            if not stage_dir.is_dir():
                continue
            for folder in ("output", "feature", "analysis", "report", "data"):
                root = stage_dir / folder
                if root.exists():
                    paths.extend(path for path in root.rglob("*") if path.is_file())
        return [
            str(path.relative_to(self.workspace_dir))
            for path in sorted(set(paths))
            if path.exists()
        ]

    def _source_signature(self) -> list[str]:
        if self._source_signature_cache is None:
            self._source_signature_cache = self._compute_source_signature()
        return list(self._source_signature_cache)

    def _write_views(
        self,
        summary: dict,
        metrics: dict,
        stage_index: dict,
        labels: dict,
        *,
        manifest: dict[str, Any],
        drc_violation_rows: Iterable[dict[str, Any]],
        include_raw_refs: bool,
        route_completion_mode: str,
        route_detail_level: str,
    ) -> None:
        write_json(
            self.foundation_dir / "views" / "ml" / "dataset_index.json",
            {
                "profile": self.profile,
                "schema_version": SCHEMA_VERSION,
                "tables_dir": "tables",
                "canonical_grid": "canonical_grid.json",
                "sample_keys": ["design_id", "run_id", "patch_id"],
                "available_tasks": ["progressive_patch_route_demand_capacity"],
            },
        )
        task_view = {
            "tasks": {
                "progressive_patch_route_demand_capacity": {
                    "input_table": "run_stage_patch_features",
                    "label_table": "run_patch_route_labels",
                    "join_keys": ["design_id", "run_id", "patch_id"],
                    "stage_policy": {
                        "P1": ["Floorplan"],
                        "P2": ["Floorplan", "place"],
                        "P3": ["Floorplan", "place", "CTS"],
                    },
                    "route_completion_mode": route_completion_mode,
                    "leakage_policy": {
                        "route_truth_as_preroute_input": "forbidden",
                        "route_only_fields": [
                            "run_patch_route_labels",
                            "run_patch_route_label_layers",
                        ],
                    },
                }
            }
        }
        write_json(self.foundation_dir / "views" / "ml" / "task_views.json", task_view)
        progressive_policy = task_view["tasks"]["progressive_patch_route_demand_capacity"]
        write_json(
            self.foundation_dir / "views" / "ml" / "progressive_patch_dataset.json",
            {
                "task": "progressive_patch_route_demand_capacity",
                "sample_key": ["design_id", "run_id", "patch_id"],
                "input_table": "run_stage_patch_features",
                "label_table": "run_patch_route_labels",
                "join_keys": progressive_policy["join_keys"],
                "stage_policy": progressive_policy["stage_policy"],
                "allowed_input_stages": progressive_policy["stage_policy"],
                "label_source": {
                    "table": "run_patch_route_labels",
                    "stage": "route",
                    "artifact_table": "artifacts",
                    "completion_mode": route_completion_mode,
                },
                "route_completion_mode": route_completion_mode,
                "route_detail_level": route_detail_level,
                "forbidden_input_tables": [
                    "run_patch_route_labels",
                    "run_patch_route_label_layers",
                ],
                "forbidden_input_columns": [
                    "route_oracle",
                    "label_refs",
                    "label_source_artifact_id",
                    "source_artifact_id",
                ],
                "leakage_policy": progressive_policy["leakage_policy"],
            },
        )
        write_json(
            self.foundation_dir / "views" / "agent" / "run_summary.json",
            {
                "profile": self.profile,
                "workspace": summary["workspace"],
                "stages": _summary_stages(summary),
                "entity_counts": summary["entity_counts"],
                "quality_warnings": self._quality.get("warnings", []),
                "evidence_index": "views/agent/evidence_index.json",
            },
        )
        write_json(
            self.foundation_dir / "views" / "agent" / "qor_snapshot.json",
            {"metrics": metrics, "labels": labels},
        )
        write_json(
            self.foundation_dir / "views" / "agent" / "attribution_inputs.v1.json",
            self._attribution_inputs_view(manifest, drc_violation_rows),
        )
        top_patches = _top_patch_view_items(self._vector_records)
        top_nets = _top_net_view_items(self._vector_records)
        write_json(
            self.foundation_dir / "views" / "agent" / "top_patches.json", {"items": top_patches}
        )
        write_json(self.foundation_dir / "views" / "agent" / "top_nets.json", {"items": top_nets})
        write_json(
            self.foundation_dir / "views" / "agent" / "evidence_index.json",
            {
                "schema": "schema.json",
                "table_index": "manifest.json:tables",
                "stage_index": stage_index,
                "raw_refs": "raw_refs/artifacts.json" if include_raw_refs else None,
                "raw_refs_disabled": not include_raw_refs,
                "entity_evidence": {
                    "patches": {
                        "view": "views/agent/top_patches.json",
                        "table": "run_stage_patch_features",
                        "key": "patch_id",
                    },
                    "nets": {
                        "view": "views/agent/top_nets.json",
                        "table": "nets",
                        "key": "net_key",
                    },
                    "provenance": {"table": "provenance", "key": "provenance_id"},
                },
            },
        )

    def _attribution_inputs_view(
        self,
        manifest: dict[str, Any],
        drc_violation_rows: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        table_registry = manifest.get("tables") or {}
        table_refs = {
            name: {
                "ref": table_registry[name]["path"],
                "sha256": table_registry[name]["sha256"],
            }
            for name in _ATTRIBUTION_INPUT_TABLES
        }
        rows = list(drc_violation_rows)
        drc_available = any(
            status == "available"
            for status in (self._quality.get("availability", {}).get("drc", {}) or {}).values()
        )
        wire_available = table_registry["wire_segments"]["row_count"] > 0
        row_refs_available = table_registry["instance_row_refs"]["row_count"] > 0
        clock_refs_available = table_registry["clock_instance_refs"]["row_count"] > 0
        drc_wire_available = drc_available and wire_available
        seed_ids = _attribution_seed_ids(rows)
        short_seed_ids = _attribution_seed_ids(rows, native_type="short")
        r3_seed_ids = self._r3_seed_ids()
        return {
            "schema_version": "foundation_data/ecc/attribution_inputs.v1",
            "design_id": manifest.get("design_id"),
            "run_id": manifest.get("run_id"),
            "tables": table_refs,
            "profiles": _attribution_profile_inputs(
                drc_wire_available=drc_wire_available,
                d2_available=drc_available and row_refs_available,
                c1_available=clock_refs_available,
                seed_ids=seed_ids,
                short_seed_ids=short_seed_ids,
                r3_seed_ids=r3_seed_ids,
            ),
        }

    def _r3_seed_ids(self) -> list[str]:
        candidates: list[tuple[float, str]] = []
        for record in self._records_for_stage("patches", "place"):
            patch_id = _patch_id_from_record(record)
            if patch_id is None:
                continue
            estimators = record.get("pre_route_estimators") or {}
            density = record.get("local_density") or {}
            congestion = _to_float(estimators.get("egr_overflow_union"))
            pin_density = _to_float(density.get("pin_density"))
            values = [
                value
                for value in (congestion, pin_density)
                if value is not None and math.isfinite(value) and value > 0
            ]
            if values:
                candidates.append((max(values), str(patch_id)))
        return [
            patch_id
            for _score, patch_id in sorted(candidates, key=lambda item: (-item[0], item[1]))[
                :_ATTRIBUTION_SEED_ID_LIMIT
            ]
        ]

    def _record_raw_ref(
        self, stage: StageInfo, path: Path, artifact_type: str, metadata: dict[str, Any]
    ) -> None:
        try:
            relative = str(path.relative_to(self.workspace_dir))
        except ValueError:
            relative = str(path)
        self._raw_refs.append(
            {"stage": stage.name, "type": artifact_type, "path": relative, "metadata": metadata}
        )
        for key in _raw_ref_lookup_keys(metadata):
            self._raw_ref_by_stage_type_key[(stage.name, artifact_type, key)] = relative

    def _mark(self, entity: str, key: str, status: str, reason: str = "") -> None:
        self._quality.setdefault("availability", {}).setdefault(entity, {})[key] = status
        if status != "available":
            self._quality.setdefault("null_reason", {}).setdefault(entity, {})[key] = (
                reason or "missing"
            )


def _previous_stage_name(stages: list[StageInfo], stage_name: str) -> str | None:
    names = [stage.name for stage in stages]
    if stage_name not in names:
        return None
    index = names.index(stage_name)
    return names[index - 1] if index > 0 else None


def _raw_ref_lookup_keys(metadata: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for raw_key in (metadata.get("key"), metadata.get("category")):
        if raw_key:
            keys.add(str(raw_key))
    for raw_key in metadata.get("keys") or []:
        if raw_key:
            keys.add(str(raw_key))
    if metadata.get("category") == "congestion":
        keys.update(
            {
                "horizontal",
                "vertical",
                "union",
                "horizontal_overflow",
                "vertical_overflow",
                "union_overflow",
            }
        )
    return keys


def _matrix_to_patch_values(
    matrix: list[list[float]], canonical_grid: dict
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for patch in canonical_grid.get("patches", []):
        row = int(patch["row"])
        col = int(patch["col"])
        value = _matrix_value(matrix, row, col)
        if value is None:
            continue
        values.append({"patch_id": int(patch["patch_id"]), "row": row, "col": col, "value": value})
    return values


def _rebuild_allcell_maps(maps: dict[str, MapMatrix]) -> None:
    """Keep public allcell maps as stdcell plus macro maps.

    ecc-tools' gcell patch exporter currently builds allcell density from every
    IDB instance returned by getDensityCells(); fixed in-core filler/tap cells can
    have an empty type, so they inflate allcell_density/allcell_pin_density. For
    the ICCD feature maps, allcell means standard cells plus macros.
    """

    _replace_with_matrix_sum(maps, "allcell_density", "stdcell_density", "macro_density")
    _replace_with_matrix_sum(
        maps, "allcell_pin_density", "stdcell_pin_density", "macro_pin_density"
    )


def _ordered_instance_record(record: dict[str, Any], record_id: int) -> dict[str, Any]:
    return {
        "id": record_id,
        "stage": record["stage"],
        "name": record["name"],
        "source": record["source"],
        "identity": record["identity"],
        "physical_state": record["physical_state"],
        "connectivity_summary": record["connectivity_summary"],
        "patch_anchor": record["patch_anchor"],
        "progressive_metadata": record["progressive_metadata"],
        "clock_tree": record["clock_tree"],
        "route_analysis": record["route_analysis"],
        "null_reason": record["null_reason"],
    }


def _instance_key_from_layout_name(name: str) -> str:
    if name.startswith("Instance_"):
        return name.removeprefix("Instance_")
    if name.startswith("Macro_"):
        return name.removeprefix("Macro_")
    return name


def _component_lookup_key(name: Any) -> str:
    return str(name).strip()


def _component_bbox_from_def(
    component: dict[str, Any],
    lef_macro: LefMacro | None,
    units: int | None,
) -> dict[str, float] | None:
    origin = component.get("origin")
    size = getattr(lef_macro, "size", None) if lef_macro is not None else None
    if not isinstance(origin, dict) or not isinstance(size, dict):
        return None
    width = size.get("width")
    height = size.get("height")
    if width is None or height is None:
        return None
    llx = float(origin["x"])
    lly = float(origin["y"])
    return {
        "llx": llx,
        "lly": lly,
        "urx": llx + float(width) * _lef_scale(units),
        "ury": lly + float(height) * _lef_scale(units),
    }


def _cell_class(master: str, name: str) -> str:
    lower = f"{master} {name}".lower()
    if "dff" in lower or "df" in lower or "latch" in lower or "reg" in lower:
        return "sequential"
    if "clk" in lower or "clock" in lower:
        return "clock_related"
    if "buf" in lower:
        return "buffer"
    if "inv" in lower:
        return "inverter"
    return "combinational"


def _physical_class(master: str, name: str) -> str:
    lower = f"{master} {name}".lower()
    if "macro" in lower or "sram" in lower or "mem" in lower:
        return "macro"
    return "physical_only" if _is_physical_only_cell_name(name, master) else "stdcell"


def _is_clock_related(master: str, name: str) -> bool:
    lower = f"{master} {name}".lower()
    return "clk" in lower or "clock" in lower or _cell_class(master, name) == "sequential"


def _attach_progressive_metadata(
    stages: list[StageInfo], instances_by_stage: dict[str, list[dict[str, Any]]]
) -> None:
    first_seen: dict[str, str] = {}
    for stage in stages:
        for record in instances_by_stage.get(stage.name, []):
            key = str(record.get("identity", {}).get("instance_key"))
            first_seen.setdefault(key, stage.name)
    place_keys = {
        str(record.get("identity", {}).get("instance_key"))
        for record in instances_by_stage.get("place", [])
    }
    previous_by_key: dict[str, dict[str, Any]] = {}
    for stage in stages:
        current = instances_by_stage.get(stage.name, [])
        current_by_key = {
            str(record.get("identity", {}).get("instance_key")): record for record in current
        }
        for key, record in current_by_key.items():
            previous = previous_by_key.get(key)
            current_center = record.get("physical_state", {}).get("center")
            previous_center = previous.get("physical_state", {}).get("center") if previous else None
            dx = dy = moved = None
            if isinstance(current_center, dict) and isinstance(previous_center, dict):
                dx = float(current_center["x"]) - float(previous_center["x"])
                dy = float(current_center["y"]) - float(previous_center["y"])
                moved = dx != 0.0 or dy != 0.0
            first_stage = first_seen.get(key, stage.name)
            created_stage = "Synthesis" if first_stage in {"Floorplan", "place"} else first_stage
            created_stage_source = (
                "def_component" if created_stage == "Synthesis" else "first_observed"
            )
            record["progressive_metadata"] = {
                "available_from": first_stage,
                "created_stage": created_stage,
                "created_stage_source": created_stage_source,
                "exists_in_prev_stage": previous is not None,
                "exists_in_place": key in place_keys,
                "moved_from_prev_stage": moved,
                "dx_from_prev_stage": dx,
                "dy_from_prev_stage": dy,
                "route_only_oracle": False,
            }
            record["clock_tree"] = _clock_tree_block(record)
        previous_by_key = current_by_key


def _clock_tree_block(record: dict[str, Any]) -> dict[str, Any] | None:
    identity = record.get("identity", {})
    master = str(identity.get("master") or "")
    name = str(record.get("name") or identity.get("instance_key") or "")
    summary = record.get("connectivity_summary", {})
    clock_net_count = int(summary.get("clock_pin_count") or 0)
    is_buffer = "buf" in f"{master} {name}".lower()
    is_clock = _is_clock_like(name) or _is_clock_like(master) or clock_net_count > 0
    if not (is_clock and is_buffer):
        return None
    return {
        "is_clock_tree_node": True,
        "clock_tree_role": "clock_buffer",
        "clock_net_count": clock_net_count,
    }


def _attach_connectivity_summaries(records: list[dict[str, Any]], parsed_def: DefData) -> None:
    by_key = {record.get("identity", {}).get("instance_key"): record for record in records}
    centers = {
        key: record.get("physical_state", {}).get("center") for key, record in by_key.items()
    }
    net_hpwl: dict[str, float | None] = {}
    net_cross_patch: dict[str, bool | None] = {}
    net_degrees = {net.name: len(net.pins) for net in parsed_def.nets}
    for net in parsed_def.nets:
        points = [
            centers.get(str(pin.get("instance")))
            for pin in net.pins
            if str(pin.get("instance")) in centers
        ]
        valid = [point for point in points if isinstance(point, dict)]
        if len(valid) >= 2:
            xs = [float(point["x"]) for point in valid]
            ys = [float(point["y"]) for point in valid]
            net_hpwl[net.name] = (max(xs) - min(xs)) + (max(ys) - min(ys))
        else:
            net_hpwl[net.name] = None
        patch_ids = {
            by_key[str(pin.get("instance"))].get("physical_state", {}).get("patch_id")
            for pin in net.pins
            if str(pin.get("instance")) in by_key
        }
        patch_ids.discard(None)
        net_cross_patch[net.name] = len(patch_ids) > 1 if patch_ids else None
    pins_by_instance: dict[str, list[dict[str, Any]]] = {}
    for net in parsed_def.nets:
        for pin in net.pins:
            instance = str(pin.get("instance"))
            pins_by_instance.setdefault(instance, []).append(
                {**pin, "net": net.name, "net_degree": net_degrees.get(net.name, 0)}
            )
    for key, record in by_key.items():
        pins = pins_by_instance.get(str(key), [])
        connected_nets = sorted({str(pin.get("net")) for pin in pins if pin.get("net")})
        hpwls = [net_hpwl[net] for net in connected_nets if net_hpwl.get(net) is not None]
        has_center = isinstance(record.get("physical_state", {}).get("center"), dict)
        record["connectivity_summary"] = {
            "pin_count": len(pins),
            "connected_net_count": len(connected_nets),
            "fanout_count": sum(max(0, int(pin.get("net_degree") or 0) - 1) for pin in pins),
            "clock_pin_count": sum(
                1
                for pin in pins
                if _is_clock_like(str(pin.get("net"))) or _is_clock_like(str(pin.get("pin_name")))
            ),
            "max_net_degree": max((int(pin.get("net_degree") or 0) for pin in pins), default=0),
            "sum_connected_hpwl": sum(hpwls)
            if has_center and hpwls
            else (0.0 if has_center and connected_nets else None),
            "max_connected_hpwl": max(hpwls)
            if has_center and hpwls
            else (0.0 if has_center and connected_nets else None),
            "avg_connected_hpwl": (sum(hpwls) / len(hpwls))
            if has_center and hpwls
            else (0.0 if has_center and connected_nets else None),
            "cross_patch_net_count": sum(1 for net in connected_nets if net_cross_patch.get(net))
            if has_center
            else None,
        }
        if connected_nets and not has_center:
            record.setdefault("null_reason", {})["connectivity_hpwl"] = (
                "not_available_before_placement"
            )


def _pin_records_for_stage(
    stage: StageInfo,
    parsed_def: DefData,
    instances: list[dict[str, Any]],
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
    sta_report: dict[str, Any] | None,
    workspace_dir: Path,
    lef_macros: dict[str, LefMacro] | None = None,
    drc_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source = str(parsed_def.path.relative_to(workspace_dir))
    instance_by_key = {
        str(record.get("identity", {}).get("instance_key")): record for record in instances
    }
    component_by_name = {
        str(component.get("name")): component for component in parsed_def.components
    }
    net_by_name = {net.name: net for net in parsed_def.nets}
    net_use_by_name = {net.name: net.use for net in parsed_def.nets if net.use}
    wires_by_net = {net.name: list(net.wires) for net in parsed_def.nets}
    route_label_demand_capacity_by_patch = (
        _route_label_demand_capacity_by_patch(stage.directory, canonical_grid)
        if stage.name == "route"
        else {}
    )
    raw_pins: list[dict[str, Any]] = []
    seen: set[str] = set()

    for def_index, pin in enumerate(parsed_def.pins):
        record = {
            **pin,
            "pin_kind": "io_port",
            "def_section": "PINS",
            "def_index": pin.get("def_index", def_index),
        }
        key = _pin_key(record)
        if key not in seen:
            raw_pins.append(record)
            seen.add(key)

    for net in parsed_def.nets:
        for def_index, pin in enumerate(net.pins):
            if str(pin.get("instance")) == "PIN":
                continue
            record = {
                **pin,
                "net": pin.get("net") or net.name,
                "pin_kind": "instance_terminal",
                "def_section": "NETS",
                "def_index": def_index,
            }
            key = _pin_key(record)
            if key not in seen:
                raw_pins.append(record)
                seen.add(key)

    interim = [
        _build_pin_record(
            record_id,
            stage,
            raw_pin,
            source,
            instance_by_key,
            component_by_name,
            net_use_by_name,
            canonical_grid,
            stage_maps,
            sta_report,
            workspace_dir,
            parsed_def,
            lef_macros or {},
            drc_report,
            route_label_demand_capacity_by_patch,
            wires_by_net,
        )
        for record_id, raw_pin in enumerate(raw_pins)
    ]
    _attach_pin_connectivity_context(interim, net_by_name)
    _attach_pin_nearby_context(interim)
    _attach_pin_route_detour_ratios(interim)
    return [_ordered_pin_record(record, idx) for idx, record in enumerate(interim)]


def _build_pin_record(
    record_id: int,
    stage: StageInfo,
    raw_pin: dict[str, Any],
    source: str,
    instance_by_key: dict[str, dict[str, Any]],
    component_by_name: dict[str, dict[str, Any]],
    net_use_by_name: dict[str, str],
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
    sta_report: dict[str, Any] | None,
    workspace_dir: Path,
    parsed_def: DefData,
    lef_macros: dict[str, LefMacro],
    drc_report: dict[str, Any] | None,
    route_label_demand_capacity_by_patch: dict[int, float] | None = None,
    wires_by_net: dict[str, list[DefWire]] | None = None,
) -> dict[str, Any]:
    del record_id
    pin_kind = str(raw_pin.get("pin_kind") or "instance_terminal")
    instance_name = str(raw_pin.get("instance") or "")
    pin_name = str(raw_pin.get("pin_name") or "")
    parent_key = None if pin_kind == "io_port" else instance_name
    parent = instance_by_key.get(parent_key or "")
    component = component_by_name.get(parent_key or "")
    net = str(raw_pin.get("net") or "")
    pin_key = _pin_key(raw_pin)
    null_reason: dict[str, str] = {}
    identity = _pin_identity(raw_pin, pin_key, parent, component)
    parent_instance = _pin_parent_instance(parent, component, parent_key)
    lef_pin = _lookup_lef_pin(identity.get("parent_master"), pin_name, lef_macros)
    electrical = _pin_electrical_context(raw_pin, net_use_by_name.get(net), null_reason, lef_pin)
    lef_macro = _lookup_lef_macro(identity.get("parent_master"), lef_macros)
    component_origin = component.get("origin") if isinstance(component, dict) else None
    geometry = _pin_geometry(
        raw_pin,
        pin_kind,
        parent_instance,
        canonical_grid,
        null_reason,
        lef_pin,
        parsed_def.units,
        lef_macro,
        component_origin,
    )
    patch_anchor = _pin_patch_anchor(geometry, canonical_grid, stage_maps)
    timing_context = _pin_timing_context(
        pin_key, identity["full_name"], net, sta_report, workspace_dir
    )
    if timing_context["available"] and timing_context["timing_path_count"] == 0:
        null_reason["timing_context"] = "pin_not_found_in_timing_paths"
    elif not timing_context["available"]:
        null_reason["timing_context"] = "missing_sta_artifacts"
    route_context = _pin_route_context(
        stage.name,
        net,
        geometry,
        parsed_def,
        stage_maps,
        canonical_grid,
        route_label_demand_capacity_by_patch or {},
        drc_report,
        wires_by_net or {},
    )
    if route_context is None:
        null_reason["route_context"] = "not_route_stage"
    return {
        "stage": stage.name,
        "pin_key": pin_key,
        "source": source,
        "identity": identity,
        "electrical_context": electrical,
        "parent_instance": parent_instance,
        "geometry": geometry,
        "connectivity_context": {},
        "timing_context": timing_context,
        "patch_anchor": patch_anchor,
        "route_context": route_context,
        "progressive_metadata": {},
        "source_refs": {
            "def": source,
            "def_section": raw_pin.get("def_section"),
            "def_index": raw_pin.get("def_index"),
            "lef": _workspace_relative_path(lef_pin.source, workspace_dir)
            if lef_pin and lef_pin.source
            else None,
            "lef_macro": identity.get("parent_master"),
            "lef_pin": pin_name,
            "liberty": None,
            "sta": timing_context.get("source"),
            "route": route_context.get("source") if isinstance(route_context, dict) else None,
        },
        "null_reason": null_reason,
    }


def _lookup_lef_pin(master: Any, pin_name: str, lef_macros: dict[str, LefMacro]) -> Any:
    macro = lef_macros.get(str(master or ""))
    if not macro:
        return None
    return macro.pins.get(pin_name)


def _lookup_lef_macro(master: Any, lef_macros: dict[str, LefMacro]) -> LefMacro | None:
    return lef_macros.get(str(master or ""))


def _workspace_relative_path(value: Any, workspace_dir: Path) -> str:
    path = Path(str(value))
    try:
        return str(path.relative_to(workspace_dir))
    except ValueError:
        return str(path)


def _lef_scale(units: int | None) -> float:
    return float(units or 1000)


def _scale_lef_rect(rect: dict[str, Any], units: int | None) -> dict[str, float]:
    scale = _lef_scale(units)
    return {key: float(rect[key]) * scale for key in ("llx", "lly", "urx", "ury")}


def _transform_local_rect(
    rect: dict[str, float],
    origin: dict[str, Any],
    orientation: str | None,
    macro_size: dict[str, float] | None,
    units: int | None,
) -> dict[str, float] | None:
    ox = float(origin["x"])
    oy = float(origin["y"])
    orient = (orientation or "N").upper()
    width = (
        float(macro_size.get("width", 0.0)) * _lef_scale(units)
        if isinstance(macro_size, dict)
        else None
    )
    height = (
        float(macro_size.get("height", 0.0)) * _lef_scale(units)
        if isinstance(macro_size, dict)
        else None
    )
    points = [
        (rect["llx"], rect["lly"]),
        (rect["llx"], rect["ury"]),
        (rect["urx"], rect["lly"]),
        (rect["urx"], rect["ury"]),
    ]

    def transform(x: float, y: float) -> tuple[float, float] | None:
        if orient in {"N", "R0"}:
            return ox + x, oy + y
        if orient in {"S", "R180"} and width is not None and height is not None:
            return ox + width - x, oy + height - y
        if orient in {"FN", "MY"} and width is not None:
            return ox + width - x, oy + y
        if orient in {"FS", "MX"} and height is not None:
            return ox + x, oy + height - y
        if orient in {"E", "R270"} and width is not None:
            return ox + y, oy + width - x
        if orient in {"W", "R90"} and height is not None:
            return ox + height - y, oy + x
        return None

    transformed = [transform(x, y) for x, y in points]
    if any(point is None for point in transformed):
        return None
    xs = [point[0] for point in transformed if point is not None]
    ys = [point[1] for point in transformed if point is not None]
    return {"llx": min(xs), "lly": min(ys), "urx": max(xs), "ury": max(ys)}


def _pin_identity(
    raw_pin: dict[str, Any],
    pin_key: str,
    parent: dict[str, Any] | None,
    component: dict[str, Any] | None,
) -> dict[str, Any]:
    pin_kind = str(raw_pin.get("pin_kind") or "instance_terminal")
    instance_name = str(raw_pin.get("instance") or "")
    pin_name = str(raw_pin.get("pin_name") or "")
    parent_identity = parent.get("identity", {}) if isinstance(parent, dict) else {}
    parent_master = parent_identity.get("master") or (
        component.get("master") if isinstance(component, dict) else None
    )
    physical_class = parent_identity.get("physical_class")
    return {
        "pin_key": pin_key,
        "pin_kind": pin_kind,
        "instance": instance_name,
        "parent_instance_key": None if pin_kind == "io_port" else instance_name,
        "parent_master": parent_master,
        "pin_name": pin_name,
        "full_name": f"PIN/{pin_name}" if pin_kind == "io_port" else f"{instance_name}/{pin_name}",
        "net": raw_pin.get("net"),
        "net_key": raw_pin.get("net"),
        "is_io": pin_kind == "io_port",
        "is_macro_pin": physical_class == "macro",
        "classification_source": "def_section" if pin_kind == "io_port" else "def_component_join",
    }


def _pin_parent_instance(
    parent: dict[str, Any] | None,
    component: dict[str, Any] | None,
    parent_key: str | None,
) -> dict[str, Any] | None:
    if parent_key is None:
        return None
    identity = parent.get("identity", {}) if isinstance(parent, dict) else {}
    physical_state = parent.get("physical_state", {}) if isinstance(parent, dict) else {}
    master = identity.get("master") or (
        component.get("master") if isinstance(component, dict) else None
    )
    return {
        "instance_key": parent_key,
        "name": parent.get("name") if isinstance(parent, dict) else parent_key,
        "master": master,
        "cell_class": identity.get("cell_class") or _cell_class(str(master or ""), parent_key),
        "physical_class": identity.get("physical_class")
        or _physical_class(str(master or ""), parent_key),
        "bbox": physical_state.get("bbox"),
        "center": physical_state.get("center"),
        "orientation": physical_state.get("orientation")
        or (component.get("orientation") if isinstance(component, dict) else None),
        "patch_id": physical_state.get("patch_id"),
        "overlap_patch_ids": physical_state.get("overlap_patch_ids") or [],
    }


def _pin_electrical_context(
    raw_pin: dict[str, Any], net_use: str | None, null_reason: dict[str, str], lef_pin: Any = None
) -> dict[str, Any]:
    lef_direction = getattr(lef_pin, "direction", None) if lef_pin is not None else None
    lef_use = getattr(lef_pin, "use", None) if lef_pin is not None else None
    direction = str(raw_pin.get("direction") or lef_direction or "UNKNOWN").upper()
    use = str(raw_pin.get("use") or net_use or lef_use or "UNKNOWN").upper()
    name_blob = f"{raw_pin.get('net') or ''} {raw_pin.get('pin_name') or ''}".lower()
    is_clock = use == "CLOCK" or _is_clock_like(name_blob)
    is_reset = "reset" in name_blob or "rst" in name_blob
    is_power_ground = use in {"POWER", "GROUND"} or any(
        token in name_blob.split() for token in ("vdd", "vss", "vcc", "gnd")
    )
    if direction == "UNKNOWN":
        null_reason["electrical_direction"] = "missing_pin_direction"
    if use == "UNKNOWN":
        null_reason["electrical_use"] = "missing_pin_use"
    direction_source = (
        "def_pin_direction"
        if raw_pin.get("direction")
        else "lef_pin_direction"
        if lef_direction
        else "unknown"
    )
    use_source = (
        "def_pin_use"
        if raw_pin.get("use")
        else "def_net_use"
        if net_use
        else "lef_pin_use"
        if lef_use
        else "heuristic_name_rule"
        if is_clock or is_reset or is_power_ground
        else "unknown"
    )
    return {
        "direction": direction,
        "use": "CLOCK"
        if is_clock and use == "UNKNOWN"
        else "RESET"
        if is_reset and use == "UNKNOWN"
        else use,
        "is_clock": is_clock,
        "is_reset": is_reset,
        "is_power_ground": is_power_ground,
        "is_signal": not is_clock
        and not is_reset
        and not is_power_ground
        and use in {"SIGNAL", "UNKNOWN"},
        "direction_source": direction_source,
        "use_source": use_source,
    }


def _pin_geometry(
    raw_pin: dict[str, Any],
    pin_kind: str,
    parent_instance: dict[str, Any] | None,
    canonical_grid: dict,
    null_reason: dict[str, str],
    lef_pin: Any = None,
    units: int | None = None,
    lef_macro: LefMacro | None = None,
    component_origin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if pin_kind == "io_port":
        origin = raw_pin.get("origin")
        shapes = raw_pin.get("shapes") if isinstance(raw_pin.get("shapes"), list) else []
        if isinstance(origin, dict) and shapes:
            absolute_shapes = []
            boxes = []
            for idx, shape in enumerate(shapes):
                rect = shape.get("rect") if isinstance(shape, dict) else None
                if not isinstance(rect, dict):
                    continue
                abs_rect = {
                    "llx": float(origin["x"]) + float(rect["llx"]),
                    "lly": float(origin["y"]) + float(rect["lly"]),
                    "urx": float(origin["x"]) + float(rect["urx"]),
                    "ury": float(origin["y"]) + float(rect["ury"]),
                }
                boxes.append(abs_rect)
                absolute_shapes.append(
                    {
                        "shape_id": idx,
                        "port_index": 0,
                        "layer": shape.get("layer"),
                        "shape_type": "rect",
                        "rect": abs_rect,
                        "polygon": None,
                    }
                )
            if boxes:
                bbox = _bbox_union(boxes)
                center = _bbox_center(bbox)
                lookup = _patch_grid_lookup(canonical_grid)
                patch = _grid_patch_for_point(lookup, center)
                if patch is None:
                    patch = _patch_for_point(canonical_grid.get("patches", []), center)
                return {
                    "geometry_status": "exact",
                    "anchor_source": "io_pin_shape",
                    "bbox": bbox,
                    "center": center,
                    "layers": sorted(
                        {str(shape["layer"]) for shape in absolute_shapes if shape.get("layer")}
                    ),
                    "shape_count": len(absolute_shapes),
                    "area": sum(_bbox_area(box) for box in boxes),
                    "local_shapes": [
                        {
                            "shape_id": idx,
                            "port_index": 0,
                            "layer": shape.get("layer"),
                            "shape_type": "rect",
                            "rect": shape.get("rect"),
                            "polygon": None,
                        }
                        for idx, shape in enumerate(shapes)
                    ],
                    "absolute_shapes": absolute_shapes,
                    "patch_id": int(patch["patch_id"]) if patch else None,
                    "overlap_patch_ids": _grid_overlap_patch_ids(lookup, bbox)
                    or _overlap_patch_ids(canonical_grid.get("patches", []), bbox),
                }
        if isinstance(origin, dict):
            center = {"x": float(origin["x"]), "y": float(origin["y"])}
            lookup = _patch_grid_lookup(canonical_grid)
            patch = _grid_patch_for_point(lookup, center)
            if patch is None:
                patch = _patch_for_point(canonical_grid.get("patches", []), center)
            null_reason["geometry_bbox"] = "missing_def_pin_shape"
            return _empty_pin_geometry(
                "fallback_to_instance_anchor",
                "io_pin_origin",
                center,
                int(patch["patch_id"]) if patch else None,
            )
        null_reason["geometry_bbox"] = "missing_def_pin_shape"
        return _empty_pin_geometry("missing", "none", None, None)

    center = parent_instance.get("center") if isinstance(parent_instance, dict) else None
    patch_id = parent_instance.get("patch_id") if isinstance(parent_instance, dict) else None
    origin = component_origin
    if (
        not isinstance(origin, dict)
        and isinstance(parent_instance, dict)
        and isinstance(parent_instance.get("bbox"), dict)
    ):
        bbox = parent_instance["bbox"]
        origin = {"x": float(bbox["llx"]), "y": float(bbox["lly"])}
    shapes = getattr(lef_pin, "shapes", None) if lef_pin is not None else None
    if isinstance(origin, dict) and shapes:
        absolute_shapes = []
        boxes = []
        macro_size = lef_macro.size if lef_macro is not None else None
        for shape in shapes:
            rect = shape.get("rect") if isinstance(shape, dict) else None
            if not isinstance(rect, dict):
                continue
            local_rect = _scale_lef_rect(rect, units)
            abs_rect = _transform_local_rect(
                local_rect,
                origin,
                parent_instance.get("orientation") if isinstance(parent_instance, dict) else None,
                macro_size,
                units,
            )
            if abs_rect is None:
                null_reason["geometry_bbox"] = "orientation_transform_unsupported"
                continue
            boxes.append(abs_rect)
            absolute_shapes.append(
                {**{k: v for k, v in shape.items() if k != "source"}, "rect": abs_rect}
            )
        if boxes:
            bbox = _bbox_union(boxes)
            pin_center = _bbox_center(bbox)
            lookup = _patch_grid_lookup(canonical_grid)
            patch = _grid_patch_for_point(lookup, pin_center)
            if patch is None:
                patch = _patch_for_point(canonical_grid.get("patches", []), pin_center)
            return {
                "geometry_status": "exact",
                "anchor_source": "lef_pin_shape",
                "bbox": bbox,
                "center": pin_center,
                "layers": sorted(
                    {str(shape["layer"]) for shape in absolute_shapes if shape.get("layer")}
                ),
                "shape_count": len(absolute_shapes),
                "area": sum(_bbox_area(box) for box in boxes),
                "local_shapes": [
                    {
                        **{k: v for k, v in shape.items() if k != "source"},
                        "rect": _scale_lef_rect(shape["rect"], units),
                    }
                    for shape in shapes
                    if isinstance(shape.get("rect"), dict)
                ],
                "absolute_shapes": absolute_shapes,
                "patch_id": int(patch["patch_id"]) if patch else None,
                "overlap_patch_ids": _grid_overlap_patch_ids(lookup, bbox)
                or _overlap_patch_ids(canonical_grid.get("patches", []), bbox),
            }
    if isinstance(center, dict):
        null_reason["geometry_bbox"] = (
            "missing_lef_pin_shape"
            if not shapes
            else null_reason.get("geometry_bbox", "missing_instance_origin")
        )
        return _empty_pin_geometry(
            "fallback_to_instance_anchor", "parent_instance_center", center, patch_id
        )
    null_reason["geometry_bbox"] = "missing_instance_origin"
    return _empty_pin_geometry("missing", "none", None, None)


def _empty_pin_geometry(
    status: str, anchor_source: str, center: dict[str, Any] | None, patch_id: Any
) -> dict[str, Any]:
    return {
        "geometry_status": status,
        "anchor_source": anchor_source,
        "bbox": None,
        "center": {"x": float(center["x"]), "y": float(center["y"])}
        if isinstance(center, dict)
        else None,
        "layers": [],
        "shape_count": 0,
        "area": None,
        "local_shapes": [],
        "absolute_shapes": [],
        "patch_id": int(patch_id) if patch_id is not None else None,
        "overlap_patch_ids": [],
    }


def _pin_patch_anchor(
    geometry: dict[str, Any],
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
) -> dict[str, Any]:
    center = geometry.get("center")
    bbox = geometry.get("bbox")
    patches = canonical_grid.get("patches", []) if isinstance(canonical_grid, dict) else []
    lookup = _patch_grid_lookup(canonical_grid)
    primary_patch = _grid_patch_for_point(lookup, center) if isinstance(center, dict) else None
    if primary_patch is None and isinstance(center, dict):
        primary_patch = _patch_for_point(patches, center)
    patch_id = (
        int(primary_patch["patch_id"]) if primary_patch is not None else geometry.get("patch_id")
    )
    row = int(primary_patch["row"]) if primary_patch is not None else None
    col = int(primary_patch["col"]) if primary_patch is not None else None
    overlap_patch_ids = (
        _grid_overlap_patch_ids(lookup, bbox)
        if isinstance(bbox, dict)
        else list(geometry.get("overlap_patch_ids") or [])
    )
    if not overlap_patch_ids and isinstance(bbox, dict):
        overlap_patch_ids = _overlap_patch_ids(patches, bbox)
    if patch_id is not None and patch_id not in overlap_patch_ids and isinstance(bbox, dict):
        overlap_patch_ids = [int(patch_id), *overlap_patch_ids]
    return {
        "primary_patch_id": patch_id,
        "overlap_patch_ids": overlap_patch_ids,
        "anchor_source": "exact_pin_geometry"
        if geometry.get("geometry_status") == "exact"
        else "parent_instance_anchor"
        if geometry.get("anchor_source") == "parent_instance_center"
        else "none",
        "local_cell_density": _matrix_value(
            stage_maps.get("density", {}).get("allcell_density"), row, col
        )
        if row is not None and col is not None
        else None,
        "local_pin_density": _matrix_value(
            stage_maps.get("density", {}).get("allcell_pin_density"), row, col
        )
        if row is not None and col is not None
        else None,
        "local_rudy": _matrix_value(stage_maps.get("rudy", {}).get("rudy_union"), row, col)
        if row is not None and col is not None
        else None,
        "local_egr_overflow": _matrix_value(stage_maps.get("congestion", {}).get("union"), row, col)
        if row is not None and col is not None
        else None,
        "nearby_pin_count": None,
        "nearby_io_pin_count": None,
        "nearby_macro_pin_count": None,
    }


def _pin_timing_context(
    pin_key: str, full_name: str, net: str, sta_report: dict[str, Any] | None, workspace_dir: Path
) -> dict[str, Any]:
    records = sta_report.get("records", []) if isinstance(sta_report, dict) else []
    refs = []
    slacks: list[float] = []
    arrivals: list[float] = []
    slews: list[float] = []
    caps: list[float] = []
    role = "unknown"
    point_names = {
        full_name,
        full_name.replace("/", ":"),
        full_name.split("/", 1)[-1],
        pin_key,
        pin_key.replace(":", "/"),
    }
    for idx, record in enumerate(records):
        points = [item for item in record.get("path_points", []) if isinstance(item, dict)]
        nodes = [item for item in record.get("wire_path_nodes", []) if isinstance(item, dict)]
        point_keys = {str(item.get("pin_key")) for item in [*points, *nodes] if item.get("pin_key")}
        point_raw_names = {
            str(item.get("raw_name") or item.get("raw_point"))
            for item in [*points, *nodes]
            if item.get("raw_name") or item.get("raw_point")
        }
        endpoints = record.get("endpoints", {}) if isinstance(record.get("endpoints"), dict) else {}
        endpoint_key = (
            str(endpoints.get("endpoint", {}).get("pin_key") or "")
            if isinstance(endpoints.get("endpoint"), dict)
            else ""
        )
        start_key = (
            str(endpoints.get("startpoint", {}).get("pin_key") or "")
            if isinstance(endpoints.get("startpoint"), dict)
            else ""
        )
        if (
            pin_key not in point_keys
            and not point_names.intersection(point_raw_names)
            and net not in " ".join(point_raw_names)
        ):
            continue
        refs.append(idx)
        timing = (
            record.get("path_timing", {}) if isinstance(record.get("path_timing"), dict) else {}
        )
        slack = _to_float(timing.get("slack"))
        if slack is not None:
            slacks.append(slack)
        if pin_key == endpoint_key:
            role = "endpoint"
        elif pin_key == start_key:
            role = "startpoint"
        elif role == "unknown":
            role = "internal"
        electrical = record.get("path_electrical", {})
        if isinstance(electrical, dict):
            caps.extend(
                float(value)
                for value in electrical.get("capacitance_list", [])
                if value is not None
            )
            slews.extend(
                float(value) for value in electrical.get("slew_list", []) if value is not None
            )
        path_delay = _to_float(timing.get("path_delay"))
        if path_delay is not None:
            arrivals.append(path_delay)
    source = sta_report.get("source") if isinstance(sta_report, dict) else None
    if source:
        try:
            source = str(Path(str(source)).relative_to(workspace_dir))
        except ValueError:
            source = str(source)
    return {
        "available": bool(sta_report and sta_report.get("available")),
        "timing_path_count": len(refs),
        "is_on_critical_path": bool(refs),
        "timing_role": role,
        "worst_slack_seen": min(slacks) if slacks else None,
        "min_arrival": min(arrivals) if arrivals else None,
        "max_arrival": max(arrivals) if arrivals else None,
        "max_slew": max(slews) if slews else None,
        "max_cap": max(caps) if caps else None,
        "path_refs": refs[:5],
        "source": source,
    }


def _pin_route_context(
    stage_name: str,
    net: str,
    geometry: dict[str, Any],
    parsed_def: DefData,
    stage_maps: dict[str, dict[str, MapMatrix]],
    canonical_grid: dict,
    route_label_demand_capacity_by_patch: dict[int, float],
    drc_report: dict[str, Any] | None,
    wires_by_net: dict[str, list[DefWire]] | None = None,
) -> dict[str, Any] | None:
    if stage_name != "route":
        return None
    net_wires = (wires_by_net or {}).get(net)
    if net_wires is None:
        net_wires = [
            wire for def_net in parsed_def.nets if def_net.name == net for wire in def_net.wires
        ]
    patch_id = geometry.get("patch_id")
    local_final_overflow = None
    if patch_id is not None:
        row_col = _patch_row_col(canonical_grid, int(patch_id))
        if row_col:
            local_final_overflow = _matrix_value(
                stage_maps.get("congestion", {}).get("union"), row_col[0], row_col[1]
            )
        if local_final_overflow is None:
            local_final_overflow = route_label_demand_capacity_by_patch.get(int(patch_id))
    nearby_wires = [
        wire for wire in net_wires if not wire.via and _wire_near_geometry(wire, geometry)
    ]
    nearby_vias = [wire for wire in net_wires if wire.via and _wire_near_geometry(wire, geometry)]
    return {
        "route_only_oracle": True,
        "nearby_wire_count": len(nearby_wires) if geometry.get("center") else None,
        "nearby_via_count": len(nearby_vias),
        "nearby_drc_count": _drc_count_near_geometry(drc_report, geometry),
        "local_final_overflow": local_final_overflow,
        "pin_access_congestion": local_final_overflow,
        "net_routed_length": sum(wire.length for wire in net_wires if not wire.via)
        if net_wires
        else 0.0,
        "net_via_count": sum(1 for wire in net_wires if wire.via),
        "net_detour_ratio": None,
        "source": _workspace_relative_from_parsed_def(parsed_def),
    }


def _attach_pin_connectivity_context(
    records: list[dict[str, Any]], net_by_name: dict[str, DefNet]
) -> None:
    by_net: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        net = str(record.get("identity", {}).get("net") or "")
        by_net.setdefault(net, []).append(record)
    driver_by_net: dict[str, str | None] = {}
    roles_by_key: dict[str, str] = {}
    for net, pins in by_net.items():
        drivers = []
        for pin in pins:
            direction = str(pin.get("electrical_context", {}).get("direction") or "UNKNOWN").upper()
            pin_kind = pin.get("identity", {}).get("pin_kind")
            role = "top_port" if pin_kind == "io_port" else "unknown"
            if direction == "OUTPUT":
                role = "driver"
            elif direction == "INPUT":
                role = "sink"
            elif direction == "INOUT":
                role = "bidirectional"
            if role == "driver":
                drivers.append(pin["pin_key"])
            roles_by_key[pin["pin_key"]] = role
        driver_by_net[net] = drivers[0] if len(drivers) == 1 else None
    for record in records:
        identity = record["identity"]
        net = str(identity.get("net") or "")
        pins = by_net.get(net, [])
        centers = [
            pin.get("geometry", {}).get("center")
            for pin in pins
            if isinstance(pin.get("geometry", {}).get("center"), dict)
        ]
        bboxes = [
            pin.get("geometry", {}).get("bbox")
            for pin in pins
            if isinstance(pin.get("geometry", {}).get("bbox"), dict)
        ]
        patch_ids = {pin.get("patch_anchor", {}).get("primary_patch_id") for pin in pins}
        patch_ids.discard(None)
        connected_instances = {
            pin.get("identity", {}).get("parent_instance_key")
            for pin in pins
            if pin.get("identity", {}).get("parent_instance_key")
        }
        pin_role = roles_by_key.get(record["pin_key"], "unknown")
        sinks = [pin for pin in pins if roles_by_key.get(pin["pin_key"]) == "sink"]
        net_bbox = _bbox_union(bboxes) if bboxes else _bbox_from_points(centers)
        hpwl = _hpwl_from_points(centers)
        record["connectivity_context"] = {
            "net": net,
            "net_degree": len(pins),
            "net_fanout": len(sinks) if driver_by_net.get(net) else max(0, len(pins) - 1),
            "pin_role": pin_role,
            "is_driver": pin_role == "driver",
            "is_sink": pin_role == "sink",
            "driver_pin_key": driver_by_net.get(net),
            "sink_count": len(sinks),
            "same_net_pin_count": len(pins),
            "connected_instance_count": len(connected_instances),
            "connected_io_count": sum(1 for pin in pins if pin.get("identity", {}).get("is_io")),
            "net_hpwl": hpwl,
            "net_bbox": net_bbox,
            "net_cross_patch": len(patch_ids) > 1 if patch_ids else None,
            "cross_patch_count": len(patch_ids),
            "classification_source": "def_io_direction"
            if identity.get("is_io")
            and record.get("electrical_context", {}).get("direction") != "UNKNOWN"
            else "unknown",
        }
        if hpwl is None:
            record.setdefault("null_reason", {})["connectivity_hpwl"] = (
                "not_available_before_placement"
            )
        if driver_by_net.get(net) is None and len(pins) > 1:
            record.setdefault("null_reason", {})["connectivity_role"] = "ambiguous_driver_sink"


def _attach_pin_nearby_context(records: list[dict[str, Any]]) -> None:
    by_patch: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        patch_id = record.get("patch_anchor", {}).get("primary_patch_id")
        if patch_id is None:
            continue
        by_patch.setdefault(int(patch_id), []).append(record)
    for record in records:
        patch_id = record.get("patch_anchor", {}).get("primary_patch_id")
        patch_anchor = record.setdefault("patch_anchor", {})
        if patch_id is None:
            patch_anchor["nearby_pin_count"] = None
            patch_anchor["nearby_io_pin_count"] = None
            patch_anchor["nearby_macro_pin_count"] = None
            continue
        nearby = by_patch.get(int(patch_id), [])
        patch_anchor["nearby_pin_count"] = len(nearby)
        patch_anchor["nearby_io_pin_count"] = sum(
            1 for pin in nearby if pin.get("identity", {}).get("is_io")
        )
        patch_anchor["nearby_macro_pin_count"] = sum(
            1 for pin in nearby if pin.get("identity", {}).get("is_macro_pin")
        )


def _attach_pin_route_detour_ratios(records: list[dict[str, Any]]) -> None:
    by_net: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        net = str(record.get("identity", {}).get("net") or "")
        if net:
            by_net.setdefault(net, []).append(record)
    for pins in by_net.values():
        hpwl = _hpwl_from_points(
            [
                pin.get("geometry", {}).get("center")
                for pin in pins
                if isinstance(pin.get("geometry", {}).get("center"), dict)
            ]
        )
        for pin in pins:
            route_context = pin.get("route_context")
            if not isinstance(route_context, dict):
                continue
            routed_length = route_context.get("net_routed_length")
            route_context["net_detour_ratio"] = (
                (float(routed_length) / hpwl) if hpwl and routed_length is not None else None
            )


def _drc_count_near_geometry(
    drc_report: dict[str, Any] | None, geometry: dict[str, Any]
) -> int | None:
    if not drc_report or not drc_report.get("available"):
        return None
    bbox = geometry.get("bbox")
    if not isinstance(bbox, dict):
        center = geometry.get("center")
        if not isinstance(center, dict):
            return None
        bbox = {
            "llx": float(center["x"]),
            "lly": float(center["y"]),
            "urx": float(center["x"]),
            "ury": float(center["y"]),
        }
    count = 0
    for violation in drc_report.get("violations", []):
        violation_bbox = violation.get("bbox")
        if isinstance(violation_bbox, dict) and _bbox_intersects_bbox(violation_bbox, bbox):
            count += int(violation.get("count") or 1)
    return count


def _wire_near_geometry(wire: DefWire, geometry: dict[str, Any]) -> bool:
    bbox = geometry.get("bbox")
    if not isinstance(bbox, dict):
        center = geometry.get("center")
        if not isinstance(center, dict):
            return False
        bbox = {
            "llx": float(center["x"]),
            "lly": float(center["y"]),
            "urx": float(center["x"]),
            "ury": float(center["y"]),
        }
    wire_bbox = _wire_geometry(wire)["bbox"]
    return _bbox_intersects_bbox(wire_bbox, bbox)


def _attach_pin_progressive_metadata(stages: list[StageInfo], pins_dir: Path) -> None:
    records_by_stage: dict[str, list[dict[str, Any]]] = {}
    for stage in stages:
        path = pins_dir / f"{stage.name}.jsonl"
        if not path.exists():
            records_by_stage[stage.name] = []
            continue
        records_by_stage[stage.name] = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    first_seen: dict[str, str] = {}
    for stage in stages:
        for record in records_by_stage.get(stage.name, []):
            first_seen.setdefault(str(record.get("pin_key")), stage.name)
    place_keys = {str(record.get("pin_key")) for record in records_by_stage.get("place", [])}
    previous_by_key: dict[str, dict[str, Any]] = {}
    for stage in stages:
        current = records_by_stage.get(stage.name, [])
        current_by_key = {str(record.get("pin_key")): record for record in current}
        for key, record in current_by_key.items():
            previous = previous_by_key.get(key)
            center = record.get("geometry", {}).get("center")
            previous_center = previous.get("geometry", {}).get("center") if previous else None
            dx = dy = moved = None
            if isinstance(center, dict) and isinstance(previous_center, dict):
                dx = float(center["x"]) - float(previous_center["x"])
                dy = float(center["y"]) - float(previous_center["y"])
                if dx == 0.0 and dy == 0.0:
                    current_parent_center = (
                        record.get("parent_instance", {}).get("center")
                        if isinstance(record.get("parent_instance"), dict)
                        else None
                    )
                    previous_parent_center = (
                        previous.get("parent_instance", {}).get("center")
                        if isinstance(previous.get("parent_instance"), dict)
                        else None
                    )
                    if isinstance(current_parent_center, dict) and isinstance(
                        previous_parent_center, dict
                    ):
                        dx = float(current_parent_center["x"]) - float(previous_parent_center["x"])
                        dy = float(current_parent_center["y"]) - float(previous_parent_center["y"])
                moved = dx != 0.0 or dy != 0.0
            first_stage = first_seen.get(key, stage.name)
            created_stage = "Synthesis" if first_stage in {"Floorplan", "place"} else first_stage
            record["progressive_metadata"] = {
                "available_from": first_stage,
                "created_stage": created_stage,
                "created_stage_source": "def_connection"
                if created_stage == "Synthesis"
                else "first_observed",
                "exists_in_prev_stage": previous is not None,
                "exists_in_place": key in place_keys,
                "introduced_by_cts": first_stage == "CTS",
                "prev_net": previous.get("identity", {}).get("net") if previous else None,
                "net_changed_from_prev_stage": (
                    previous.get("identity", {}).get("net") != record.get("identity", {}).get("net")
                )
                if previous
                else None,
                "moved_from_prev_stage": moved,
                "dx_from_prev_stage": dx,
                "dy_from_prev_stage": dy,
                "geometry_changed_from_prev_stage": (
                    _pin_geometry_signature(record) != _pin_geometry_signature(previous)
                )
                if previous
                else None,
                "route_only_oracle": isinstance(record.get("route_context"), dict)
                and bool(record["route_context"].get("route_only_oracle")),
            }
        previous_by_key = current_by_key
        write_jsonl(
            pins_dir / f"{stage.name}.jsonl",
            [_ordered_pin_record(record, idx) for idx, record in enumerate(current)],
            sort_keys=False,
        )


def _attach_pin_progressive_metadata_in_memory(
    stages: list[StageInfo], records_by_stage: dict[str, list[dict[str, Any]]]
) -> None:
    first_seen: dict[str, str] = {}
    for stage in stages:
        for record in records_by_stage.get(stage.name, []):
            first_seen.setdefault(str(record.get("pin_key")), stage.name)
    place_keys = {str(record.get("pin_key")) for record in records_by_stage.get("place", [])}
    previous_by_key: dict[str, dict[str, Any]] = {}
    for stage in stages:
        current = records_by_stage.get(stage.name, [])
        current_by_key = {str(record.get("pin_key")): record for record in current}
        for key, record in current_by_key.items():
            previous = previous_by_key.get(key)
            center = record.get("geometry", {}).get("center")
            previous_center = previous.get("geometry", {}).get("center") if previous else None
            dx = dy = moved = None
            if isinstance(center, dict) and isinstance(previous_center, dict):
                dx = float(center["x"]) - float(previous_center["x"])
                dy = float(center["y"]) - float(previous_center["y"])
                moved = dx != 0.0 or dy != 0.0
            first_stage = first_seen.get(key, stage.name)
            created_stage = "Synthesis" if first_stage in {"Floorplan", "place"} else first_stage
            record["progressive_metadata"] = {
                "available_from": first_stage,
                "created_stage": created_stage,
                "created_stage_source": "def_connection"
                if created_stage == "Synthesis"
                else "first_observed",
                "exists_in_prev_stage": previous is not None,
                "exists_in_place": key in place_keys,
                "introduced_by_cts": first_stage == "CTS",
                "prev_net": previous.get("identity", {}).get("net") if previous else None,
                "net_changed_from_prev_stage": (
                    previous.get("identity", {}).get("net") != record.get("identity", {}).get("net")
                )
                if previous
                else None,
                "moved_from_prev_stage": moved,
                "dx_from_prev_stage": dx,
                "dy_from_prev_stage": dy,
                "geometry_changed_from_prev_stage": (
                    _pin_geometry_signature(record) != _pin_geometry_signature(previous)
                )
                if previous
                else None,
                "route_only_oracle": isinstance(record.get("route_context"), dict)
                and bool(record["route_context"].get("route_only_oracle")),
            }
        previous_by_key = current_by_key


def _attach_patch_progressive_metadata(stages: list[StageInfo], patches_dir: Path) -> None:
    previous_by_patch_id: dict[int, dict[str, Any]] = {}
    for stage in stages:
        path = patches_dir / f"{stage.name}.jsonl"
        if not path.exists():
            previous_by_patch_id = {}
            continue
        records = _read_jsonl_records(path)
        for record in records:
            patch_id = record.get("identity", {}).get("patch_id")
            if patch_id is None:
                continue
            previous = previous_by_patch_id.get(int(patch_id))
            metadata = record.setdefault("progressive_metadata", {})
            metadata["density_delta_from_prev_stage"] = _delta(
                record.get("local_density", {}).get("cell_density"),
                previous.get("local_density", {}).get("cell_density") if previous else None,
            )
            metadata["pin_count_delta_from_prev_stage"] = _delta(
                record.get("local_density", {}).get("pin_count_anchor"),
                previous.get("local_density", {}).get("pin_count_anchor") if previous else None,
            )
            metadata["rudy_delta_from_prev_stage"] = _delta(
                record.get("pre_route_estimators", {}).get("rudy_union"),
                previous.get("pre_route_estimators", {}).get("rudy_union") if previous else None,
            )
            metadata["egr_overflow_delta_from_prev_stage"] = _delta(
                record.get("pre_route_estimators", {}).get("egr_overflow_union"),
                previous.get("pre_route_estimators", {}).get("egr_overflow_union")
                if previous
                else None,
            )
        if records:
            previous_by_patch_id = {
                int(record["identity"]["patch_id"]): record
                for record in records
                if record.get("identity", {}).get("patch_id") is not None
            }
        else:
            previous_by_patch_id = {}
        write_jsonl(path, records, sort_keys=False)


def _attach_patch_progressive_metadata_in_memory(
    stages: list[StageInfo], records_by_stage: dict[str, list[dict[str, Any]]]
) -> None:
    previous_by_patch_id: dict[int, dict[str, Any]] = {}
    for stage in stages:
        records = records_by_stage.get(stage.name, [])
        for record in records:
            patch_id = record.get("identity", {}).get("patch_id")
            if patch_id is None:
                continue
            previous = previous_by_patch_id.get(int(patch_id))
            metadata = record.setdefault("progressive_metadata", {})
            metadata["density_delta_from_prev_stage"] = _delta(
                record.get("local_density", {}).get("cell_density"),
                previous.get("local_density", {}).get("cell_density") if previous else None,
            )
            metadata["pin_count_delta_from_prev_stage"] = _delta(
                record.get("local_density", {}).get("pin_count_anchor"),
                previous.get("local_density", {}).get("pin_count_anchor") if previous else None,
            )
            metadata["rudy_delta_from_prev_stage"] = _delta(
                record.get("pre_route_estimators", {}).get("rudy_union"),
                previous.get("pre_route_estimators", {}).get("rudy_union") if previous else None,
            )
            metadata["egr_overflow_delta_from_prev_stage"] = _delta(
                record.get("pre_route_estimators", {}).get("egr_overflow_union"),
                previous.get("pre_route_estimators", {}).get("egr_overflow_union")
                if previous
                else None,
            )
        previous_by_patch_id = (
            {
                int(record["identity"]["patch_id"]): record
                for record in records
                if record.get("identity", {}).get("patch_id") is not None
            }
            if records
            else {}
        )


def _attach_net_progressive_metadata(stages: list[StageInfo], nets_dir: Path) -> None:
    records_by_stage: dict[str, list[dict[str, Any]]] = {}
    for stage in stages:
        path = nets_dir / f"{stage.name}.jsonl"
        if not path.exists():
            records_by_stage[stage.name] = []
            continue
        records_by_stage[stage.name] = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    first_seen: dict[str, str] = {}
    for stage in stages:
        for record in records_by_stage.get(stage.name, []):
            first_seen.setdefault(str(record.get("net_key")), stage.name)
    place_keys = {str(record.get("net_key")) for record in records_by_stage.get("place", [])}
    previous_by_key: dict[str, dict[str, Any]] = {}
    for stage in stages:
        current = records_by_stage.get(stage.name, [])
        current_by_key = {str(record.get("net_key")): record for record in current}
        for key, record in current_by_key.items():
            previous = previous_by_key.get(key)
            first = first_seen.get(key, stage.name)
            current_summary = (
                record.get("connectivity_summary", {})
                if isinstance(record.get("connectivity_summary"), dict)
                else {}
            )
            prev_summary = (
                previous.get("connectivity_summary", {})
                if isinstance(previous, dict)
                and isinstance(previous.get("connectivity_summary"), dict)
                else {}
            )
            current_geom = (
                record.get("geometry_proxy", {})
                if isinstance(record.get("geometry_proxy"), dict)
                else {}
            )
            prev_geom = (
                previous.get("geometry_proxy", {})
                if isinstance(previous, dict) and isinstance(previous.get("geometry_proxy"), dict)
                else {}
            )
            introduced_by_cts = first in {"CTS", "legalization", "route", "drc", "filler"} and bool(
                record.get("identity", {}).get("is_clock") or _is_clock_like(key)
            )
            record["progressive_metadata"] = {
                "available_from": first,
                "created_stage": "Synthesis"
                if first in {"Floorplan", "fixFanout", "place"}
                else first,
                "created_stage_source": "def_net"
                if first in {"Floorplan", "fixFanout", "place"}
                else "first_observed",
                "exists_in_prev_stage": previous is not None,
                "exists_in_place": key in place_keys,
                "introduced_by_cts": introduced_by_cts,
                "prev_net_key": key if previous is not None else None,
                "renamed_from_prev_stage": False,
                "terminal_count_changed_from_prev_stage": _delta(
                    current_summary.get("terminal_count"), prev_summary.get("terminal_count")
                )
                if previous
                else None,
                "hpwl_delta_from_prev_stage": _delta(
                    current_geom.get("hpwl"), prev_geom.get("hpwl")
                )
                if previous
                else None,
                "patch_span_delta_from_prev_stage": _delta(
                    current_geom.get("patch_span_count"), prev_geom.get("patch_span_count")
                )
                if previous
                else None,
                "route_only_oracle": isinstance(record.get("route_analysis"), dict)
                and bool(record["route_analysis"].get("route_only_oracle")),
            }
        if current_by_key:
            previous_by_key = current_by_key
        write_jsonl(
            nets_dir / f"{stage.name}.jsonl",
            [_ordered_net_record(record, idx) for idx, record in enumerate(current)],
            sort_keys=False,
        )


def _attach_net_progressive_metadata_in_memory(
    stages: list[StageInfo], records_by_stage: dict[str, list[dict[str, Any]]]
) -> None:
    first_seen: dict[str, str] = {}
    for stage in stages:
        for record in records_by_stage.get(stage.name, []):
            first_seen.setdefault(str(record.get("net_key")), stage.name)
    place_keys = {str(record.get("net_key")) for record in records_by_stage.get("place", [])}
    previous_by_key: dict[str, dict[str, Any]] = {}
    for stage in stages:
        current = records_by_stage.get(stage.name, [])
        current_by_key = {str(record.get("net_key")): record for record in current}
        for key, record in current_by_key.items():
            previous = previous_by_key.get(key)
            first = first_seen.get(key, stage.name)
            current_summary = (
                record.get("connectivity_summary", {})
                if isinstance(record.get("connectivity_summary"), dict)
                else {}
            )
            prev_summary = (
                previous.get("connectivity_summary", {})
                if isinstance(previous, dict)
                and isinstance(previous.get("connectivity_summary"), dict)
                else {}
            )
            current_geom = (
                record.get("geometry_proxy", {})
                if isinstance(record.get("geometry_proxy"), dict)
                else {}
            )
            prev_geom = (
                previous.get("geometry_proxy", {})
                if isinstance(previous, dict) and isinstance(previous.get("geometry_proxy"), dict)
                else {}
            )
            introduced_by_cts = first in {"CTS", "legalization", "route", "drc", "filler"} and bool(
                record.get("identity", {}).get("is_clock") or _is_clock_like(key)
            )
            record["progressive_metadata"] = {
                "available_from": first,
                "created_stage": "Synthesis"
                if first in {"Floorplan", "fixFanout", "place"}
                else first,
                "created_stage_source": "def_net"
                if first in {"Floorplan", "fixFanout", "place"}
                else "first_observed",
                "exists_in_prev_stage": previous is not None,
                "exists_in_place": key in place_keys,
                "introduced_by_cts": introduced_by_cts,
                "prev_net_key": key if previous is not None else None,
                "renamed_from_prev_stage": False,
                "terminal_count_changed_from_prev_stage": _delta(
                    current_summary.get("terminal_count"), prev_summary.get("terminal_count")
                )
                if previous
                else None,
                "hpwl_delta_from_prev_stage": _delta(
                    current_geom.get("hpwl"), prev_geom.get("hpwl")
                )
                if previous
                else None,
                "patch_span_delta_from_prev_stage": _delta(
                    current_geom.get("patch_span_count"), prev_geom.get("patch_span_count")
                )
                if previous
                else None,
                "route_only_oracle": isinstance(record.get("route_analysis"), dict)
                and bool(record["route_analysis"].get("route_only_oracle")),
            }
        if current_by_key:
            previous_by_key = current_by_key


def _wire_geometry_signature(record: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if not record:
        return None
    identity = record.get("identity", {}) if isinstance(record.get("identity"), dict) else {}
    geometry = record.get("geometry", {}) if isinstance(record.get("geometry"), dict) else {}
    bbox = geometry.get("bbox")
    bbox_sig = (
        tuple(bbox.get(key) for key in ("llx", "lly", "urx", "ury"))
        if isinstance(bbox, dict)
        else None
    )
    return (identity.get("net_key"), geometry.get("layer"), geometry.get("segment_kind"), bbox_sig)


def _attach_wire_progressive_metadata(stages: list[StageInfo], wires_dir: Path) -> None:
    records_by_stage: dict[str, list[dict[str, Any]]] = {}
    for stage in stages:
        path = wires_dir / f"{stage.name}.jsonl"
        records_by_stage[stage.name] = _read_jsonl_records(path)
    first_seen: dict[tuple[Any, ...], str] = {}
    for stage in stages:
        for record in records_by_stage.get(stage.name, []):
            sig = _wire_geometry_signature(record)
            if sig is not None:
                first_seen.setdefault(sig, stage.name)
    previous_signatures: set[tuple[Any, ...]] = set()
    previous_net_keys: set[str] = set()
    for stage in stages:
        records = records_by_stage.get(stage.name, [])
        current_signatures = {_wire_geometry_signature(record) for record in records}
        current_signatures.discard(None)
        current_net_keys = {
            str(record.get("identity", {}).get("net_key"))
            for record in records
            if record.get("identity", {}).get("net_key") is not None
        }
        for record in records:
            sig = _wire_geometry_signature(record)
            net_key = (
                str(record.get("identity", {}).get("net_key"))
                if record.get("identity", {}).get("net_key") is not None
                else None
            )
            metadata = record.setdefault("progressive_metadata", {})
            metadata["available_from_stage"] = (
                first_seen.get(sig, stage.name) if sig is not None else stage.name
            )
            metadata["exists_same_geometry_in_prev_stage"] = (
                (sig in previous_signatures) if sig is not None else None
            )
            metadata["is_new_routed_geometry"] = (
                not metadata["exists_same_geometry_in_prev_stage"] if sig is not None else None
            )
            metadata["net_exists_in_prev_stage"] = (
                (net_key in previous_net_keys) if net_key is not None else None
            )
            metadata["route_only_oracle"] = isinstance(record.get("route_context"), dict) and bool(
                record["route_context"].get("route_only_oracle")
            )
            metadata["tracking_scope"] = "stage_local_wire_geometry"
        if records:
            previous_signatures = {sig for sig in current_signatures if sig is not None}
            previous_net_keys = current_net_keys
        write_jsonl(
            wires_dir / f"{stage.name}.jsonl",
            [_ordered_wire_record(record) for record in records],
            sort_keys=False,
        )


def _attach_wire_progressive_metadata_in_memory(
    stages: list[StageInfo], records_by_stage: dict[str, list[dict[str, Any]]]
) -> None:
    first_seen: dict[tuple[Any, ...], str] = {}
    for stage in stages:
        for record in records_by_stage.get(stage.name, []):
            sig = _wire_geometry_signature(record)
            if sig is not None:
                first_seen.setdefault(sig, stage.name)
    previous_signatures: set[tuple[Any, ...]] = set()
    previous_net_keys: set[str] = set()
    for stage in stages:
        records = records_by_stage.get(stage.name, [])
        current_signatures = {_wire_geometry_signature(record) for record in records}
        current_signatures.discard(None)
        current_net_keys = {
            str(record.get("identity", {}).get("net_key"))
            for record in records
            if record.get("identity", {}).get("net_key") is not None
        }
        for record in records:
            sig = _wire_geometry_signature(record)
            net_key = (
                str(record.get("identity", {}).get("net_key"))
                if record.get("identity", {}).get("net_key") is not None
                else None
            )
            metadata = record.setdefault("progressive_metadata", {})
            metadata["available_from_stage"] = (
                first_seen.get(sig, stage.name) if sig is not None else stage.name
            )
            metadata["exists_same_geometry_in_prev_stage"] = (
                (sig in previous_signatures) if sig is not None else None
            )
            metadata["is_new_routed_geometry"] = (
                not metadata["exists_same_geometry_in_prev_stage"] if sig is not None else None
            )
            metadata["net_exists_in_prev_stage"] = (
                (net_key in previous_net_keys) if net_key is not None else None
            )
            metadata["route_only_oracle"] = isinstance(record.get("route_context"), dict) and bool(
                record["route_context"].get("route_only_oracle")
            )
            metadata["tracking_scope"] = "stage_local_wire_geometry"
        if records:
            previous_signatures = {sig for sig in current_signatures if sig is not None}
            previous_net_keys = current_net_keys


def _ordered_pin_record(record: dict[str, Any], record_id: int) -> dict[str, Any]:
    return {
        "id": record_id,
        "stage": record["stage"],
        "pin_key": record["pin_key"],
        "source": record["source"],
        "identity": record["identity"],
        "electrical_context": record["electrical_context"],
        "parent_instance": record["parent_instance"],
        "geometry": record["geometry"],
        "connectivity_context": record["connectivity_context"],
        "timing_context": record["timing_context"],
        "patch_anchor": record["patch_anchor"],
        "route_context": record["route_context"],
        "progressive_metadata": record["progressive_metadata"],
        "source_refs": record["source_refs"],
        "null_reason": record["null_reason"],
    }


def _pin_key(raw_pin: dict[str, Any]) -> str:
    pin_name = str(raw_pin.get("pin_name") or "")
    if (
        str(raw_pin.get("pin_kind") or "") == "io_port"
        or str(raw_pin.get("instance") or "") == "PIN"
    ):
        return f"PIN:{pin_name}"
    return f"{raw_pin.get('instance')}:{pin_name}"


def _bbox_center(bbox: dict[str, Any]) -> dict[str, float]:
    return {
        "x": (float(bbox["llx"]) + float(bbox["urx"])) / 2.0,
        "y": (float(bbox["lly"]) + float(bbox["ury"])) / 2.0,
    }


def _bbox_from_points(points: list[dict[str, Any]]) -> dict[str, float] | None:
    if not points:
        return None
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    return {"llx": min(xs), "lly": min(ys), "urx": max(xs), "ury": max(ys)}


def _hpwl_from_points(points: list[dict[str, Any]]) -> float | None:
    if len(points) < 2:
        return None
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


def _pin_geometry_signature(record: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if not record:
        return None
    geometry = record.get("geometry", {})
    bbox = geometry.get("bbox")
    bbox_sig = (
        tuple(bbox.get(key) for key in ("llx", "lly", "urx", "ury"))
        if isinstance(bbox, dict)
        else None
    )
    return (
        geometry.get("geometry_status"),
        bbox_sig,
        tuple(geometry.get("layers") or []),
        geometry.get("shape_count"),
    )


def _is_clock_like(value: str) -> bool:
    lower = value.lower()
    return "clk" in lower or "clock" in lower


def _attach_patch_anchor(
    record: dict[str, Any], canonical_grid: dict, stage_maps: dict[str, dict[str, MapMatrix]]
) -> None:
    physical_state = record.get("physical_state", {})
    center = physical_state.get("center") if isinstance(physical_state, dict) else None
    bbox = physical_state.get("bbox") if isinstance(physical_state, dict) else None
    patches = canonical_grid.get("patches", []) if isinstance(canonical_grid, dict) else []
    lookup = _patch_grid_lookup(canonical_grid)
    primary_patch = _grid_patch_for_point(lookup, center) if isinstance(center, dict) else None
    if primary_patch is None and isinstance(center, dict):
        primary_patch = _patch_for_point(patches, center)
    overlap_patch_ids = _grid_overlap_patch_ids(lookup, bbox) if isinstance(bbox, dict) else []
    if not overlap_patch_ids and isinstance(bbox, dict):
        overlap_patch_ids = _overlap_patch_ids(patches, bbox)
    if primary_patch is not None and int(primary_patch["patch_id"]) not in overlap_patch_ids:
        overlap_patch_ids = [int(primary_patch["patch_id"]), *overlap_patch_ids]
    patch_id = int(primary_patch["patch_id"]) if primary_patch is not None else None
    row = int(primary_patch["row"]) if primary_patch is not None else None
    col = int(primary_patch["col"]) if primary_patch is not None else None
    physical_state["patch_id"] = patch_id
    physical_state["overlap_patch_ids"] = overlap_patch_ids
    record["patch_anchor"] = {
        "primary_patch_id": patch_id,
        "overlap_patch_ids": overlap_patch_ids,
        "local_cell_density": _matrix_value(
            stage_maps.get("density", {}).get("allcell_density"), row, col
        )
        if row is not None and col is not None
        else None,
        "local_pin_density": _matrix_value(
            stage_maps.get("density", {}).get("allcell_pin_density"), row, col
        )
        if row is not None and col is not None
        else None,
        "local_rudy": _matrix_value(stage_maps.get("rudy", {}).get("rudy_union"), row, col)
        if row is not None and col is not None
        else None,
        "local_egr_overflow": _matrix_value(stage_maps.get("congestion", {}).get("union"), row, col)
        if row is not None and col is not None
        else None,
    }


def _patch_grid_lookup(canonical_grid: dict[str, Any] | None) -> _PatchGridLookup | None:
    if not isinstance(canonical_grid, dict):
        return None
    patches = canonical_grid.get("patches")
    if not isinstance(patches, list) or not patches:
        return None
    rows = int(canonical_grid.get("rows") or 0)
    cols = int(canonical_grid.get("cols") or 0)
    cache_key = (id(patches), len(patches), rows, cols)
    if cache_key in _PATCH_GRID_LOOKUP_CACHE:
        return _PATCH_GRID_LOOKUP_CACHE[cache_key]

    if rows <= 0 or cols <= 0:
        _PATCH_GRID_LOOKUP_CACHE[cache_key] = None
        return None

    patches_by_coord: dict[tuple[int, int], dict[str, Any]] = {}
    patches_by_id: dict[int, dict[str, Any]] = {}
    row_bounds_by_row: dict[int, tuple[float, float]] = {}
    col_bounds_by_col: dict[int, tuple[float, float]] = {}
    rectangular = True
    for patch in patches:
        if not isinstance(patch, dict) or not isinstance(patch.get("bbox"), dict):
            rectangular = False
            continue
        row = int(patch.get("row", -1))
        col = int(patch.get("col", -1))
        if row < 0 or col < 0:
            rectangular = False
            continue
        bbox = patch["bbox"]
        row_bounds = (float(bbox["lly"]), float(bbox["ury"]))
        col_bounds = (float(bbox["llx"]), float(bbox["urx"]))
        if row in row_bounds_by_row and row_bounds_by_row[row] != row_bounds:
            rectangular = False
        if col in col_bounds_by_col and col_bounds_by_col[col] != col_bounds:
            rectangular = False
        row_bounds_by_row.setdefault(row, row_bounds)
        col_bounds_by_col.setdefault(col, col_bounds)
        patches_by_coord[(row, col)] = patch
        if patch.get("patch_id") is not None:
            patches_by_id[int(patch["patch_id"])] = patch

    if len(row_bounds_by_row) != rows or len(col_bounds_by_col) != cols:
        rectangular = False
    row_bounds = [row_bounds_by_row[row] for row in range(rows) if row in row_bounds_by_row]
    col_bounds = [col_bounds_by_col[col] for col in range(cols) if col in col_bounds_by_col]
    lookup = _PatchGridLookup(
        patches_by_coord=patches_by_coord,
        patches_by_id=patches_by_id,
        row_bounds=row_bounds,
        col_bounds=col_bounds,
        rectangular=rectangular,
        uniform=_uniform_bounds(row_bounds) and _uniform_bounds(col_bounds),
        row_origin=row_bounds[0][0] if row_bounds else None,
        col_origin=col_bounds[0][0] if col_bounds else None,
        row_step=(row_bounds[0][1] - row_bounds[0][0]) if row_bounds else None,
        col_step=(col_bounds[0][1] - col_bounds[0][0]) if col_bounds else None,
    )
    _PATCH_GRID_LOOKUP_CACHE[cache_key] = lookup
    return lookup


def _patch_grid_lookup_from_patches(
    patches: list[dict[str, Any]],
    rows: int,
    cols: int,
) -> _PatchGridLookup | None:
    return _patch_grid_lookup({"patches": patches, "rows": rows, "cols": cols})


def _grid_patch_for_point(
    lookup: _PatchGridLookup | None, point: dict[str, Any]
) -> dict[str, Any] | None:
    if lookup is None or not lookup.rectangular or point.get("x") is None or point.get("y") is None:
        return None
    col = (
        _uniform_bound_index_for_point(lookup, "col", float(point["x"])) if lookup.uniform else None
    )
    row = (
        _uniform_bound_index_for_point(lookup, "row", float(point["y"])) if lookup.uniform else None
    )
    if col is None:
        col = _bound_index_for_point(lookup.col_bounds, float(point["x"]))
    if row is None:
        row = _bound_index_for_point(lookup.row_bounds, float(point["y"]))
    if row is None or col is None:
        return None
    return lookup.patches_by_coord.get((row, col))


def _grid_overlap_patch_ids(lookup: _PatchGridLookup | None, bbox: dict[str, Any]) -> list[int]:
    if lookup is None or not lookup.rectangular:
        return []
    col_indexes = (
        _uniform_bound_indexes_for_range(lookup, "col", float(bbox["llx"]), float(bbox["urx"]))
        if lookup.uniform
        else []
    )
    row_indexes = (
        _uniform_bound_indexes_for_range(lookup, "row", float(bbox["lly"]), float(bbox["ury"]))
        if lookup.uniform
        else []
    )
    if not col_indexes:
        col_indexes = _bound_indexes_for_range(
            lookup.col_bounds, float(bbox["llx"]), float(bbox["urx"])
        )
    if not row_indexes:
        row_indexes = _bound_indexes_for_range(
            lookup.row_bounds, float(bbox["lly"]), float(bbox["ury"])
        )
    ids: list[int] = []
    for row in row_indexes:
        for col in col_indexes:
            patch = lookup.patches_by_coord.get((row, col))
            if patch is not None and _bbox_overlap_area(bbox, patch["bbox"]) > 0:
                ids.append(int(patch["patch_id"]))
    return ids


def _uniform_bounds(bounds: list[tuple[float, float]]) -> bool:
    if not bounds:
        return False
    step = bounds[0][1] - bounds[0][0]
    if step <= 0:
        return False
    tolerance = max(abs(step) * 1e-9, 1e-6)
    return all(
        abs((upper - lower) - step) <= tolerance
        and (index == 0 or abs(lower - bounds[index - 1][1]) <= tolerance)
        for index, (lower, upper) in enumerate(bounds)
    )


def _uniform_bound_index_for_point(lookup: _PatchGridLookup, axis: str, value: float) -> int | None:
    origin = lookup.col_origin if axis == "col" else lookup.row_origin
    step = lookup.col_step if axis == "col" else lookup.row_step
    count = len(lookup.col_bounds if axis == "col" else lookup.row_bounds)
    if origin is None or step is None or step <= 0 or count <= 0:
        return None
    index = int((value - origin) // step)
    if 0 <= index < count:
        return index
    upper = origin + step * count
    if value == upper:
        return count - 1
    return None


def _uniform_bound_indexes_for_range(
    lookup: _PatchGridLookup, axis: str, start: float, end: float
) -> list[int]:
    origin = lookup.col_origin if axis == "col" else lookup.row_origin
    step = lookup.col_step if axis == "col" else lookup.row_step
    count = len(lookup.col_bounds if axis == "col" else lookup.row_bounds)
    if origin is None or step is None or step <= 0 or count <= 0:
        return []
    lower = min(start, end)
    upper = max(start, end)
    if lower == upper:
        index = _uniform_bound_index_for_point(lookup, axis, lower)
        return [index] if index is not None else []
    first = max(0, int((lower - origin) // step))
    last = min(count - 1, int(((upper - origin) - 1e-9) // step))
    if last < first:
        return []
    return list(range(first, last + 1))


def _bound_index_for_point(bounds: list[tuple[float, float]], value: float) -> int | None:
    for index, (lower, upper) in enumerate(bounds):
        if lower <= value < upper:
            return index
    if bounds and value == bounds[-1][1]:
        return len(bounds) - 1
    return None


def _bound_indexes_for_range(
    bounds: list[tuple[float, float]], start: float, end: float
) -> list[int]:
    lower = min(start, end)
    upper = max(start, end)
    if lower == upper:
        index = _bound_index_for_point(bounds, lower)
        return [index] if index is not None else []
    return [
        index
        for index, (bound_lower, bound_upper) in enumerate(bounds)
        if max(lower, bound_lower) < min(upper, bound_upper)
    ]


def _patch_for_point(patches: list[dict[str, Any]], point: dict[str, Any]) -> dict[str, Any] | None:
    half_open_match = next(
        (
            patch
            for patch in patches
            if _point_in_patch_bbox_half_open(point.get("x"), point.get("y"), patch.get("bbox", {}))
        ),
        None,
    )
    if half_open_match is not None:
        return half_open_match
    return next(
        (
            patch
            for patch in patches
            if _point_in_bbox(point.get("x"), point.get("y"), patch.get("bbox", {}))
        ),
        None,
    )


def _point_in_patch_bbox_half_open(x: Any, y: Any, bbox: dict[str, Any]) -> bool:
    if x is None or y is None or not isinstance(bbox, dict):
        return False
    xf = float(x)
    yf = float(y)
    return float(bbox["llx"]) <= xf < float(bbox["urx"]) and float(bbox["lly"]) <= yf < float(
        bbox["ury"]
    )


def _overlap_patch_ids(patches: list[dict[str, Any]], bbox: dict[str, Any]) -> list[int]:
    return [
        int(patch["patch_id"])
        for patch in patches
        if isinstance(patch.get("bbox"), dict) and _bbox_overlap_area(bbox, patch["bbox"]) > 0
    ]


def _strip_stage_prefix_from_density_maps(
    maps: dict[str, MapMatrix], stage: str
) -> dict[str, MapMatrix]:
    prefix = f"{stage.lower()}_"
    stripped = {key.removeprefix(prefix): matrix for key, matrix in maps.items()}
    return {
        key: stripped[key]
        for key in [*list(_DENSITY_MAP_KEY_ORDER), *sorted(stripped)]
        if key in stripped
    }


def _replace_with_matrix_sum(
    maps: dict[str, MapMatrix], target_token: str, lhs_token: str, rhs_token: str
) -> None:
    target_key = _first_key_containing(maps, target_token)
    lhs_key = _first_key_containing(maps, lhs_token)
    rhs_key = _first_key_containing(maps, rhs_token)
    if target_key is None or lhs_key is None or rhs_key is None:
        return
    if _matrix_shape(maps[lhs_key]) != _matrix_shape(maps[rhs_key]):
        return
    maps[target_key] = [
        [
            float(lhs_value) + float(rhs_value)
            for lhs_value, rhs_value in zip(lhs_row, rhs_row, strict=True)
        ]
        for lhs_row, rhs_row in zip(maps[lhs_key], maps[rhs_key], strict=True)
    ]


def _matrix_shape(matrix: MapMatrix) -> tuple[int, int]:
    return (len(matrix), len(matrix[0]) if matrix else 0)


def _first_key_containing(maps: dict[str, MapMatrix], token: str) -> str | None:
    for key in maps:
        if token in key:
            return key
    return None


def _zero_density_maps(canonical_grid: dict) -> dict[str, MapMatrix]:
    rows = int(canonical_grid.get("rows") or 0)
    cols = int(canonical_grid.get("cols") or 0)
    if rows <= 0 or cols <= 0:
        return {}
    return {key: _empty_matrix(rows, cols) for key in _DENSITY_MAP_KEY_ORDER}


def _floorplan_specific_patch_maps(
    parsed_def: DefData,
    canonical_grid: dict,
    layout_physical_only_cells: list[dict[str, Any]] | None = None,
) -> dict[str, MapMatrix]:
    patches = canonical_grid.get("patches", [])
    rows = int(canonical_grid.get("rows") or 0)
    cols = int(canonical_grid.get("cols") or 0)
    if not patches or rows <= 0 or cols <= 0:
        return {}
    physical_only_cells = layout_physical_only_cells or _physical_only_cells_from_floorplan_def(
        parsed_def
    )
    power_grid_shapes = _power_grid_shapes_from_floorplan_def(parsed_def)
    io_pins = _io_pin_points_from_def(parsed_def)
    pg_net_shapes = _power_ground_net_shapes_from_floorplan_def(parsed_def)
    return {
        "io_pin_density": _patch_point_density(patches, rows, cols, io_pins),
        "power_grid_density": _patch_shape_density(patches, rows, cols, power_grid_shapes),
        "physical_only_cell_density": _patch_shape_density(
            patches, rows, cols, physical_only_cells
        ),
        "pg_net_count": _patch_shape_presence_count(patches, rows, cols, pg_net_shapes),
    }


def _egr_demand_capacity_maps_from_stage(
    stage_dir: Path,
) -> tuple[dict[str, MapMatrix], list[Path]]:
    early_router = stage_dir / "data" / "rt" / "rt_temp_directory" / "early_router"
    if not early_router.exists():
        return {}, []
    layer_directions = _layer_directions_from_route_guide(early_router / "route.guide")
    if not layer_directions:
        return {}, []
    demand_by_direction: dict[str, list[MapMatrix]] = {"horizontal": [], "vertical": []}
    source_paths: list[Path] = []
    for layer, direction in layer_directions.items():
        if direction not in demand_by_direction:
            continue
        demand_path = early_router / f"net_map_{layer}.csv"
        capacity_path = early_router / f"supply_map_{layer}.csv"
        if not demand_path.exists() or not capacity_path.exists():
            continue
        demand = _read_early_router_csv_matrix(demand_path)
        capacity = _read_early_router_csv_matrix(capacity_path)
        if not demand or shape(demand) != shape(capacity):
            continue
        demand_by_direction[direction].append(_matrix_subtract(demand, capacity))
        source_paths.extend([demand_path, capacity_path])
    horizontal = _sum_matrices(demand_by_direction["horizontal"])
    vertical = _sum_matrices(demand_by_direction["vertical"])
    if not horizontal and not vertical:
        return {}, source_paths
    if not horizontal:
        horizontal = _empty_matrix(*_matrix_shape(vertical))
    if not vertical:
        vertical = _empty_matrix(*_matrix_shape(horizontal))
    if _matrix_shape(horizontal) != _matrix_shape(vertical):
        return {}, source_paths
    union = [
        [max(float(h_value), float(v_value)) for h_value, v_value in zip(h_row, v_row, strict=True)]
        for h_row, v_row in zip(horizontal, vertical, strict=True)
    ]
    return {"horizontal": horizontal, "vertical": vertical, "union": union}, source_paths


def _read_early_router_csv_matrix(path: Path) -> MapMatrix:
    matrix = read_numeric_csv(path)
    return list(reversed(matrix))


def _layer_directions_from_route_guide(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    directions: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 10 or parts[0] != "wire":
            continue
        layer = parts[9]
        if layer in directions:
            continue
        try:
            x1, y1, x2, y2 = (float(parts[index]) for index in (1, 2, 3, 4))
        except ValueError:
            continue
        if x1 == x2 and y1 != y2:
            directions[layer] = "vertical"
        elif y1 == y2 and x1 != x2:
            directions[layer] = "horizontal"
    return directions


def _matrix_subtract(lhs: MapMatrix, rhs: MapMatrix) -> MapMatrix:
    return [
        [
            float(lhs_value) - float(rhs_value)
            for lhs_value, rhs_value in zip(lhs_row, rhs_row, strict=True)
        ]
        for lhs_row, rhs_row in zip(lhs, rhs, strict=True)
    ]


def _sum_matrices(matrices: list[MapMatrix]) -> MapMatrix:
    if not matrices:
        return []
    rows, cols = _matrix_shape(matrices[0])
    out = _empty_matrix(rows, cols)
    for matrix in matrices:
        if _matrix_shape(matrix) != (rows, cols):
            return []
        out = [
            [
                float(lhs_value) + float(rhs_value)
                for lhs_value, rhs_value in zip(lhs_row, rhs_row, strict=True)
            ]
            for lhs_row, rhs_row in zip(out, matrix, strict=True)
        ]
    return out


def _physical_only_cells_from_floorplan_def(parsed_def: DefData) -> list[dict[str, Any]]:
    component_boxes = _component_boxes_from_raw_def(parsed_def.path)
    out: list[dict[str, Any]] = []
    for component in parsed_def.components:
        name = str(component.get("name") or "")
        master = str(component.get("master") or "")
        if not _is_physical_only_cell_name(name, master):
            continue
        bbox = component_boxes.get(name)
        if bbox is not None:
            out.append(bbox)
            continue
        origin = component.get("origin")
        if isinstance(origin, dict):
            x = float(origin.get("x", 0.0))
            y = float(origin.get("y", 0.0))
            out.append({"llx": x, "lly": y, "urx": x, "ury": y})
    return out


def _component_boxes_from_raw_def(path: Path) -> dict[str, dict[str, float]]:
    text = _read_text_maybe_gzip(path)
    boxes: dict[str, dict[str, float]] = {}
    match = re.search(r"COMPONENTS\s+\d+\s*;(?P<body>.*?)END COMPONENTS", text, re.S)
    if not match:
        return boxes
    current_name: str | None = None
    for raw_line in match.group("body").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            parts = stripped.split()
            current_name = parts[1] if len(parts) > 1 else None
        if current_name is None:
            continue
        placed = re.search(
            r"\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", stripped
        )
        size = re.search(r"\+\s+SIZE\s+(-?\d+(?:\.\d+)?)\s+BY\s+(-?\d+(?:\.\d+)?)", stripped)
        if placed and size:
            x = float(placed.group(1))
            y = float(placed.group(2))
            width = float(size.group(1))
            height = float(size.group(2))
            boxes[current_name] = {"llx": x, "lly": y, "urx": x + width, "ury": y + height}
            current_name = None
    return boxes


def _power_grid_shapes_from_floorplan_def(parsed_def: DefData) -> list[dict[str, Any]]:
    return [
        _wire_bbox_with_width(wire)
        for net in parsed_def.nets
        if net.special and _is_power_or_ground_net(net.name)
        for wire in net.wires
    ]


def _power_ground_net_shapes_from_floorplan_def(parsed_def: DefData) -> list[dict[str, Any]]:
    return [
        _wire_bbox_with_width(wire)
        for net in parsed_def.nets
        if _is_power_or_ground_net(net.name) or str(net.use or "").upper() in {"POWER", "GROUND"}
        for wire in net.wires
    ]


def _io_pin_points_from_def(parsed_def: DefData) -> list[dict[str, Any]]:
    return [
        {"x": float(pin["origin"]["x"]), "y": float(pin["origin"]["y"])}
        for pin in parsed_def.pins
        if isinstance(pin.get("origin"), dict)
    ]


def _patch_point_density(
    patches: list[dict[str, Any]],
    rows: int,
    cols: int,
    points: list[dict[str, Any]],
) -> MapMatrix:
    matrix = _empty_matrix(rows, cols)
    lookup = _patch_grid_lookup_from_patches(patches, rows, cols)
    if lookup is not None and lookup.rectangular:
        for point in points:
            patch = _grid_patch_for_point(lookup, point)
            if patch is None:
                continue
            row, col = int(patch["row"]), int(patch["col"])
            matrix[row][col] += 1.0
        return matrix
    for patch in patches:
        row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
        matrix[row][col] = float(
            sum(1 for point in points if _point_in_bbox(point.get("x"), point.get("y"), bbox))
        )
    return matrix


def _overlapping_patch_candidates(
    lookup: _PatchGridLookup | None,
    patches: list[dict[str, Any]],
    shape: dict[str, Any],
) -> list[dict[str, Any]]:
    if lookup is None or not lookup.rectangular:
        return patches
    col_indexes = (
        _uniform_bound_indexes_for_range(lookup, "col", float(shape["llx"]), float(shape["urx"]))
        if lookup.uniform
        else []
    )
    row_indexes = (
        _uniform_bound_indexes_for_range(lookup, "row", float(shape["lly"]), float(shape["ury"]))
        if lookup.uniform
        else []
    )
    if not col_indexes:
        col_indexes = _bound_indexes_for_range(
            lookup.col_bounds,
            float(shape["llx"]),
            float(shape["urx"]),
        )
    if not row_indexes:
        row_indexes = _bound_indexes_for_range(
            lookup.row_bounds,
            float(shape["lly"]),
            float(shape["ury"]),
        )
    return [
        patch
        for row in row_indexes
        for col in col_indexes
        if (patch := lookup.patches_by_coord.get((row, col))) is not None
    ]


def _patch_shape_density(
    patches: list[dict[str, Any]],
    rows: int,
    cols: int,
    shapes: list[dict[str, Any]],
) -> MapMatrix:
    matrix = _empty_matrix(rows, cols)
    lookup = _patch_grid_lookup_from_patches(patches, rows, cols)
    if lookup is not None and lookup.rectangular:
        for shape in shapes:
            for patch in _overlapping_patch_candidates(lookup, patches, shape):
                row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
                patch_area = _bbox_area(bbox)
                if patch_area <= 0:
                    continue
                matrix[row][col] += _bbox_overlap_area(shape, bbox) / patch_area
        return matrix
    for patch in patches:
        row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
        patch_area = _bbox_area(bbox)
        if patch_area <= 0:
            continue
        matrix[row][col] = sum(_bbox_overlap_area(shape, bbox) for shape in shapes) / patch_area
    return matrix


def _patch_shape_presence_count(
    patches: list[dict[str, Any]],
    rows: int,
    cols: int,
    shapes: list[dict[str, Any]],
) -> MapMatrix:
    matrix = _empty_matrix(rows, cols)
    lookup = _patch_grid_lookup_from_patches(patches, rows, cols)
    if lookup is not None and lookup.rectangular:
        for shape in shapes:
            for patch in _overlapping_patch_candidates(lookup, patches, shape):
                row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
                if _bbox_overlap_area(shape, bbox) > 0:
                    matrix[row][col] += 1.0
        return matrix
    for patch in patches:
        row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
        matrix[row][col] = float(sum(1 for shape in shapes if _bbox_overlap_area(shape, bbox) > 0))
    return matrix


def _pg_net_count_for_patch(pg_net_count: float | None, overlap_nets: list[dict[str, Any]]) -> int:
    if pg_net_count is not None:
        return int(pg_net_count)
    return sum(1 for net in overlap_nets if net.get("identity", {}).get("is_power_ground"))


def _is_physical_only_cell_name(name: str, master: str) -> bool:
    lower = f"{name} {master}".lower()
    return any(token in lower for token in ("fill", "tap", "endcap", "decap", "welltap"))


def _is_power_or_ground_net(name: str) -> bool:
    lower = name.lower()
    return lower.startswith(("vdd", "vss", "vcc", "gnd", "power", "ground"))


def _wire_bbox_with_width(wire: DefWire) -> dict[str, float]:
    half_width = float(wire.width or 0.0) / 2.0
    return {
        "llx": min(float(wire.x1), float(wire.x2)) - half_width,
        "lly": min(float(wire.y1), float(wire.y2)) - half_width,
        "urx": max(float(wire.x1), float(wire.x2)) + half_width,
        "ury": max(float(wire.y1), float(wire.y2)) + half_width,
    }


def _read_text_maybe_gzip(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return path.read_text(encoding="utf-8", errors="replace")


def _empty_matrix(rows: int, cols: int) -> list[list[float]]:
    return [[0.0 for _ in range(cols)] for _ in range(rows)]


def _component_records_for_maps(parsed_def: DefData) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rows = parsed_def.rows
    default_width = max((float(row.step_x) for row in rows if row.step_x), default=1.0)
    default_height = max((float(row.step_y) for row in rows if row.step_y), default=1.0)
    for component in parsed_def.components:
        origin = component.get("origin") if isinstance(component, dict) else None
        if not isinstance(origin, dict):
            continue
        x = float(origin.get("x", 0.0))
        y = float(origin.get("y", 0.0))
        master = str(component.get("master") or "")
        lower = master.lower()
        is_macro = "macro" in lower or "sram" in lower or "mem" in lower
        out.append(
            {
                "name": component.get("name"),
                "llx": x,
                "lly": y,
                "urx": x + default_width,
                "ury": y + default_height,
                "is_macro": is_macro,
            }
        )
    return out


def _pin_points_for_maps(parsed_def: DefData) -> list[dict[str, Any]]:
    components_by_name = {
        str(item.get("name")): item for item in _component_records_for_maps(parsed_def)
    }
    pins: list[dict[str, Any]] = []
    for pin in parsed_def.pins:
        origin = pin.get("origin")
        if isinstance(origin, dict):
            pins.append(
                {
                    "x": float(origin.get("x", 0.0)),
                    "y": float(origin.get("y", 0.0)),
                    "is_macro": False,
                }
            )
    for net in parsed_def.nets:
        for pin in net.pins:
            component = components_by_name.get(str(pin.get("instance")))
            if component is None:
                continue
            pins.append(
                {
                    "x": (component["llx"] + component["urx"]) / 2.0,
                    "y": (component["lly"] + component["ury"]) / 2.0,
                    "is_macro": bool(component.get("is_macro")),
                }
            )
    return pins


def _net_bboxes_for_maps(parsed_def: DefData) -> list[dict[str, Any]]:
    points_by_instance = {
        str(item.get("name")): (
            (item["llx"] + item["urx"]) / 2.0,
            (item["lly"] + item["ury"]) / 2.0,
        )
        for item in _component_records_for_maps(parsed_def)
    }
    top_pin_points = {
        str(pin.get("pin_name")): (
            float(pin.get("origin", {}).get("x", 0.0)),
            float(pin.get("origin", {}).get("y", 0.0)),
        )
        for pin in parsed_def.pins
        if isinstance(pin.get("origin"), dict)
    }
    nets: list[dict[str, Any]] = []
    for net in parsed_def.nets:
        xs: list[float] = []
        ys: list[float] = []
        for pin in net.pins:
            instance = str(pin.get("instance"))
            pin_name = str(pin.get("pin_name"))
            point = (
                top_pin_points.get(pin_name)
                if instance == "PIN"
                else points_by_instance.get(instance)
            )
            if point is None:
                continue
            xs.append(point[0])
            ys.append(point[1])
        for wire in net.wires:
            xs.extend([float(wire.x1), float(wire.x2)])
            ys.extend([float(wire.y1), float(wire.y2)])
        if not xs or not ys:
            continue
        bbox = {"llx": min(xs), "lly": min(ys), "urx": max(xs), "ury": max(ys)}
        nets.append({**bbox, "overlap_count": 0})
    return nets


def _patch_cell_density(
    patches: list[dict[str, Any]], rows: int, cols: int, cells: list[dict[str, Any]]
) -> MapMatrix:
    matrix = _empty_matrix(rows, cols)
    for patch in patches:
        row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
        patch_area = _bbox_area(bbox)
        if patch_area <= 0:
            continue
        matrix[row][col] = sum(_bbox_overlap_area(cell, bbox) for cell in cells) / patch_area
    return matrix


def _patch_pin_density(
    patches: list[dict[str, Any]], rows: int, cols: int, pins: list[dict[str, Any]]
) -> MapMatrix:
    matrix = _empty_matrix(rows, cols)
    for patch in patches:
        row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
        matrix[row][col] = float(
            sum(1 for pin in pins if _point_in_bbox(pin.get("x"), pin.get("y"), bbox))
        )
    return matrix


def _patch_net_density(
    patches: list[dict[str, Any]], rows: int, cols: int, nets: list[dict[str, Any]]
) -> MapMatrix:
    matrix = _empty_matrix(rows, cols)
    for net in nets:
        net["overlap_count"] = sum(
            1 for patch in patches if _bbox_overlap_area(net, patch["bbox"]) > 0
        )
    for patch in patches:
        row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
        patch_area = _bbox_area(bbox)
        if patch_area <= 0:
            continue
        matrix[row][col] = sum(_bbox_overlap_area(net, bbox) for net in nets) / patch_area
    return matrix


def _patch_rudy(
    patches: list[dict[str, Any]], rows: int, cols: int, nets: list[dict[str, Any]], direction: str
) -> MapMatrix:
    matrix = _empty_matrix(rows, cols)
    for patch in patches:
        row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
        patch_area = _bbox_area(bbox)
        if patch_area <= 0:
            continue
        value = 0.0
        for net in nets:
            overlap = _bbox_overlap_area(net, bbox)
            if overlap <= 0:
                continue
            width = max(0.0, float(net["urx"]) - float(net["llx"]))
            height = max(0.0, float(net["ury"]) - float(net["lly"]))
            horizontal = 1.0 if height == 0 else 1.0 / height
            vertical = 1.0 if width == 0 else 1.0 / width
            if direction == "horizontal":
                value += overlap * horizontal / patch_area
            elif direction == "vertical":
                value += overlap * vertical / patch_area
            else:
                value += overlap * (horizontal + vertical) / patch_area
        matrix[row][col] = value
    return matrix


def _patch_margin(
    patches: list[dict[str, Any]],
    rows: int,
    cols: int,
    macros: list[dict[str, Any]],
    diearea: dict[str, float] | None,
    direction: str,
) -> MapMatrix:
    matrix = _empty_matrix(rows, cols)
    core = diearea or _bbox_union([patch["bbox"] for patch in patches])
    for patch in patches:
        row, col, bbox = int(patch["row"]), int(patch["col"]), patch["bbox"]
        if _bbox_overlap_area(bbox, core) <= 0:
            continue
        patch_area = _bbox_area(bbox)
        if (
            patch_area > 0
            and sum(_bbox_overlap_area(macro, bbox) for macro in macros) > 0.5 * patch_area
        ):
            continue
        center_x = (float(bbox["llx"]) + float(bbox["urx"])) / 2.0
        center_y = (float(bbox["lly"]) + float(bbox["ury"])) / 2.0
        h_left, h_right = float(core["llx"]), float(core["urx"])
        v_down, v_up = float(core["lly"]), float(core["ury"])
        for macro in macros:
            macro_cx = (float(macro["llx"]) + float(macro["urx"])) / 2.0
            macro_cy = (float(macro["lly"]) + float(macro["ury"])) / 2.0
            if float(macro["lly"]) <= center_y <= float(macro["ury"]):
                if macro_cx > center_x:
                    h_right = min(h_right, float(macro["llx"]))
                else:
                    h_left = max(h_left, float(macro["urx"]))
            if float(macro["llx"]) <= center_x <= float(macro["urx"]):
                if macro_cy > center_y:
                    v_up = min(v_up, float(macro["lly"]))
                else:
                    v_down = max(v_down, float(macro["ury"]))
        horizontal = h_right - h_left
        vertical = v_up - v_down
        matrix[row][col] = (
            horizontal
            if direction == "horizontal"
            else vertical
            if direction == "vertical"
            else horizontal + vertical
        )
    return matrix


def _bbox_area(bbox: dict[str, Any] | None) -> float | None:
    if not bbox:
        return None
    return max(0.0, float(bbox["urx"]) - float(bbox["llx"])) * max(
        0.0, float(bbox["ury"]) - float(bbox["lly"])
    )


def _bbox_overlap_area(a: dict[str, Any], b: dict[str, Any]) -> float:
    overlap_lx = max(float(a["llx"]), float(b["llx"]))
    overlap_ly = max(float(a["lly"]), float(b["lly"]))
    overlap_ux = min(float(a["urx"]), float(b["urx"]))
    overlap_uy = min(float(a["ury"]), float(b["ury"]))
    return max(0.0, overlap_ux - overlap_lx) * max(0.0, overlap_uy - overlap_ly)


def _bbox_union(boxes: list[dict[str, Any]]) -> dict[str, float]:
    if not boxes:
        return {"llx": 0.0, "lly": 0.0, "urx": 0.0, "ury": 0.0}
    return {
        "llx": min(float(box["llx"]) for box in boxes),
        "lly": min(float(box["lly"]) for box in boxes),
        "urx": max(float(box["urx"]) for box in boxes),
        "ury": max(float(box["ury"]) for box in boxes),
    }


def _stable_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = _stable_digest(parts)[:16]
    return f"{prefix}_{digest}"


def _stage_id(run_id: str, stage_order: int, stage_name: str) -> str:
    return _stable_id("stage", run_id, stage_order, stage_name)


def _file_digest(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_or_string(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _workspace_relative_artifact_path(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    path = Path(text)
    parts = path.parts
    for marker in (
        "Synthesis_yosys",
        "Floorplan_ecc",
        "fixFanout_ecc",
        "place_dreamplace",
        "CTS_ecc",
        "legalization_dreamplace",
        "route_ecc",
        "drc_final_ecc",
        "drc_ecc",
        "filler_ecc",
        "home",
    ):
        if marker in parts:
            return str(Path(*parts[parts.index(marker) :]))
    return text


def _source_artifact_id(value: Any) -> str:
    return _stable_id("artifact", _workspace_relative_artifact_path(value))


def _attribution_seed_ids(
    rows: Iterable[dict[str, Any]], *, native_type: str | None = None
) -> list[str]:
    return sorted(
        {
            str(row["violation_id"])
            for row in rows
            if row.get("availability") == "available"
            and (native_type is None or str(row.get("native_type") or "").casefold() == native_type)
        }
    )[:_ATTRIBUTION_SEED_ID_LIMIT]


def _attribution_profile_input(
    availability: str,
    profile_id: str,
    seed_ids: list[str],
) -> dict[str, Any]:
    return {
        "availability": availability,
        "rule_version": _ATTRIBUTION_RULE_VERSIONS[profile_id],
        "seed_ids": seed_ids,
    }


def _attribution_profile_inputs(
    *,
    drc_wire_available: bool,
    d2_available: bool,
    c1_available: bool,
    seed_ids: list[str],
    short_seed_ids: list[str],
    r3_seed_ids: list[str],
) -> dict[str, dict[str, Any]]:
    availability = "available" if drc_wire_available else "missing"
    d2_status = "available" if d2_available else "missing"
    c1_status = "available" if c1_available else "missing"
    return {
        "C1": _attribution_profile_input(c1_status, "C1", []),
        "R1": _attribution_profile_input(availability, "R1", seed_ids),
        "R3": _attribution_profile_input(
            "available" if r3_seed_ids else "missing", "R3", r3_seed_ids
        ),
        "D1": _attribution_profile_input(availability, "D1", short_seed_ids),
        "D2": _attribution_profile_input(d2_status, "D2", seed_ids if d2_available else []),
    }


def _instance_row_ref_rows(
    instance_rows: Iterable[dict[str, Any]],
    placement_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_stage: dict[str, list[dict[str, Any]]] = {}
    for row in placement_rows:
        rows_by_stage.setdefault(str(row["stage_name"]), []).append(row)
    refs = []
    for instance in instance_rows:
        for row in rows_by_stage.get(str(instance["stage_name"]), []):
            if not _instance_origin_in_placement_row(instance, row):
                continue
            refs.append(
                {
                    "design_id": instance["design_id"],
                    "run_id": instance["run_id"],
                    "stage_name": instance["stage_name"],
                    "instance_key": instance["instance_key"],
                    "row_id": row["row_id"],
                    "relation": "origin_on_row_lattice",
                    "availability": "available",
                }
            )
    return refs


def _instance_origin_in_placement_row(instance: dict[str, Any], row: dict[str, Any]) -> bool:
    x = instance.get("origin_x")
    y = instance.get("origin_y")
    if x is None or y is None:
        return False
    return _lattice_contains(
        float(x), float(row["origin_x"]), int(row["count_x"]), float(row["step_x"])
    ) and _lattice_contains(
        float(y), float(row["origin_y"]), int(row["count_y"]), float(row["step_y"])
    )


def _lattice_contains(value: float, origin: float, count: int, step: float) -> bool:
    if count <= 0 or step <= 0:
        return False
    offset = (value - origin) / step
    return 0 <= offset < count and abs(offset - round(offset)) < 1e-6


def _metric_artifact_relative_path(stage_name: str, metric_name: str) -> str:
    directory = _stage_directory_name(stage_name)
    if metric_name == "features":
        return f"{directory}/feature"
    return f"{directory}/analysis/{metric_name}"


def _stage_directory_name(stage_name: str) -> str:
    mapping = {
        "Synthesis": "Synthesis_yosys",
        "Floorplan": "Floorplan_ecc",
        "fixFanout": "fixFanout_ecc",
        "place": "place_dreamplace",
        "CTS": "CTS_ecc",
        "legalization": "legalization_dreamplace",
        "route": "route_ecc",
        "drc": "drc_ecc",
        "drc_final": "drc_final_ecc",
        "filler": "filler_ecc",
    }
    return mapping.get(stage_name, stage_name)


def _provenance_target_key(row: dict[str, Any]) -> str:
    preferred = [
        "design_id",
        "run_id",
        "stage_name",
        "patch_id",
        "entity_type",
        "entity_key",
        "net_key",
        "pin_key",
        "instance_key",
        "wire_segment_key",
        "path_id",
        "metric_name",
        "category",
        "channel",
        "block_name",
    ]
    return json_value(
        {key: row.get(key) for key in preferred if key in row and row.get(key) is not None}
    )


def _semantic_block_source_doc(entity_type: str) -> str:
    return {
        "patch": "vec_patches.md",
        "instance": "vec_instance.md",
        "pin": "vec_pins.md",
        "net": "vec_nets.md",
        "wire_segment": "vec_wires.md",
        "routing_graph": "vec_routing_graph.md",
        "timing_path": "vec_timing_paths.md",
    }.get(entity_type, "legacy_foundation_schema.md")


def _semantic_block_landing(entity_type: str, block_name: str) -> dict[str, str]:
    if block_name == "source_refs":
        return {
            "normalized_status": "side_table",
            "target_table": "provenance",
            "target_key": "entity scoped provenance_id",
            "future_normalization_plan": (
                "Keep detailed source refs in provenance/artifacts; migrate residual "
                "source-specific fields into field-level provenance rows."
            ),
        }
    if block_name == "progressive_metadata":
        return {
            "normalized_status": "side_table",
            "target_table": "stage_deltas",
            "target_key": "entity scoped delta rows",
            "future_normalization_plan": (
                "Expand high-value movement, geometry, connectivity and timing deltas "
                "into scalar stage_deltas metrics."
            ),
        }
    return {
        "normalized_status": "preserved_only",
        "target_table": "semantic_blocks",
        "target_key": f"{entity_type}:{block_name}",
        "future_normalization_plan": (
            "Normalize recurring null/availability reasons into provenance and quality "
            "summaries after migration audit."
        ),
    }


def _semantic_block_payload(
    payload: Any, entity_type: str, block_name: str, stage_name: str
) -> Any:
    if block_name != "source_refs":
        return payload
    rewritten = _rewrite_legacy_refs(payload, entity_type, stage_name)
    if isinstance(rewritten, dict):
        return {**rewritten, "semantic_entity_type": entity_type}
    return rewritten


def _rewrite_legacy_refs(value: Any, entity_type: str, stage_name: str) -> Any:
    table_map = {
        "patches": "run_stage_patch_features",
        "instances": "instance_stage_state",
        "pins": "pin_stage_state",
        "nets": "net_terminals",
        "wires": "wire_segments",
        "timing_paths": "timing_paths",
        "routing_graph": "routing_vertices/routing_edges",
        "density_maps": "run_stage_patch_maps:category=density",
        "rudy_maps": "run_stage_patch_maps:category=rudy",
        "egr_maps": "run_stage_patch_maps:category=congestion",
        "maps": "run_stage_patch_maps",
        "tech_layer": "tech_layers",
        "tech_via": "tech_vias",
    }
    if isinstance(value, str):
        if any(token in value for token in ("vectors/", "maps/", "labels/")):
            return {
                "table": table_map.get(entity_type, "table_index"),
                "query": {"stage_name": stage_name},
                "legacy_ref_replaced": True,
                "legacy_ref_hash": _stable_digest((value,))[:16],
            }
        return value
    if isinstance(value, list):
        return [_rewrite_legacy_refs(item, entity_type, stage_name) for item in value]
    if isinstance(value, dict):
        return {
            key: _rewrite_legacy_refs(item, str(key), stage_name) for key, item in value.items()
        }
    return value


def _overall_status(stages: list[StageInfo]) -> str:
    if not stages:
        return "unknown"
    states = {stage.state for stage in stages}
    return "Success" if states == {"Success"} else ",".join(sorted(states))


def _patch_id_from_record(record: dict[str, Any]) -> int:
    for value in (
        record.get("id"),
        record.get("patch_id"),
        (record.get("identity") or {}).get("patch_id"),
    ):
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    patch_key = str(record.get("patch_key") or "")
    if patch_key.startswith("patch:"):
        try:
            return int(patch_key.split(":", 1)[1])
        except (TypeError, ValueError):
            return 0
    return 0


def _matrix_value(matrix: list[list[float]] | None, row: int, col: int) -> float | None:
    if not matrix or row >= len(matrix) or not matrix[row] or col >= len(matrix[row]):
        return None
    return float(matrix[row][col])


def _value_from_named_map(
    maps: dict[str, list[list[float]]], token: str, row: int, col: int
) -> float | None:
    for name, matrix in maps.items():
        if token in name:
            return _matrix_value(matrix, row, col)
    return None


def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    return list(_iter_jsonl_records(path))


def _iter_jsonl_records(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _read_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _null_reason_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for key, value in (record.get("null_reason") or {}).items():
            reason = f"{key}={value}"
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _block_availability_counts(records: list[dict[str, Any]], block_name: str) -> dict[str, int]:
    counts = {"available": 0, "missing": 0, "not_applicable": 0}
    for record in records:
        availability = record.get(block_name, {}).get("availability")
        if availability not in counts:
            availability = "available" if availability is None else str(availability)
            counts.setdefault(availability, 0)
        counts[availability] += 1
    return counts


def _pre_route_availability_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"available": 0, "missing": 0, "not_applicable": 0}
    estimator_fields = (
        "rudy_horizontal",
        "rudy_vertical",
        "rudy_union",
        "egr_overflow_horizontal",
        "egr_overflow_vertical",
        "egr_overflow_union",
        "margin_horizontal",
        "margin_vertical",
    )
    for record in records:
        estimators = record.get("pre_route_estimators", {})
        if estimators.get("available_for_training_input") is False:
            counts["not_applicable"] += 1
        elif any(estimators.get(field) is not None for field in estimator_fields):
            counts["available"] += 1
        else:
            counts["missing"] += 1
    return counts


def _drc_for_patch(drc_report: dict[str, Any] | None, bbox: dict[str, Any]) -> dict[str, Any]:
    if not drc_report or not drc_report.get("available"):
        return {
            "count": None,
            "by_type": {},
            "by_layer": {},
            "unlocalized_count": None,
            "availability": "missing",
        }
    violations = drc_report.get("violations", [])
    if not violations:
        total = int(drc_report.get("count") or 0)
        return {
            "count": 0 if total == 0 else None,
            "by_type": {},
            "by_layer": {},
            "unlocalized_count": total or 0,
        }
    count = 0
    by_type: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    unlocalized = 0
    for violation in violations:
        amount = int(violation.get("count") or 1)
        violation_bbox = violation.get("bbox")
        if not violation_bbox:
            unlocalized += amount
            continue
        if not _bbox_intersects_bbox(violation_bbox, bbox):
            continue
        count += amount
        violation_type = str(violation.get("type") or "unknown")
        by_type[violation_type] = by_type.get(violation_type, 0) + amount
        layer = violation.get("layer")
        if layer:
            layer_name = str(layer)
            by_layer[layer_name] = by_layer.get(layer_name, 0) + amount
    return {
        "count": count,
        "by_type": by_type,
        "by_layer": by_layer,
        "unlocalized_count": unlocalized,
    }


def _wire_length_for_patch(wire: dict[str, Any], patch_id: int) -> float:
    for item in wire.get("patch_intersections", []):
        if int(item.get("patch_id", -1)) == patch_id:
            return float(item.get("length") or 0.0)
    geometry = wire.get("geometry", {}) if isinstance(wire.get("geometry"), dict) else {}
    return float(geometry.get("length") or wire.get("length") or 0.0)


def _instance_overlap_area(instances: list[dict[str, Any]], bbox: dict[str, Any]) -> float:
    total = 0.0
    for item in instances:
        item_bbox = item.get("physical_state", {}).get("bbox")
        if isinstance(item_bbox, dict):
            total += _bbox_overlap_area(item_bbox, bbox)
    return total


def _sum_optional(values: Any) -> float | None:
    present = [float(value) for value in values if value is not None]
    return sum(present) if present else None


def _max_optional(values: Any) -> float | None:
    present = [float(value) for value in values if value is not None]
    return max(present) if present else None


def _mean_optional(values: Any) -> float | None:
    present = [float(value) for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _value_from_patch_id(
    canonical_grid: dict, maps: dict[str, list[list[float]]], token: str, patch_id: int
) -> float | None:
    row_col = _patch_row_col(canonical_grid, patch_id)
    return _value_from_named_map(maps, token, row_col[0], row_col[1]) if row_col else None


def _matrix_value_for_patch_id(
    canonical_grid: dict, matrix: list[list[float]] | None, patch_id: int
) -> float | None:
    row_col = _patch_row_col(canonical_grid, patch_id)
    return _matrix_value(matrix, row_col[0], row_col[1]) if row_col else None


def _timing_path_patch_ids(record: dict[str, Any]) -> set[int]:
    out = set()
    spatial = record.get("path_spatial", {}) if isinstance(record.get("path_spatial"), dict) else {}
    out.update(int(item) for item in spatial.get("touched_patch_ids", []) if item is not None)
    for endpoint in (
        record.get("endpoints", {}) if isinstance(record.get("endpoints"), dict) else {}
    ).values():
        if isinstance(endpoint, dict) and endpoint.get("patch_id") is not None:
            out.add(int(endpoint["patch_id"]))
    for key in ("path_points", "wire_path_nodes"):
        for point in record.get(key, []):
            if isinstance(point, dict) and point.get("patch_id") is not None:
                out.add(int(point["patch_id"]))
    return out


def _timing_for_scoped_patch_paths(
    scoped_paths: list[dict[str, Any]], patch_id: int | None = None, stage: str | None = None
) -> dict[str, Any]:
    slacks = [
        float(
            item.get("path_timing", {}).get("slack")
            if isinstance(item.get("path_timing"), dict)
            else item.get("slack")
        )
        for item in scoped_paths
        if (
            item.get("path_timing", {}).get("slack")
            if isinstance(item.get("path_timing"), dict)
            else item.get("slack")
        )
        is not None
    ]
    endpoint_count = sum(
        1
        for item in scoped_paths
        if item.get("endpoints", {}).get("endpoint", {}).get("patch_id") == patch_id
    )
    startpoint_count = sum(
        1
        for item in scoped_paths
        if item.get("endpoints", {}).get("startpoint", {}).get("patch_id") == patch_id
    )
    max_slews = [
        item.get("path_electrical", {}).get("max_slew")
        for item in scoped_paths
        if item.get("path_electrical", {}).get("max_slew") is not None
    ]
    max_caps = [
        max(item.get("path_electrical", {}).get("capacitance_list", []) or [])
        for item in scoped_paths
        if item.get("path_electrical", {}).get("capacitance_list")
    ]
    return {
        "feature_role": "stage_qor_context",
        "available_for_training_input": stage != "route",
        "availability": "available" if scoped_paths else "missing",
        "critical_path_count": len(scoped_paths),
        "worst_slack_min": min(slacks) if slacks else None,
        "endpoint_count": endpoint_count,
        "startpoint_count": startpoint_count,
        "max_slew": max(max_slews) if max_slews else None,
        "max_cap": max(max_caps) if max_caps else None,
        "source": f"vectors/timing_paths/{stage}.jsonl" if stage else None,
    }


def _electrical_for_scoped_patch_paths(
    scoped_paths: list[dict[str, Any]], patch_id: int | None = None, stage: str | None = None
) -> dict[str, Any]:
    caps: list[float] = []
    slews: list[float] = []
    resistances: list[float] = []
    incrs: list[float] = []
    for path in scoped_paths:
        electrical = path.get("path_electrical", {})
        if not isinstance(electrical, dict):
            continue
        caps.extend(
            float(value) for value in electrical.get("capacitance_list", []) if value is not None
        )
        slews.extend(float(value) for value in electrical.get("slew_list", []) if value is not None)
        resistances.extend(
            float(value) for value in electrical.get("resistance_list", []) if value is not None
        )
        incrs.extend(
            float(value) for value in electrical.get("incr_delay_list", []) if value is not None
        )
    return {
        "feature_role": "stage_qor_context",
        "available_for_training_input": stage != "route",
        "availability": "available" if caps or slews or resistances or incrs else "missing",
        "capacitance_sum": sum(caps) if caps else None,
        "resistance_sum": sum(resistances) if resistances else None,
        "incr_delay_sum": sum(incrs) if incrs else None,
        "max_slew": max(slews) if slews else None,
        "scope": "patch" if patch_id is not None else "stage",
        "source": f"vectors/timing_paths/{stage}.jsonl" if stage else None,
    }


def _timing_for_patch(
    timing_paths: list[dict[str, Any]], patch_id: int | None = None, stage: str | None = None
) -> dict[str, Any]:
    scoped_paths = (
        timing_paths
        if patch_id is None
        else [item for item in timing_paths if patch_id in _timing_path_patch_ids(item)]
    )
    return _timing_for_scoped_patch_paths(scoped_paths, patch_id, stage)


def _electrical_for_patch(
    timing_paths: list[dict[str, Any]], patch_id: int | None = None, stage: str | None = None
) -> dict[str, Any]:
    scoped_paths = (
        timing_paths
        if patch_id is None
        else [item for item in timing_paths if patch_id in _timing_path_patch_ids(item)]
    )
    return _electrical_for_scoped_patch_paths(scoped_paths, patch_id, stage)


def _timing_electrical_contexts_by_patch(
    timing_paths: list[dict[str, Any]], *, stage: str | None
) -> dict[int, tuple[dict[str, Any], dict[str, Any]]]:
    by_patch: dict[int, list[dict[str, Any]]] = {}
    for path in timing_paths:
        for patch_id in _timing_path_patch_ids(path):
            by_patch.setdefault(int(patch_id), []).append(path)
    return {
        patch_id: (
            _timing_for_scoped_patch_paths(paths, patch_id, stage),
            _electrical_for_scoped_patch_paths(paths, patch_id, stage),
        )
        for patch_id, paths in by_patch.items()
    }


def _route_native_demand_capacity_oracle(label: dict[str, Any]) -> dict[str, Any]:
    h_demand_capacity = label.get("horizontal")
    v_demand_capacity = label.get("vertical")
    h_util = label.get("horizontal_utilization")
    v_util = label.get("vertical_utilization")
    union_demand_capacity = _max_optional([h_demand_capacity, v_demand_capacity])
    union_utilization = _max_optional([h_util, v_util])
    return {
        "horizontal_demand": label.get("horizontal_demand"),
        "horizontal_capacity": label.get("horizontal_capacity"),
        "horizontal_demand_capacity": h_demand_capacity,
        "horizontal_utilization": h_util,
        "vertical_demand": label.get("vertical_demand"),
        "vertical_capacity": label.get("vertical_capacity"),
        "vertical_demand_capacity": v_demand_capacity,
        "vertical_utilization": v_util,
        "union_demand_capacity": union_demand_capacity,
        "union_utilization": union_utilization,
        "tightness_class": _tightness_class(union_demand_capacity, union_utilization),
    }


def _tightness_class(union_demand_capacity: Any, union_utilization: Any) -> str:
    if union_demand_capacity is None and union_utilization is None:
        return "unknown"
    if union_demand_capacity is not None and float(union_demand_capacity) > 0:
        return "over_capacity"
    if union_utilization is not None and float(union_utilization) >= 0.9:
        return "near_capacity"
    return "relaxed"


def _patch_null_reason(
    stage: str,
    density_maps: dict[str, MapMatrix],
    rudy_maps: dict[str, MapMatrix],
    congestion_maps: dict[str, MapMatrix],
    timing_context: dict[str, Any],
    electrical_context: dict[str, Any],
    route_oracle: dict[str, Any] | None,
    native_demand_capacity: dict[str, Any],
    drc_context: dict[str, Any],
) -> dict[str, str]:
    out: dict[str, str] = {}
    if not density_maps:
        out["local_density"] = "missing_density_maps"
    if not rudy_maps and not congestion_maps:
        out["pre_route_estimators"] = (
            "missing_pre_route_maps" if stage != "route" else "not_applicable_for_stage"
        )
    if timing_context.get("availability") == "missing":
        out["timing_context"] = "missing_sta_artifacts"
    if electrical_context.get("availability") == "missing":
        out["electrical_context"] = "missing_electrical_artifacts"
    if stage != "route":
        out["route_oracle"] = "not_route_stage"
    elif route_oracle is not None and not native_demand_capacity:
        out["route_oracle"] = "missing_router_native_route_demand_capacity_artifact"
    if drc_context.get("availability") == "missing":
        out["drc_context"] = "missing_drc_artifacts"
    return out


def _bbox_intersects_bbox(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return not (
        float(a["urx"]) < float(b["llx"])
        or float(a["llx"]) > float(b["urx"])
        or float(a["ury"]) < float(b["lly"])
        or float(a["lly"]) > float(b["ury"])
    )


def _demand_capacity_label(label: dict[str, Any]) -> dict[str, Any]:
    h_demand = label.get("horizontal_demand")
    v_demand = label.get("vertical_demand")
    h_capacity = label.get("horizontal_capacity")
    v_capacity = label.get("vertical_capacity")
    return {
        "horizontal": label.get("horizontal_demand_capacity"),
        "vertical": label.get("vertical_demand_capacity"),
        "union": label.get("union_demand_capacity"),
        "horizontal_demand": h_demand,
        "vertical_demand": v_demand,
        "horizontal_capacity": h_capacity,
        "vertical_capacity": v_capacity,
        "horizontal_utilization": label.get("horizontal_utilization"),
        "vertical_utilization": label.get("vertical_utilization"),
        "source": label.get("source"),
    }


def _extract_ppa_metric_values(payload: dict[str, Any]) -> dict[str, Any]:
    ppa_tokens = (
        "wns",
        "tns",
        "frequency",
        "area",
        "wire_length",
        "wirelength",
        "via",
        "drc",
        "buffer",
        "util",
        "power",
        "slack",
    )
    blocked_tokens = ("path", "source", "map", "distribution", "creator", "invocation")
    out: dict[str, Any] = {}
    for key, value in payload.items():
        lower = str(key).lower()
        if any(token in lower for token in blocked_tokens):
            continue
        if any(token in lower for token in ppa_tokens) and isinstance(
            value, str | int | float | bool | type(None)
        ):
            out[str(key)] = value
    return out


def _extract_route_ppa_metrics(features: Any) -> dict[str, Any]:
    if not isinstance(features, dict):
        return {}
    route_step = features.get("route.step.json")
    if not isinstance(route_step, dict):
        return {}
    route_payload = route_step.get("route")
    if not isinstance(route_payload, dict):
        return {}
    dr_iters = route_payload.get("DR")
    if not isinstance(dr_iters, list) or not dr_iters or not isinstance(dr_iters[-1], dict):
        return {}
    last_iter = dr_iters[-1]
    return {
        "route_wire_length": last_iter.get("total_wire_length"),
        "route_via_count": last_iter.get("total_via_num"),
        "route_violation_count": last_iter.get("total_violation_num"),
    }


def _strip_empty_info(flow: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(flow))
    steps = normalized.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and step.get("info") == {}:
                step.pop("info", None)
    return normalized


def _summary_flow(flow: dict[str, Any], stages: list[StageInfo]) -> dict[str, Any]:
    normalized = _strip_empty_info(flow)
    steps = normalized.get("steps")
    if isinstance(steps, list):
        by_name = {step.get("name"): step for step in steps if isinstance(step, dict)}
        normalized["steps"] = [by_name[stage.name] for stage in stages if stage.name in by_name]
    return normalized


def _top_patch_view_items(
    vector_records: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    rows = list(vector_records.get("patches", {}).get("route") or [])
    if not rows:
        for stage_name in sorted(vector_records.get("patches", {})):
            rows = list(vector_records.get("patches", {}).get(stage_name) or [])
            if rows:
                break
    items = []
    for record in rows:
        patch_id = _patch_id_from_record(record)
        oracle = record.get("route_oracle") or {}
        native = oracle.get("native_demand_capacity") if isinstance(oracle, dict) else {}
        drc = record.get("drc_context") if isinstance(record.get("drc_context"), dict) else {}
        timing = (
            record.get("timing_context") if isinstance(record.get("timing_context"), dict) else {}
        )
        density = (
            record.get("local_density") if isinstance(record.get("local_density"), dict) else {}
        )
        score = _first_numeric(
            native.get("union_demand_capacity") if isinstance(native, dict) else None,
            drc.get("count"),
            _negative_or_none(timing.get("worst_slack_min")),
            density.get("cell_density"),
        )
        if score is None:
            continue
        items.append(
            {
                "patch_id": patch_id,
                "stage": record.get("stage"),
                "table": "run_stage_patch_features",
                "query": {"patch_id": patch_id},
                "label_table": "run_patch_route_labels",
                "score": score,
                "score_source": "route_native_union_demand_capacity"
                if isinstance(native, dict) and native.get("union_demand_capacity") is not None
                else "fallback_qor_or_density",
                "provenance": {
                    "table": "provenance",
                    "query": {
                        "provenance_id": _stable_id(
                            "patch_features", record.get("stage"), record.get("patch_key")
                        )
                    },
                },
            }
        )
    return sorted(items, key=lambda item: (item["score"] is not None, item["score"]), reverse=True)[
        :20
    ]


def _top_net_view_items(
    vector_records: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    rows = list(vector_records.get("nets", {}).get("route") or [])
    if not rows:
        for stage_name in sorted(vector_records.get("nets", {})):
            rows = list(vector_records.get("nets", {}).get(stage_name) or [])
            if rows:
                break
    items = []
    for record in rows:
        net_key = str(record.get("net_key") or (record.get("identity") or {}).get("net_key"))
        summary = record.get("connectivity_summary") or {}
        route = record.get("route_analysis") or {}
        fanout = _to_float(summary.get("fanout")) or 0.0
        route_wire_length = _to_float(route.get("total_routed_length"))
        score = _first_numeric(route_wire_length, fanout)
        items.append(
            {
                "net_key": net_key,
                "stage": record.get("stage"),
                "table": "nets",
                "query": {"entity_key": net_key},
                "fanout": summary.get("fanout"),
                "route_wire_length": route.get("total_routed_length"),
                "score": score,
                "score_source": "route_wire_length" if route_wire_length is not None else "fanout",
                "provenance": {
                    "table": "provenance",
                    "query": {
                        "provenance_id": _stable_id(
                            "semantic_block", record.get("stage"), "net", net_key, "source_refs"
                        )
                    },
                },
            }
        )
    return sorted(items, key=lambda item: (item["score"] is not None, item["score"]), reverse=True)[
        :20
    ]


def _first_numeric(*values: Any) -> float | None:
    for value in values:
        numeric = _to_float(value)
        if numeric is not None:
            return numeric
    return None


def _negative_or_none(value: Any) -> float | None:
    numeric = _to_float(value)
    return -numeric if numeric is not None else None


def _summary_stages(summary: dict[str, Any]) -> list[dict[str, Any]]:
    steps = summary.get("flow", {}).get("steps", [])
    if not isinstance(steps, list):
        return []
    stages = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        stages.append({key: step.get(key) for key in ("name", "tool", "state") if key in step})
    return stages


def _scale_bbox(bbox: dict[str, float] | None, scale: float) -> dict[str, float] | None:
    if bbox is None:
        return None
    return {key: float(value) * scale for key, value in bbox.items()}


def _def_unit_scale(parsed_def: DefData) -> float:
    return 1.0 / float(parsed_def.units) if parsed_def.units else 1.0


def _get_nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = __import__("re").search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _runtime_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if ":" not in text:
        return _to_float(text)
    parts = text.split(":")
    if len(parts) > 3:
        return None
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None
    seconds = 0.0
    for part in values:
        seconds = seconds * 60 + part
    return seconds


def _stage_flow_step_by_name(flow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name")): item
        for item in flow.get("steps", [])
        if isinstance(item, dict) and item.get("name")
    }


def _point_in_bbox(x: Any, y: Any, bbox: dict[str, Any]) -> bool:
    if x is None or y is None:
        return False
    xf = float(x)
    yf = float(y)
    return float(bbox["llx"]) <= xf <= float(bbox["urx"]) and float(bbox["lly"]) <= yf <= float(
        bbox["ury"]
    )


def _ordered_timing_path_record(record: dict[str, Any], record_id: int) -> dict[str, Any]:
    return {
        "id": record_id,
        "stage": record["stage"],
        "path_key": record["path_key"],
        "source": record["source"],
        "identity": record["identity"],
        "analysis_context": record["analysis_context"],
        "endpoints": record["endpoints"],
        "path_timing": record["path_timing"],
        "path_electrical": record["path_electrical"],
        "path_points": record["path_points"],
        "timing_edges": record["timing_edges"],
        "wire_path_nodes": record["wire_path_nodes"],
        "path_spatial": record["path_spatial"],
        "progressive_metadata": record["progressive_metadata"],
        "coverage": record["coverage"],
        "source_refs": record["source_refs"],
        "null_reason": record["null_reason"],
    }


def _timing_path_key(stage: str, record: dict[str, Any]) -> str:
    delay_type = str(record.get("analysis_context", {}).get("delay_type") or "unknown")
    rank = int(record.get("path_timing", {}).get("rank_in_stage") or 0)
    endpoint = (
        record.get("identity", {}).get("endpoint_key")
        or record.get("endpoints", {}).get("endpoint", {}).get("raw_name")
        or "unknown_endpoint"
    )
    return f"{stage}|{delay_type}|rank{rank}|{endpoint}"


def _enrich_timing_path_record(
    record: dict[str, Any],
    instance_by_key: dict[str, dict[str, Any]],
    pin_by_key: dict[str, dict[str, Any]],
    net_by_pin_pair: dict[frozenset[str], dict[str, Any]],
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
) -> dict[str, Any]:
    for endpoint in record.get("endpoints", {}).values():
        if isinstance(endpoint, dict):
            _enrich_timing_point(endpoint, instance_by_key, pin_by_key)
    for point in record.get("path_points", []):
        if isinstance(point, dict):
            _enrich_timing_point(point, instance_by_key, pin_by_key)
    for node in record.get("wire_path_nodes", []):
        if isinstance(node, dict):
            _enrich_timing_point(node, instance_by_key, pin_by_key)
    points_by_id = {
        point.get("point_id"): point
        for point in record.get("path_points", [])
        if isinstance(point, dict)
    }
    for edge in record.get("timing_edges", []):
        if isinstance(edge, dict):
            _enrich_timing_edge(edge, points_by_id, net_by_pin_pair)
    record["path_spatial"] = _timing_path_spatial(
        record.get("path_points", []), canonical_grid, stage_maps
    )
    record["coverage"] = _timing_path_coverage(record)
    _update_timing_path_null_reasons(record, stage_maps)
    return record


def _enrich_timing_point(
    point: dict[str, Any],
    instance_by_key: dict[str, dict[str, Any]],
    pin_by_key: dict[str, dict[str, Any]],
) -> None:
    pin_key = point.get("pin_key")
    pin = pin_by_key.get(str(pin_key)) if pin_key else None
    if isinstance(pin, dict):
        point["pin_join_status"] = "joined"
        identity = pin.get("identity", {})
        if not point.get("instance_key"):
            point["instance_key"] = identity.get("parent_instance_key")
        if not point.get("instance_name"):
            point["instance_name"] = identity.get("instance")
        if not point.get("pin_name"):
            point["pin_name"] = identity.get("pin_name")
        point["net_key"] = identity.get("net_key")
        geometry = pin.get("geometry", {}) if isinstance(pin.get("geometry"), dict) else {}
        point["center"] = geometry.get("center")
        point["patch_id"] = geometry.get("patch_id")
        anchor_source = pin.get("patch_anchor", {}).get("anchor_source")
        point["spatial_anchor_source"] = (
            anchor_source
            if anchor_source in {"exact_pin_geometry", "parent_instance_anchor"}
            else "missing"
        )
        return
    instance_key = point.get("instance_key")
    inst = instance_by_key.get(str(instance_key)) if instance_key else None
    if isinstance(inst, dict):
        point["pin_join_status"] = "missing_pin_fallback_instance"
        physical = (
            inst.get("physical_state", {}) if isinstance(inst.get("physical_state"), dict) else {}
        )
        point["center"] = physical.get("center")
        point["patch_id"] = physical.get("patch_id")
        point["spatial_anchor_source"] = (
            "parent_instance_anchor" if physical.get("center") else "missing"
        )
        return
    point["pin_join_status"] = "missing"
    point["center"] = None
    point["patch_id"] = None
    point["spatial_anchor_source"] = "missing"


def _enrich_timing_edge(
    edge: dict[str, Any],
    points_by_id: dict[Any, dict[str, Any]],
    net_by_pin_pair: dict[frozenset[str], dict[str, Any]],
) -> None:
    from_pin = edge.get("from_pin_key")
    to_pin = edge.get("to_pin_key")
    lookup = (
        net_by_pin_pair.get(frozenset([str(from_pin), str(to_pin)]))
        if from_pin and to_pin
        else None
    )
    if lookup:
        edge["net_name"] = lookup.get("net_name")
        edge["net_key"] = lookup.get("net_key")
        edge["net_degree"] = lookup.get("net_degree")
        edge["net_hpwl"] = lookup.get("net_hpwl")
        edge["net_cross_patch"] = lookup.get("net_cross_patch")
        edge["net_join_status"] = "joined"
    elif edge.get("edge_kind") == "net_arc":
        edge["net_join_status"] = "missing"
    from_point = points_by_id.get(edge.get("from_point_id"), {})
    to_point = points_by_id.get(edge.get("to_point_id"), {})
    if edge.get("edge_kind") == "cell_arc" and str(from_point.get("instance_key") or "") == str(
        to_point.get("instance_key") or ""
    ):
        pair_lookup = (
            net_by_pin_pair.get(frozenset([str(from_pin), str(to_pin)]))
            if from_pin and to_pin
            else None
        )
        if pair_lookup:
            edge["net_name"] = pair_lookup.get("net_name")
            edge["net_key"] = pair_lookup.get("net_key")
            edge["net_degree"] = pair_lookup.get("net_degree")
            edge["net_hpwl"] = pair_lookup.get("net_hpwl")
            edge["net_cross_patch"] = pair_lookup.get("net_cross_patch")
            edge["net_join_status"] = "joined"


def _net_lookup_by_pin_pair(parsed_def: DefData | None) -> dict[frozenset[str], dict[str, Any]]:
    if parsed_def is None:
        return {}
    out: dict[frozenset[str], dict[str, Any]] = {}
    for net in parsed_def.nets:
        pin_keys = [_pin_key(pin) for pin in net.pins]
        summary = {
            "net_name": net.name,
            "net_key": net.name,
            "net_degree": len(pin_keys),
            "net_hpwl": None,
            "net_cross_patch": None,
        }
        for left in pin_keys:
            for right in pin_keys:
                if left != right:
                    out[frozenset([left, right])] = summary
    return out


def _timing_path_spatial(
    points: list[dict[str, Any]], canonical_grid: dict, stage_maps: dict[str, dict[str, MapMatrix]]
) -> dict[str, Any]:
    patch_ids = []
    centers = []
    counts = {"exact_pin_geometry": 0, "parent_instance_anchor": 0, "missing": 0}
    for point in points:
        source = point.get("spatial_anchor_source") or "missing"
        if source not in counts:
            source = "missing"
        counts[source] += 1
        if isinstance(point.get("center"), dict):
            centers.append(point["center"])
        if point.get("patch_id") is not None:
            patch_ids.append(int(point["patch_id"]))
    unique_patch_ids = sorted(set(patch_ids))
    patches = canonical_grid.get("patches", []) if isinstance(canonical_grid, dict) else []
    patch_by_id = {int(patch["patch_id"]): patch for patch in patches if "patch_id" in patch}
    return {
        "anchor_source_policy": "prefer_pin_geometry_fallback_parent_instance",
        "start_patch_id": patch_ids[0] if patch_ids else None,
        "end_patch_id": patch_ids[-1] if patch_ids else None,
        "touched_patch_ids": unique_patch_ids,
        "patch_count": len(unique_patch_ids),
        "cross_patch_count": max(0, len(unique_patch_ids) - 1),
        "path_bbox": _bbox_from_points(centers),
        "anchor_source_counts": counts,
        "has_missing_spatial_anchor": counts["missing"] > 0,
        "stage_map_summary": {
            "cell_density": _matrix_stats_for_patch_ids(
                stage_maps.get("density", {}).get("allcell_density"), unique_patch_ids, patch_by_id
            ),
            "pin_density": _matrix_stats_for_patch_ids(
                stage_maps.get("density", {}).get("allcell_pin_density"),
                unique_patch_ids,
                patch_by_id,
            ),
            "rudy": _matrix_stats_for_patch_ids(
                stage_maps.get("rudy", {}).get("rudy_union"), unique_patch_ids, patch_by_id
            ),
            "egr_overflow": _matrix_stats_for_patch_ids(
                stage_maps.get("congestion", {}).get("union"), unique_patch_ids, patch_by_id
            ),
        },
    }


def _matrix_stats_for_patch_ids(
    matrix: MapMatrix | None, patch_ids: list[int], patch_by_id: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    values = []
    for patch_id in patch_ids:
        patch = patch_by_id.get(patch_id)
        if not patch:
            continue
        value = _matrix_value(matrix, int(patch["row"]), int(patch["col"]))
        if value is not None:
            values.append(float(value))
    return {
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "avg": sum(values) / len(values) if values else None,
        "count": len(values),
    }


def _timing_path_coverage(record: dict[str, Any]) -> dict[str, Any]:
    points = record.get("path_points", [])
    edges = record.get("timing_edges", [])
    wire_nodes = record.get("wire_path_nodes", [])
    return {
        "point_count": len(points),
        "parsed_point_count": sum(1 for point in points if point.get("parse_status") == "parsed"),
        "pin_join_count": sum(1 for point in points if point.get("pin_join_status") == "joined"),
        "edge_count": len(edges),
        "net_join_count": sum(1 for edge in edges if edge.get("net_join_status") == "joined"),
        "wire_node_count": len(wire_nodes),
        "matched_wire_node_count": sum(
            1 for node in wire_nodes if node.get("matched_point_id") is not None
        ),
        "spatial_anchor_count": sum(1 for point in points if isinstance(point.get("center"), dict)),
        "missing_spatial_anchor_count": sum(
            1 for point in points if not isinstance(point.get("center"), dict)
        ),
        "has_complete_endpoint_join": all(
            record.get("endpoints", {}).get(key, {}).get("pin_join_status") == "joined"
            for key in ("startpoint", "endpoint")
        ),
        "has_wire_path": bool(wire_nodes),
        "coverage_notes": [],
    }


def _update_timing_path_null_reasons(
    record: dict[str, Any], stage_maps: dict[str, dict[str, MapMatrix]]
) -> None:
    null_reason = record.setdefault("null_reason", {})
    path_spatial_reason = null_reason.setdefault("path_spatial", {})
    spatial = record.get("path_spatial", {}) if isinstance(record.get("path_spatial"), dict) else {}
    if spatial.get("has_missing_spatial_anchor"):
        path_spatial_reason["spatial_anchor"] = "missing_spatial_anchor"
    summaries = (
        spatial.get("stage_map_summary", {})
        if isinstance(spatial.get("stage_map_summary"), dict)
        else {}
    )
    if summaries and all(
        isinstance(summary, dict) and int(summary.get("count") or 0) == 0
        for summary in summaries.values()
    ):
        has_stage_maps = any(
            stage_maps.get(category) for category in ("density", "rudy", "congestion")
        )
        if not has_stage_maps:
            path_spatial_reason["stage_map_summary"] = "missing_stage_maps"
        elif spatial.get("patch_count", 0) == 0 and spatial.get("has_missing_spatial_anchor"):
            path_spatial_reason["stage_map_summary"] = "missing_spatial_anchor"
        elif spatial.get("patch_count", 0) > 0:
            path_spatial_reason["stage_map_summary"] = "missing_stage_maps"


def _attach_timing_progressive_metadata(
    stage_name: str, records: list[dict[str, Any]], timing_dir: Path
) -> None:
    stage_order = [
        "Synthesis",
        "Floorplan",
        "fixFanout",
        "place",
        "CTS",
        "legalization",
        "route",
        "drc",
        "filler",
    ]
    previous_stage = None
    if stage_name in stage_order:
        idx = stage_order.index(stage_name)
        for candidate in reversed(stage_order[:idx]):
            if (timing_dir / f"{candidate}.jsonl").exists():
                previous_stage = candidate
                break
    prev_by_endpoint: dict[str, dict[str, Any]] = {}
    if previous_stage:
        for item in _iter_jsonl_records(timing_dir / f"{previous_stage}.jsonl"):
            endpoint = item.get("identity", {}).get("endpoint_key")
            if endpoint and endpoint not in prev_by_endpoint:
                prev_by_endpoint[endpoint] = item
    for record in records:
        endpoint = record.get("identity", {}).get("endpoint_key")
        prev = prev_by_endpoint.get(endpoint) if endpoint else None
        current_timing = record.get("path_timing", {})
        prev_timing = prev.get("path_timing", {}) if isinstance(prev, dict) else {}
        record["progressive_metadata"] = {
            "available_from": stage_name,
            "endpoint_seen_in_prev_stage": prev is not None,
            "exists_in_prev_stage": prev is not None,
            "slack_delta_from_prev_stage": _delta(
                current_timing.get("slack"), prev_timing.get("slack")
            ),
            "delay_delta_from_prev_stage": _delta(
                current_timing.get("path_delay"), prev_timing.get("path_delay")
            ),
            "rank_delta_from_prev_stage": _delta(
                current_timing.get("rank_in_stage"), prev_timing.get("rank_in_stage")
            ),
            "endpoint_best_slack_delta_from_prev_stage": _delta(
                current_timing.get("slack"), prev_timing.get("slack")
            ),
            "tracking_key_source": "endpoint_key",
        }


def _delta(current: Any, previous: Any) -> float | None:
    if current is None or previous is None:
        return None
    return float(current) - float(previous)


def _net_identity(net: DefNet) -> dict[str, Any]:
    use = str(net.use or "UNKNOWN").upper()
    lower = net.name.lower()
    is_pg = (
        use in {"POWER", "GROUND"}
        or lower in {"vdd", "vss", "vcc", "gnd"}
        or any(token in lower for token in ("vdd", "vss", "gnd"))
    )
    is_clock = use == "CLOCK" or _is_clock_like(lower)
    is_reset = "reset" in lower or "rst" in lower
    is_special = bool(net.special or any(wire.special for wire in net.wires))
    if is_pg:
        net_class = "power_ground"
    elif is_clock:
        net_class = "clock"
    elif is_special:
        net_class = "special"
    else:
        net_class = "signal"
    return {
        "net_key": net.name,
        "name": net.name,
        "use": use,
        "net_class": net_class,
        "is_special": is_special,
        "is_clock": is_clock,
        "is_reset": is_reset,
        "is_power_ground": is_pg,
        "is_signal": net_class == "signal",
        "classification_source": "def_use_and_heuristic_name_rule",
    }


def _terminal_refs_for_net(pins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for pin in sorted(pins, key=lambda item: str(item.get("pin_key") or ""))[:256]:
        identity = pin.get("identity", {}) if isinstance(pin.get("identity"), dict) else {}
        parent = (
            pin.get("parent_instance") if isinstance(pin.get("parent_instance"), dict) else None
        )
        connectivity = (
            pin.get("connectivity_context", {})
            if isinstance(pin.get("connectivity_context"), dict)
            else {}
        )
        patch_anchor = (
            pin.get("patch_anchor", {}) if isinstance(pin.get("patch_anchor"), dict) else {}
        )
        geometry = pin.get("geometry", {}) if isinstance(pin.get("geometry"), dict) else {}
        pin_role = connectivity.get("pin_role") or "unknown"
        refs.append(
            {
                "pin_key": pin.get("pin_key"),
                "pin_kind": identity.get("pin_kind"),
                "instance": identity.get("instance"),
                "pin_name": identity.get("pin_name"),
                "full_name": identity.get("full_name"),
                "parent_instance_key": identity.get("parent_instance_key"),
                "parent_master": identity.get("parent_master"),
                "parent_cell_class": parent.get("cell_class") if parent else None,
                "parent_physical_class": parent.get("physical_class") if parent else None,
                "pin_role": pin_role,
                "is_driver": bool(connectivity.get("is_driver")),
                "is_sink": bool(connectivity.get("is_sink")),
                "is_io": bool(identity.get("is_io")),
                "is_macro_pin": bool(identity.get("is_macro_pin")),
                "patch_id": patch_anchor.get("primary_patch_id"),
                "geometry_status": geometry.get("geometry_status"),
                "anchor_source": geometry.get("anchor_source") or patch_anchor.get("anchor_source"),
                "is_on_critical_path": bool(
                    pin.get("timing_context", {}).get("is_on_critical_path")
                ),
                "center": geometry.get("center"),
                "bbox": geometry.get("bbox"),
            }
        )
    return refs


def _anchor_point(ref: dict[str, Any]) -> dict[str, Any] | None:
    center = ref.get("center")
    if isinstance(center, dict):
        return center
    bbox = ref.get("bbox")
    if isinstance(bbox, dict):
        return _bbox_center(bbox)
    return None


def _net_anchor_quality(terminal_refs: list[dict[str, Any]]) -> str:
    statuses = [str(ref.get("geometry_status") or "missing") for ref in terminal_refs]
    if not statuses or all(status == "missing" for status in statuses):
        return "missing"
    exact = sum(1 for status in statuses if status == "exact")
    fallback = sum(1 for status in statuses if status.startswith("fallback"))
    if exact == len(statuses):
        return "all_exact"
    if fallback == len(statuses):
        return "all_fallback"
    if exact or fallback:
        return "mixed_exact_and_fallback"
    return "missing"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _map_values_for_patches(
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
    patch_ids: list[int],
    category: str,
    name: str,
) -> list[float]:
    matrix = stage_maps.get(category, {}).get(name)
    values: list[float] = []
    for patch_id in patch_ids:
        row_col = _patch_row_col(canonical_grid, patch_id)
        if row_col is None:
            continue
        value = _matrix_value(matrix, row_col[0], row_col[1])
        if value is not None:
            values.append(value)
    return values


def _net_patch_anchor(
    terminal_refs: list[dict[str, Any]],
    geometry_proxy: dict[str, Any],
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
) -> dict[str, Any]:
    patch_ids = list(geometry_proxy.get("patch_ids") or [])
    terminal_count_by_patch = {
        str(patch_id): sum(1 for ref in terminal_refs if ref.get("patch_id") == patch_id)
        for patch_id in patch_ids
    }
    primary_patch_id = None
    if patch_ids:
        max_terminal_count = max(terminal_count_by_patch.values(), default=0)
        primary_patch_id = min(
            (
                patch_id
                for patch_id in patch_ids
                if terminal_count_by_patch.get(str(patch_id), 0) == max_terminal_count
            ),
            default=patch_ids[0],
        )
    cell_values = _map_values_for_patches(
        canonical_grid, stage_maps, patch_ids, "density", "allcell_density"
    )
    pin_values = _map_values_for_patches(
        canonical_grid, stage_maps, patch_ids, "density", "allcell_pin_density"
    )
    rudy_values = _map_values_for_patches(
        canonical_grid, stage_maps, patch_ids, "rudy", "rudy_union"
    )
    egr_values = _map_values_for_patches(
        canonical_grid, stage_maps, patch_ids, "congestion", "union"
    )
    return {
        "primary_patch_id": primary_patch_id,
        "patch_ids": patch_ids,
        "patch_span_count": len(patch_ids),
        "anchor_source": "terminal_patch_ids" if patch_ids else "missing_terminal_geometry",
        "local_cell_density_mean": _mean(cell_values),
        "local_pin_density_mean": _mean(pin_values),
        "local_rudy_mean": _mean(rudy_values),
        "local_rudy_max": max(rudy_values) if rudy_values else None,
        "local_egr_overflow_mean": _mean(egr_values),
        "local_egr_overflow_max": max(egr_values) if egr_values else None,
        "terminal_count_by_patch": terminal_count_by_patch,
    }


def _net_timing_context(
    net_name: str,
    terminal_refs: list[dict[str, Any]],
    sta_report: dict[str, Any] | None,
    workspace_dir: Path,
) -> dict[str, Any]:
    records = sta_report.get("records", []) if isinstance(sta_report, dict) else []
    terminal_keys = {str(ref.get("pin_key")) for ref in terminal_refs if ref.get("pin_key")}
    terminal_names = {str(ref.get("full_name")) for ref in terminal_refs if ref.get("full_name")}
    terminal_names.update(str(ref.get("pin_name")) for ref in terminal_refs if ref.get("pin_name"))
    path_refs = []
    slacks: list[float] = []
    arrivals: list[float] = []
    slews: list[float] = []
    caps: list[float] = []
    driver_pin_keys: set[str] = set()
    endpoint_pin_keys: set[str] = set()
    for idx, record in enumerate(records):
        points = [
            item
            for item in [
                *record.get("path_points", []),
                *record.get("wire_path_nodes", []),
            ]
            if isinstance(item, dict)
        ]
        point_keys = {str(item.get("pin_key")) for item in points if item.get("pin_key")}
        point_nets = {str(item.get("net_key")) for item in points if item.get("net_key")}
        point_names = {
            str(item.get("raw_name") or item.get("raw_point") or item.get("pin_name"))
            for item in points
            if item.get("raw_name") or item.get("raw_point") or item.get("pin_name")
        }
        edge_nets = {
            str(edge.get("net_key") or edge.get("net_name"))
            for edge in record.get("timing_edges", [])
            if isinstance(edge, dict) and (edge.get("net_key") or edge.get("net_name"))
        }
        if (
            net_name not in point_nets
            and net_name not in edge_nets
            and not terminal_keys.intersection(point_keys)
            and not terminal_names.intersection(point_names)
        ):
            continue
        timing = (
            record.get("path_timing", {}) if isinstance(record.get("path_timing"), dict) else {}
        )
        slack = _to_float(timing.get("slack"))
        if slack is not None:
            slacks.append(slack)
        path_delay = _to_float(timing.get("path_delay"))
        if path_delay is not None:
            arrivals.append(path_delay)
        electrical = (
            record.get("path_electrical", {})
            if isinstance(record.get("path_electrical"), dict)
            else {}
        )
        caps.extend(
            float(value) for value in electrical.get("capacitance_list", []) if value is not None
        )
        slews.extend(float(value) for value in electrical.get("slew_list", []) if value is not None)
        endpoints = record.get("endpoints", {}) if isinstance(record.get("endpoints"), dict) else {}
        start_key = (
            endpoints.get("startpoint", {}).get("pin_key")
            if isinstance(endpoints.get("startpoint"), dict)
            else None
        )
        endpoint_key = (
            endpoints.get("endpoint", {}).get("pin_key")
            if isinstance(endpoints.get("endpoint"), dict)
            else None
        )
        if start_key and str(start_key) in terminal_keys:
            driver_pin_keys.add(str(start_key))
        if endpoint_key and str(endpoint_key) in terminal_keys:
            endpoint_pin_keys.add(str(endpoint_key))
        path_id = record.get("id", idx)
        path_refs.append({"path_id": path_id, "role": "internal", "slack": slack})
    source = sta_report.get("source") if isinstance(sta_report, dict) else None
    if source:
        try:
            source = str(Path(str(source)).relative_to(workspace_dir))
        except ValueError:
            source = str(source)
    return {
        "available": bool(sta_report and sta_report.get("available")),
        "timing_path_count": len(path_refs),
        "is_on_critical_path": bool(path_refs),
        "worst_slack_seen": min(slacks) if slacks else None,
        "min_arrival": min(arrivals) if arrivals else None,
        "max_arrival": max(arrivals) if arrivals else None,
        "max_slew": max(slews) if slews else None,
        "max_cap": max(caps) if caps else None,
        "driver_pin_keys": sorted(driver_pin_keys),
        "endpoint_pin_count": len(endpoint_pin_keys),
        "path_refs": sorted(
            path_refs,
            key=lambda item: (
                item["slack"] is None,
                item["slack"] if item["slack"] is not None else 0.0,
            ),
        )[:8],
        "source": source,
    }


def _route_analysis_for_net(
    stage: StageInfo,
    parsed_def: DefData,
    net: DefNet,
    route_wires: list[DefWire],
    terminal_hpwl: float | None,
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
    route_label_demand_capacity_by_patch: dict[int, float],
) -> dict[str, Any] | None:
    if stage.name != "route":
        return None
    if len(route_wires) > 100:
        wire_geometries = [_wire_geometry(wire) for wire in route_wires[:1000]]
        wire_bboxes = [
            geometry["bbox"]
            for geometry in wire_geometries
            if isinstance(geometry.get("bbox"), dict)
        ]
        routed_wire_length = sum(wire.length for wire in route_wires)
        return {
            "route_only_oracle": True,
            "routed_wire_count": sum(1 for wire in route_wires if not wire.via),
            "routed_wire_length": routed_wire_length,
            "routed_bbox": _bbox_union(wire_bboxes) if wire_bboxes else None,
            "covered_layers": sorted({wire.layer for wire in route_wires}),
            "via_count": sum(1 for wire in route_wires if wire.via),
            "detour_ratio": routed_wire_length / terminal_hpwl
            if terminal_hpwl and terminal_hpwl > 0
            else None,
            "routed_patch_ids": [],
            "routed_patch_count": None,
            "overlapped_congested_patch_count": None,
            "final_overflow_sum": None,
            "final_overflow_max": None,
            "patch_attribution_refs": [],
            "patch_attribution_ref_count_total": None,
            "patch_attribution_refs_truncated": True,
            "source": _workspace_relative_from_parsed_def(parsed_def),
            "summary_mode": "large_net_skip_patch_attribution",
        }
    wire_geometries = [_wire_geometry(wire) for wire in route_wires]
    wire_bboxes = [
        geometry["bbox"] for geometry in wire_geometries if isinstance(geometry.get("bbox"), dict)
    ]
    routed_bbox = _bbox_union(wire_bboxes) if wire_bboxes else None
    patch_stats: dict[int, dict[str, Any]] = {}
    for wire, geometry in zip(route_wires, wire_geometries, strict=True):
        intersections = _wire_patch_intersections(geometry, canonical_grid)
        for item in intersections:
            patch_id = int(item["patch_id"])
            stat = patch_stats.setdefault(
                patch_id,
                {
                    "patch_id": patch_id,
                    "wire_length_in_patch": 0.0,
                    "via_count_in_patch": 0,
                    "final_overflow": None,
                    "wire_segment_count": 0,
                    "covered_layers": set(),
                },
            )
            stat["wire_length_in_patch"] += float(item.get("length") or 0.0)
            stat["wire_segment_count"] += 1
            stat["covered_layers"].add(wire.layer)
            if wire.via:
                stat["via_count_in_patch"] += 1
    for patch_id, stat in patch_stats.items():
        row_col = _patch_row_col(canonical_grid, patch_id)
        final_overflow = (
            _matrix_value(stage_maps.get("congestion", {}).get("union"), row_col[0], row_col[1])
            if row_col
            else None
        )
        if final_overflow is None:
            final_overflow = route_label_demand_capacity_by_patch.get(patch_id)
        stat["final_overflow"] = final_overflow
        stat["contribution_score"] = stat["wire_length_in_patch"] * max(final_overflow or 0.0, 0.0)
    attribution_refs = [
        {
            "patch_id": stat["patch_id"],
            "wire_length_in_patch": stat["wire_length_in_patch"],
            "via_count_in_patch": stat["via_count_in_patch"],
            "final_overflow": stat["final_overflow"],
            "wire_segment_count": stat["wire_segment_count"],
            "covered_layers": sorted(stat["covered_layers"]),
            "contribution_score": stat["contribution_score"],
        }
        for stat in sorted(
            patch_stats.values(),
            key=lambda item: (-float(item["contribution_score"]), int(item["patch_id"])),
        )
    ]
    final_overflows = [
        float(item["final_overflow"])
        for item in attribution_refs
        if item["final_overflow"] is not None
    ]
    routed_wire_length = sum(wire.length for wire in route_wires)
    return {
        "route_only_oracle": True,
        "routed_wire_count": len([wire for wire in route_wires if not wire.via]),
        "routed_wire_length": routed_wire_length,
        "routed_bbox": routed_bbox,
        "covered_layers": sorted({wire.layer for wire in route_wires}),
        "via_count": sum(1 for wire in route_wires if wire.via),
        "detour_ratio": routed_wire_length / terminal_hpwl
        if terminal_hpwl and terminal_hpwl > 0
        else None,
        "routed_patch_ids": sorted(patch_stats),
        "routed_patch_count": len(patch_stats),
        "overlapped_congested_patch_count": sum(1 for value in final_overflows if value > 0),
        "final_overflow_sum": sum(final_overflows) if final_overflows else None,
        "final_overflow_max": max(final_overflows) if final_overflows else None,
        "patch_attribution_refs": attribution_refs[:64],
        "patch_attribution_ref_count_total": len(attribution_refs),
        "patch_attribution_refs_truncated": len(attribution_refs) > 64,
        "source": _workspace_relative_from_parsed_def(parsed_def),
    }


def _route_label_demand_capacity_by_patch(
    stage_dir: Path, canonical_grid: dict
) -> dict[int, float]:
    labels = parse_route_native_demand_capacity_artifacts(stage_dir, canonical_grid).get(
        "labels", []
    )
    return {
        int(label["patch_id"]): float(label["union_demand_capacity"])
        for label in labels
        if label.get("patch_id") is not None and label.get("union_demand_capacity") is not None
    }


def _build_net_record(
    stage: StageInfo,
    parsed_def: DefData,
    net: DefNet,
    idx: int,
    pins: list[dict[str, Any]],
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
    sta_report: dict[str, Any] | None,
    route_label_demand_capacity_by_patch: dict[int, float] | None = None,
) -> dict[str, Any]:
    source_rel = _workspace_relative_from_parsed_def(parsed_def)
    terminal_refs = _terminal_refs_for_net(pins) or [
        {
            "pin_key": _pin_key(
                {
                    **pin,
                    "pin_kind": "io_port" if pin.get("instance") == "PIN" else "instance_terminal",
                }
            ),
            "pin_kind": "io_port" if pin.get("instance") == "PIN" else "instance_terminal",
            "instance": pin.get("instance"),
            "pin_name": pin.get("pin_name"),
            "full_name": f"PIN/{pin.get('pin_name')}"
            if pin.get("instance") == "PIN"
            else f"{pin.get('instance')}/{pin.get('pin_name')}",
            "parent_instance_key": None if pin.get("instance") == "PIN" else pin.get("instance"),
            "parent_master": None,
            "parent_cell_class": None,
            "parent_physical_class": None,
            "pin_role": "unknown",
            "is_driver": False,
            "is_sink": False,
            "is_io": pin.get("instance") == "PIN",
            "is_macro_pin": False,
            "patch_id": None,
            "geometry_status": "missing",
            "anchor_source": "none",
            "is_on_critical_path": False,
            "center": None,
            "bbox": None,
        }
        for pin in net.pins
    ]
    centers = [
        point for point in (_anchor_point(ref) for ref in terminal_refs) if isinstance(point, dict)
    ]
    bboxes = [ref["bbox"] for ref in terminal_refs if isinstance(ref.get("bbox"), dict)]
    patch_ids = sorted(
        {int(ref["patch_id"]) for ref in terminal_refs if ref.get("patch_id") is not None}
    )
    role_counts = {
        role: sum(1 for ref in terminal_refs if ref.get("pin_role") == role)
        for role in ("driver", "sink", "bidirectional", "unknown")
    }
    hpwl = _hpwl_from_points(centers)
    bbox = (
        _bbox_union([*bboxes, *([_bbox_from_points(centers)] if centers else [])])
        if bboxes
        else _bbox_from_points(centers)
    )
    route_wires = [wire for wire in net.wires if not wire.special]
    identity = _net_identity(net)
    null_reason: dict[str, str] = {}
    if hpwl is None:
        null_reason["geometry_proxy"] = "missing_terminal_anchors"
    if stage.name != "route":
        null_reason["route_analysis"] = "route_only_not_available_for_preroute_stage"
    elif not route_wires:
        null_reason["route_analysis"] = "no_routed_wires"
    timing_context = _net_timing_context(
        net.name, terminal_refs, sta_report, parsed_def.path.parents[2]
    )
    if not timing_context["available"]:
        null_reason["timing_context"] = "missing_sta_artifact"
    elif timing_context["timing_path_count"] == 0:
        null_reason["timing_context"] = "net_not_in_timing_paths"
    geometry_proxy = {
        "anchor_source": "terminal_anchor" if centers or bboxes else "none",
        "anchor_quality": _net_anchor_quality(terminal_refs),
        "terminal_bbox": bbox,
        "terminal_center": _bbox_center(bbox) if isinstance(bbox, dict) else None,
        "hpwl": hpwl,
        "x_span": None if bbox is None else float(bbox["urx"]) - float(bbox["llx"]),
        "y_span": None if bbox is None else float(bbox["ury"]) - float(bbox["lly"]),
        "area": None if bbox is None else _bbox_area(bbox),
        "aspect_ratio": None
        if bbox is None or float(bbox["ury"]) == float(bbox["lly"])
        else (float(bbox["urx"]) - float(bbox["llx"])) / (float(bbox["ury"]) - float(bbox["lly"])),
        "patch_ids": patch_ids,
        "patch_span_count": len(patch_ids),
        "cross_patch": len(patch_ids) > 1,
        "exact_terminal_count": sum(
            1 for ref in terminal_refs if ref.get("geometry_status") == "exact"
        ),
        "fallback_terminal_count": sum(
            1
            for ref in terminal_refs
            if str(ref.get("geometry_status") or "").startswith("fallback")
        ),
        "missing_anchor_terminal_count": sum(
            1 for ref in terminal_refs if not ref.get("center") and not ref.get("bbox")
        ),
    }
    patch_anchor = _net_patch_anchor(terminal_refs, geometry_proxy, canonical_grid, stage_maps)
    route_analysis = _route_analysis_for_net(
        stage,
        parsed_def,
        net,
        route_wires,
        hpwl,
        canonical_grid,
        stage_maps,
        route_label_demand_capacity_by_patch or {},
    )
    return {
        "stage": stage.name,
        "net_key": net.name,
        "name": net.name,
        "source": source_rel,
        "identity": identity,
        "connectivity_summary": {
            "terminal_count": len(terminal_refs),
            "pin_count": len(terminal_refs),
            "connected_instance_count": len(
                {
                    ref.get("parent_instance_key")
                    for ref in terminal_refs
                    if ref.get("parent_instance_key")
                }
            ),
            "connected_io_count": sum(
                1 for ref in terminal_refs if ref.get("pin_kind") == "io_port"
            ),
            "macro_pin_count": sum(
                1 for ref in terminal_refs if ref.get("parent_physical_class") == "macro"
            ),
            "driver_count": role_counts["driver"],
            "sink_count": role_counts["sink"],
            "bidirectional_count": role_counts["bidirectional"],
            "unknown_role_count": role_counts["unknown"],
            "fanout": role_counts["sink"]
            if role_counts["driver"] == 1
            else max(0, len(terminal_refs) - 1),
            "clock_sink_count": sum(
                1
                for ref in terminal_refs
                if ref.get("pin_role") == "sink" and _is_clock_like(str(ref.get("pin_name") or ""))
            ),
            "sequential_sink_count": sum(
                1
                for ref in terminal_refs
                if ref.get("pin_role") == "sink" and ref.get("parent_cell_class") == "sequential"
            ),
            "physical_only_terminal_count": sum(
                1 for ref in terminal_refs if ref.get("parent_physical_class") == "physical_only"
            ),
            "max_terminals_per_patch": max(
                [
                    sum(1 for ref in terminal_refs if ref.get("patch_id") == patch_id)
                    for patch_id in patch_ids
                ],
                default=0,
            ),
            "cross_patch": len(patch_ids) > 1,
            "cross_patch_count": len(patch_ids),
            "classification_source": "pin_connectivity_context" if pins else "def_net_connections",
            "terminal_refs_truncated": len(pins) > 256,
            "terminal_ref_count_total": len(pins) if pins else len(net.pins),
            "max_terminal_refs": 256,
        },
        "terminal_refs": terminal_refs,
        "geometry_proxy": geometry_proxy,
        "patch_anchor": patch_anchor,
        "timing_context": timing_context,
        "route_analysis": route_analysis,
        "progressive_metadata": {},
        "source_refs": {
            "def": _workspace_relative_from_parsed_def(parsed_def),
            "def_section": "SPECIALNETS" if net.special else "NETS",
            "def_index": idx,
            "pins": f"foundation_data/ecc/vectors/pins/{stage.name}.jsonl",
            "instances": f"foundation_data/ecc/vectors/instances/{stage.name}.jsonl",
            "maps": f"foundation_data/ecc/maps/{stage.name}",
            "sta": timing_context.get("source"),
            "wires": "foundation_data/ecc/vectors/wires/route.jsonl"
            if stage.name == "route"
            else None,
            "routing_graph": "foundation_data/ecc/vectors/routing_graphs/route.jsonl"
            if stage.name == "route"
            else None,
            "route": _workspace_relative_from_parsed_def(parsed_def)
            if stage.name == "route"
            else None,
        },
        "null_reason": null_reason,
    }


def _workspace_relative_from_parsed_def(parsed_def: DefData) -> str:
    parts = parsed_def.path.parts
    for marker in (
        "Floorplan_ecc",
        "place_dreamplace",
        "CTS_ecc",
        "route_ecc",
        "drc_ecc",
        "filler_ecc",
        "fixFanout_ecc",
        "legalization_dreamplace",
    ):
        if marker in parts:
            index = parts.index(marker)
            return str(Path(*parts[index:]))
    return parsed_def.path.name


def _ordered_net_record(record: dict[str, Any], record_id: int) -> dict[str, Any]:
    return {
        "id": record_id,
        "stage": record["stage"],
        "net_key": record["net_key"],
        "name": record["name"],
        "source": record.get("source"),
        "identity": record["identity"],
        "connectivity_summary": record["connectivity_summary"],
        "terminal_refs": record["terminal_refs"],
        "geometry_proxy": record["geometry_proxy"],
        "patch_anchor": record["patch_anchor"],
        "timing_context": record["timing_context"],
        "route_analysis": record["route_analysis"],
        "progressive_metadata": record["progressive_metadata"],
        "source_refs": record["source_refs"],
        "null_reason": record["null_reason"],
    }


def _wire_segment_summary(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("identity") or {}
    geometry = record.get("geometry") or {}
    layer_context = record.get("layer_context") or {}
    track_context = record.get("track_context") or {}
    patch_anchor = record.get("patch_anchor") or {}
    return {
        "wire_key": record.get("wire_key") or identity.get("wire_key"),
        "net_key": identity.get("net_key"),
        "wire_class": identity.get("wire_class"),
        "segment_kind": identity.get("segment_kind"),
        "geometry_status": geometry.get("geometry_status"),
        "shape_type": geometry.get("shape_type"),
        "layer_index": layer_context.get("layer_index"),
        "track_available": track_context.get("available"),
        "primary_patch_id": patch_anchor.get("primary_patch_id"),
    }


def _wire_class(net: DefNet) -> str:
    identity = _net_identity(net)
    return str(identity["net_class"])


def _wire_geometry(wire: DefWire) -> dict[str, Any]:
    segment_kind = "via" if wire.via else "wire_segment"
    bbox = {
        "llx": min(wire.x1, wire.x2),
        "lly": min(wire.y1, wire.y2),
        "urx": max(wire.x1, wire.x2),
        "ury": max(wire.y1, wire.y2),
    }
    center = {"x": (wire.x1 + wire.x2) / 2.0, "y": (wire.y1 + wire.y2) / 2.0}
    direction = "point" if segment_kind == "via" else wire.direction
    length = 0.0 if segment_kind == "via" else wire.length
    return {
        "segment_kind": segment_kind,
        "layer": wire.layer,
        "start": {"x": wire.x1, "y": wire.y1, "layer": wire.layer},
        "end": {"x": wire.x2, "y": wire.y2, "layer": wire.layer},
        "bbox": bbox,
        "center": center,
        "direction": direction,
        "length": length,
        "manhattan_length": length,
        "width": wire.width,
        "area_proxy": None if wire.width is None else length * float(wire.width),
        "shape_type": "point_via" if segment_kind == "via" else "orthogonal_segment",
        "geometry_status": "exact",
    }


def _patch_row_col(canonical_grid: dict, patch_id: int | None) -> tuple[int, int] | None:
    if patch_id is None:
        return None
    lookup = _patch_grid_lookup(canonical_grid)
    if lookup is not None:
        patch = lookup.patches_by_id.get(int(patch_id))
        if patch is not None:
            return int(patch["row"]), int(patch["col"])
    for patch in canonical_grid.get("patches", []):
        if int(patch.get("patch_id")) == int(patch_id):
            return int(patch["row"]), int(patch["col"])
    return None


def _wire_patch_intersections(
    geometry: dict[str, Any], canonical_grid: dict
) -> list[dict[str, Any]]:
    bbox = geometry.get("bbox")
    if not isinstance(bbox, dict):
        return []
    total_length = float(geometry.get("length") or 0.0)
    intersections: list[dict[str, Any]] = []
    lookup = _patch_grid_lookup(canonical_grid)
    candidate_patches = _grid_overlap_patches_for_wire(lookup, bbox) or canonical_grid.get(
        "patches", []
    )
    for patch in candidate_patches:
        patch_bbox = patch.get("bbox", {})
        if not isinstance(patch_bbox, dict) or not _wire_bbox_intersects_patch(bbox, patch_bbox):
            continue
        length = _clipped_segment_length(geometry, patch_bbox)
        if total_length > 0 and length <= 0:
            continue
        intersections.append(
            {
                "patch_id": int(patch["patch_id"]),
                "row": int(patch["row"]),
                "col": int(patch["col"]),
                "length": length,
                "length_fraction": (length / total_length) if total_length > 0 else None,
                "area_proxy": None
                if geometry.get("width") is None
                else length * float(geometry["width"]),
                "is_primary_patch": False,
                "intersection_bbox": _bbox_intersection(bbox, patch_bbox),
            }
        )
    if not intersections:
        center = geometry.get("center", {})
        primary = _grid_patch_for_point(lookup, center) if isinstance(center, dict) else None
        if primary is None:
            primary = _patch_for_point(canonical_grid.get("patches", []), center)
        if primary:
            intersections.append(
                {
                    "patch_id": int(primary["patch_id"]),
                    "row": int(primary["row"]),
                    "col": int(primary["col"]),
                    "length": total_length,
                    "length_fraction": 1.0 if total_length > 0 else None,
                    "area_proxy": None,
                    "is_primary_patch": True,
                    "intersection_bbox": bbox,
                }
            )
    if intersections:
        primary_patch_id = intersections[0]["patch_id"]
        for item in intersections:
            item["is_primary_patch"] = item["patch_id"] == primary_patch_id
    return intersections


def _primary_wire_patch_intersection(
    geometry: dict[str, Any], patch: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if patch is None:
        return []
    patch_bbox = patch.get("bbox") or {}
    length = _clipped_segment_length(geometry, patch_bbox) if patch_bbox else 0.0
    if length <= 0 and geometry.get("segment_kind") != "via":
        length = float(geometry.get("length") or 0.0)
    return [
        {
            "patch_id": int(patch["patch_id"]),
            "row": int(patch.get("row") or 0),
            "col": int(patch.get("col") or 0),
            "length": length,
            "intersect_length": length,
            "area_proxy": None,
            "direction": geometry.get("direction"),
            "layer": geometry.get("layer"),
            "is_primary": True,
            "is_primary_patch": True,
            "capacity_contribution": None,
        }
    ]


def _grid_overlap_patches_for_wire(
    lookup: _PatchGridLookup | None, bbox: dict[str, Any]
) -> list[dict[str, Any]]:
    if lookup is None or not lookup.rectangular:
        return []
    col_indexes = (
        _uniform_bound_indexes_for_range(lookup, "col", float(bbox["llx"]), float(bbox["urx"]))
        if lookup.uniform
        else []
    )
    row_indexes = (
        _uniform_bound_indexes_for_range(lookup, "row", float(bbox["lly"]), float(bbox["ury"]))
        if lookup.uniform
        else []
    )
    if not col_indexes:
        col_indexes = _bound_indexes_for_wire_range(
            lookup.col_bounds, float(bbox["llx"]), float(bbox["urx"])
        )
    if not row_indexes:
        row_indexes = _bound_indexes_for_wire_range(
            lookup.row_bounds, float(bbox["lly"]), float(bbox["ury"])
        )
    patches: list[dict[str, Any]] = []
    for row in row_indexes:
        for col in col_indexes:
            patch = lookup.patches_by_coord.get((row, col))
            if patch is not None:
                patches.append(patch)
    return patches


def _bound_indexes_for_wire_range(
    bounds: list[tuple[float, float]], start: float, end: float
) -> list[int]:
    lower = min(start, end)
    upper = max(start, end)
    if lower == upper:
        index = _bound_index_for_point(bounds, lower)
        return [index] if index is not None else []
    return [
        index
        for index, (bound_lower, bound_upper) in enumerate(bounds)
        if _range_overlaps_half_open(lower, upper, bound_lower, bound_upper)
    ]


def _wire_bbox_intersects_patch(a: dict[str, Any], b: dict[str, Any]) -> bool:
    allx = float(a["llx"])
    aurx = float(a["urx"])
    blx = float(b["llx"])
    burx = float(b["urx"])
    ally = float(a["lly"])
    aury = float(a["ury"])
    bly = float(b["lly"])
    bury = float(b["ury"])
    x_overlap = _range_overlaps_half_open(allx, aurx, blx, burx)
    y_overlap = _range_overlaps_half_open(ally, aury, bly, bury)
    return x_overlap and y_overlap


def _range_overlaps_half_open(start: float, end: float, lower: float, upper: float) -> bool:
    if start == end:
        point = start
        return lower <= point < upper
    return max(min(start, end), lower) < min(max(start, end), upper)


def _bbox_intersection(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    return {
        "llx": max(float(a["llx"]), float(b["llx"])),
        "lly": max(float(a["lly"]), float(b["lly"])),
        "urx": min(float(a["urx"]), float(b["urx"])),
        "ury": min(float(a["ury"]), float(b["ury"])),
    }


def _clipped_segment_length(geometry: dict[str, Any], bbox: dict[str, Any]) -> float:
    start = geometry.get("start", {})
    end = geometry.get("end", {})
    x1 = float(start.get("x", 0.0))
    y1 = float(start.get("y", 0.0))
    x2 = float(end.get("x", 0.0))
    y2 = float(end.get("y", 0.0))
    if x1 == x2 and y1 == y2:
        return 0.0 if _point_in_bbox(x1, y1, bbox) else 0.0
    if y1 == y2:
        if not (float(bbox["lly"]) <= y1 <= float(bbox["ury"])):
            return 0.0
        return max(0.0, min(max(x1, x2), float(bbox["urx"])) - max(min(x1, x2), float(bbox["llx"])))
    if x1 == x2:
        if not (float(bbox["llx"]) <= x1 <= float(bbox["urx"])):
            return 0.0
        return max(0.0, min(max(y1, y2), float(bbox["ury"])) - max(min(y1, y2), float(bbox["lly"])))
    return 0.0


def _build_wire_record(
    stage: StageInfo,
    parsed_def: DefData,
    net: DefNet,
    wire: DefWire,
    idx: int,
    segment_index: int,
    canonical_grid: dict,
    stage_maps: dict[str, dict[str, MapMatrix]],
    net_record: dict[str, Any] | None,
    native_demand_capacity_by_patch: dict[int, dict[str, Any]] | None = None,
    drc_report: dict[str, Any] | None = None,
    tech_layers: dict[str, dict[str, Any]] | None = None,
    tech_vias: dict[str, dict[str, Any]] | None = None,
    net_context: dict[str, Any] | None = None,
    *,
    large_design_route: bool = False,
) -> dict[str, Any]:
    source_section = "SPECIALNETS" if wire.special or net.special else "NETS"
    segment_kind = "via" if wire.via else "wire_segment"
    wire_key = f"{stage.name}:{source_section}:{net.name}:{segment_index}"
    identity_base = _net_identity(net)
    geometry = _wire_geometry(wire)
    lookup = _patch_grid_lookup(canonical_grid)
    center = geometry.get("center", {})
    center_patch = _grid_patch_for_point(lookup, center) if isinstance(center, dict) else None
    if center_patch is None:
        center_patch = _patch_for_point(canonical_grid.get("patches", []), center)
    primary_patch_id = int(center_patch["patch_id"]) if center_patch else None
    if large_design_route:
        intersections = _primary_wire_patch_intersection(geometry, center_patch)
    else:
        intersections = _wire_patch_intersections(geometry, canonical_grid)
        if primary_patch_id is None:
            primary_patch_id = intersections[0]["patch_id"] if intersections else None
    if intersections and primary_patch_id is not None:
        for item in intersections:
            item["is_primary_patch"] = int(item["patch_id"]) == int(primary_patch_id)
    row_col = _patch_row_col(canonical_grid, primary_patch_id)
    null_reason: dict[str, str] = {}
    if wire.width is None:
        null_reason["geometry_width"] = "def_route_missing_width"
    track = _track_for_layer(parsed_def, wire.layer)
    if track is None:
        null_reason["track_context"] = "missing_track_context"
    layer_context = _wire_layer_context(wire, geometry, track, tech_layers or {}, null_reason)
    track_context = _wire_track_context(wire, geometry, track)
    capacity_context = _wire_capacity_context(
        stage.name,
        geometry,
        intersections,
        primary_patch_id,
        native_demand_capacity_by_patch or {},
        layer_context,
    )
    if not capacity_context.get("available"):
        null_reason["capacity_context"] = (
            "missing_track_capacity" if stage.name == "route" else "not_implemented"
        )
    patch_anchor = _wire_patch_anchor(
        stage_maps, canonical_grid, geometry, primary_patch_id, intersections
    )
    if large_design_route:
        source_rel = _workspace_relative_from_parsed_def(parsed_def)
        return {
            "id": idx,
            "stage": stage.name,
            "wire_key": wire_key,
            "source": source_rel,
            "identity": {
                "wire_key": wire_key,
                "net": net.name,
                "net_key": net.name,
                "source_section": source_section,
                "segment_index": segment_index,
                "wire_class": _wire_class(net),
                "segment_kind": segment_kind,
                "is_signal": identity_base["is_signal"],
                "is_clock": identity_base["is_clock"],
                "is_power_ground": identity_base["is_power_ground"],
                "is_special": identity_base["is_special"],
                "classification_source": "def_net_use_and_name_rule",
            },
            "geometry": geometry,
            "layer_context": layer_context,
            "track_context": track_context,
            "capacity_context": capacity_context,
            "patch_anchor": patch_anchor,
            "patch_intersections": intersections,
            "net_context": {
                "net": net.name,
                "net_key": net.name,
                "terminal_count": len(net.pins),
                "source": "large_design_lightweight",
            },
            "endpoint_context": {
                "available": False,
                "classification_source": "large_design_lightweight",
            },
            "timing_context": {"available": False, "source": "large_design_lightweight"},
            "route_context": {
                "route_only_oracle": True,
                "local_final_overflow": _route_wire_local_overflow(
                    primary_patch_id, native_demand_capacity_by_patch or {}, stage_maps, row_col
                ),
                "layer_demand_capacity_ratio": capacity_context.get("layer_demand_capacity_ratio"),
                "patch_layer_usage": capacity_context.get("patch_layer_demand"),
                "nearby_wire_count": None,
                "nearby_via_count": None,
                "nearby_drc_count": None,
                "contributes_to_overflow_patch": None,
                "source": "routed_def_reconstruction_large_design_lightweight",
            },
            "via_context": {"via_name": wire.via} if wire.via else None,
            "progressive_metadata": {
                "available_from_stage": stage.name,
                "route_only_oracle": True,
                "tracking_scope": "stage_local_wire_geometry",
            },
            "source_refs": {
                "def": source_rel,
                "def_section": source_section,
                "segment_index": segment_index,
                "route": "routed_def_reconstruction_large_design_lightweight",
            },
            "null_reason": null_reason,
        }
    route_context = None
    if stage.name == "route":
        local_overflow = _route_wire_local_overflow(
            primary_patch_id, native_demand_capacity_by_patch or {}, stage_maps, row_col
        )
        nearby_counts_enabled = len(net.wires) <= 100 and not large_design_route
        route_context = {
            "route_only_oracle": True,
            "local_final_overflow": local_overflow,
            "layer_demand_capacity_ratio": capacity_context.get("layer_demand_capacity_ratio"),
            "patch_layer_usage": capacity_context.get("patch_layer_demand"),
            "nearby_wire_count": _nearby_wire_count(
                parsed_def, net.name, geometry, include_vias=False
            )
            if nearby_counts_enabled
            else None,
            "nearby_via_count": _nearby_wire_count(
                parsed_def, net.name, geometry, include_vias=True
            )
            if nearby_counts_enabled
            else None,
            "nearby_drc_count": _drc_count_near_geometry(drc_report, geometry),
            "contributes_to_overflow_patch": bool(local_overflow and local_overflow > 0),
            "source": "routed_def_reconstruction"
            if nearby_counts_enabled
            else "routed_def_reconstruction_large_design_summary",
        }
        if local_overflow is None:
            null_reason["route_context"] = "missing_route_overflow_artifact"
    else:
        null_reason["route_context"] = "not_route_stage"
    endpoint_context = {
        "available": False,
        "start_kind": "unknown",
        "end_kind": "unknown",
        "nearest_start_pin_key": None,
        "nearest_end_pin_key": None,
        "start_nearest_pin_distance": None,
        "end_nearest_pin_distance": None,
        "connected_via_keys": [],
        "classification_source": "not_implemented",
    }
    null_reason["endpoint_context"] = "not_implemented"
    timing_context = {
        "available": False,
        "timing_path_count": None,
        "is_on_critical_net": None,
        "worst_slack_seen": None,
        "max_slew": None,
        "max_cap": None,
        "path_refs": [],
        "source": None,
    }
    null_reason["timing_context"] = "missing_sta_artifacts"
    via_context = (
        _wire_via_context(wire, parsed_def, segment_index, tech_vias or {}, null_reason)
        if wire.via
        else None
    )
    if not wire.via:
        null_reason["via_context"] = "not_via_segment"
    source_rel = _workspace_relative_from_parsed_def(parsed_def)
    return {
        "id": idx,
        "stage": stage.name,
        "wire_key": wire_key,
        "source": source_rel,
        "identity": {
            "wire_key": wire_key,
            "net": net.name,
            "net_key": net.name,
            "source_section": source_section,
            "segment_index": segment_index,
            "wire_class": _wire_class(net),
            "segment_kind": segment_kind,
            "is_signal": identity_base["is_signal"],
            "is_clock": identity_base["is_clock"],
            "is_power_ground": identity_base["is_power_ground"],
            "is_special": identity_base["is_special"],
            "classification_source": "def_net_use_and_name_rule",
        },
        "geometry": geometry,
        "layer_context": layer_context,
        "track_context": track_context,
        "capacity_context": capacity_context,
        "patch_anchor": patch_anchor,
        "patch_intersections": intersections,
        "net_context": net_context or _wire_net_context(net, net_record),
        "endpoint_context": endpoint_context,
        "timing_context": timing_context,
        "route_context": route_context,
        "via_context": via_context,
        "progressive_metadata": {
            "available_from_stage": stage.name,
            "is_new_routed_geometry": None,
            "exists_same_geometry_in_prev_stage": None,
            "net_exists_in_prev_stage": None,
            "route_only_oracle": stage.name == "route" and route_context is not None,
            "tracking_scope": "stage_local_wire_geometry",
        },
        "source_refs": {
            "def": source_rel,
            "def_section": source_section,
            "net_index": None,
            "segment_index": segment_index,
            "raw_route_token_index": None,
            "tech_layer": "foundation_data/ecc/vectors/tech/layers.json",
            "tech_via": "foundation_data/ecc/vectors/tech/vias.json" if wire.via else None,
            "sta": None,
            "route": "routed_def_reconstruction" if stage.name == "route" else None,
        },
        "null_reason": null_reason,
    }


def _wire_layer_context(
    wire: DefWire,
    geometry: dict[str, Any],
    track: DefTrack | None,
    tech_layers: dict[str, dict[str, Any]],
    null_reason: dict[str, str],
) -> dict[str, Any]:
    tech_layer = tech_layers.get(wire.layer, {})
    identity = (
        tech_layer.get("identity", {}) if isinstance(tech_layer.get("identity"), dict) else {}
    )
    routing = (
        tech_layer.get("routing_properties", {})
        if isinstance(tech_layer.get("routing_properties"), dict)
        else {}
    )
    preferred = routing.get("preferred_direction")
    if preferred == "unknown":
        preferred = None
    pitch = (
        routing.get("pitch")
        if routing.get("pitch") is not None
        else (track.step if track else None)
    )
    source = routing.get("source") or ("def_tracks" if track else None)
    if not tech_layer and track is None:
        null_reason["layer_context"] = "missing_tech_layer_context"
    return {
        "layer": wire.layer,
        "layer_index": identity.get("order") if identity else _layer_order_from_name(wire.layer),
        "routing_direction_preference": preferred,
        "pitch": pitch,
        "width_default": routing.get("width"),
        "is_preferred_direction": (geometry.get("direction") == preferred)
        if preferred and geometry.get("direction") in {"horizontal", "vertical"}
        else None,
        "source": source or "missing_tech_layer",
    }


def _wire_track_context(
    wire: DefWire, geometry: dict[str, Any], track: DefTrack | None
) -> dict[str, Any]:
    if track is None:
        return {
            "available": False,
            "track_axis": None,
            "is_on_track": None,
            "nearest_track_distance": None,
            "track_count": None,
            "track_step": None,
            "null_reason": "missing_track_context",
        }
    fixed_coord = None
    if geometry.get("direction") == "horizontal":
        fixed_coord = geometry.get("start", {}).get("y")
    elif geometry.get("direction") == "vertical":
        fixed_coord = geometry.get("start", {}).get("x")
    elif geometry.get("direction") == "point":
        fixed_coord = (
            geometry.get("start", {}).get("y")
            if track.axis == "Y"
            else geometry.get("start", {}).get("x")
        )
    distance = _distance_to_track(float(fixed_coord), track) if fixed_coord is not None else None
    return {
        "available": True,
        "track_axis": track.axis,
        "is_on_track": (distance == 0.0) if distance is not None else None,
        "nearest_track_distance": distance,
        "track_count": track.count,
        "track_step": track.step,
        "null_reason": None if distance is not None else "complex_segment_track_alignment_unknown",
    }


def _distance_to_track(coord: float, track: DefTrack) -> float:
    if track.step == 0:
        return abs(coord - track.start)
    raw = round((coord - track.start) / track.step)
    idx = max(0, min(int(raw), int(track.count) - 1)) if track.count else int(raw)
    return abs(coord - (track.start + idx * track.step))


def _wire_capacity_context(
    stage_name: str,
    geometry: dict[str, Any],
    intersections: list[dict[str, Any]],
    primary_patch_id: int | None,
    native_demand_capacity_by_patch: dict[int, dict[str, Any]],
    layer_context: dict[str, Any],
) -> dict[str, Any]:
    primary_length = _primary_patch_length(intersections, primary_patch_id)
    label = (
        native_demand_capacity_by_patch.get(int(primary_patch_id))
        if primary_patch_id is not None
        else None
    )
    direction = geometry.get("direction")
    if (
        stage_name == "route"
        and isinstance(label, dict)
        and direction in {"horizontal", "vertical"}
    ):
        demand = label.get(f"{direction}_demand")
        capacity = label.get(f"{direction}_capacity")
        utilization = label.get(f"{direction}_utilization")
        if utilization is None and demand is not None and capacity not in (None, 0):
            utilization = float(demand) / float(capacity)
        return {
            "available": True,
            "patch_layer_demand": primary_length,
            "patch_layer_capacity": capacity,
            "patch_layer_utilization": utilization,
            "layer_demand_capacity_ratio": utilization,
            "source": "routed_def_reconstruction",
        }
    source = (
        "current_stage_real_wires_only"
        if stage_name != "route"
        else "missing_route_overflow_artifact"
    )
    return {
        "available": stage_name != "route" and primary_length is not None,
        "patch_layer_demand": primary_length if stage_name != "route" else None,
        "patch_layer_capacity": None,
        "patch_layer_utilization": None,
        "layer_demand_capacity_ratio": None,
        "source": source,
    }


def _primary_patch_length(
    intersections: list[dict[str, Any]], primary_patch_id: int | None
) -> float | None:
    if primary_patch_id is None:
        return None
    for item in intersections:
        if int(item.get("patch_id", -1)) == int(primary_patch_id):
            return float(item.get("length") or 0.0)
    return None


def _wire_patch_anchor(
    stage_maps: dict[str, dict[str, MapMatrix]],
    canonical_grid: dict,
    geometry: dict[str, Any],
    primary_patch_id: int | None,
    intersections: list[dict[str, Any]],
) -> dict[str, Any]:
    row_col = _patch_row_col(canonical_grid, primary_patch_id)
    row, col = row_col if row_col else (None, None)
    return {
        "primary_patch_id": primary_patch_id,
        "overlap_patch_ids": [int(item["patch_id"]) for item in intersections],
        "anchor_source": "via_point"
        if geometry.get("segment_kind") == "via"
        else "segment_midpoint"
        if primary_patch_id is not None
        else "none",
        "local_cell_density": _matrix_value(
            stage_maps.get("density", {}).get("allcell_density"), row, col
        )
        if row is not None and col is not None
        else None,
        "local_pin_density": _matrix_value(
            stage_maps.get("density", {}).get("allcell_pin_density"), row, col
        )
        if row is not None and col is not None
        else None,
        "local_rudy": _matrix_value(stage_maps.get("rudy", {}).get("rudy_union"), row, col)
        if row is not None and col is not None
        else None,
        "local_egr_overflow": _matrix_value(stage_maps.get("congestion", {}).get("union"), row, col)
        if row is not None and col is not None
        else None,
    }


def _route_wire_local_overflow(
    primary_patch_id: int | None,
    native_demand_capacity_by_patch: dict[int, dict[str, Any]],
    stage_maps: dict[str, dict[str, MapMatrix]],
    row_col: tuple[int, int] | None,
) -> float | None:
    if primary_patch_id is not None:
        label = native_demand_capacity_by_patch.get(int(primary_patch_id))
        if isinstance(label, dict) and label.get("union_demand_capacity") is not None:
            return float(label["union_demand_capacity"])
    if row_col:
        return _matrix_value(stage_maps.get("congestion", {}).get("union"), row_col[0], row_col[1])
    return None


def _nearby_wire_count(
    parsed_def: DefData, net_name: str, geometry: dict[str, Any], *, include_vias: bool
) -> int | None:
    net_wires = [
        wire for def_net in parsed_def.nets if def_net.name == net_name for wire in def_net.wires
    ]
    return sum(
        1
        for wire in net_wires
        if bool(wire.via) == include_vias and _wire_near_geometry(wire, geometry)
    )


def _wire_via_context(
    wire: DefWire,
    parsed_def: DefData,
    segment_index: int,
    tech_vias: dict[str, dict[str, Any]],
    null_reason: dict[str, str],
) -> dict[str, Any]:
    tech_via = tech_vias.get(str(wire.via), {})
    stack = tech_via.get("layer_stack", {}) if isinstance(tech_via.get("layer_stack"), dict) else {}
    if not stack:
        via_defs = {str(item.get("name")): item for item in parsed_def.vias if item.get("name")}
        via_def = via_defs.get(str(wire.via), {})
        layers = list(via_def.get("layers") or []) or _infer_via_stack_layers_from_name(
            str(wire.via), {wire.layer: {}}
        )
        stack = _via_layer_stack(
            layers,
            {},
            "def_via_layers"
            if via_def.get("layers")
            else "heuristic_from_name"
            if layers
            else "missing",
        )
    lower = stack.get("bottom_layer")
    upper = stack.get("top_layer")
    cut = stack.get("cut_layer")
    via_source = (
        "vectors_tech_vias"
        if tech_via
        else "heuristic_via_name_rule"
        if stack.get("stack_source") == "heuristic_from_name"
        else "def_routed_wires"
    )
    if not (lower and upper and cut):
        null_reason["via_context"] = "missing_tech_via_definition"
    return {
        "via_name": wire.via,
        "cut_layer": cut,
        "lower_layer": lower,
        "upper_layer": upper,
        "layer_transition": f"{lower}->{upper}" if lower and upper else None,
        "is_default_via": None,
        "via_source": via_source,
    }


def _track_for_layer(parsed_def: DefData, layer: str) -> DefTrack | None:
    return next((track for track in parsed_def.tracks if track.layer == layer), None)


def _wire_net_context(net: DefNet, net_record: dict[str, Any] | None) -> dict[str, Any]:
    identity = _net_identity(net)
    summary = net_record.get("connectivity_summary", {}) if isinstance(net_record, dict) else {}
    wires = [wire for wire in net.wires]
    xs = [coord for wire in wires for coord in (wire.x1, wire.x2)]
    ys = [coord for wire in wires for coord in (wire.y1, wire.y2)]
    patch_ids = (
        net_record.get("geometry_proxy", {}).get("patch_ids", [])
        if isinstance(net_record, dict)
        else []
    )
    return {
        "net": net.name,
        "net_key": net.name,
        "net_use": identity["use"],
        "is_clock": identity["is_clock"],
        "is_power_ground": identity["is_power_ground"],
        "is_special": identity["is_special"],
        "net_degree": summary.get("terminal_count", len(net.pins)),
        "net_fanout": summary.get("fanout", max(0, len(net.pins) - 1)),
        "driver_pin_key": None,
        "sink_count": summary.get("sink_count"),
        "net_total_routed_length": sum(wire.length for wire in wires),
        "net_via_count": sum(1 for wire in wires if wire.via),
        "net_bbox": {"llx": min(xs), "lly": min(ys), "urx": max(xs), "ury": max(ys)}
        if xs and ys
        else None,
        "net_cross_patch": len(patch_ids) > 1 if patch_ids else None,
        "cross_patch_count": len(patch_ids),
        "terminal_count": summary.get("terminal_count", len(net.pins)),
    }


def _ordered_wire_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "stage": record["stage"],
        "wire_key": record["wire_key"],
        "source": record["source"],
        "identity": record["identity"],
        "geometry": record["geometry"],
        "layer_context": record["layer_context"],
        "track_context": record["track_context"],
        "capacity_context": record["capacity_context"],
        "patch_anchor": record["patch_anchor"],
        "patch_intersections": record["patch_intersections"],
        "net_context": record["net_context"],
        "endpoint_context": record["endpoint_context"],
        "timing_context": record["timing_context"],
        "route_context": record["route_context"],
        "via_context": record["via_context"],
        "progressive_metadata": record["progressive_metadata"],
        "source_refs": record["source_refs"],
        "null_reason": record["null_reason"],
    }


def _build_routing_graph_record(
    stage: StageInfo,
    parsed_def: DefData,
    net: DefNet,
    idx: int,
    def_net_index: int,
    canonical_grid: dict,
    pins: list[dict[str, Any]],
    net_record: dict[str, Any] | None,
) -> dict[str, Any]:
    graph_key = f"{stage.name}:{net.name}"
    source = _workspace_relative_from_parsed_def(parsed_def)
    source_section = "SPECIALNETS" if net.special else "NETS"
    via_layers = _via_layers_by_name(parsed_def)
    vertex_ids: dict[tuple[float, float, str], int] = {}
    vertex_source_refs: dict[int, dict[str, Any]] = {}

    def vertex_id(point: tuple[float, float, str], source_ref: dict[str, Any]) -> int:
        if point not in vertex_ids:
            vertex_ids[point] = len(vertex_ids)
        vid = vertex_ids[point]
        current = vertex_source_refs.setdefault(
            vid, {"def": source, "wire_segment_ids": [], "via_names": [], "pin_refs": []}
        )
        if (
            source_ref.get("wire_segment_id") is not None
            and source_ref["wire_segment_id"] not in current["wire_segment_ids"]
        ):
            current["wire_segment_ids"].append(source_ref["wire_segment_id"])
        if source_ref.get("via_name") and source_ref["via_name"] not in current["via_names"]:
            current["via_names"].append(source_ref["via_name"])
        return vid

    edges: list[dict[str, Any]] = []
    for segment_index, wire in enumerate(net.wires):
        geometry = _wire_geometry(wire)
        intersections = _routing_graph_patch_intersections(
            geometry, canonical_grid, wire.layer, "via_point" if wire.via else "segment_overlap"
        )
        edge_id = len(edges)
        if wire.via:
            from_layer, to_layer = _resolve_via_transition_layers(
                wire, net.wires, segment_index, via_layers
            )
            source_id = vertex_id(
                (wire.x1, wire.y1, from_layer),
                {"wire_segment_id": segment_index, "via_name": wire.via},
            )
            target_id = vertex_id(
                (wire.x1, wire.y1, to_layer),
                {"wire_segment_id": segment_index, "via_name": wire.via},
            )
            via_geometry = {
                "layer": None,
                "start": {"x": wire.x1, "y": wire.y1, "layer": from_layer},
                "end": {"x": wire.x2, "y": wire.y2, "layer": to_layer},
                "direction": "point",
                "length": 0.0,
                "bbox": geometry["bbox"],
            }
            intersections = _routing_graph_patch_intersections(
                via_geometry, canonical_grid, f"{from_layer}/{to_layer}", "via_point"
            )
            edge_null_reason = {"wire_ref": "via_transition_has_no_wire_segment_ref"}
            wire_ref = None
            via_ref = {
                "via_name": wire.via,
                "coordinate": {"x": wire.x1, "y": wire.y1},
                "from_layer": from_layer,
                "to_layer": to_layer,
            }
        else:
            source_id = vertex_id(
                (wire.x1, wire.y1, wire.layer), {"wire_segment_id": segment_index}
            )
            target_id = vertex_id(
                (wire.x2, wire.y2, wire.layer), {"wire_segment_id": segment_index}
            )
            via_geometry = {
                "layer": geometry["layer"],
                "start": geometry["start"],
                "end": geometry["end"],
                "direction": geometry["direction"],
                "length": geometry["length"],
                "bbox": geometry["bbox"],
            }
            edge_null_reason = {"via_ref": "not_a_via_transition"}
            wire_ref = {
                "wire_key": f"{stage.name}:{source_section}:{net.name}:{segment_index}",
                "source_section": source_section,
                "segment_index": segment_index,
            }
            via_ref = None
        edges.append(
            {
                "edge_id": edge_id,
                "edge_key": f"{graph_key}:e{edge_id}",
                "edge_kind": "via_transition" if wire.via else "wire_segment",
                "source_vertex_id": source_id,
                "target_vertex_id": target_id,
                "geometry": via_geometry,
                "patch_intersections": intersections,
                "wire_ref": wire_ref,
                "via_ref": via_ref,
                "source_refs": {
                    "def": source,
                    "def_section": source_section,
                    "def_net_index": def_net_index,
                    "wire_index": segment_index,
                    "via_name": wire.via,
                },
                "null_reason": edge_null_reason,
            }
        )

    incident: dict[int, set[int]] = {vid: set() for vid in vertex_ids.values()}
    for edge in edges:
        incident.setdefault(edge["source_vertex_id"], set()).add(edge["edge_id"])
        incident.setdefault(edge["target_vertex_id"], set()).add(edge["edge_id"])

    terminal_matches = _match_routing_vertices_to_terminals(vertex_ids, pins, threshold=1000.0)
    vertices = []
    for (x, y, layer), vid in sorted(vertex_ids.items(), key=lambda item: item[1]):
        patch = _patch_for_point(canonical_grid.get("patches", []), {"x": x, "y": y})
        degree = len(incident.get(vid, set()))
        terminal_match = terminal_matches.get(vid, _unmatched_terminal_match())
        terminal_ref = terminal_match.get("terminal_ref")
        null_reason: dict[str, str] = {}
        if patch is None:
            null_reason["patch_id"] = "point_outside_canonical_grid"
        if terminal_ref is None:
            null_reason["terminal_ref"] = "unmatched_pin_anchor"
        source_refs = vertex_source_refs.get(
            vid, {"def": source, "wire_segment_ids": [], "via_names": [], "pin_refs": []}
        )
        if terminal_ref:
            source_refs = {**source_refs, "pin_refs": [terminal_ref.get("pin_key")]}
        vertices.append(
            {
                "vertex_id": vid,
                "vertex_key": f"{graph_key}:v{vid}",
                "coordinate": {"x": x, "y": y, "layer": layer},
                "vertex_kind": _routing_vertex_kind(
                    terminal_ref, source_refs.get("via_names", []), degree
                ),
                "degree": degree,
                "incident_edge_ids": sorted(incident.get(vid, set())),
                "patch_id": int(patch["patch_id"]) if patch else None,
                "terminal_ref": terminal_ref,
                "terminal_match": {k: v for k, v in terminal_match.items() if k != "terminal_ref"},
                "source_refs": source_refs,
                "null_reason": null_reason,
            }
        )

    patch_footprint = _routing_graph_patch_footprint(edges, vertices)
    comps = _connected_components(
        len(vertices), [(edge["source_vertex_id"], edge["target_vertex_id"]) for edge in edges]
    )
    identity = _net_identity(net)
    wire_edge_count = sum(1 for edge in edges if edge["edge_kind"] == "wire_segment")
    via_edge_count = sum(1 for edge in edges if edge["edge_kind"] == "via_transition")
    total_routed_length = sum(
        float(edge["geometry"].get("length") or 0.0)
        for edge in edges
        if edge["edge_kind"] == "wire_segment"
    )
    used_layers = sorted({str(layer) for edge in edges for layer in _edge_layers(edge) if layer})
    terminal_matching = _routing_graph_terminal_matching_summary(pins, vertices, threshold=1000.0)
    timing_context, timing_null = _routing_graph_timing_context(net.name, net_record)
    route_null_reason = {
        "route_context.detour_ratio": "missing_hpwl_proxy"
        if _routing_graph_detour_ratio(total_routed_length, net_record) is None
        else None,
        "route_context.local_final_overflow_summary": "missing_route_overflow_map",
        "route_context.drc_count": "missing_drc_join",
    }
    null_reason = {k: v for k, v in route_null_reason.items() if v}
    if timing_null:
        null_reason["timing_context"] = timing_null
    return {
        "id": idx,
        "stage": stage.name,
        "graph_key": graph_key,
        "net_key": net.name,
        "name": net.name,
        "source": source,
        "identity": {
            "graph_key": graph_key,
            "net_key": net.name,
            "name": net.name,
            "use": identity["use"],
            "source_section": source_section,
            "net_class": identity["net_class"],
            "is_signal": identity["is_signal"],
            "is_clock": identity["is_clock"],
            "is_reset": identity["is_reset"],
            "is_power_ground": identity["is_power_ground"],
            "is_special": identity["is_special"],
            "has_routed_geometry": bool(edges),
            "classification_source": identity["classification_source"],
        },
        "graph_semantics": _routing_graph_semantics(vertices, pins),
        "vertices": vertices,
        "edges": edges,
        "patch_footprint": patch_footprint,
        "graph_metrics": {
            "vertex_count": len(vertices),
            "edge_count": len(edges),
            "wire_edge_count": wire_edge_count,
            "via_edge_count": via_edge_count,
            "branch_vertex_count": sum(
                1
                for vertex in vertices
                if vertex["vertex_kind"] == "branch_point" or int(vertex.get("degree") or 0) >= 3
            ),
            "terminal_vertex_count": sum(1 for vertex in vertices if vertex.get("terminal_ref")),
            "connected_component_count": comps,
            "total_routed_length": total_routed_length,
            "layer_count": len(used_layers),
            "used_layers": used_layers,
            "max_vertex_degree": max(
                (int(vertex.get("degree") or 0) for vertex in vertices), default=0
            ),
            "has_cycle": _routing_graph_has_cycle(
                len(vertices),
                [(edge["source_vertex_id"], edge["target_vertex_id"]) for edge in edges],
            ),
        },
        "terminal_matching": terminal_matching,
        "timing_context": timing_context,
        "route_context": {
            "route_only_oracle": True,
            "source": source,
            "total_routed_length": total_routed_length,
            "via_count": via_edge_count,
            "wire_segment_count": wire_edge_count,
            "detour_ratio": _routing_graph_detour_ratio(total_routed_length, net_record),
            "local_final_overflow_summary": None,
            "drc_count": None,
        },
        "progressive_metadata": {
            "available_from": "route",
            "created_stage": "route",
            "exists_before_route": False,
            "not_available_before_route": True,
            "route_only_oracle": True,
            "pre_route_placeholder_policy": "empty_stage_file",
        },
        "source_refs": {
            "def": source,
            "def_section": source_section,
            "def_net_index": def_net_index,
            "net_vector_ref": f"vectors/nets/{stage.name}.jsonl:{net.name}",
            "wire_vector_refs": [
                edge["wire_ref"]["wire_key"] for edge in edges if edge.get("wire_ref")
            ],
            "pin_vector_refs": [
                vertex["terminal_ref"]["pin_key"]
                for vertex in vertices
                if vertex.get("terminal_ref")
            ],
            "timing_path_refs": [
                ref.get("path_key") or ref.get("path_id")
                for ref in timing_context.get("path_refs", [])
            ],
        },
        "coverage": {
            "has_routed_geometry": bool(edges),
            "vertex_count": len(vertices),
            "edge_count": len(edges),
            "wire_ref_count": sum(1 for edge in edges if edge.get("wire_ref")),
            "via_ref_count": sum(1 for edge in edges if edge.get("via_ref")),
            "terminal_match_count": terminal_matching["matched_terminal_count"],
            "terminal_unmatched_count": terminal_matching["unmatched_count"],
            "terminal_match_rate": terminal_matching["terminal_match_rate"],
            "edge_patch_intersection_count": sum(
                len(edge.get("patch_intersections", [])) for edge in edges
            ),
            "edge_patch_intersection_coverage": (
                sum(1 for edge in edges if edge.get("patch_intersections")) / len(edges)
            )
            if edges
            else None,
            "connected_component_count": comps,
        },
        "null_reason": null_reason,
    }


def _connected_components(vertex_count: int, edges: list[tuple[int, int]]) -> int:
    if vertex_count == 0:
        return 0
    parent = list(range(vertex_count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    return len({find(i) for i in range(vertex_count)})


def _ordered_routing_graph_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id", 0),
        "stage": record["stage"],
        "graph_key": record["graph_key"],
        "net_key": record["net_key"],
        "name": record["name"],
        "source": record["source"],
        "identity": record["identity"],
        "graph_semantics": record["graph_semantics"],
        "vertices": record["vertices"],
        "edges": record["edges"],
        "patch_footprint": record["patch_footprint"],
        "graph_metrics": record["graph_metrics"],
        "terminal_matching": record["terminal_matching"],
        "timing_context": record["timing_context"],
        "route_context": record["route_context"],
        "progressive_metadata": record["progressive_metadata"],
        "source_refs": record["source_refs"],
        "coverage": record["coverage"],
        "null_reason": record["null_reason"],
    }


def _neighbor_patch_ids(row: int, col: int, rows: int, cols: int) -> list[int]:
    ids = []
    for rr in range(max(0, row - 1), min(rows, row + 2)):
        for cc in range(max(0, col - 1), min(cols, col + 2)):
            ids.append(rr * cols + cc)
    return ids


def _adjacent_patch_ids(row: int, col: int, rows: int, cols: int) -> list[int]:
    out = []
    for rr, cc in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
        if 0 <= rr < rows and 0 <= cc < cols:
            out.append(rr * cols + cc)
    return out


def _distance_to_die_boundary(
    bbox: dict[str, Any], die_bbox: dict[str, Any] | None
) -> dict[str, float] | None:
    if not isinstance(die_bbox, dict):
        return None
    return {
        "left": float(bbox["llx"]) - float(die_bbox["llx"]),
        "right": float(die_bbox["urx"]) - float(bbox["urx"]),
        "bottom": float(bbox["lly"]) - float(die_bbox["lly"]),
        "top": float(die_bbox["ury"]) - float(bbox["ury"]),
    }


def _field_migration_checklist() -> list[dict[str, Any]]:
    rows = [
        (
            "vec_patches.md:identity",
            "preserved_as_table",
            ["patches"],
            "patch stable key and grid identity",
        ),
        (
            "vec_patches.md:geometry",
            "preserved_as_table",
            ["patches"],
            "patch bbox/center/die geometry",
        ),
        (
            "vec_patches.md:local_density.instance_count_center",
            "preserved_as_table",
            ["run_stage_patch_features.instance_count_center"],
            "patch density scalar",
        ),
        (
            "vec_patches.md:local_connectivity.cross_patch_net_count",
            "preserved_as_table",
            ["run_stage_patch_features.cross_patch_net_count"],
            "connectivity scalar",
        ),
        (
            "vec_patches.md:pre_route_estimators.rudy_horizontal",
            "preserved_as_table",
            ["run_stage_patch_features.rudy_horizontal"],
            "pre-route estimator scalar",
        ),
        (
            "vec_patches.md:timing_context",
            "preserved_as_table",
            ["run_stage_patch_features", "timing_paths", "semantic_blocks"],
            "timing summary and detailed path tables",
        ),
        (
            "vec_patches.md:drc_context",
            "preserved_as_table",
            ["run_stage_patch_features.drc_count", "semantic_blocks"],
            "DRC count and residual context",
        ),
        (
            "vec_patches.md:source_refs",
            "preserved_as_semantic_block",
            ["provenance", "semantic_blocks"],
            "source refs are rewritten to table/API refs",
        ),
        (
            "vec_patches.md:null_reason",
            "preserved_as_semantic_block",
            ["quality", "semantic_blocks"],
            "null reasons remain auditable",
        ),
        (
            "vec_patches.md:progressive_metadata",
            "preserved_as_table",
            ["stage_deltas", "semantic_blocks"],
            "progressive deltas and residual metadata",
        ),
        (
            "labels_route_native_demand_capacity.md:by_layer",
            "preserved_as_table",
            ["run_patch_route_label_layers"],
            "direction/layer attribution",
        ),
        (
            "vec_wires.md:patch_intersections",
            "preserved_as_table",
            ["wire_patch_intersections"],
            "wire per-patch contribution",
        ),
        (
            "vec_wires.md:route_context",
            "preserved_as_semantic_block",
            ["semantic_blocks", "wire_segments"],
            "route context is not embedded in core wire row",
        ),
        (
            "vec_nets.md:terminal_refs",
            "preserved_as_table",
            ["net_terminals"],
            "terminal refs split from net row",
        ),
        (
            "vec_timing_paths.md:path_points",
            "preserved_as_table",
            ["timing_path_points"],
            "point sequence",
        ),
        (
            "vec_timing_paths.md:wire_path_nodes",
            "preserved_as_table",
            ["timing_wire_path_nodes"],
            "wire path evidence",
        ),
        (
            "views_ml.md:leakage_policy",
            "preserved_as_view",
            ["views/ml/task_views.json"],
            "training leakage policy",
        ),
        (
            "views_agent.md:evidence_index",
            "preserved_as_view",
            [
                "views/agent/evidence_index.json",
                "views/agent/top_patches.json",
                "views/agent/top_nets.json",
            ],
            "agent evidence entrypoints",
        ),
    ]
    return [
        {
            "source_field_path": source,
            "status": status,
            "target": target,
            "preserved_reason": reason,
            "deprecated_with_reason": None,
        }
        for source, status, target, reason in rows
    ]


def _edge_position(row: int, col: int, rows: int, cols: int) -> str:
    vertical = "top" if row == 0 else "bottom" if row == rows - 1 else ""
    horizontal = "left" if col == 0 else "right" if col == cols - 1 else ""
    if vertical and horizontal:
        return "corner"
    if vertical:
        return f"{vertical}_edge"
    if horizontal:
        return f"{horizontal}_edge"
    return "interior"


def _via_layers_by_name(parsed_def: DefData) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for via in parsed_def.vias:
        layers = [
            str(layer) for layer in via.get("layers", []) if str(layer).upper().startswith("MET")
        ]
        if len(layers) >= 2:
            out[str(via.get("name"))] = (layers[0], layers[-1])
    return out


def _resolve_via_transition_layers(
    wire: DefWire, wires: list[DefWire], index: int, via_layers: dict[str, tuple[str, str]]
) -> tuple[str, str]:
    fallback = via_layers.get(str(wire.via or ""))
    if not fallback:
        fallback = _infer_routing_transition_layers_from_via_name(str(wire.via or ""))
    previous_layer = next(
        (wires[pos].layer for pos in range(index - 1, -1, -1) if not wires[pos].via), None
    )
    next_layer = next(
        (wires[pos].layer for pos in range(index + 1, len(wires)) if not wires[pos].via), None
    )
    if fallback:
        return fallback
    if previous_layer and next_layer and previous_layer != next_layer:
        return previous_layer, next_layer
    if previous_layer and next_layer and previous_layer == next_layer:
        return previous_layer, f"{previous_layer}_via_unknown_target"
    if previous_layer:
        return previous_layer, f"{previous_layer}_via_unknown_target"
    return wire.layer, f"{wire.layer}_via_unknown_target"


def _infer_routing_transition_layers_from_via_name(via_name: str) -> tuple[str, str] | None:
    metals = re.findall(r"MET\d+", via_name.upper())
    if len(metals) >= 2:
        unique = sorted(set(metals), key=lambda item: int(re.search(r"\d+", item).group(0)))
        if len(unique) >= 2:
            return unique[0], unique[-1]
    match = re.search(r"VIA(\d+)", via_name.upper())
    if match:
        lower = int(match.group(1))
        return f"MET{lower}", f"MET{lower + 1}"
    return None


def _routing_graph_patch_intersections(
    geometry: dict[str, Any], canonical_grid: dict, layer: str, kind: str
) -> list[dict[str, Any]]:
    raw = _wire_patch_intersections(geometry, canonical_grid)
    layer_value = layer
    if kind == "via_point":
        start_layer = geometry.get("start", {}).get("layer")
        end_layer = geometry.get("end", {}).get("layer")
        if start_layer and end_layer and start_layer != end_layer:
            layer_value = f"{start_layer}/{end_layer}"
    return [
        {
            "patch_id": int(item["patch_id"]),
            "layer": layer_value,
            "length": float(item.get("length") or 0.0),
            "area_proxy": item.get("area_proxy"),
            "intersection_kind": kind,
            **(
                {"row": item.get("row"), "col": item.get("col")}
                if item.get("row") is not None and item.get("col") is not None
                else {}
            ),
            **(
                {"length_fraction": item.get("length_fraction")}
                if "length_fraction" in item
                else {}
            ),
        }
        for item in raw
    ]


def _pin_bbox_contains_point(pin: dict[str, Any], x: float, y: float, layer: str) -> bool:
    geometry = pin.get("geometry", {}) if isinstance(pin.get("geometry"), dict) else {}
    for pin_shape in (
        geometry.get("absolute_shapes", [])
        if isinstance(geometry.get("absolute_shapes"), list)
        else []
    ):
        rect = pin_shape.get("rect") if isinstance(pin_shape, dict) else None
        shape_layer = pin_shape.get("layer") if isinstance(pin_shape, dict) else None
        if (
            isinstance(rect, dict)
            and (not shape_layer or str(shape_layer) == str(layer))
            and _point_in_bbox(x, y, rect)
        ):
            return True
    bbox = geometry.get("bbox")
    layers = (
        {str(item) for item in geometry.get("layers", [])}
        if isinstance(geometry.get("layers"), list)
        else set()
    )
    return (
        isinstance(bbox, dict)
        and (not layers or str(layer) in layers)
        and _point_in_bbox(x, y, bbox)
    )


def _pin_anchor_point(pin: dict[str, Any]) -> dict[str, float] | None:
    geometry = pin.get("geometry", {}) if isinstance(pin.get("geometry"), dict) else {}
    center = geometry.get("center")
    if isinstance(center, dict) and center.get("x") is not None and center.get("y") is not None:
        return {"x": float(center["x"]), "y": float(center["y"])}
    bbox = geometry.get("bbox")
    return _bbox_center(bbox) if isinstance(bbox, dict) else None


def _terminal_ref_from_pin(pin: dict[str, Any]) -> dict[str, Any]:
    connectivity = (
        pin.get("connectivity_context", {})
        if isinstance(pin.get("connectivity_context"), dict)
        else {}
    )
    identity = pin.get("identity", {}) if isinstance(pin.get("identity"), dict) else {}
    return {
        "pin_key": pin.get("pin_key"),
        "terminal_role": connectivity.get("pin_role") or "unknown",
        "pin_name": identity.get("pin_name"),
        "instance": identity.get("instance"),
    }


def _unmatched_terminal_match() -> dict[str, Any]:
    return {
        "match_status": "unmatched",
        "distance": None,
        "match_source": None,
        "terminal_ref": None,
    }


def _match_routing_vertices_to_terminals(
    vertex_ids: dict[tuple[float, float, str], int], pins: list[dict[str, Any]], threshold: float
) -> dict[int, dict[str, Any]]:
    matches = {vid: _unmatched_terminal_match() for vid in vertex_ids.values()}
    used_pins: set[str] = set()
    for (x, y, layer), vid in sorted(vertex_ids.items(), key=lambda item: item[1]):
        exact = next(
            (
                pin
                for pin in pins
                if str(pin.get("pin_key")) not in used_pins
                and _pin_bbox_contains_point(pin, x, y, layer)
            ),
            None,
        )
        if exact:
            used_pins.add(str(exact.get("pin_key")))
            matches[vid] = {
                "match_status": "exact_shape",
                "distance": 0.0,
                "match_source": "pin_absolute_shape",
                "terminal_ref": _terminal_ref_from_pin(exact),
            }
            continue
        candidates = []
        for pin in pins:
            if str(pin.get("pin_key")) in used_pins:
                continue
            point = _pin_anchor_point(pin)
            if not isinstance(point, dict):
                continue
            distance = abs(float(point["x"]) - x) + abs(float(point["y"]) - y)
            candidates.append((distance, str(pin.get("pin_key") or ""), pin))
        if candidates:
            distance, _, nearest = min(candidates, key=lambda item: (item[0], item[1]))
            if distance <= threshold:
                used_pins.add(str(nearest.get("pin_key")))
                matches[vid] = {
                    "match_status": "nearest_same_net",
                    "distance": distance,
                    "match_source": "nearest_same_net_pin",
                    "terminal_ref": _terminal_ref_from_pin(nearest),
                }
    return matches


def _routing_vertex_kind(
    terminal_ref: dict[str, Any] | None, via_names: list[str], degree: int
) -> str:
    if terminal_ref:
        return "terminal_anchor"
    if via_names:
        return "via_point"
    if degree >= 3:
        return "branch_point"
    if degree == 2:
        return "wire_junction"
    return "wire_endpoint"


def _routing_graph_patch_footprint(
    edges: list[dict[str, Any]], vertices: list[dict[str, Any]]
) -> dict[str, Any]:
    length_by_patch: dict[int, float] = {}
    layer_usage: dict[tuple[int, str], dict[str, Any]] = {}
    touched_patch_ids = {
        int(vertex["patch_id"]) for vertex in vertices if vertex.get("patch_id") is not None
    }
    layers: set[str] = set()
    for edge in edges:
        edge_kind = edge.get("edge_kind")
        edge_layers = _edge_layers(edge)
        layers.update(edge_layers)
        for item in edge.get("patch_intersections", []):
            patch_id = int(item["patch_id"])
            layer = str(item.get("layer") or edge.get("geometry", {}).get("layer") or "unknown")
            length = float(item.get("length") or 0.0)
            touched_patch_ids.add(patch_id)
            length_by_patch[patch_id] = length_by_patch.get(patch_id, 0.0) + length
            stat = layer_usage.setdefault(
                (patch_id, layer),
                {
                    "patch_id": patch_id,
                    "layer": layer,
                    "routed_length": 0.0,
                    "wire_edge_count": 0,
                    "via_edge_count": 0,
                },
            )
            stat["routed_length"] += length
            if edge_kind == "via_transition":
                stat["via_edge_count"] += 1
            else:
                stat["wire_edge_count"] += 1
    dominant_patch_id = (
        max(length_by_patch.items(), key=lambda item: (item[1], -item[0]))[0]
        if length_by_patch
        else (min(touched_patch_ids) if touched_patch_ids else None)
    )
    return {
        "primary_patch_id": dominant_patch_id,
        "dominant_patch_id": dominant_patch_id,
        "touched_patch_ids": sorted(touched_patch_ids),
        "touched_patch_count": len(touched_patch_ids),
        "total_routed_length_by_patch": {
            str(pid): length_by_patch.get(pid, 0.0) for pid in sorted(touched_patch_ids)
        },
        "layer_usage_by_patch": sorted(
            layer_usage.values(), key=lambda item: (item["patch_id"], item["layer"])
        ),
        "touched_layer_ids": sorted(layers),
        "cross_patch": len(touched_patch_ids) > 1,
    }


def _edge_layers(edge: dict[str, Any]) -> list[str]:
    geometry = edge.get("geometry", {}) if isinstance(edge.get("geometry"), dict) else {}
    if edge.get("edge_kind") == "via_transition":
        layers = [geometry.get("start", {}).get("layer"), geometry.get("end", {}).get("layer")]
        return [str(layer) for layer in layers if layer]
    layer = geometry.get("layer")
    return [str(layer)] if layer else []


def _routing_graph_terminal_matching_summary(
    pins: list[dict[str, Any]], vertices: list[dict[str, Any]], threshold: float
) -> dict[str, Any]:
    exact = sum(
        1
        for vertex in vertices
        if vertex.get("terminal_match", {}).get("match_status") == "exact_shape"
    )
    nearest = sum(
        1
        for vertex in vertices
        if vertex.get("terminal_match", {}).get("match_status") == "nearest_same_net"
    )
    matched = exact + nearest
    expected = len(pins)
    unmatched = max(0, expected - matched)
    return {
        "strategy": "exact_shape_then_nearest_same_net",
        "nearest_terminal_distance_threshold": threshold,
        "exact_match_count": exact,
        "nearest_match_count": nearest,
        "unmatched_count": unmatched,
        "matched_terminal_count": matched,
        "expected_terminal_count": expected,
        "terminal_match_rate": (matched / expected) if expected else None,
    }


def _routing_graph_semantics(
    vertices: list[dict[str, Any]], pins: list[dict[str, Any]]
) -> dict[str, Any]:
    role_by_pin = {
        str(pin.get("pin_key")): pin.get("connectivity_context", {}).get("pin_role")
        for pin in pins
        if isinstance(pin.get("connectivity_context"), dict)
    }
    driver_refs = []
    sink_refs = []
    for vertex in vertices:
        ref = vertex.get("terminal_ref")
        if not isinstance(ref, dict):
            continue
        item = {"pin_key": ref.get("pin_key"), "vertex_id": vertex.get("vertex_id")}
        role = role_by_pin.get(str(ref.get("pin_key"))) or ref.get("terminal_role")
        if role == "driver":
            driver_refs.append(item)
        elif role == "sink":
            sink_refs.append(item)
    root_vertex_id = driver_refs[0]["vertex_id"] if len(driver_refs) == 1 else None
    return {
        "topology_direction": "undirected",
        "root_vertex_id": root_vertex_id,
        "root_source": "driver_terminal_match" if root_vertex_id is not None else "unknown",
        "driver_terminal_refs": driver_refs,
        "sink_terminal_refs": sink_refs,
        "direction_annotation_source": "pins_connectivity_context"
        if pins
        else "missing_pin_context",
    }


def _routing_graph_timing_context(
    net_name: str, net_record: dict[str, Any] | None
) -> tuple[dict[str, Any], str | None]:
    source_ctx = (
        net_record.get("timing_context", {})
        if isinstance(net_record, dict) and isinstance(net_record.get("timing_context"), dict)
        else {}
    )
    available = bool(source_ctx.get("available"))
    path_refs = source_ctx.get("path_refs") if isinstance(source_ctx.get("path_refs"), list) else []
    timing_path_count = int(source_ctx.get("timing_path_count") or len(path_refs) or 0)
    context = {
        "available": available,
        "is_timing_critical_net": bool(source_ctx.get("is_on_critical_path") or path_refs),
        "timing_path_count": timing_path_count,
        "worst_slack_seen": source_ctx.get("worst_slack_seen"),
        "min_slack_seen": source_ctx.get("worst_slack_seen"),
        "max_criticality_seen": None,
        "path_refs": path_refs,
        "source": source_ctx.get("source"),
    }
    if not available:
        return context, "missing_sta_artifact"
    if timing_path_count == 0:
        return context, "net_not_found_in_timing_paths"
    return context, None


def _routing_graph_detour_ratio(
    total_routed_length: float, net_record: dict[str, Any] | None
) -> float | None:
    hpwl = None
    if isinstance(net_record, dict):
        hpwl = (
            net_record.get("geometry_proxy", {}).get("hpwl")
            if isinstance(net_record.get("geometry_proxy"), dict)
            else None
        )
    value = _to_float(hpwl)
    if value and value > 0:
        return total_routed_length / value
    return None


def _routing_graph_has_cycle(vertex_count: int, edges: list[tuple[int, int]]) -> bool:
    parent = list(range(vertex_count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a == b:
            return True
        ra, rb = find(a), find(b)
        if ra == rb:
            return True
        parent[rb] = ra
    return False


def _empty_layer_item(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "track_axes": [],
        "stage_sources": {},
        "source_refs_def": [],
        "source_refs_rt_log": [],
    }


def _empty_via_item(name: str, *, source: str) -> dict[str, Any]:
    return {
        "name": name,
        "layers": [],
        "source": source,
        "usage_count": 0,
        "stage_usage_counts": {},
        "stage_definition_counts": {},
        "stage_sources": {},
        "source_refs_def": [],
    }


def _normalize_direction(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"h", "horizontal"}:
        return "horizontal"
    if text in {"v", "vertical"}:
        return "vertical"
    if text:
        return "unknown"
    return None


def _layer_type(name: str, lef_layer: Any = None) -> str:
    lef_type = getattr(lef_layer, "layer_type", None)
    if lef_type:
        normalized = str(lef_type).lower()
        if normalized == "routing":
            return "routing"
        if normalized == "cut":
            return "cut"
        if normalized == "masterslice":
            return "masterslice"
        if normalized == "implant":
            return "implant"
        return normalized
    upper = name.upper()
    if upper.startswith(("MET", "M")) or upper in {"RDL", "T4M2"}:
        return "routing"
    if "VIA" in upper or upper in {"CT", "RV", "T4V2"}:
        return "cut"
    return "unknown"


def _layer_order_from_name(name: str) -> int | None:
    upper = name.upper()
    if upper == "CT":
        return 5
    if upper.startswith("VIA"):
        digits = re.findall(r"\d+", upper)
        return int(digits[0]) * 2 + 6 if digits else None
    if upper.startswith("MET"):
        digits = re.findall(r"\d+", upper)
        return int(digits[0]) * 2 + 5 if digits else None
    if upper == "T4V2":
        return 16
    if upper == "T4M2":
        return 17
    if upper == "RV":
        return 18
    if upper == "RDL":
        return 19
    return None


def _layer_order_sort_key(item: dict[str, Any]) -> int:
    value = item.get("order")
    if value is None:
        value = _layer_order_from_name(str(item.get("name", "")))
    return int(value) if value is not None else 10_000


def _layer_pitch_from_tracks(
    preferred_direction: str | None, steps_by_axis: dict[str, list[float]]
) -> float | None:
    axis = (
        "Y"
        if preferred_direction == "horizontal"
        else "X"
        if preferred_direction == "vertical"
        else None
    )
    candidates = (
        steps_by_axis.get(axis or "", [])
        if axis
        else [step for values in steps_by_axis.values() for step in values]
    )
    if not candidates:
        return None
    return sorted(candidates)[len(candidates) // 2]


def _estimated_track_count(
    preferred_direction: str | None, track_count_by_axis: dict[str, int]
) -> int | None:
    if not track_count_by_axis:
        return None
    axis = (
        "Y"
        if preferred_direction == "horizontal"
        else "X"
        if preferred_direction == "vertical"
        else None
    )
    if axis and axis in track_count_by_axis:
        return track_count_by_axis[axis]
    return max(track_count_by_axis.values())


def _stage_track_variants(axes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variants: dict[tuple[Any, Any, Any, Any], set[str]] = {}
    for axis in axes:
        key = (axis.get("axis"), axis.get("start"), axis.get("count"), axis.get("step"))
        variants.setdefault(key, set()).add(str(axis.get("stage")))
    return [
        {"axis": key[0], "start": key[1], "count": key[2], "step": key[3], "stages": sorted(stages)}
        for key, stages in sorted(
            variants.items(), key=lambda item: tuple(str(part) for part in item[0])
        )
    ]


def _stage_sources(raw: dict[str, Any], stage_names: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for stage in [*stage_names, "library"]:
        values = raw.get(stage)
        if values:
            result[stage] = sorted(str(value) for value in values)
    return result


def _join_sources(values: list[str | None]) -> str | None:
    present = [value for value in values if value]
    return "+".join(present) if present else None


def _unique_dicts(items: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out = []
    for item in items:
        key = tuple(item.get(k) for k in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append({k: item.get(k) for k in keys if k in item and item.get(k) is not None})
    return out


def _physical_class_from_lef_or_name(name: str, lef_macro: Any = None) -> str:
    macro_class = str(getattr(lef_macro, "macro_class", "") or "").upper()
    if macro_class in {"BLOCK", "RING", "COVER"}:
        return "macro"
    if macro_class in {"PAD", "ENDCAP"}:
        return "io" if macro_class == "PAD" else "physical_only"
    return _physical_class(name, name)


def _is_buffer_like_cell_name(name: str, master: str) -> bool:
    lower = f"{name} {master}".lower()
    return any(token in lower for token in ("buf", "inv", "clkbuf", "fanout"))


def _is_clock_pin_name(name: str) -> bool:
    lower = name.lower()
    return lower in {"clk", "clock", "ck"} or "clk" in lower or "clock" in lower


def _is_power_ground_pin_name(name: str) -> bool:
    lower = name.lower()
    return lower.startswith(("vdd", "vss", "vcc", "gnd", "power", "ground")) or lower in {
        "vpwr",
        "vgnd",
    }


def _library_from_lef_source(source: Any) -> str | None:
    if not source:
        return None
    return Path(str(source)).stem


def _infer_via_stack_layers_from_name(
    name: str, layer_items: dict[str, Any] | None = None
) -> list[str]:
    layer_items = layer_items or {}
    upper = name.upper()
    metals = re.findall(r"MET\d+", upper)
    if len(metals) >= 2:
        ordered = sorted(set(metals), key=lambda item: _layer_order_from_name(item) or 0)
        via_digits = re.findall(r"VIA(\d+)", upper)
        cut = (
            f"VIA{via_digits[-1]}"
            if via_digits
            else _cut_between_routing_layers(ordered[0], ordered[-1])
        )
        return [ordered[0], cut, ordered[-1]] if cut else ordered
    via_digits = re.findall(r"VIA(\d+)", upper)
    if via_digits:
        bottom = f"MET{via_digits[-1]}"
        top = f"MET{int(via_digits[-1]) + 1}"
        if bottom in layer_items or top in layer_items:
            return [bottom, f"VIA{via_digits[-1]}", top]
    return []


def _cut_between_routing_layers(bottom: str, top: str) -> str | None:
    bottom_digits = re.findall(r"\d+", bottom)
    top_digits = re.findall(r"\d+", top)
    if bottom_digits and top_digits and int(top_digits[0]) == int(bottom_digits[0]) + 1:
        return f"VIA{bottom_digits[0]}"
    return None


def _via_layer_stack(
    layers: list[str], layer_order_by_name: dict[str, Any], stack_source: str
) -> dict[str, Any]:
    routing_layers = [layer for layer in layers if _layer_type(layer) == "routing"]
    cut_layers = [layer for layer in layers if _layer_type(layer) == "cut"]
    routing_layers = sorted(
        routing_layers,
        key=lambda layer: layer_order_by_name.get(layer)
        if layer_order_by_name.get(layer) is not None
        else _layer_order_from_name(layer) or 10_000,
    )
    return {
        "layers": layers,
        "bottom_layer": routing_layers[0] if routing_layers else None,
        "cut_layer": cut_layers[0] if cut_layers else None,
        "top_layer": routing_layers[-1] if routing_layers else None,
        "stack_source": stack_source,
    }


def _via_geometry(
    layer_stack: dict[str, Any], rects_by_layer: dict[str, list[dict[str, float]]]
) -> dict[str, Any]:
    bottom_rect = _first_rect(rects_by_layer, layer_stack.get("bottom_layer"))
    cut_rect = _first_rect(rects_by_layer, layer_stack.get("cut_layer"))
    top_rect = _first_rect(rects_by_layer, layer_stack.get("top_layer"))
    cut_count = (
        len(rects_by_layer.get(str(layer_stack.get("cut_layer")), []))
        if layer_stack.get("cut_layer")
        else None
    )
    if cut_count == 0:
        cut_count = None
    status = (
        "exact"
        if bottom_rect and cut_rect and top_rect
        else "partial"
        if any([bottom_rect, cut_rect, top_rect])
        else "name_only"
        if layer_stack.get("layers")
        else "missing"
    )
    return {
        "bottom_rect": bottom_rect,
        "cut_rect": cut_rect,
        "top_rect": top_rect,
        "row": None,
        "col": None,
        "cut_count": cut_count,
        "geometry_status": status,
    }


def _first_rect(
    rects_by_layer: dict[str, list[dict[str, float]]], layer: Any
) -> dict[str, float] | None:
    if not layer:
        return None
    rects = rects_by_layer.get(str(layer)) or []
    return rects[0] if rects else None
