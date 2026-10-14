"""Generic, private-data-free campaign manifest and ledger operations."""

from ecc_experience.benchmark.ledger import initialize, record_trial, status
from ecc_experience.benchmark.manifest import CampaignManifest, load_manifest

__all__ = ["CampaignManifest", "initialize", "load_manifest", "record_trial", "status"]

__all__ = ["CampaignManifest", "load_manifest"]
