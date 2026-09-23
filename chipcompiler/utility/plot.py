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

def plot_csv_table(input_path: str, output_path: str = None) -> bool:
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
        ax.axis("tight")
        ax.axis("off")

        # Create table
        table = ax.table(cellText=df.values, colLabels=df.columns, cellLoc="center", loc="center")

        # Set table style
        table.auto_set_font_size(value=False)
        table.set_fontsize(10)
        table.scale(1.1, 1.5)

        # Save the plot
        fig.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)

        return True
    except Exception:
        plt.close("all")
        return False


def plot_csv_bar_chart(
    input_path: str,
    output_path: str = None,
    title: str = "Bar Chart",
    xlabel: str = "Category",
    ylabel: str = "Value",
    *,
    integer_yaxis: bool = False,
) -> bool:
    """
    Plot bar chart from CSV data and save to output path.

    Args:
        input_path (str): Path to the input CSV file.
        output_path (str, optional): Path to save the output PNG file. Defaults to None.
        title (str): Title of the bar chart.
        xlabel (str): Label for the x-axis.
        ylabel (str): Label for the y-axis.
        integer_yaxis (bool): Whether to use integer ticks on the y-axis. Defaults to False.

    Returns:
        bool: True if the plot is successful, False otherwise.
    """
    if not os.path.exists(input_path) or not input_path.lower().endswith(".csv"):
        return False

    if not output_path:
        output_path = input_path.replace(".csv", ".png")

    try:
        # Read CSV data with first column as index
        df = pd.read_csv(input_path, index_col=0)

        # Create figure and axis
        fig, ax = plt.subplots(figsize=(12, 8))

        # Plot bar chart
        df.plot(kind="bar", ax=ax)

        # Set labels and title
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend()
        ax.grid(axis="y", alpha=0.75)

        # Set y-axis ticks to integers if requested
        if integer_yaxis:
            import matplotlib.ticker as ticker

            ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))

        # Adjust layout
        plt.tight_layout()

        # Save the plot
        fig.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)

        return True
    except Exception:
        plt.close("all")
        return False
