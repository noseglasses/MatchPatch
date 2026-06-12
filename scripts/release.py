#!/usr/bin/env python3
"""Prepare and optionally publish a MatchPatch release."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
REPOSITORY = "noseglasses/MatchPatch"
DEFAULT_BRANCH = "main"
VERSION_RE = re.compile(r"^\d+(?:\.\d+)+(?:[a-zA-Z0-9_.!+-]+)?$")


class ReleaseError(RuntimeError):
    """A release precondition failed."""


def info(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def run(
    args: list[str],
    *,
    capture: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> str:
    print("+ " + " ".join(args), flush=True)
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )
    if check and result.returncode != 0:
        if capture:
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
        raise ReleaseError(f"Command failed with exit code {result.returncode}: {' '.join(args)}")
    if capture:
        return result.stdout.strip()
    return ""


def venv_bin(name: str) -> str:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    path = data_home / "matchpatch" / ".venv-wsl" / "bin" / name
    return str(path)


def wsl_uv_env() -> dict[str, str]:
    env = os.environ.copy()
    data_home = Path(env.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(data_home / "matchpatch" / ".venv-wsl"))
    return env


def require_executable(path: str) -> None:
    if not Path(path).is_file():
        raise ReleaseError(f"Required executable not found: {path}")


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise ReleaseError(f"Required command not found on PATH: {name}")


def require_script(path: str) -> None:
    script = ROOT / path
    if not script.is_file():
        raise ReleaseError(f"Required script not found: {path}")
    if not os.access(script, os.X_OK):
        raise ReleaseError(f"Required script is not executable: {path}")


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
            + status
        )


def current_branch() -> str:
    return run(["git", "branch", "--show-current"], capture=True)


def ensure_branch(branch: str, allow_other_branch: bool) -> None:
    actual = current_branch()
    if actual != branch and not allow_other_branch:
        raise ReleaseError(f"Expected branch '{branch}', but current branch is '{actual}'.")


def preflight_local_tools(
    skip_sync: bool, skip_pre_push: bool, gui_tests: bool, installer: bool
) -> None:
    info("Checking local release prerequisites")
    for command in ("git", "uv"):
        require_command(command)

    require_script("scripts/sync-wsl.sh")
    require_script("scripts/build-docs.sh")
    if gui_tests:
        require_script("scripts/test-gui.sh")
    if installer:
        require_script("scripts/test-windows-installer-from-wsl.sh")

    if skip_sync:
        for executable in ("ruff", "ty", "pytest", "sphinx-build"):
            require_executable(venv_bin(executable))
        if not skip_pre_push:
            require_executable(venv_bin("pre-commit"))


def github_permissions() -> dict[str, object]:
    repo_json = run(["gh", "api", f"repos/{REPOSITORY}"], capture=True)
    repo = json.loads(repo_json)
    permissions = repo.get("permissions")
    if not isinstance(permissions, dict):
        raise ReleaseError("GitHub API response did not include repository permissions.")
    return permissions


def require_github_permissions(branch: str) -> None:
    info("Checking GitHub authentication and repository permissions")
    require_command("gh")
    run(["gh", "auth", "status"])
    run(["gh", "repo", "view", REPOSITORY, "--json", "nameWithOwner"], capture=True)

    permissions = github_permissions()
    can_push = any(bool(permissions.get(name)) for name in ("push", "maintain", "admin"))
    if not can_push:
        raise ReleaseError(f"GitHub user does not have push permission for {REPOSITORY}.")

    run(["gh", "release", "list", "--repo", REPOSITORY, "--limit", "1"], capture=True)
    run(["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"], capture=True)
    run(["git", "push", "--dry-run", "origin", f"HEAD:refs/heads/{branch}"])


def require_release_workflow_prerequisites() -> None:
    info("Checking release workflow publishing prerequisites")
    if not RELEASE_WORKFLOW.is_file():
        raise ReleaseError(f"Release workflow not found: {RELEASE_WORKFLOW.relative_to(ROOT)}")

    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    required_snippets = {
        'tag trigger for "v*"': '- "v*"',
        "PyPI environment": "name: pypi",
        "OIDC id-token write permission": "id-token: write",
        "package build": "uv build --no-sources",
        "trusted publishing command": "uv publish",
        "Windows installer attachment": "gh release upload",
    }
    missing = [label for label, snippet in required_snippets.items() if snippet not in text]
    if missing:
        raise ReleaseError(
            "Release workflow is missing required publishing wiring: " + ", ".join(missing)
        )


def preflight(args: argparse.Namespace) -> None:
    preflight_local_tools(args.skip_sync, args.skip_pre_push, args.gui_tests, args.installer)
    require_release_workflow_prerequisites()
    if args.publish:
        require_github_permissions(args.branch)


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


def ensure_tag_available(tag: str) -> None:
    if local_tag_exists(tag):
        raise ReleaseError(f"Local tag already exists: {tag}")
    if remote_tag_exists(tag):
        raise ReleaseError(f"Remote tag already exists on origin: {tag}")


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


def require_local_tag_ready(version: str, tag: str) -> None:
    if not local_tag_exists(tag):
        raise ReleaseError(f"Local release tag does not exist: {tag}")
    if remote_tag_exists(tag):
        raise ReleaseError(f"Remote tag already exists on origin: {tag}")
    if read_pyproject_version() != version:
        raise ReleaseError(f"pyproject.toml does not contain release version {version}")

    head_sha = run(["git", "rev-parse", "HEAD"], capture=True)
    tag_sha = run(["git", "rev-list", "-n", "1", tag], capture=True)
    if head_sha != tag_sha:
        raise ReleaseError(f"Local tag {tag} does not point at HEAD.")


def local_release_is_prepared(version: str, tag: str) -> bool:
    if not local_tag_exists(tag):
        return False
    require_local_tag_ready(version, tag)
    return True


def sync_wsl(skip_sync: bool) -> None:
    if skip_sync:
        return
    info("Synchronizing the WSL development environment")
    run(["scripts/sync-wsl.sh"])


def update_lockfile() -> None:
    info("Updating dependency lockfile")
    run(["uv", "lock"], env=wsl_uv_env())


def run_quality_checks(skip_pre_push: bool, gui_tests: bool) -> None:
    info("Running local quality checks")
    for executable in ("ruff", "ty", "pytest"):
        require_executable(venv_bin(executable))
    run([venv_bin("ruff"), "check", "."])
    run([venv_bin("ruff"), "format", "--check", "."])
    run([venv_bin("ty"), "check"])
    run([venv_bin("pytest")])
    if gui_tests:
        run(["scripts/test-gui.sh"])
    if not skip_pre_push:
        require_executable(venv_bin("pre-commit"))
        run([venv_bin("pre-commit"), "install", "--install-hooks"])
        run([venv_bin("pre-commit"), "run", "--all-files", "--hook-stage", "pre-push"])


def build_docs() -> None:
    info("Building strict offline documentation")
    run(["scripts/build-docs.sh"])
    if not (ROOT / "docs_html" / "index.html").is_file():
        raise ReleaseError("Documentation build did not produce docs_html/index.html")


def build_and_smoke_distributions(version: str) -> None:
    info("Building and smoke-testing Python distributions")
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    run(["uv", "build", "--no-sources"])

    wheels = sorted((ROOT / "dist").glob("matchpatch-*.whl"))
    sdists = sorted((ROOT / "dist").glob("matchpatch-*.tar.gz"))
    if len(wheels) != 1:
        raise ReleaseError(f"Expected exactly one wheel in dist/, found {len(wheels)}")
    if len(sdists) != 1:
        raise ReleaseError(
            f"Expected exactly one source distribution in dist/, found {len(sdists)}"
        )

    wheel = str(wheels[0])
    sdist = str(sdists[0])
    run(
        [
            "uv",
            "run",
            "--isolated",
            "--no-project",
            "--with",
            wheel,
            "python",
            "-c",
            "import matchpatch",
        ]
    )
    run(
        [
            "uv",
            "run",
            "--isolated",
            "--no-project",
            "--with",
            sdist,
            "python",
            "-c",
            "import matchpatch",
        ]
    )
    output = run(
        ["uv", "run", "--isolated", "--no-project", "--with", wheel, "matchpatch", "--version"],
        capture=True,
    )
    if version not in output:
        raise ReleaseError(f"Built CLI version did not contain {version!r}: {output}")


def run_installer_smoke() -> None:
    info("Building and smoke-testing the Windows installer")
    run(["scripts/test-windows-installer-from-wsl.sh"])


def git_diff_check() -> None:
    info("Checking release diff")
    run(["git", "diff", "--check"])


def release_commit_message(tag: str) -> str:
    return f"chore(release): {tag}"


def validate_commit_message(message: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as message_file:
        message_file.write(message)
        message_path = message_file.name
    try:
        run([sys.executable, "scripts/check_commit_msg.py", message_path])
    finally:
        Path(message_path).unlink(missing_ok=True)


def commit_and_tag(version: str, tag: str) -> None:
    info("Committing version bump and creating the release tag")
    message = release_commit_message(tag)
    validate_commit_message(message)
    run(["git", "add", "pyproject.toml", "uv.lock"])
    run(["git", "commit", "-m", message])
    run(["git", "tag", "-a", tag, "-m", f"MatchPatch {tag}"])
    run(["git", "show", "--stat", tag])


def confirm_publish(yes: bool, tag: str, branch: str) -> None:
    if yes:
        return
    print()
    answer = input(
        f"Push branch '{branch}' and tag '{tag}' to origin, triggering the release? [y/N] "
    )
    if answer.strip().lower() not in {"y", "yes"}:
        raise ReleaseError("Publish cancelled.")


def push_release(branch: str, tag: str) -> None:
    info("Pushing the release commit and tag")
    run(["git", "push", "origin", branch])
    run(["git", "push", "origin", tag])


def find_release_run(tag: str, attempts: int = 12) -> int | None:
    for _ in range(attempts):
        output = run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                "release.yml",
                "--limit",
                "20",
                "--json",
                "databaseId,headBranch,event,status,conclusion",
            ],
            capture=True,
            check=False,
        )
        if output:
            runs = json.loads(output)
            for run_data in runs:
                if run_data.get("headBranch") == tag:
                    return int(run_data["databaseId"])
        time.sleep(5)
    return None


def watch_release_workflow(tag: str) -> None:
    info("Watching the GitHub Actions release workflow")
    run_id = find_release_run(tag)
    if run_id is None:
        print(f"Could not find a release workflow run for {tag}. Check GitHub Actions manually.")
        return
    run(["gh", "run", "watch", str(run_id)])
    run(["gh", "run", "view", str(run_id)])


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
    run([sys.executable, "-m", "pip", "index", "versions", "matchpatch"])


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        version = parse_version_arg(args.version)
        tag = f"v{version}"

        ensure_repo_root()
        ensure_branch(args.branch, args.allow_current_branch)
        require_clean_tree()
        preflight(args)
        sync_branch(args.branch, args.skip_pull)
        require_clean_tree()

        prepared_already = args.publish and local_release_is_prepared(version, tag)
        if prepared_already:
            info(f"Found prepared local release {tag}")
        else:
            ensure_tag_available(tag)
            current_version = read_pyproject_version()
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

        if args.publish:
            run(["gh", "auth", "status"])
            confirm_publish(args.yes, tag, args.branch)
            push_release(args.branch, tag)
            watch_release_workflow(tag)
            verify_public_release(version, tag, args.notes_file)
            info(f"Release {tag} published.")
        else:
            info(f"Release {tag} is prepared locally.")
            print(f"Next step: {Path('scripts/release.py')} {version} --publish")

        return 0
    except ReleaseError as error:
        print(f"\nrelease.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
