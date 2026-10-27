"""Nightly update check against the ecos-installer releases.

The installer publishes dated nightly prereleases (tag
``v<base>-nightly.<yyyymmdd>[.N]``) whose release body carries machine-readable
``ecc-version:``/``ecc-commit:`` fields. Comparing the locally stamped build
identity (or, for unstamped installs, the base version) against the newest
nightly decides whether an update is available. Failures degrade to
``unknown`` instead of erroring: the check must never break a workflow.
"""

import json
import os
import re
import urllib.request
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

DEFAULT_RELEASES_URL = (
    "https://api.github.com/repos/openecos-projects/ecos-installer/releases?per_page=20"
)
RELEASES_URL_ENV = "ECC_UPDATE_RELEASES_URL"
INSTALLER_URLS = (
    "https://github.com/openecos-projects/ecos-installer/releases",
    "https://cnb.cool/ecoslab/ecos-installer/-/releases",
)
REQUEST_TIMEOUT_SECONDS = 5.0

STATUS_UP_TO_DATE = "up_to_date"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_UNKNOWN = "unknown"

_BODY_FIELDS = ("ecc-version", "ecc-commit")
_NIGHTLY_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+-nightly\.(\d{8})(?:\.(\d+))?$")


@dataclass(frozen=True)
class NightlyRelease:
    tag: str
    date: int  # yyyymmdd from the tag
    rerun: int  # same-day rerun suffix, 1 when the tag carries none
    ecc_version: str | None
    ecc_commit: str | None


@dataclass(frozen=True)
class UpdateCheckResult:
    status: str
    current_version: str
    current_commit: str | None
    current_build_date: str | None
    latest: NightlyRelease | None


def fetch_releases(url: str | None = None, timeout: float = REQUEST_TIMEOUT_SECONDS) -> list[dict]:
    target = url or os.environ.get(RELEASES_URL_ENV) or DEFAULT_RELEASES_URL
    request = urllib.request.Request(
        target,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ecc-check-update"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("releases payload is not a list")
    return payload


def _body_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in body.splitlines():
        name, sep, value = line.partition(":")
        if sep and name in _BODY_FIELDS and name not in fields and value.strip():
            fields[name] = value.strip()
    return fields


def _parse_nightly(release: dict) -> NightlyRelease | None:
    if not isinstance(release, dict):
        return None
    if not release.get("prerelease") or release.get("draft"):
        return None
    tag = release.get("tag_name")
    if not isinstance(tag, str):
        return None
    match = _NIGHTLY_TAG_RE.match(tag)
    if match is None:
        return None
    body = release.get("body")
    fields = _body_fields(body if isinstance(body, str) else "")
    return NightlyRelease(
        tag=tag,
        date=int(match.group(1)),
        rerun=int(match.group(2) or 1),
        ecc_version=fields.get("ecc-version"),
        ecc_commit=fields.get("ecc-commit"),
    )


def latest_nightly(releases: list[dict]) -> NightlyRelease | None:
    parsed = [nightly for nightly in map(_parse_nightly, releases) if nightly is not None]
    return max(parsed, key=lambda nightly: (nightly.date, nightly.rerun), default=None)


def _nightly_base(nightly_version: str) -> str:
    return nightly_version.split("-nightly.", 1)[0]


def decide(
    current_version: str,
    current_commit: str | None,
    current_build_date: str | None,
    latest: NightlyRelease | None,
) -> str:
    if latest is None:
        return STATUS_UNKNOWN

    # Semantic ordering first: a lower base version is outdated no matter how
    # fresh its build date is, and a higher one never needs a "downgrade".
    if latest.ecc_version:
        try:
            current = Version(current_version)
            base = Version(_nightly_base(latest.ecc_version))
        except InvalidVersion:
            pass
        else:
            if current < base:
                return STATUS_UPDATE_AVAILABLE
            if current > base:
                return STATUS_UP_TO_DATE

    # Same base (or unparseable versions): the build identity decides.
    if current_build_date and current_build_date.isdigit():
        if current_commit and latest.ecc_commit and current_commit == latest.ecc_commit:
            return STATUS_UP_TO_DATE
        current_date = int(current_build_date)
        if current_date < latest.date:
            return STATUS_UPDATE_AVAILABLE
        if current_date > latest.date:
            return STATUS_UP_TO_DATE
        if current_commit and latest.ecc_commit:
            return STATUS_UPDATE_AVAILABLE  # same day, different commits
    return STATUS_UNKNOWN


def check_for_update(
    current_version: str,
    build_commit: str | None,
    build_date: str | None,
    *,
    url: str | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> UpdateCheckResult:
    try:
        latest = latest_nightly(fetch_releases(url, timeout))
    except (OSError, ValueError):
        return UpdateCheckResult(
            status=STATUS_UNKNOWN,
            current_version=current_version,
            current_commit=build_commit,
            current_build_date=build_date,
            latest=None,
        )
    status = decide(current_version, build_commit, build_date, latest)
    return UpdateCheckResult(
        status=status,
        current_version=current_version,
        current_commit=build_commit,
        current_build_date=build_date,
        latest=latest,
    )
