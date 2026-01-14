#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for multi-threading
import matplotlib.pyplot as plt

def plot_csv_map(input_path : str, output_path : str=None) -> bool:
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
        
        return True
    except Exception as e:
        plt.close('all')
        return False
    
def plot_csv_table(input_path: str, output_path: str=None) -> bool:
    """
    Plot CSV data as a table and save to output path.
    
    Args:
        input_path (str): Path to the input CSV file.
        output_path (str, optional): Path to save the output PNG file. Defaults to None.
    
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
        
        # Create figure and axis
        fig, ax = plt.subplots(figsize=(len(df.columns) * 2, len(df) * 0.5))
        ax.axis('tight')
        ax.axis('off')
        
        # Create table
        table = ax.table(cellText=df.values, colLabels=df.columns, cellLoc='center', loc='center')
        
        # Set table style
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.1, 1.5)
        
        # Save the plot
        fig.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        
        return True
    except Exception as e:
        plt.close('all')
        return False
    
def plot_metrics(metrics: dict, output_path: str=None, col=4) -> bool:
    """
    Plot metrics as a table and save to output path.
    
    Args:
        metrics (dict): Dictionary of metrics to plot.
        output_path (str): Path to save the output PNG file.
        col (int): Number of columns in the table.
    
    Returns:
        bool: True if the plot is successful, False otherwise.
    """       
    try:
        import math
        
        keys = list(metrics.keys())
        values = list(metrics.values())
        
        # Calculate number of rows needed
        num_metrics = len(metrics)
        rows = math.ceil(num_metrics / col)
        
        # Create table data with col columns and rows rows
        table_data = []
        for i in range(rows):
            row_data = []
            for j in range(col):
                index = j + i * col
                if index < num_metrics:
                    row_data.append(f"{keys[index]}")
                    row_data.append(f"{values[index]}")
                else:
                    row_data.append("")
                    row_data.append("")
            table_data.append(row_data)
        
        # Calculate figure size based on number of rows and columns
        fig_width = 2 * col  # Each column pair (key-value) takes about 2 inches
        fig_height =  rows  # Each row takes about 1 inches
        
        # Create figure and table
        fig, ax = plt.subplots(figsize=(fig_width, fig_height))
        ax.axis('tight')
        ax.axis('off')
        
        # Create table
        table = ax.table(cellText=table_data, cellLoc='left', loc='center')
        
        # Set table style
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(2, 1)  # Scale table for better readability
        
        # Make key fonts bold
        for i in range(len(table_data)):
            for j in range(0, len(table_data[i]), 2):  # Keys are in even indices (0, 2, 4, ...)
                if table_data[i][j]:  # Only set style if cell is not empty
                    table[(i, j)].set_text_props(weight='bold')
        
        # Set title
        # plt.title('Metrics Overview', fontsize=16, pad=20)
        
        # Save the plot
        fig.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        
        return True
    except Exception as e:
        print(f"Error plotting metrics: {e}")
        plt.close('all')
        return False