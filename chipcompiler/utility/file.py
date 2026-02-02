#!/usr/bin/env python

import os


def chmod_folder(folder:str, mode:int = 0o777):
    def _try_chmod(self, path):
        try:
            os.chmod(path, 0o777)
        except Exception:
            pass

    for root, dirs, files in os.walk(folder):
        _try_chmod(root)
        for file in files:
            _try_chmod(os.path.join(root, file))
        for dir in dirs:
            full_path = os.path.join(root, dir)
            _try_chmod(full_path)

def find_files(directory : str, key : str):
    result_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(f"{key}"):
                result_files.append(os.path.join(root, file))
    return result_files