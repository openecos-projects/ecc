#!/usr/bin/env python
import os

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # Use non-interactive backend for multi-threading
import matplotlib.pyplot as plt

if not hasattr(np, "Inf"):
    np.Inf = np.inf


def plot_csv_map(input_path: str, output_path: str = None) -> bool:
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
            if "x" in df.columns and "y" in df.columns and "value" in df.columns:
                # For CSV with x, y, value columns (scatter plot with color)
                scatter = ax.scatter(df["x"], df["y"], c=df["value"], cmap="viridis")
                fig.colorbar(scatter, ax=ax, label="Value")
            else:
                # For matrix-like CSV data (heatmap)
                img = ax.imshow(df.values, cmap="viridis", origin="upper")
                fig.colorbar(img, ax=ax, label="Value")
                ax.set_xticks(range(df.shape[1]))
                ax.set_xticklabels(df.columns if df.columns[0] != "0" else range(df.shape[1]))
                ax.set_yticks(range(df.shape[0]))
        else:
            # For 1D data
            ax.plot(df.values.flatten())

        title, _ = os.path.splitext(os.path.basename(input_path))
        ax.set_title(title)
        ax.set_xlabel("X")
        ax.set_ylabel("Y")

        # Save the plot
        fig.savefig(output_path, dpi=300, bbox_inches="tight")

        # Clean up
        plt.close(fig)

        return True
    except Exception:
        plt.close("all")
        return False
