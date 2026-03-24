#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os

import concurrent.futures
from tqdm import tqdm
from chipcompiler.data import WorkspaceStep, Workspace, Parameters, StepEnum
from chipcompiler.utility import (
    json_read, 
    plot_csv_map, 
    plot_csv_table, 
    plot_csv_bar_chart,
    plot_metrics
)

import matplotlib.pyplot as plt
import numpy as np

class ECCToolsPlot:
    def __init__(self, workspace: Workspace, step: WorkspaceStep):
        self.workspace = workspace
        self.step = step
    
    def plot(self) -> bool:
        state = True
        match self.step.name:
            case StepEnum.FLOORPLAN.value:
                state = state & self.default_plot()
            case StepEnum.NETLIST_OPT.value:
                state = state & self.default_plot() 
            case StepEnum.PLACEMENT.value:
                state = state & self.default_plot() & self.plot_placement_heatmap() 
            case StepEnum.CTS.value:
                state = state & self.default_plot() & self.plot_placement_heatmap()
            case StepEnum.TIMING_OPT_DRV.value:
                state = state & self.default_plot()
            case StepEnum.TIMING_OPT_HOLD.value:
                state = state & self.default_plot()
            case StepEnum.LEGALIZATION.value:
                state = state & self.default_plot()
            case StepEnum.ROUTING.value:
                state = state & self.default_plot() & self.plot_routing_heatmap() & self.plot_layer_via_distribution() & self.plot_layer_wire_distribution()
            case StepEnum.DRC.value:
                state = state & self.default_plot() & self.plot_drc_statis() & self.plot_layer_via_distribution() & self.plot_layer_wire_distribution()
            case StepEnum.FILLER.value:
                state = state & self.default_plot() & self.plot_layer_via_distribution() & self.plot_layer_wire_distribution()
                
            case default:
                self.workspace.logger.warning(f"Step {self.step.name} not supported for plotting.")
        
        return state
    
    def default_plot(self) -> bool:
        return self.plot_step_metrics() & self.plot_instance_distribution() & self.plot_pin_distribution()
    
    def plot_step_metrics(self) -> bool:
        # generate report image and dscription
        json_path = self.step.analysis.get('metrics', "")
        image_path = json_path.replace(".json", ".png")
        metrics = json_read(json_path)
        return plot_metrics(metrics=metrics, output_path=image_path)

    def plot_placement_heatmap(self) -> bool:
        json_map_path = self.step.feature.get("map", "")
        json_map = json_read(json_map_path)
        if not json_map:
            return False
        
        # density map
        csv_list = []
        csv_list.extend([
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
            json_map.get("Congestion", {}).get("map", {}).get("lutrudy", {}).get("horizontal", ""),
            json_map.get("Congestion", {}).get("map", {}).get("lutrudy", {}).get("union", ""),
            json_map.get("Congestion", {}).get("map", {}).get("lutrudy", {}).get("vertical", ""),
            json_map.get("Congestion", {}).get("map", {}).get("rudy", {}).get("horizontal", ""),
            json_map.get("Congestion", {}).get("map", {}).get("rudy", {}).get("union", ""),
            json_map.get("Congestion", {}).get("map", {}).get("rudy", {}).get("vertical", "")
        ])
        self.plot_array_maps(input_paths=csv_list)
        
        return True
    
    def plot_routing_heatmap(self) -> bool:
        data_dir = self.step.data.get(f"{StepEnum.ROUTING.value}", "")
        if not os.path.exists(data_dir):
            return False
        
        csv_list = []
        for root, dirs, files in os.walk(data_dir):
            for file in files:
                if file.endswith(".csv"):
                    csv_path = os.path.join(root, file)
                    csv_list.append(csv_path)
        
        self.plot_array_maps(input_paths=csv_list)
                    
        return True
    
    def plot_array_maps(self, input_paths : list[str]):
        """
        Plot array maps from multiple CSV files using multi-threading with progress bar.
        
        Args:
            input_paths (list[str]): List of paths to input CSV files.
        """
        if not input_paths:
            return
        
        # Filter out invalid paths
        valid_paths = [path for path in input_paths if path and os.path.exists(path) and path.lower().endswith(".csv")]
        
        if not valid_paths:
            self.workspace.logger.warning("No valid CSV files found for plotting.")
            return
        
        # Use ThreadPoolExecutor for multi-threading with progress bar (limit to 10 threads)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Create a progress bar
            results = list(tqdm(
                executor.map(plot_csv_map, valid_paths),
                total=len(valid_paths),
                desc="Plotting array maps",
                unit="file"
            ))
    
    def plot_drc_statis(self) -> bool:
        # build layer header
        layers = []
        layer_dict = {} # layer drc number distribution
        db_json = json_read(self.step.feature.get("db", ""))
        
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
        drc_json = json_read(self.step.feature.get("step", ""))
        if len(drc_json) == 0:
            return False
        
        # Get DRC distribution data
        drc_distribution = drc_json.get("drc", {}).get("distribution", {})
        
        # Build drc_statis dictionary
        drc_statis = {}
        import copy
        drc_total_dict= copy.deepcopy(layer_dict)
        
        # Get DRC distribution data
        drc_distribution = drc_json.get("drc", {}).get("distribution", {})
        if isinstance(drc_distribution, dict):
            for drc_type, drc_data in drc_distribution.items():
                drc_statis[drc_type] = copy.deepcopy(layer_dict)
                
                for layer, layer_data in drc_data.get("layers", {}).items():
                    drc_statis[drc_type][layer] = drc_statis[drc_type][layer] + layer_data.get("number", 0)
                    drc_total_dict[layer] = drc_total_dict.get(layer, 0) + + layer_data.get("number", 0)
        
        drc_total_dict["total"] = drc_json.get("drc", {}).get("number", 0)
        drc_statis["total"] = drc_total_dict
        
        # Save drc_statis to CSV file
        import csv
        statis_csv = self.step.analysis.get("statis_csv", "")
        # Write to CSV file
        with open(statis_csv, 'w', newline='') as csvfile:
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
        
        # Plot the CSV table
        # plot_csv_table(input_path=statis_csv)
        output_path=statis_csv.replace(".csv", ".png")
        plot_csv_bar_chart(input_path=statis_csv, output_path=output_path, title="DRC Violation Distribution by Layer", xlabel="DRC Type", ylabel="Violation Count", integer_yaxis=True)

        self.workspace.home.set_metrics_drc_dist(image_path=output_path)
        
        return True
    
    def plot_instance_distribution(self) -> bool:
        data = json_read(self.step.feature.get("db", ""))
        if not data or "Instances" not in data:
            self.workspace.logger.warning("No Instances data found for plotting.")
            return False
        
        instances_data = data["Instances"]
        instance_types = list(instances_data.keys())
        
        if not instance_types:
            self.workspace.logger.warning("No instance types found for plotting.")
            return False
        
        # Prepare data for plotting
        plot_data = {}
        for inst_type in instance_types:
            plot_data[inst_type] = {
                "num": instances_data[inst_type].get("num", 0),
                "area": instances_data[inst_type].get("area", 0),
                "pin_num": instances_data[inst_type].get("pin_num", 0)
            }
        
        # Save the plot
        db_path = self.step.feature.get("db", "")
        if db_path:
            image_path = db_path.replace(".json", ".inst_dist.png")
            from chipcompiler.utility import plot_bar_chart
            
            success = plot_bar_chart(
                data=plot_data,
                output_path=image_path,
                title="Instance Distribution by Number, Area and Pin Count",
                xlabel="Instance Type",
                ylabel="Value",
                integer_yaxis=False
            )
            
            if success:
                # update home page metrics
                if hasattr(self.workspace, 'home') and hasattr(self.workspace.home, 'set_metrics_inst_dist'):
                    self.workspace.home.set_metrics_inst_dist(image_path=image_path)
            else:
                self.workspace.logger.warning("Failed to generate instance distribution plot")
                return False
        else:
            self.workspace.logger.warning("Cannot save plot: no db path provided")
            return False
        
        return True
    
    def plot_pin_distribution(self) -> bool:
        data = json_read(self.step.feature.get("db", ""))
        if not data or "Pins" not in data:
            self.workspace.logger.warning("No Pins data found for plotting.")
            return False
        
        pins_data = data["Pins"]
        pin_distribution = pins_data.get("pin_distribution", [])
        
        if not pin_distribution:
            self.workspace.logger.warning("No pin distribution data found for plotting.")
            return False
        
        # Prepare data for plotting
        plot_data = {}
        for item in pin_distribution:
            pin_num = item.get("pin_num", "unknown")
            plot_data[f"{pin_num}"] = {
                "inst_num": item.get("inst_num", 0),
                "net_num": item.get("net_num", 0)
            }
        
        # Save the plot
        db_path = self.step.feature.get("db", "")
        if db_path:
            image_path = db_path.replace(".json", ".pin_dist.png")
            from chipcompiler.utility import plot_bar_chart
            
            success = plot_bar_chart(
                data=plot_data,
                output_path=image_path,
                title="Pin Distribution by Instance and Net Count",
                xlabel="pin number",
                ylabel="distribution",
                integer_yaxis=True
            )
            
            if success:
                self.workspace.home.set_metrics_pin_dist(image_path=image_path)
            else:
                self.workspace.logger.warning("Failed to generate pin distribution plot")
                return False
        else:
            self.workspace.logger.warning("Cannot save plot: no db path provided")
            return False
        
        return True
    
    def plot_layer_via_distribution(self) -> bool:
        data = json_read(self.step.feature.get("db", ""))
        if not data or "Layers" not in data:
            self.workspace.logger.warning("No Layers data found for plotting.")
            return False
        
        layers_data = data["Layers"]
        layer_via_distribution = layers_data.get("cut_layers", [])
        
        if not layer_via_distribution:
            self.workspace.logger.warning("No layer via distribution data found for plotting.")
            return False
        
        # Prepare data for plotting
        plot_data = {}
        for item in layer_via_distribution:
            layer_name = item.get("layer_name", "unknown")
            plot_data[f"{layer_name}"] = {
                "via_num": item.get("via_num", 0)
            }
        
        # Save the plot
        db_path = self.step.feature.get("db", "")
        if db_path:
            image_path = db_path.replace(".json", ".layer_via_dist.png")
            from chipcompiler.utility import plot_bar_chart
            
            success = plot_bar_chart(
                data=plot_data,
                output_path=image_path,
                title="Layer Via Distribution",
                xlabel="Layer Name",
                ylabel="Via Number",
                integer_yaxis=True
            )
            
            if success:
                # update home page metrics
                if hasattr(self.workspace, 'home') and hasattr(self.workspace.home, 'set_metrics_layer_via_dist'):
                    self.workspace.home.set_metrics_layer_via_dist(image_path=image_path)
            else:
                self.workspace.logger.warning("Failed to generate layer via distribution plot")
                return False
        else:
            self.workspace.logger.warning("Cannot save plot: no db path provided")
            return False
        
        return True
    
    def plot_layer_wire_distribution(self) -> bool:
        data = json_read(self.step.feature.get("db", ""))
        if not data or "Layers" not in data:
            self.workspace.logger.warning("No Layers data found for plotting.")
            return False
        
        layers_data = data["Layers"]
        layer_wire_distribution = layers_data.get("routing_layers", [])
        
        if not layer_wire_distribution:
            self.workspace.logger.warning("No layer wire distribution data found for plotting.")
            return False
        
        # Prepare data for plotting
        plot_data = {}
        for item in layer_wire_distribution:
            layer_name = item.get("layer_name", "unknown")
            plot_data[f"{layer_name}"] = {
                "wire_len": item.get("wire_len", 0)
            }
        
        # Save the plot
        db_path = self.step.feature.get("db", "")
        if db_path:
            image_path = db_path.replace(".json", ".layer_wire_dist.png")
            from chipcompiler.utility import plot_bar_chart
            
            success = plot_bar_chart(
                data=plot_data,
                output_path=image_path,
                title="Layer Wire Distribution",
                xlabel="Layer Name",
                ylabel="Wire Length",
                integer_yaxis=False
            )
            
            if success:
                # update home page metrics
                if hasattr(self.workspace, 'home') and hasattr(self.workspace.home, 'set_metrics_layer_wire_dist'):
                    self.workspace.home.set_metrics_layer_wire_dist(image_path=image_path)
            else:
                self.workspace.logger.warning("Failed to generate layer wire distribution plot")
                return False
        else:
            self.workspace.logger.warning("Cannot save plot: no db path provided")
            return False
        
        return True
