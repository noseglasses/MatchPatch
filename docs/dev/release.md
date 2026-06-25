# Release Checklist

Use `scripts/release.py` to prepare and publish MatchPatch releases. The script
keeps the release path intentionally small: prepare the release, review the
generated notes, approve them, then publish the tag.

MatchPatch releases are tag-driven. A pushed tag named `v<version>` starts
`.github/workflows/release.yml`. The workflow verifies that the tag matches
`project.version` in `pyproject.toml`, builds and publishes the Python
distributions to PyPI, builds the offline documentation payload, and builds,
smoke-tests, uploads, and attaches the Windows installer and macOS DMG to the
GitHub Release.

The macOS app bundle is currently ad-hoc signed so its bundle seal is valid, but
it is not Developer ID signed or notarized. The artifacts are suitable for
release testing and distribution checks, but first launch may require manual
Gatekeeper approval on macOS.

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
scripts/release.py 0.8.1 --publish
```

The script will:

- check release prerequisites before changing files;
- require a clean working tree;
- require the release branch, normally `main`;
- fetch tags and fast-forward the branch;
- check that `v0.8.1` does not already exist locally or on `origin`;
- update `project.version` in `pyproject.toml`;
- run `scripts/sync-wsl.sh`;
- run `ruff check .`, `ruff format --check .`, `ty check`, and `pytest` from
  the shared WSL environment;
- run the pre-push hook suite;
- build the strict Sphinx docs;
- build and smoke-test the wheel and source distribution;
- run `git diff --check`;
- commit the version bump as `chore(release): v0.8.1`;
- create the annotated tag `v0.8.1`;
- ask for confirmation before publishing;
- push the release commit and tag;
- watch the GitHub Actions release workflow;
- check that the GitHub Release has `MatchPatch-Setup-0.8.1.exe` and
  `MatchPatch-macOS-arm64-0.8.1.dmg`;
- check PyPI package versions.

Use `--yes` when running in a trusted terminal and you do not want the final
publish confirmation prompt:

```bash
scripts/release.py 0.8.1 --publish --yes
```

For a cautious two-step release, prepare everything locally first:

```bash
scripts/release.py 0.8.1
```

That prepare step writes or refreshes a changelog draft at
`dist/release-notes/matchpatch-v<version>.md` by default, along with the
supporting evidence bundle and prompt beside it. If AI drafting is enabled, the
script uses the configured provider to generate the Markdown; otherwise it
writes a manual scaffold. These default generated files live under ignored
`dist/` output and are not intended to be committed.

Review and edit the generated Markdown, then approve the exact content for the
prepared release range. Publishing is blocked until this approval gate passes:

```bash
scripts/release.py 0.8.1 --approve-changelog
```

If that succeeds, publish the prepared local tag later:

```bash
scripts/release.py 0.8.1 --publish
```

## Release Notes

Publishing requires an approved changelog. The approval record is stored in a
matching `.approved.json` sidecar next to the notes file after
`--approve-changelog` succeeds. The approval step is local-only; it validates the
prepared tag, notes content, and release evidence without contacting GitHub or an
AI provider.

If you want to use a manually written Markdown file, point `--notes-file` at it
before approving and publishing. If you want the prepare step to write the
draft somewhere else, use `--changelog-file` instead:

```bash
scripts/release.py 0.8.1 --notes-file /tmp/matchpatch-0.8.1-notes.md --approve-changelog
scripts/release.py 0.8.1 --publish --notes-file /tmp/matchpatch-0.8.1-notes.md
scripts/release.py 0.8.1 --changelog-file /tmp/matchpatch-0.8.1-draft.md
```

The publish step refuses to continue if the approved notes no longer match the
current Markdown content or release range. After the workflow finishes, the
script applies the approved notes to the GitHub Release.

For AI drafting, set `MATCHPATCH_CHANGELOG_PROVIDER=openai-compatible` and
`MATCHPATCH_CHANGELOG_API_KEY`. You can also override
`MATCHPATCH_CHANGELOG_MODEL`, `MATCHPATCH_CHANGELOG_BASE_URL`, and
`MATCHPATCH_CHANGELOG_TIMEOUT` if needed.

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
scripts/release.py 0.8.1 --gui-tests
```

Build and smoke-test the Windows installer locally before tagging:

```bash
scripts/release.py 0.8.1 --installer
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

- Pass a PEP 440 package version, for example `0.8.1`.
- Do not include the leading `v` when calling the script.
- The Git tag is always `v<version>`.
- Do not reuse a version after PyPI publishing succeeds.
- Do not reuse a pushed tag after a partial public release. Prefer a new patch
  version unless the tag never left your machine.

## After Publishing

Open the GitHub Release and check the notes:

```bash
gh release view v0.8.1 --web
```

Open PyPI and verify the new version:

```bash
gh browse https://pypi.org/project/matchpatch/
```

Test the published PyPI package in fresh WSL and native Windows virtual
environments using the "Test The Published PyPI Package" section in
[Commands](commands.md).
This catches missing wheel dependency metadata and entry-point startup problems
that a repository checkout can hide.

Download the installers from the GitHub Release and run final smoke tests on a
Windows machine and an arm64 macOS machine if the release includes installer or
GUI changes.

For macOS, treat the GitHub Actions jobs as the source of truth:

- `quality.yml` builds and smoke-tests the DMG on `macos-15`.
- The macOS DMG smoke mounts the image and runs both bundled CLI startup and
  non-interactive GUI startup from `MatchPatch.app`.
- `release.yml` uploads `MatchPatch-macOS-<arch>-<version>.dmg` to the GitHub
  Release after the same smoke checks pass.
- The release artifact is not Developer ID signed or notarized, so the first
  launch may show a manual Gatekeeper approval prompt.
- We do not have local Mac hardware in development, so real USB MIDI/audio
  validation still depends on CI-safe mocks or external hardware testers.

First public Mac release checklist:

1. Confirm the GitHub Release contains the expected DMG name for the runner
   architecture.
2. Download the DMG on macOS and confirm it mounts and opens.
3. Expect a first-launch Gatekeeper prompt unless a future Developer ID signed
   and notarized release path has been added.
4. Treat CI as packaging validation only until a maintainer or tester confirms
   real Helix and Pod Go hardware on macOS.

### Deferred macOS Signing And Notarization

These steps are intentionally out of scope until the project has Apple
Developer Program funding and release credentials. Keep them documented here so
future maintainers know what needs to be added later:

- import a Developer ID certificate from GitHub Actions secrets;
- sign `MatchPatch.app` with the hardened runtime and any required
  entitlements;
- optionally sign the DMG or other final distribution artifact;
- submit the build with `xcrun notarytool`;
- staple the notarization ticket with `xcrun stapler`;
- verify the signed release with `spctl --assess`;
- define the GitHub secrets required for signing and notarization;
- document the credential rotation process for those secrets.

Do not add any of those steps to the current release workflow until the project
can support them. The release path described above remains without Developer ID
signing or notarization today, and there is no promise of a smooth Gatekeeper
experience yet.

## Failure Recovery

If the script fails before it creates the commit, fix the reported problem and
run it again. If it changed `pyproject.toml`, either keep the version change and
continue after fixing the problem, or restore the file manually before choosing
a different version.

If the script fails after creating the local tag but before publishing, inspect
the state:

```bash
git status --short
git show --stat v0.8.1
```

Delete an unpublished local tag if you need to redo the local release:

```bash
git tag -d v0.8.1
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
gh release upload v0.8.1 dist/installer/MatchPatch-Setup-0.8.1.exe --clobber
```

For macOS releases, use the matching DMG name from the release job, for example
`dist/installer/MatchPatch-macOS-arm64-0.8.1.dmg`.
