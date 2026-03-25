#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import Workspace, WorkspaceStep

class EngineDB:
    """
    this class is for ECC lifecycle management
    db : use ecc-tools-idb as the database engine
    """
    from chipcompiler.tools.ecc import ECCToolsModule
    def __init__(self, workspace : Workspace, eda : ECCToolsModule= None):
        self.workspace = workspace
        self.eda = eda
    
    @property
    def engine(self):
        return self.eda

    def create_db_engine(self, step: WorkspaceStep) -> bool:
        """
        create db engine from ecc module
        """
        if self.eda is not None:
            return True
        
        # check eda tool exist
        from chipcompiler.tools import load_eda_module
        eda_module = load_eda_module("ecc")
        if eda_module is None:
            return False
        
        from chipcompiler.tools.ecc import create_db_engine
        self.eda = create_db_engine(self.workspace, step)
        if self.eda is not None:
            self.workspace.logger.info("ecc db initialize success.")
            return True
        else:
            self.workspace.logger.error("ecc db initialize failed.")
            return False
    
    def update_db_from_step(self,
                            step : WorkspaceStep):
        """
        update data after step finished, 
        update data by read the def or verilog, parsing nessary infomation,
        for example, 
        if step is "place", read instances data from step output def file and update to db egine.
        """
        def_file = step.output["def"]
        
        self.eda.read_def()