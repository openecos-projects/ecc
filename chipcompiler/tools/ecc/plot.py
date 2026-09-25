#!/usr/bin/env python
import concurrent.futures
import os

from tqdm import tqdm

from chipcompiler.data import EccStep, StepEnum, Workspace
from chipcompiler.utility import (
    json_read,
    plot_csv_map,
)


class ECCToolsPlot:
    def __init__(self, workspace: Workspace, step: EccStep):
        self.workspace = workspace
        self.step = step

    def plot(self) -> bool:
        state = True
        match self.step.name:
            case StepEnum.PLACEMENT.value:
                state = state & self.plot_placement_heatmap()
            case StepEnum.CTS.value:
                state = state & self.plot_placement_heatmap()
            case StepEnum.DRC.value:
                state = state & self.plot_drc_statis()
            case (
                StepEnum.POST_FLOORPLAN.value
                | StepEnum.LEGALIZATION.value
                | StepEnum.ROUTING.value
                | StepEnum.LVS.value
                | StepEnum.FILLER.value
            ):
                pass

            case _:
                self.workspace.logger.warning(f"Step {self.step.name} not supported for plotting.")

        return state

    def plot_placement_heatmap(self) -> bool:
        json_map_path = self.step.feature.map or ""
        json_map = json_read(json_map_path)
        if not json_map:
            return False

        # density map
        csv_list = []
        csv_list.extend(
            [
                json_map.get("Density", {}).get("cell", {}).get("allcell_density", ""),
                json_map.get("Density", {}).get("cell", {}).get("macro_density", ""),
                json_map.get("Density", {}).get("cell", {}).get("stdcell_density", ""),
                json_map.get("Density", {}).get("margin", {}).get("horizontal", ""),
                json_map.get("Density", {}).get("margin", {}).get("union", ""),
                json_map.get("Density", {}).get("margin", {}).get("vertical", ""),
                json_map.get("Density", {}).get("net", {}).get("allnet_density", ""),
                json_map.get("Density", {}).get("net", {}).get("global_net_density", ""),
                json_map.get("Density", {}).get("net", {}).get("local_net_density", ""),
                json_map.get("Density", {}).get("pin", {}).get("allcell_pin_density", ""),
                json_map.get("Density", {}).get("pin", {}).get("macro_pin_density", ""),
                json_map.get("Density", {}).get("pin", {}).get("stdcell_pin_density", ""),
                json_map.get("Congestion", {}).get("map", {}).get("egr", {}).get("horizontal", ""),
                json_map.get("Congestion", {}).get("map", {}).get("egr", {}).get("union", ""),
                json_map.get("Congestion", {}).get("map", {}).get("egr", {}).get("vertical", ""),
                json_map.get("Congestion", {})
                .get("map", {})
                .get("lutrudy", {})
                .get("horizontal", ""),
                json_map.get("Congestion", {}).get("map", {}).get("lutrudy", {}).get("union", ""),
                json_map.get("Congestion", {})
                .get("map", {})
                .get("lutrudy", {})
                .get("vertical", ""),
                json_map.get("Congestion", {}).get("map", {}).get("rudy", {}).get("horizontal", ""),
                json_map.get("Congestion", {}).get("map", {}).get("rudy", {}).get("union", ""),
                json_map.get("Congestion", {}).get("map", {}).get("rudy", {}).get("vertical", ""),
            ]
        )
        self.plot_array_maps(input_paths=csv_list)

        return True

    def plot_array_maps(self, input_paths: list[str]):
        """
        Plot array maps from multiple CSV files using multi-threading with progress bar.

        Args:
            input_paths (list[str]): List of paths to input CSV files.
        """
        if not input_paths:
            return

        # Filter out invalid paths
        valid_paths = [
            path
            for path in input_paths
            if path and os.path.exists(path) and path.lower().endswith(".csv")
        ]

        if not valid_paths:
            self.workspace.logger.warning("No valid CSV files found for plotting.")
            return

        # Use ThreadPoolExecutor for multi-threading with progress bar (limit to 10 threads)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Create a progress bar
            list(
                tqdm(
                    executor.map(plot_csv_map, valid_paths),
                    total=len(valid_paths),
                    desc="Plotting array maps",
                    unit="file",
                )
            )

    def plot_drc_statis(self) -> bool:
        # build layer header
        layers = []
        layer_dict = {}  # layer drc number distribution
        db_json = json_read(self.step.feature.db or "")

        # Get cut layers
        for item in db_json.get("Layers", {}).get("cut_layers", []):
            layer_dict[item.get("layer_name")] = 0
            layers.append(item)

        # Get routing layers
        for item in db_json.get("Layers", {}).get("routing_layers", []):
            layer_dict[item.get("layer_name")] = 0
            layers.append(item)

        # Sort layers by layer_order
        def cmp_layer(item):
            return item.get("layer_order", 0)

        sorted_layers = sorted(layers, key=cmp_layer)

        # Get layer names in order
        layer_names = [layer.get("layer_name") for layer in sorted_layers]
        layer_names.append("total")

        # build drc statis
        drc_json = json_read(self.step.feature.step or "")
        if len(drc_json) == 0:
            return False

        # Get DRC distribution data
        drc_distribution = drc_json.get("drc", {}).get("distribution", {})

        # Build drc_statis dictionary
        drc_statis = {}
        import copy

        drc_total_dict = copy.deepcopy(layer_dict)

        # Get DRC distribution data
        drc_distribution = drc_json.get("drc", {}).get("distribution", {})
        if isinstance(drc_distribution, dict):
            for drc_type, drc_data in drc_distribution.items():
                drc_statis[drc_type] = copy.deepcopy(layer_dict)

                for layer, layer_data in drc_data.get("layers", {}).items():
                    drc_statis[drc_type][layer] = drc_statis[drc_type][layer] + layer_data.get(
                        "number", 0
                    )
                    drc_total_dict[layer] = drc_total_dict.get(layer, 0) + layer_data.get(
                        "number", 0
                    )
                drc_statis[drc_type]["total"] = sum(drc_statis[drc_type].values())

        drc_total_dict["total"] = sum(drc_total_dict.values())
        drc_statis["total"] = drc_total_dict

        # Save drc_statis to CSV file
        import csv

        statis_csv = str(self.step.analysis.statis_csv or "")
        # Write to CSV file
        with open(statis_csv, "w", newline="") as csvfile:
            # Define headers: first column is "Type", followed by layer names
            csv_headers = ["Type"] + layer_names
            writer = csv.DictWriter(csvfile, fieldnames=csv_headers)

            # Write headers
            writer.writeheader()

            # Write data rows
            for drc_type, layer_counts in drc_statis.items():
                row = {"Type": drc_type}
                # Add counts for each layer, defaulting to 0 if not present
                for layer in layer_names:
                    row[layer] = layer_counts.get(layer, 0)
                writer.writerow(row)

        return True
