#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os

def chmod_folder(folder:str, mode:int = 0o777):
    def _try_chmod(self, path):
        try:
            os.chmod(path, 0o777)
        except Exception as e:
            # print("chmod error for path : " + path)
            pass
        
    for root, dirs, files in os.walk(folder):
        _try_chmod(root)
        for file in files:
            _try_chmod(os.path.join(root, file))
        for dir in dirs:
            full_path = os.path.join(root, dir)
            _try_chmod(full_path)
            _try_chmod(full_path)