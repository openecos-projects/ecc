#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import Workspace, WorkspaceStep, StepEnum

class EngineDB:
    """
    this class is for ECC lifecycle management
    db : use ecc-tools-idb as the database engine
    """
    from chipcompiler.tools.ecc import ECCToolsModule
    def __init__(self, workspace : Workspace, ecc_module : ECCToolsModule= None):
        self.workspace = workspace
        self.ecc_module = ecc_module
        
    def has_init(self) -> bool:
        return self.ecc_module is not None and self.ecc_module.ecc is not None
    
    @property
    def engine(self):
        return self.ecc_module

    def create_db_engine(self, step: WorkspaceStep) -> bool:
        """
        create db engine from ecc module
        """
        if self.ecc_module is not None:
            return True
        
        if step is None:
            return False
        
        # check eda tool exist
        from chipcompiler.tools import load_eda_module
        eda_module = load_eda_module("ecc")
        if eda_module is None:
            return False
        
        from chipcompiler.tools.ecc import create_db_engine
        self.ecc_module = create_db_engine(self.workspace, step)
        if self.ecc_module is not None:
            self.workspace.logger.info(f"ecc db initialize success for step {step.name}.")
            return True
        else:
            self.workspace.logger.warning(f"ecc db initialize failed for step {step.name}.")
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
        
        self.ecc_module.read_def()