#!/usr/bin/env python3
"""Prepare and optionally publish a MatchPatch release."""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import release_changelog  # noqa: E402,F401
import release_changelog_flow  # noqa: E402
from release_support import (  # noqa: E402
    ReleaseError,
    build_and_smoke_distributions,
    build_docs,
    commit_and_tag,
    confirm_publish,
    git_diff_check,
    info,
    preflight,
    print_next_steps,
    push_release,
    run,
    run_installer_smoke,
    run_quality_checks,
    sync_wsl,
    update_lockfile,
    watch_release_workflow,
)

ApprovedChangelog = release_changelog_flow.ApprovedChangelog
build_evidence_commit_ids = release_changelog_flow.build_evidence_commit_ids
changelog_approval_path = release_changelog_flow.changelog_approval_path
changelog_paths = release_changelog_flow.changelog_paths
normalize_generated_changelog = release_changelog_flow.normalize_generated_changelog
validate_changelog_evidence_references = (
    release_changelog_flow.validate_changelog_evidence_references
)
validate_changelog_filler = release_changelog_flow.validate_changelog_filler
validate_changelog_length = release_changelog_flow.validate_changelog_length
validate_changelog_markdown = release_changelog_flow.validate_changelog_markdown
validate_changelog_shape = release_changelog_flow.validate_changelog_shape

PYPROJECT = ROOT / "pyproject.toml"
DEFAULT_BRANCH = "main"
VERSION_RE = re.compile(r"^\d+(?:\.\d+)+(?:[a-zA-Z0-9_.!+-]+)?$")


@dataclass(frozen=True)
class ReleaseNumStat:
    """Structured diff stat for one changed file."""

    insertions: int | None
    deletions: int | None
    path: str


@dataclass(frozen=True)
class ReleaseCommitEvidence:
    """Deterministic evidence for one release-range commit."""

    commit: str
    short_commit: str
    subject: str
    body: str | None
    changed_files: list[str]
    diff_stat: list[ReleaseNumStat]


def ensure_repo_root() -> None:
    root = run(["git", "rev-parse", "--show-toplevel"], capture=True)
    if Path(root).resolve() != ROOT:
        raise ReleaseError(f"Run this script from the MatchPatch checkout at {ROOT}")


def git_status_porcelain() -> str:
    return run(["git", "status", "--short"], capture=True)


def require_clean_tree() -> None:
    status = git_status_porcelain()
    if status:
        raise ReleaseError(
            "Working tree is not clean. Commit, stash, or remove unrelated changes before releasing.\n"
            + status,
            next_steps=[
                "Review the modified files with `git status --short` and `git diff`.",
                "Commit, stash, or remove those changes.",
                "Re-run the release command once the working tree is clean.",
            ],
        )


def current_branch() -> str:
    return run(["git", "branch", "--show-current"], capture=True)


def ensure_branch(branch: str, allow_other_branch: bool) -> None:
    actual = current_branch()
    if actual != branch and not allow_other_branch:
        raise ReleaseError(
            f"Expected branch '{branch}', but current branch is '{actual}'.",
            next_steps=[
                f"Switch to `{branch}` with `git switch {branch}`.",
                "Re-run the release command.",
                "Use `--allow-current-branch` only if you intentionally release from this branch.",
            ],
        )


def sync_branch(branch: str, skip_pull: bool) -> None:
    if skip_pull:
        return
    info("Fetching tags and fast-forwarding the release branch")
    run(["git", "fetch", "origin", "--tags"])
    run(["git", "pull", "--ff-only", "origin", branch])


def parse_version_arg(version: str) -> str:
    if version.startswith("v"):
        raise ReleaseError("Pass the package version without a leading 'v', for example: 0.2.0")
    if not VERSION_RE.fullmatch(version):
        raise ReleaseError(f"Version does not look like a PEP 440 release version: {version}")
    return version


def read_pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            break
        if in_project:
            match = re.match(r'^version\s*=\s*"([^"]+)"\s*$', stripped)
            if match:
                return match.group(1)
    raise ReleaseError("Could not find [project] version in pyproject.toml")


def write_pyproject_version(version: str) -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    in_project = False
    changed = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            break
        if in_project and re.match(r"^version\s*=", stripped):
            old_line = line
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f'version = "{version}"{newline}'
            changed = old_line != lines[index]
            break
    else:
        raise ReleaseError("Could not update [project] version in pyproject.toml")

    if not changed:
        raise ReleaseError(f"pyproject.toml already has version {version}")
    PYPROJECT.write_text("".join(lines), encoding="utf-8")


def ensure_tag_available(version: str, tag: str) -> None:
    if local_tag_exists(tag):
        raise ReleaseError(
            f"Local tag already exists: {tag}",
            next_steps=[
                f"If this tag is the prepared release, run `scripts/release.py {version} --publish`.",
                f"If you need to rebuild the release, delete the local tag with `git tag -d {tag}` and re-run the release command.",
            ],
        )
    if remote_tag_exists(tag):
        raise ReleaseError(
            f"Remote tag already exists on origin: {tag}",
            next_steps=[
                f"Check the published release with `gh release view {tag}`.",
                f"If the release is complete, no further local release step is required for {tag}.",
                "Only delete or replace a remote release tag if you are intentionally correcting a bad release.",
            ],
        )


def local_tag_exists(tag: str) -> bool:
    return bool(
        run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
            capture=True,
            check=False,
        )
    )


def remote_tag_exists(tag: str) -> bool:
    return bool(
        run(
            ["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"],
            capture=True,
            check=False,
        )
    )


def previous_release_tag(target_tag: str, target_commit: str = "HEAD") -> str | None:
    previous = run(
        [
            "git",
            "describe",
            "--tags",
            "--abbrev=0",
            "--match",
            "v[0-9]*",
            "--exclude",
            target_tag,
            target_commit,
        ],
        capture=True,
        check=False,
    )
    return previous or None


def release_commit_range(previous_tag: str | None, target_commit: str) -> str:
    if previous_tag:
        return f"{previous_tag}..{target_commit}"
    return target_commit


def commit_hashes_in_range(commit_range: str) -> list[str]:
    output = run(["git", "rev-list", "--reverse", commit_range], capture=True, check=False)
    if not output:
        return []
    return output.splitlines()


def parse_numstat_line(line: str) -> ReleaseNumStat:
    added, deleted, path = line.split("\t", 2)
    insertions = None if added == "-" else int(added)
    deletions = None if deleted == "-" else int(deleted)
    return ReleaseNumStat(insertions=insertions, deletions=deletions, path=path)


def commit_diff_stat(commit: str) -> list[ReleaseNumStat]:
    output = run(
        [
            "git",
            "show",
            "--numstat",
            "--format=",
            "--no-renames",
            "--no-ext-diff",
            "--first-parent",
            commit,
        ],
        capture=True,
    )
    if not output:
        return []
    return [parse_numstat_line(line) for line in output.splitlines() if line.strip()]


def commit_metadata(commit: str) -> tuple[str, str, str | None]:
    output = run(
        ["git", "show", "--quiet", "--format=%H%x1f%s%x1f%b", commit],
        capture=True,
        strip=False,
    )
    parts = output.split("\x1f", 2)
    if len(parts) != 3:
        raise ReleaseError(f"Could not parse commit metadata for {commit}")
    commit_hash, subject, body = parts
    subject = subject.strip()
    body = body.strip("\n")
    return commit_hash, subject, body or None


def collect_release_commit_evidence(commit_range: str) -> list[ReleaseCommitEvidence]:
    evidence: list[ReleaseCommitEvidence] = []
    for commit in commit_hashes_in_range(commit_range):
        commit_hash, subject, body = commit_metadata(commit)
        diff_stat = commit_diff_stat(commit)
        evidence.append(
            ReleaseCommitEvidence(
                commit=commit_hash,
                short_commit=commit_hash[:12],
                subject=subject,
                body=body,
                changed_files=[stat.path for stat in diff_stat],
                diff_stat=diff_stat,
            )
        )
    return evidence


def build_release_evidence(
    version: str, tag: str, target_commit: str = "HEAD"
) -> dict[str, object]:
    resolved_target_commit = run(["git", "rev-parse", target_commit], capture=True)
    previous_tag = previous_release_tag(tag, resolved_target_commit)
    commit_range = release_commit_range(previous_tag, resolved_target_commit)
    commits = collect_release_commit_evidence(commit_range)
    return {
        "version": version,
        "tag": tag,
        "previous_tag": previous_tag,
        "range": commit_range,
        "target_commit": resolved_target_commit,
        "commits": [
            {
                "commit": commit.commit,
                "short_commit": commit.short_commit,
                "subject": commit.subject,
                "body": commit.body,
                "changed_files": commit.changed_files,
                "diff_stat": [asdict(stat) for stat in commit.diff_stat],
            }
            for commit in commits
        ],
    }


def load_release_evidence(version: str, tag: str) -> dict[str, object]:
    return build_release_evidence(version, tag, target_commit=tag)


def approve_changelog(version: str, tag: str, args: argparse.Namespace) -> ApprovedChangelog:
    return release_changelog_flow.approve_changelog(
        version,
        tag,
        args,
        evidence_loader=load_release_evidence,
    )


def require_approved_changelog(
    version: str, tag: str, args: argparse.Namespace
) -> ApprovedChangelog:
    return release_changelog_flow.require_approved_changelog(
        version,
        tag,
        args,
        evidence_loader=load_release_evidence,
    )


def maybe_refresh_changelog_draft(version: str, tag: str, args: argparse.Namespace) -> None:
    release_changelog_flow.maybe_refresh_changelog_draft(
        version,
        tag,
        args,
        evidence_loader=load_release_evidence,
    )


def require_local_tag_ready(version: str, tag: str, *, check_remote: bool = True) -> None:
    if not local_tag_exists(tag):
        raise ReleaseError(f"Local release tag does not exist: {tag}")
    if check_remote and remote_tag_exists(tag):
        raise ReleaseError(
            f"Remote tag already exists on origin: {tag}",
            next_steps=[
                f"Check the published release with `gh release view {tag}`.",
                f"If the release is complete, no further release step is required for {tag}.",
            ],
        )
    if read_pyproject_version() != version:
        raise ReleaseError(
            f"pyproject.toml does not contain release version {version}",
            next_steps=[
                "Check the current version with `rg -n '^version =' pyproject.toml`.",
                f"Delete the local tag with `git tag -d {tag}` if it was created for the wrong commit.",
                f"Re-run `scripts/release.py {version}` after the version and tag state agree.",
            ],
        )

    head_sha = run(["git", "rev-parse", "HEAD"], capture=True)
    tag_sha = run(["git", "rev-list", "-n", "1", tag], capture=True)
    if head_sha != tag_sha:
        raise ReleaseError(
            f"Local tag {tag} does not point at HEAD.",
            next_steps=[
                f"Inspect the tagged commit with `git show --stat {tag}`.",
                "Inspect HEAD with `git show --stat HEAD`.",
                f"If the tag is wrong, delete it with `git tag -d {tag}` and re-run the release command.",
            ],
        )


def local_release_is_prepared(version: str, tag: str, *, check_remote: bool = True) -> bool:
    if not local_tag_exists(tag):
        return False
    require_local_tag_ready(version, tag, check_remote=check_remote)
    return True


def require_version_needs_bump(current_version: str, version: str, tag: str) -> None:
    if current_version != version:
        return
    raise ReleaseError(
        f"pyproject.toml already contains version {version}, but local tag {tag} is missing.",
        next_steps=[
            "Check whether HEAD is the intended release commit with `git log --oneline -1`.",
            f'If HEAD is the finished release commit, create the missing tag with `git tag -a {tag} -m "MatchPatch {tag}"`.',
            f"Then publish with `scripts/release.py {version} --publish`.",
            f"If HEAD is not a finished release commit, restore the previous version or choose a new release version before re-running `scripts/release.py {version}`.",
        ],
    )


def verify_public_release(version: str, tag: str, notes_file: str | None) -> None:
    info("Verifying GitHub Release and PyPI")
    if notes_file:
        run(
            [
                "gh",
                "release",
                "edit",
                tag,
                "--title",
                f"MatchPatch {tag}",
                "--notes-file",
                notes_file,
            ]
        )
    release_json = run(
        ["gh", "release", "view", tag, "--json", "tagName,name,isDraft,isPrerelease,assets"],
        capture=True,
    )
    release = json.loads(release_json)
    expected_asset = f"MatchPatch-Setup-{version}.exe"
    assets = {asset["name"] for asset in release.get("assets", [])}
    if expected_asset not in assets:
        raise ReleaseError(f"GitHub Release is missing installer asset: {expected_asset}")
    run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys, urllib.request; "
                "data = json.load(urllib.request.urlopen('https://pypi.org/pypi/matchpatch/json')); "
                "sys.exit(0 if sys.argv[1] in data['releases'] else 1)"
            ),
            version,
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and optionally publish a MatchPatch release.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("version", help="Release version without the leading v, for example 0.2.0.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Release branch.")
    parser.add_argument(
        "--allow-current-branch", action="store_true", help="Release from the current branch."
    )
    parser.add_argument(
        "--skip-pull", action="store_true", help="Do not fetch tags or pull the release branch."
    )
    parser.add_argument("--skip-sync", action="store_true", help="Do not run scripts/sync-wsl.sh.")
    parser.add_argument(
        "--skip-pre-push", action="store_true", help="Do not run the pre-push hook suite."
    )
    parser.add_argument("--gui-tests", action="store_true", help="Also run scripts/test-gui.sh.")
    parser.add_argument(
        "--installer", action="store_true", help="Also build and smoke-test the Windows installer."
    )
    parser.add_argument(
        "--publish", action="store_true", help="Push the release commit and tag to origin."
    )
    parser.add_argument(
        "--yes", action="store_true", help="Do not ask for confirmation before publishing."
    )
    parser.add_argument(
        "--notes-file", help="Release notes file to apply after the workflow completes."
    )
    parser.add_argument(
        "--approve-changelog",
        action="store_true",
        help="Approve the current changelog Markdown for the prepared release range.",
    )
    parser.add_argument(
        "--changelog-file",
        help="Markdown file to write or refresh as the draft changelog during prepare.",
    )
    parser.add_argument(
        "--changelog-evidence-file",
        help="JSON evidence bundle to write alongside the changelog prompt.",
    )
    parser.add_argument(
        "--changelog-prompt-file",
        help="Text file containing the bounded prompt used for manual drafting.",
    )
    parser.add_argument(
        "--generate-changelog",
        action="store_true",
        help="Use the configured provider to draft the changelog from the evidence bundle.",
    )
    parser.add_argument(
        "--skip-changelog-ai",
        action="store_true",
        help="Write the changelog evidence bundle, prompt, and manual draft scaffold without AI.",
    )
    parser.add_argument(
        "--changelog-provider",
        help="Changelog provider name, for example openai-compatible.",
    )
    parser.add_argument(
        "--changelog-model",
        help="Model name to use with the configured changelog provider.",
    )
    parser.add_argument(
        "--changelog-base-url",
        help="Base URL for the configured changelog provider API.",
    )
    parser.add_argument(
        "--changelog-timeout",
        type=float,
        help="Timeout in seconds for the changelog provider request.",
    )
    return parser.parse_args()


def handle_approval_only(version: str, tag: str, args: argparse.Namespace) -> bool:
    if not args.approve_changelog or args.publish:
        return False
    require_local_tag_ready(version, tag, check_remote=False)
    approve_changelog(version, tag, args)
    print_next_steps(
        [
            f"Publish the prepared release with `{Path('scripts/release.py')} {version} --publish`.",
        ],
        file=sys.stdout,
    )
    return True


def prepare_release_if_needed(version: str, tag: str, args: argparse.Namespace) -> bool:
    prepared_already = local_release_is_prepared(version, tag)
    if prepared_already:
        info(f"Found prepared local release {tag}")
        return True

    ensure_tag_available(version, tag)
    current_version = read_pyproject_version()
    require_version_needs_bump(current_version, version, tag)
    info(f"Updating project version: {current_version} -> {version}")
    write_pyproject_version(version)
    if read_pyproject_version() != version:
        raise ReleaseError("Version update did not stick.")

    update_lockfile()
    sync_wsl(args.skip_sync)
    run_quality_checks(args.skip_pre_push, args.gui_tests)
    build_docs()
    build_and_smoke_distributions(version)
    if args.installer:
        run_installer_smoke()
    git_diff_check()
    commit_and_tag(version, tag)
    maybe_refresh_changelog_draft(version, tag, args)
    return False


def main() -> int:
    args = parse_args()
    try:
        version = parse_version_arg(args.version)
        tag = f"v{version}"

        ensure_repo_root()
        ensure_branch(args.branch, args.allow_current_branch)
        require_clean_tree()
        preflight(args)
        if handle_approval_only(version, tag, args):
            return 0

        sync_branch(args.branch, args.skip_pull)
        require_clean_tree()
        prepared_already = prepare_release_if_needed(version, tag, args)

        if prepared_already and not args.publish and not args.approve_changelog:
            maybe_refresh_changelog_draft(version, tag, args)

        approved_changelog: ApprovedChangelog | None = None
        if args.approve_changelog:
            approved_changelog = approve_changelog(version, tag, args)

        if args.publish:
            approved_changelog = approved_changelog or require_approved_changelog(
                version, tag, args
            )
            run(["gh", "auth", "status"])
            confirm_publish(args.yes, tag, args.branch)
            push_release(args.branch, tag)
            watch_release_workflow(tag)
            verify_public_release(version, tag, str(approved_changelog.notes_path))
            info(f"Release {tag} published.")
            print(f"Release {tag} is complete.")
        elif args.approve_changelog:
            print_next_steps(
                [
                    f"Publish the prepared release with `{Path('scripts/release.py')} {version} --publish`.",
                ],
                file=sys.stdout,
            )
        else:
            info(f"Release {tag} is prepared locally.")
            print_next_steps(
                [
                    f"Review the release commit and tag with `git show --stat {tag}`.",
                    f"Edit the changelog draft and approve it with `{Path('scripts/release.py')} {version} --approve-changelog`.",
                    f"Publish it with `{Path('scripts/release.py')} {version} --publish` after approval.",
                ],
                file=sys.stdout,
            )

        return 0
    except ReleaseError as error:
        print(f"\nrelease.py: {error}", file=sys.stderr)
        print_next_steps(error.next_steps)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
