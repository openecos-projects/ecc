import sys
import os

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from chipcompiler.data import Parameters
from chipcompiler.data.parameter import get_parameters as _get_parameters

def get_parameters(pdk_name : str, design : str = "", path : str = "") -> Parameters:
    """
    Return the Parameters instance based on the given pdk name.
    """
    return _get_parameters(pdk_name, design, path, current_dir)
