# Release Checklist

Use `scripts/release.py` to prepare and publish MatchPatch releases. The script
keeps the release path intentionally small: pass the new version, let it run the
checks, then decide whether to publish the tag.

MatchPatch releases are tag-driven. A pushed tag named `v<version>` starts
`.github/workflows/release.yml`. The workflow verifies that the tag matches
`project.version` in `pyproject.toml`, builds and publishes the Python
distributions to PyPI, builds the offline documentation payload, and builds,
smoke-tests, and attaches the Windows installer to the GitHub Release.

## Prerequisites

- You have push access to `noseglasses/MatchPatch`.
- You can publish GitHub Releases for the repository.
- The PyPI project is configured for trusted publishing from the GitHub Actions
  `pypi` environment.
- `gh`, `git`, `uv`, and the MatchPatch WSL tooling are available.
- `gh auth status` succeeds before publishing.
- The working tree is clean before starting the release.

The script checks these prerequisites before it edits `pyproject.toml`. For a
publishing run, it verifies local tools, required MatchPatch helper scripts,
the release workflow publishing configuration, GitHub authentication, repository
permissions, release visibility, the remote release branch, and a dry-run push
to the release branch. PyPI trusted publishing cannot be fully proven from a
local checkout; the script checks that the release workflow is wired for the
`pypi` environment, OIDC `id-token: write`, `uv publish`, and installer upload,
then the GitHub Actions release job proves the PyPI trusted-publisher
configuration when it publishes.

## Normal Release

From the repository root, run the release script with the package version
without the leading `v`:

```bash
scripts/release.py 0.2.0 --publish
```

The script will:

- check release prerequisites before changing files;
- require a clean working tree;
- require the release branch, normally `main`;
- fetch tags and fast-forward the branch;
- check that `v0.2.0` does not already exist locally or on `origin`;
- update `project.version` in `pyproject.toml`;
- run `scripts/sync-wsl.sh`;
- run `ruff check .`, `ruff format --check .`, `ty check`, and `pytest` from
  the shared WSL environment;
- run the pre-push hook suite;
- build the strict Sphinx docs;
- build and smoke-test the wheel and source distribution;
- run `git diff --check`;
- commit the version bump as `chore(release): v0.2.0`;
- create the annotated tag `v0.2.0`;
- ask for confirmation before publishing;
- push the release commit and tag;
- watch the GitHub Actions release workflow;
- check that the GitHub Release has `MatchPatch-Setup-0.2.0.exe`;
- check PyPI package versions.

Use `--yes` when running in a trusted terminal and you do not want the final
publish confirmation prompt:

```bash
scripts/release.py 0.2.0 --publish --yes
```

For a cautious two-step release, prepare everything locally first:

```bash
scripts/release.py 0.2.0
```

If that succeeds, publish the prepared local tag later:

```bash
scripts/release.py 0.2.0 --publish
```

## Release Notes

Write release notes in a temporary Markdown file before publishing if you do not
want the placeholder GitHub Release notes created by the workflow.

```bash
scripts/release.py 0.2.0 --publish --notes-file /tmp/matchpatch-0.2.0-notes.md
```

The script applies that file to the GitHub Release after the release workflow
finishes.

Suggested sections:

- Highlights
- User-visible changes
- Installer changes
- Documentation changes
- Fixes
- Known issues

## Optional Checks

Run the GUI test wrapper as part of the release:

```bash
scripts/release.py 0.2.0 --gui-tests
```

Build and smoke-test the Windows installer locally before tagging:

```bash
scripts/release.py 0.2.0 --installer
```

The installer check uses `scripts/test-windows-installer-from-wsl.sh`, which
mirrors the checkout to the configured Windows workdir and runs the native
installer smoke tests. This is slower, but useful for releases that touch
packaging, GUI startup, bundled docs, or installer behavior.

## Useful Flags

- `--branch <name>` releases from a branch other than `main`.
- `--allow-current-branch` permits the current branch instead of enforcing the
  branch name.
- `--skip-pull` skips `git fetch origin --tags` and `git pull --ff-only`.
- `--skip-sync` skips `scripts/sync-wsl.sh`.
- `--skip-pre-push` skips the pre-push hook suite.
- `--publish` pushes the release commit and tag.
- `--yes` skips the publish confirmation prompt.

Avoid skip flags for a normal public release. They are intended for recovering
from local tooling trouble after you already understand which check was run
elsewhere.

## Version Rules

- Pass a PEP 440 package version, for example `0.2.0`.
- Do not include the leading `v` when calling the script.
- The Git tag is always `v<version>`.
- Do not reuse a version after PyPI publishing succeeds.
- Do not reuse a pushed tag after a partial public release. Prefer a new patch
  version unless the tag never left your machine.

## After Publishing

Open the GitHub Release and check the notes:

```bash
gh release view v0.2.0 --web
```

Open PyPI and verify the new version:

```bash
gh browse https://pypi.org/project/matchpatch/
```

Download the installer from the GitHub Release and run a final smoke test on a
Windows machine if the release includes installer or GUI changes.

## Failure Recovery

If the script fails before it creates the commit, fix the reported problem and
run it again. If it changed `pyproject.toml`, either keep the version change and
continue after fixing the problem, or restore the file manually before choosing
a different version.

If the script fails after creating the local tag but before publishing, inspect
the state:

```bash
git status --short
git show --stat v0.2.0
```

Delete an unpublished local tag if you need to redo the local release:

```bash
git tag -d v0.2.0
```

If the tag was pushed and PyPI publishing succeeded, do not reuse the same
version. Fix the problem, choose a new patch version, and release again.

Rerun a failed GitHub Actions release job only when the source tag is still
correct and the failure was environmental:

```bash
gh run rerun <run-id> --failed
```

If an installer asset must be replaced after a successful rebuild, upload it
with `--clobber` only when the tag still represents the exact source used to
build that asset:

```bash
gh release upload v0.2.0 dist/installer/MatchPatch-Setup-0.2.0.exe --clobber
```
