#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from chipcompiler.tools.ecc.module import ECCToolsModule


def test_ecc_tools_module_imports_installed_native_extension():
    module = ECCToolsModule()
    assert module.get_ecc() is not None
