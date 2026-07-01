# Release Guide

ECC releases are branch-verified and tag-published.

Use a `release/v<version>` branch to prepare and validate the exact commit that
will be released. After the release branch CI is green, create the `v<version>`
tag from the remote release branch tip. The tag push triggers
`.github/workflows/release.yml`, which builds the release artifact and creates
the GitHub Release.

Do not tag an older commit with a new version if that commit still contains the
old version metadata. The release workflow checks that the tag, `pyproject.toml`,
and `chipcompiler/__init__.py` all agree.

## Release Flow

Set the release variables first:

```bash
OLD_VERSION=0.1.0-alpha.4
NEW_VERSION=0.1.0-alpha.5
TAG=v${NEW_VERSION}
RELEASE_BRANCH=release/${TAG}
BASE_COMMIT=a6679f6053f54c3a0a5c6fbd6250ac5a137cfa3d
```

Create the release branch from the commit you want to release:

```bash
git fetch origin
git switch -c "${RELEASE_BRANCH}" "${BASE_COMMIT}"
```

If the base commit does not already contain the current release CI
infrastructure, cherry-pick the release infrastructure commits before bumping
the version. For `v0.1.0-alpha.5`, the current release infrastructure changes
are:

```bash
git cherry-pick \
  63feefe \
  68a4b14 \
  326565e \
  3e71693 \
  f13da89 \
  b86404d \
  7c651b5
```

Bump the package version on the release branch:

```bash
sed -i "s/version = \"${OLD_VERSION}\"/version = \"${NEW_VERSION}\"/" pyproject.toml
sed -i "s/__version__ = \"${OLD_VERSION}\"/__version__ = \"${NEW_VERSION}\"/" chipcompiler/__init__.py

git add pyproject.toml chipcompiler/__init__.py
git commit -m "chore: bump version to ${TAG}"
```

Run the local version check if Python is available:

```bash
EXPECTED_REF="${RELEASE_BRANCH}" bash .github/scripts/check-version.sh
```

Push the release branch:

```bash
git push -u origin "${RELEASE_BRANCH}"
```

Wait for the `release/v*` branch CI to pass. The CI runs the same version check
against the branch name, so a branch named `release/v0.1.0-alpha.5` must contain
version `0.1.0-alpha.5` in both version files.

After CI is green, create the annotated tag from the remote release branch tip:

```bash
git fetch origin
git tag -a "${TAG}" "origin/${RELEASE_BRANCH}" -m "${TAG}"
git push origin "${TAG}"
```

The tag push starts `.github/workflows/release.yml`. That workflow checks out the
tagged commit, verifies the tag/version match, builds the CLI bundle, uploads the
artifact, and creates the GitHub Release.

## Hotfix Releases

For a hotfix, set `BASE_COMMIT` to the last known good commit you want to patch,
not to `main`. Cherry-pick only the fixes and release infrastructure that should
be part of the hotfix.

Before pushing the release branch, verify that an unwanted commit is not in the
branch history:

```bash
UNWANTED_COMMIT=c58e1dedecd8b7a77c2b02eda5b1d48bfb9c2d00

if git merge-base --is-ancestor "${UNWANTED_COMMIT}" HEAD; then
  echo "ERROR: unwanted commit is included in this release branch"
  exit 1
fi
```

For `v0.1.0-alpha.5`, using
`a6679f6053f54c3a0a5c6fbd6250ac5a137cfa3d` as `BASE_COMMIT` keeps
`c58e1dedecd8b7a77c2b02eda5b1d48bfb9c2d00` out of the ancestry, as long as the
release branch is built by cherry-picking the needed changes onto that base.

## Checklist

- The release branch is named `release/v<version>`.
- `pyproject.toml` and `chipcompiler/__init__.py` contain the same version.
- The release branch CI is green before creating the tag.
- The tag is annotated and points to `origin/release/v<version>`.
- No unwanted commit is an ancestor of the release branch.
- The GitHub Release is created by the `v*` tag workflow, not by an automatic
  tag from `main`.
