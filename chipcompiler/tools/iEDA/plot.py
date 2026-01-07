#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for multi-threading
import matplotlib.pyplot as plt
import concurrent.futures
from tqdm import tqdm
from chipcompiler.data import WorkspaceStep, Workspace, Parameters, StepEnum
from chipcompiler.utility import json_read

class IEDAPlot:
    def __init__(self, workspace: Workspace, step: WorkspaceStep):
        self.workspace = workspace
        self.step = step
    
    def plot(self) -> bool:
        match self.step.name:
            case StepEnum.PLACEMENT.value | StepEnum.CTS.value:
                return self.plot_placement_heatmap()
            case StepEnum.ROUTING.value:
                return self.plot_routing_heatmap()
                
            case default:
                self.workspace.logger.warning(f"Step {self.step.name} not supported for plotting.")
        
        self.workspace.logger.info(f"Plotting completed for step {self.step.name}")
        return True
    
    def plot_placement_heatmap(self):
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
        
        # Function to process a single path
        def process_path(input_path):
            return self.plot_array_map(input_path=input_path)
        
        # Use ThreadPoolExecutor for multi-threading with progress bar
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Create a progress bar
            results = list(tqdm(
                executor.map(process_path, valid_paths),
                total=len(valid_paths),
                desc="Plotting array maps",
                unit="file"
            ))
        
        # Count successful and failed plots
        successful = sum(results)
        failed = len(results) - successful
        
        self.workspace.logger.info(f"Plotting completed: {successful} successful, {failed} failed.")
        
    def plot_array_map(self, input_path : str, output_path : str=None) -> bool:
        """
        Plot array map from CSV file.
        
        Args:
            input_path (str): Path to the input CSV file.
            output_path (str, optional): Path to the output PNG file. Defaults to None.
        
        Returns:
            bool: True if the plot is successful, False otherwise.
        """
        if not os.path.exists(input_path) or not input_path.lower().endswith(".csv"):
            return False
        
        if not output_path:
            output_path = input_path.replace(".csv", ".png")
        
        try:
            # Read CSV data
            df = pd.read_csv(input_path)
            
            # Create a new figure and axis for each thread
            fig, ax = plt.subplots(figsize=(10, 8))
            
            # Assuming the CSV has columns that can be used as x, y, and value
            # If the CSV has a grid structure without headers, we can use it directly
            if df.shape[1] > 1:
                # Try different approaches based on CSV structure
                if 'x' in df.columns and 'y' in df.columns and 'value' in df.columns:
                    # For CSV with x, y, value columns (scatter plot with color)
                    scatter = ax.scatter(df['x'], df['y'], c=df['value'], cmap='viridis')
                    fig.colorbar(scatter, ax=ax, label='Value')
                else:
                    # For matrix-like CSV data (heatmap)
                    img = ax.imshow(df.values, cmap='viridis', origin='lower')
                    fig.colorbar(img, ax=ax, label='Value')
                    ax.set_xticks(range(df.shape[1]))
                    ax.set_xticklabels(df.columns if df.columns[0] != '0' else range(df.shape[1]))
                    ax.set_yticks(range(df.shape[0]))
            else:
                # For 1D data
                ax.plot(df.values.flatten())
            
            title, _ = os.path.splitext(os.path.basename(input_path))
            ax.set_title(title)
            ax.set_xlabel('X')
            ax.set_ylabel('Y')
            
            # Save the plot
            fig.savefig(output_path, dpi=300, bbox_inches='tight')
            
            # Clean up
            plt.close(fig)
            
            self.workspace.logger.info(f"Plot image saved to {output_path}")
            
            return True
        except Exception as e:
            self.workspace.logger.error(f"Error plotting array map: {e}")
            # Ensure figure is closed even if error occurs
            plt.close('all')
            return False
    