#!/usr/bin/env python
import copy
import csv

from chipcompiler.data import EccStep, Workspace
from chipcompiler.utility import json_read


class ECCToolsPlot:
    def __init__(self, workspace: Workspace, step: EccStep):
        self.workspace = workspace
        self.step = step

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
