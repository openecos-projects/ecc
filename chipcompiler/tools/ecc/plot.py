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
    plot_metrics
)

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
                state = state & self.default_plot() & self.plot_routing_heatmap()
            case StepEnum.DRC.value:
                state = state & self.default_plot() & self.plot_drc_statis()
            case StepEnum.FILLER.value:
                state = state & self.default_plot()
                
            case default:
                self.workspace.logger.warning(f"Step {self.step.name} not supported for plotting.")
        
        self.workspace.logger.info(f"Plotting completed for step {self.step.name}")
        return state
    
    def default_plot(self) -> bool:
        return self.plot_step_metrics() & self.plot_instance_distribution()
    
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
        
        self.workspace.logger.info(f"Plotting {len(valid_paths)} array maps with multi-threading...")
        
        # Use ThreadPoolExecutor for multi-threading with progress bar (limit to 10 threads)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Create a progress bar
            results = list(tqdm(
                executor.map(plot_csv_map, valid_paths),
                total=len(valid_paths),
                desc="Plotting array maps",
                unit="file"
            ))
        
        # Count successful and failed plots
        successful = sum(results)
        failed = len(results) - successful
        
        self.workspace.logger.info(f"Plotting completed: {successful} successful, {failed} failed.")
    
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
        
        # Log the CSV creation
        self.workspace.logger.info(f"DRC statistics saved to {statis_csv}")
        
        # Plot the CSV table
        plot_csv_table(input_path=statis_csv)
        
        return True
    
    def plot_instance_distribution(self) -> bool:
        import matplotlib.pyplot as plt
        import numpy as np
        
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
        metrics = ["num", "area", "pin_num"]
        metric_labels = {"num": "Number", "area": "Area", "pin_num": "Pin Number"}
        colors = ['skyblue', 'lightgreen', 'salmon']
        
        # Create single figure
        fig, ax = plt.subplots(figsize=(12, 8))
        fig.suptitle("Instance Distribution", fontsize=16)
        
        # Set bar width and positions
        bar_width = 0.25
        x = np.arange(len(instance_types))
        
        # Plot each metric as grouped bars
        for i, metric in enumerate(metrics):
            values = [instances_data[inst][metric] for inst in instance_types]
            positions = x + i * bar_width
            bars = ax.bar(positions, values, bar_width, color=colors[i], label=metric_labels[metric])
            
            # Add value labels on top of bars
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height, f'{height:.2f}',
                        ha='center', va='bottom')
        
        # Set labels and title
        ax.set_xlabel('Instance Type')
        ax.set_ylabel('Value')
        ax.set_title('Instance Distribution by Number, Area and Pin Count')
        ax.set_xticks(x + bar_width)
        ax.set_xticklabels(instance_types, rotation=45, ha='right')
        ax.legend()
        ax.grid(axis='y', alpha=0.75)
        
        # Adjust layout
        plt.tight_layout(rect=[0, 0, 1, 0.95])
        
        # Save the plot
        db_path = self.step.feature.get("db", "")
        if db_path:
            image_path = db_path.replace(".json", ".inst_dist.png")
            plt.savefig(image_path, dpi=300, bbox_inches='tight')
            self.workspace.logger.info(f"Instance distribution plot saved to {image_path}")
            
            # update home page metrics
            self.workspace.home.set_metrics_inst_dist(image_path=image_path)
        else:
            self.workspace.logger.warning("Cannot save plot: no db path provided")
            return False
        
        plt.close()
        
        return True
