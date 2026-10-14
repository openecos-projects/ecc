import json

from chipcompiler.cli import main as cli_main
from chipcompiler.update_check import (
    REQUEST_TIMEOUT_SECONDS,
    STATUS_UNKNOWN,
    STATUS_UP_TO_DATE,
    STATUS_UPDATE_AVAILABLE,
    NightlyRelease,
    UpdateCheckResult,
    check_for_update,
    decide,
    fetch_releases,
    latest_nightly,
)

LATEST_COMMIT = "27084f4779d7e8ddb69ea9c25f9c116aaaab29c7"
OTHER_COMMIT = "1111111111111111111111111111111111111111"


def release(tag, body="", *, prerelease=True, draft=False):
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "body": body,
    }


def nightly_body(commit=LATEST_COMMIT, version="0.1.0-alpha.13-nightly.20261012.g27084f4"):
    return (
        "Nightly build of the ECOS toolchain.\n"
        "\n"
        "| tool | version | commit |\n"
        "|---|---|---|\n"
        f"| ecc | {version} | [27084f4](https://github.com/x/ecc/commit/{commit}) |\n"
        "\n"
        f"ecc-commit: {commit}\n"
        f"ecc-version: {version}\n"
    )


def latest(**overrides):
    fields = {
        "tag": "v0.1.0-nightly.20261013.2",
        "date": 20261013,
        "rerun": 2,
        "ecc_version": "0.1.0-alpha.13-nightly.20261012.g27084f4",
        "ecc_commit": LATEST_COMMIT,
    }
    fields.update(overrides)
    return NightlyRelease(**fields)


def test_latest_nightly_prefers_newest_date_and_rerun():
    releases = [
        release("v0.1.0-nightly.20261012"),
        release("v0.1.0-nightly.20261013"),
        release("v0.1.0-nightly.20261013.2", nightly_body()),
        release("v0.1.0-nightly.20261013.1"),
        release("v0.1.0-nightly.20261011"),
    ]

    assert latest_nightly(releases) == latest()


def test_latest_nightly_ignores_non_nightly_and_non_prereleases():
    releases = [
        release("v0.1.0", prerelease=False),
        release("v0.1.0-nightly-not-a-date"),
        release("v0.1.0-nightly.20261012", draft=True),
        release("v0.1.0-nightly.20261010", nightly_body(commit=OTHER_COMMIT)),
    ]

    assert latest_nightly(releases) == latest(
        tag="v0.1.0-nightly.20261010",
        date=20261010,
        rerun=1,
        ecc_commit=OTHER_COMMIT,
    )


def test_latest_nightly_tolerates_missing_body_fields():
    parsed = latest_nightly([release("v0.1.0-nightly.20261013", "no fields here")])

    assert parsed == latest(
        tag="v0.1.0-nightly.20261013", rerun=1, ecc_version=None, ecc_commit=None
    )


def test_latest_nightly_returns_none_without_matches():
    assert latest_nightly([]) is None
    assert latest_nightly([release("v0.1.0")]) is None


def test_latest_nightly_skips_malformed_release_entries():
    releases = [
        "not-a-dict",
        {
            "tag_name": "v0.1.0-nightly.20261013",
            "prerelease": True,
            "body": {"unexpected": "dict"},
        },
    ]

    # The non-dict entry is skipped; the non-string body degrades to no fields.
    assert latest_nightly(releases) == latest(
        tag="v0.1.0-nightly.20261013", rerun=1, ecc_version=None, ecc_commit=None
    )
    assert latest_nightly(["not-a-dict"]) is None


def test_body_field_parsing_takes_first_match_and_skips_empty_values():
    body = (
        f"ecc-version: 0.1.0-alpha.13-nightly.20261012.g27084f4\n"
        f"ecc-commit: {LATEST_COMMIT}\n"
        "ecc-commit: deadbeef\n"
        "ecc-version: \n"
    )

    parsed = latest_nightly([release("v0.1.0-nightly.20261012", body)])

    assert parsed.ecc_version == "0.1.0-alpha.13-nightly.20261012.g27084f4"
    assert parsed.ecc_commit == LATEST_COMMIT


def test_decide_with_build_identity():
    # A carried-forward nightly re-publishes the same ecc commit: content-equal wins over dates.
    assert decide("0.1.0-alpha.13", LATEST_COMMIT, "20261012", latest()) == STATUS_UP_TO_DATE
    assert decide("0.1.0-alpha.13", OTHER_COMMIT, "20261012", latest()) == STATUS_UPDATE_AVAILABLE
    assert decide("0.1.0-alpha.13", OTHER_COMMIT, "20261014", latest()) == STATUS_UP_TO_DATE
    # Same calendar day with different commits cannot be ordered: be conservative.
    assert decide("0.1.0-alpha.13", OTHER_COMMIT, "20261013", latest()) == STATUS_UPDATE_AVAILABLE
    assert decide("0.1.0-alpha.13", OTHER_COMMIT, "20261013", latest(ecc_commit=None)) == (
        STATUS_UNKNOWN
    )


def test_decide_without_build_identity_compares_base_versions():
    assert decide("0.1.0-alpha.12", None, None, latest()) == STATUS_UPDATE_AVAILABLE
    assert decide("0.1.0-alpha.14", None, None, latest()) == STATUS_UP_TO_DATE
    assert decide("0.1.0-alpha.13", None, None, latest()) == STATUS_UNKNOWN


def test_decide_degrades_to_unknown_on_unusable_metadata():
    unusable = latest(ecc_version=None, ecc_commit=None)
    assert decide("0.1.0-alpha.13", None, None, unusable) == STATUS_UNKNOWN
    assert decide("0.1.0-alpha.13", None, None, None) == STATUS_UNKNOWN
    assert decide("not-a-version", None, None, latest(ecc_version="garbage")) == STATUS_UNKNOWN


def test_check_for_update_returns_unknown_on_fetch_failure(monkeypatch):
    def failing_fetch(url=None, timeout=5.0):
        raise OSError("network unreachable")

    monkeypatch.setattr("chipcompiler.update_check.fetch_releases", failing_fetch)

    assert check_for_update("0.1.0-alpha.13", LATEST_COMMIT, "20261013") == UpdateCheckResult(
        status=STATUS_UNKNOWN,
        current_version="0.1.0-alpha.13",
        current_commit=LATEST_COMMIT,
        current_build_date="20261013",
        latest=None,
    )


def test_check_for_update_returns_unknown_on_timeout(monkeypatch):
    def timing_out(request, timeout=None):
        raise TimeoutError("read timed out")

    monkeypatch.setattr("chipcompiler.update_check.urllib.request.urlopen", timing_out)

    assert check_for_update("0.1.0-alpha.12", None, None).status == STATUS_UNKNOWN


def test_fetch_releases_applies_the_request_timeout(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def read(self):
            return b"[]"

    def fake_urlopen(request, timeout=None):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("chipcompiler.update_check.urllib.request.urlopen", fake_urlopen)

    fetch_releases()

    assert captured["timeout"] == REQUEST_TIMEOUT_SECONDS


def test_check_for_update_reads_releases_url_override(monkeypatch, capsys):
    requested = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def read(self):
            return json.dumps([release("v0.1.0-nightly.20261013", nightly_body())]).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        requested["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setenv("ECC_UPDATE_RELEASES_URL", "https://mirror.example/releases")
    monkeypatch.setattr("chipcompiler.update_check.urllib.request.urlopen", fake_urlopen)

    result = check_for_update("0.1.0-alpha.12", None, None)

    assert requested["url"] == "https://mirror.example/releases"
    assert result == UpdateCheckResult(
        status=STATUS_UPDATE_AVAILABLE,
        current_version="0.1.0-alpha.12",
        current_commit=None,
        current_build_date=None,
        latest=latest(tag="v0.1.0-nightly.20261013", rerun=1),
    )


def patched_result(monkeypatch, result):
    monkeypatch.setattr(
        "chipcompiler.cli.commands.check_update.check_for_update",
        lambda *a, **k: result,
    )


def test_check_update_command_reports_available_update(monkeypatch, capsys):
    patched_result(
        monkeypatch,
        UpdateCheckResult(
            status=STATUS_UPDATE_AVAILABLE,
            current_version="0.1.0-alpha.13",
            current_commit=OTHER_COMMIT,
            current_build_date="20261010",
            latest=latest(),
        ),
    )

    rc = cli_main.run(["check-update"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out == (
        "Current version : 0.1.0-alpha.13 (nightly 2026-10-10, g1111111)\n"
        "Latest nightly  : 0.1.0-alpha.13-nightly.20261012.g27084f4 (2026-10-13)\n"
        "Status          : update available\n"
        "\n"
        "Get the latest nightly build:\n"
        "  https://github.com/openecos-projects/ecos-installer/releases\n"
        "  https://cnb.cool/ecoslab/ecos-installer/-/releases\n"
    )


def test_check_update_command_reports_up_to_date_without_links(monkeypatch, capsys):
    patched_result(
        monkeypatch,
        UpdateCheckResult(
            status=STATUS_UP_TO_DATE,
            current_version="0.1.0-alpha.13",
            current_commit=LATEST_COMMIT,
            current_build_date="20261012",
            latest=latest(),
        ),
    )

    rc = cli_main.run(["check-update"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out == (
        "Current version : 0.1.0-alpha.13 (nightly 2026-10-12, g27084f4)\n"
        "Latest nightly  : 0.1.0-alpha.13-nightly.20261012.g27084f4 (2026-10-13)\n"
        "Status          : up to date\n"
    )


def test_check_update_command_json_payload_whole_object(monkeypatch, capsys):
    patched_result(
        monkeypatch,
        UpdateCheckResult(
            status=STATUS_UNKNOWN,
            current_version="0.1.0-alpha.12",
            current_commit=None,
            current_build_date=None,
            latest=None,
        ),
    )

    rc = cli_main.run(["check-update", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data == {
        "schema_version": 1,
        "status": "unknown",
        "current": {
            "version": "0.1.0-alpha.12",
            "build_commit": None,
            "build_date": None,
        },
        "latest": None,
        "installer_urls": [
            "https://github.com/openecos-projects/ecos-installer/releases",
            "https://cnb.cool/ecoslab/ecos-installer/-/releases",
        ],
    }
