#!/usr/bin/env python
import os

from chipcompiler.data import Workspace, WorkspaceStep


class KlayoutModule:
    def __init__(self, workspace : Workspace, step : WorkspaceStep):
        from chipcompiler.tools.klayout.utility import is_eda_exist
        if not is_eda_exist():
            raise ImportError("KLayout tool is not installed or not found.")

        self.workspace = workspace
        self.step = step
        
    def save_layout_image(self) -> bool:
        """
        Save the layout image to the specified path.
        """        
        gds_file = self.step.output.get("gds", None)
        img_file = self.step.output.get("image", None)
        
        if gds_file is None or img_file is None or not os.path.exists(gds_file):
            return False
        
        self.save_snapshot_image(gds_file=gds_file,
                                 img_file=img_file,
                                 weight=1920,
                                 height=1920)
        return True 
        
    def save_snapshot_image(self,
                            gds_file: str, 
                            img_file: str, 
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
        from klayout import lay
        
        lv = lay.LayoutView()
        lv.set_config("background-color", "#F5F5F5")  # background of ECOS MERGE tab
        lv.set_config("grid-visible", "false")
        lv.set_config("grid-show-ruler", "false")
        lv.set_config("text-visible", "false")
    
        # Load the GDS file
        lv.load_layout(gds_file, 0)
        lv.max_hier()
    
        # Event processing for delayed configuration events
        lv.timer()
    
        # Save the image
        lv.save_image(img_file, weight, height)
