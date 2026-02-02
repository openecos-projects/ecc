#!/usr/bin/env python

import os
from contextlib import suppress


def chmod_folder(folder: str, mode: int = 0o777):
    for root, dirs, files in os.walk(folder):
        with suppress(Exception):
            os.chmod(root, mode)

        for file in files:
            with suppress(Exception):
                os.chmod(os.path.join(root, file), mode)

        for dir_ in dirs:
            with suppress(Exception):
                os.chmod(os.path.join(root, dir_), mode)


def find_files(directory: str, key: str):
    result_files = []
    for root, _dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(f"{key}"):
                result_files.append(os.path.join(root, file))
    return result_files
