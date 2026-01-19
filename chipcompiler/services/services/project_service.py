#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
import json
from typing import Tuple, Optional, Dict, Any

from chipcompiler.data import (
    create_workspace,
    PDK,
    Parameters
)


class ProjectService:
    """Service layer for project operations"""
    
    @staticmethod
    def open_project(path: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Open an existing project by reading its configuration files.
        
        Args:
            path: Path to the project directory
            
        Returns:
            Tuple of (success, message, project_info)
        """
        try:
            # Validate project directory exists
            if not os.path.isdir(path):
                return False, f"Directory does not exist: {path}", None
            
            # Check for flow.json (required for valid ECC project)
            flow_path = os.path.join(path, "flow.json")
            if not os.path.exists(flow_path):
                return False, "Not a valid ECC project directory (flow.json missing)", None
            
            # Read flow.json
            with open(flow_path, 'r') as f:
                flow_data = json.load(f)
            
            # Extract project name from parameters.json if it exists
            project_name = os.path.basename(path)
            param_path = os.path.join(path, "parameters.json")
            if os.path.exists(param_path):
                with open(param_path, 'r') as f:
                    params = json.load(f)
                    project_name = params.get("Design", project_name)
            
            project_info = {
                "name": project_name,
                "path": path,
                "flow": flow_data
            }
            
            return True, f"Project loaded successfully", project_info
            
        except json.JSONDecodeError as e:
            return False, f"Failed to parse project files: {str(e)}", None
        except Exception as e:
            return False, f"Failed to open project: {str(e)}", None
    
    @staticmethod
    def create_project(path: str, name: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Create a new project workspace.
        
        Args:
            path: Path where the project will be created
            name: Name of the project
            
        Returns:
            Tuple of (success, message, project_info)
        """
        try:
            # Validate path
            if not os.path.isdir(path):
                return False, f"Parent directory does not exist: {path}", None
            
            # Create project directory
            project_path = os.path.join(path, name)
            
            # Create workspace with default PDK and parameters
            workspace = create_workspace(
                directory=project_path,
                origin_def="",
                origin_verilog="",
                pdk=PDK(name="Default_PDK"),
                parameters=Parameters(data={
                    "Design": name,
                    "Top module": "top",
                    "Clock": "clk",
                    "Frequency max [MHz]": 100
                })
            )
            
            # Initialize empty flow.json
            flow_path = os.path.join(project_path, "flow.json")
            with open(flow_path, 'w') as f:
                json.dump({"steps": []}, f, indent=2)
            
            project_info = {
                "name": name,
                "path": project_path,
                "flow": {"steps": []}
            }
            
            return True, f"Project created at {project_path}", project_info
            
        except Exception as e:
            return False, f"Failed to create project: {str(e)}", None
