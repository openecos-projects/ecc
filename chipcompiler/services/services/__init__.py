from .ecc import ECCService

global _ecc_service
_ecc_service = ECCService()

def ecc_service():
    global _ecc_service
    return _ecc_service

__all__ = [
    'ECCService',
    'ecc_service'
]