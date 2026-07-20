#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from pathlib import Path

from chipcompiler.data import EccOutput, WorkspaceStep, Workspace, StateEnum, StepEnum
from chipcompiler.utility.path import path_text
from klayout import db
from klayout import lay

class KlayoutModule:
    def __init__(self, workspace : Workspace, step : WorkspaceStep):
        from chipcompiler.tools.klayout_tool.utility import is_eda_exist
        if not is_eda_exist():
            raise ImportError("KLayout tool is not installed or not found.")

        self.workspace = workspace
        self.step = step
        
    def save_layout_image(self) -> bool:
        """
        Save the layout image to the specified path.
        """        
        output = self.step.output
        gds_file = output.gds if isinstance(output, EccOutput) else None
        img_file = output.image

        if gds_file is None or img_file is None or not os.path.exists(gds_file):
            return False
        
        self.save_snapshot_image(gds_file=gds_file,
                                 img_file=img_file,
                                 weight=1920,
                                 height=1920)
        
        # update home page layout
        self.workspace.home.set_layout(path=img_file)
        
        return True 
        
    def save_snapshot_image(self,
                            gds_file: str | Path,
                            img_file: str | Path,
                            weight: int = 1920,
                            height: int = 1920):
        """
        Takes a screenshot of a GDS file and saves it as an image.
        @Reference: https://gist.github.com/sequoiap/48af5f611cca838bb1ebc3008eef3a6e
    
        Args:
            gds_file (str): Path to the input GDS file
            img_file (str): Path to the output image file
            weight (int, optional): Image width. Defaults to 1920
            height (int, optional): Image height. Defaults to 1920
        """
        # Set display configuration options
        lv = lay.LayoutView()
        lv.set_config("background-color", "#F5F5F5")  # background of ECOS MERGE tab
        lv.set_config("grid-visible", "false")
        lv.set_config("grid-show-ruler", "false")
        lv.set_config("text-visible", "false")
    
        # Load the GDS file
        lv.load_layout(path_text(gds_file), 0)
        lv.max_hier()
    
        # Event processing for delayed configuration events
        lv.timer()
    
        # Save the image
        lv.save_image(path_text(img_file), weight, height)
