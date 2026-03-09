"""
.. deprecated::
    This package has been moved to ``ecos_server.ecc``.
    Use ``from ecos_server.ecc import ...`` instead.
    This package will be removed in a future release.

    Module mapping:

    ========================================  ==========================================
    Old module                                New module
    ========================================  ==========================================
    chipcompiler.server                       ecos_server.ecc
    chipcompiler.server.main                  ecos_server.main
    chipcompiler.server.routers.ecc           ecos_server.ecc.routers.workspace
    chipcompiler.server.routers.sse           ecos_server.ecc.routers.sse
    chipcompiler.server.schemas.*             ecos_server.ecc.schemas.*
    chipcompiler.server.services.*            ecos_server.ecc.services.*
    chipcompiler.server.sse.*                 ecos_server.ecc.sse.* / ecos_server.sse.*
    ========================================  ==========================================
"""
import warnings
warnings.warn(
    "chipcompiler.server is deprecated and will be removed in a future release. "
    "Use ecos_server.ecc instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .main import app
from .routers import workspace_router
from .schemas import (
    CMDEnum,
    ResponseEnum,
    ECCRequest,
    ECCResponse,
    InfoEnum
)
from .services import (
    ECCService,
    ecc_service
)

__all__ = [
    'app',
    'workspace_router',
    'CMDEnum',
    'ResponseEnum',
    'ECCRequest',
    'ECCResponse',
    'InfoEnum',
    'ECCService',
    'ecc_service'
]