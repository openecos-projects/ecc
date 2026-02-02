#!/usr/bin/env python

import json
import os


def json_read(file_path: str) -> dict:
    """
    Read a JSON file and return its content as a dictionary.
    """
    data = {}
    if os.path.isfile(file_path) is False:
        return data
    
    try:
        if file_path.endswith('.gz'):
            import gzip
            with gzip.open(file_path, 'rt') as f:
                data = json.load(f)
        else:
            with open(file_path) as f:
                data = json.load(f)
    except Exception:
        return data
            
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
    except Exception:
        return False
    
def dict_to_str(d, indent=0):
    result = []
    for key, value in d.items():
        result.append('  ' * indent + f"{key}:")
        if isinstance(value, dict):
            result.append(dict_to_str(value, indent + 1))
        else:
            result.append('  ' * (indent + 1) + str(value))
    return '\n'.join(result)