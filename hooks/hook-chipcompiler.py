"""
PyInstaller hook for chipcompiler.

Ensure the ECC pybind extension and adjacent runtime libraries are bundled.
"""

from pathlib import Path

from PyInstaller.utils.hooks import get_module_file_attribute

binaries = []

chipcompiler_dir = Path(get_module_file_attribute("chipcompiler")).parent
ecc_bin_dir = chipcompiler_dir / "tools" / "ecc" / "bin"

if ecc_bin_dir.exists():
    for so_file in ecc_bin_dir.rglob("*.so"):
        binaries.append((str(so_file), str(so_file.parent.relative_to(chipcompiler_dir.parent))))
