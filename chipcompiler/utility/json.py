#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
import logging
import json

def json_read(file_path: str) -> dict:
    """
    Read a JSON file and return its content as a dictionary.
    """
    data = {}
    if os.path.isfile(file_path) is False:
        logging.error(f"JSON file not found: {file_path}")
        return data
    
    try:
        if file_path.endswith('.gz'):
            import gzip
            with gzip.open(file_path, 'rt') as f:
                data = json.load(f)
        else:
            with open(file_path, 'r') as f:
                data = json.load(f)
    except Exception as e:
        logging.error(f"Error reading JSON file {file_path}: {e}")
            
    return data

def json_write(file_path: str, data: dict={}, indent=4) -> bool:
    """
    Write a dictionary to a JSON file.
    """
    try:
        if file_path.endswith('.gz'):
            import gzip
            with gzip.open(file_path, 'wt') as f:
                json.dump(data, f, indent=indent)
        else:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=indent)
        return True
    except Exception as e:
        logging.error(f"Error writing JSON file {file_path}: {e}")
        return False