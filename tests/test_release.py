import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)


def sample_release_evidence() -> dict[str, object]:
    return {
        "version": "0.9.0",
        "tag": "v0.9.0",
        "previous_tag": "v0.8.2",
        "range": "v0.8.2..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "target_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "commits": [
            {
                "commit": "1111111111111111111111111111111111111111",
                "short_commit": "111111111111",
                "subject": "fix: helpful change",
                "body": None,
                "changed_files": ["src/matchpatch/release.py"],
                "diff_stat": [
                    {"insertions": 3, "deletions": 1, "path": "src/matchpatch/release.py"}
                ],
            },
            {
                "commit": "2222222222222222222222222222222222222222",
                "short_commit": "222222222222",
                "subject": "docs: release notes cleanup",
                "body": None,
                "changed_files": ["docs/dev/release.md"],
                "diff_stat": [{"insertions": 1, "deletions": 0, "path": "docs/dev/release.md"}],
            },
        ],
    }


def test_previous_release_tag_uses_git_describe(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(args, *, capture=False, check=True, env=None, strip=True):
        del capture, check, env, strip
        calls.append(tuple(args))
        if args == [
            "git",
            "describe",
            "--tags",
            "--abbrev=0",
            "--match",
            "v[0-9]*",
            "--exclude",
            "v0.8.2",
            "HEAD",
        ]:
            return "v0.8.1"
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(release, "run", fake_run)

    assert release.previous_release_tag("v0.8.2") == "v0.8.1"
    assert calls == [
        (
            "git",
            "describe",
            "--tags",
            "--abbrev=0",
            "--match",
            "v[0-9]*",
            "--exclude",
            "v0.8.2",
            "HEAD",
        )
    ]


def test_build_release_evidence_collects_commit_metadata(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    target_commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    commit_one = "1111111111111111111111111111111111111111"
    commit_two = "2222222222222222222222222222222222222222"

    def fake_run(args, *, capture=False, check=True, env=None, strip=True):
        del capture, check, env, strip
        calls.append(tuple(args))
        if args == ["git", "rev-parse", "HEAD"]:
            return target_commit
        if args == [
            "git",
            "describe",
            "--tags",
            "--abbrev=0",
            "--match",
            "v[0-9]*",
            "--exclude",
            "v0.9.0",
            target_commit,
        ]:
            return "v0.8.2"
        if args == ["git", "rev-list", "--reverse", "v0.8.2.." + target_commit]:
            return "\n".join([commit_one, commit_two])
        if args == ["git", "show", "--quiet", "--format=%H%x1f%s%x1f%b", commit_one]:
            return commit_one + "\x1ffix: first change\x1fBody line 1\nBody line 2\n"
        if args == ["git", "show", "--quiet", "--format=%H%x1f%s%x1f%b", commit_two]:
            return commit_two + "\x1fdocs: second change\x1f"
        if args == [
            "git",
            "show",
            "--numstat",
            "--format=",
            "--no-renames",
            "--no-ext-diff",
            "--first-parent",
            commit_one,
        ]:
            return "3\t1\tsrc/matchpatch/release.py\n0\t0\tdocs/dev/release.md\n"
        if args == [
            "git",
            "show",
            "--numstat",
            "--format=",
            "--no-renames",
            "--no-ext-diff",
            "--first-parent",
            commit_two,
        ]:
            return "1\t0\tdocs/dev/release.md\n"
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(release, "run", fake_run)

    evidence = release.build_release_evidence("0.9.0", "v0.9.0")

    assert evidence["version"] == "0.9.0"
    assert evidence["tag"] == "v0.9.0"
    assert evidence["previous_tag"] == "v0.8.2"
    assert evidence["range"] == f"v0.8.2..{target_commit}"
    assert evidence["target_commit"] == target_commit
    assert [commit["commit"] for commit in evidence["commits"]] == [commit_one, commit_two]
    assert evidence["commits"][0]["short_commit"] == commit_one[:12]
    assert evidence["commits"][0]["body"] == "Body line 1\nBody line 2"
    assert evidence["commits"][0]["changed_files"] == [
        "src/matchpatch/release.py",
        "docs/dev/release.md",
    ]
    assert evidence["commits"][0]["diff_stat"] == [
        {"insertions": 3, "deletions": 1, "path": "src/matchpatch/release.py"},
        {"insertions": 0, "deletions": 0, "path": "docs/dev/release.md"},
    ]
    assert evidence["commits"][1]["body"] is None
    assert evidence["commits"][1]["changed_files"] == ["docs/dev/release.md"]


def test_validate_changelog_helpers_cover_shape_length_filler_and_evidence() -> None:
    good_markdown = "# Release Notes\n\n- Fix release evidence for [evidence:abc1234]."

    assert release.validate_changelog_shape(good_markdown) is None
    assert release.validate_changelog_length(good_markdown, max_chars=200) is None
    assert release.validate_changelog_filler(good_markdown) is None
    assert release.validate_changelog_evidence_references(good_markdown, {"abc1234"}) is None
    assert release.validate_changelog_markdown(good_markdown, {"abc1234"}) is None


def test_validate_changelog_helpers_reject_bad_input() -> None:
    assert (
        release.validate_changelog_shape("Release notes")
        == "Changelog Markdown must start with a level 1 or 2 heading."
    )
    assert (
        release.validate_changelog_length("x" * 4001)
        == "Changelog Markdown is too long: 4001 characters (max 4000)."
    )
    assert (
        release.validate_changelog_filler("# Notes\n\n- Various improvements across the app.")
        == "Changelog Markdown contains vague filler: 'Various improvements'."
    )
    assert (
        release.validate_changelog_evidence_references(
            "# Notes\n\n- [evidence:deadbee]", {"abc1234"}
        )
        == "Changelog Markdown references unknown evidence commit IDs: deadbee"
    )
    assert (
        release.validate_changelog_evidence_references("# Notes\n\n- Detail", {"abc1234"})
        == "Changelog Markdown must reference at least one evidence commit ID."
    )


def test_build_changelog_prompt_is_bounded_and_uses_only_supplied_evidence() -> None:
    evidence = {
        "version": "0.9.0",
        "tag": "v0.9.0",
        "previous_tag": "v0.8.2",
        "range": "v0.8.2..HEAD",
        "target_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "commits": [
            {
                "commit": f"{index:040x}",
                "short_commit": f"{index:012x}",
                "subject": f"Commit {index} subject",
                "body": "Body line 1\nBody line 2\nBody line 3\nBody line 4\nBody line 5",
                "changed_files": [f"src/file{index}.py", f"docs/file{index}.md"],
                "diff_stat": [
                    {"insertions": index, "deletions": index + 1, "path": f"src/file{index}.py"}
                ],
            }
            for index in range(12)
        ],
    }

    prompt = release.release_changelog.build_changelog_prompt(evidence)

    assert len(prompt) <= release.release_changelog.MAX_PROMPT_CHARS
    assert "Use only the supplied evidence." in prompt
    assert "Commit 0 subject" in prompt
    assert "... 4 more commits omitted from the prompt ..." in prompt
    assert "Body line 5" not in prompt


def test_draft_changelog_notes_reports_missing_ai_configuration(
    monkeypatch, tmp_path: Path
) -> None:
    evidence = sample_release_evidence()

    monkeypatch.delenv("MATCHPATCH_CHANGELOG_PROVIDER", raising=False)
    monkeypatch.delenv("MATCHPATCH_CHANGELOG_API_KEY", raising=False)
    monkeypatch.delenv("MATCHPATCH_CHANGELOG_MODEL", raising=False)
    monkeypatch.delenv("MATCHPATCH_CHANGELOG_BASE_URL", raising=False)
    monkeypatch.delenv("MATCHPATCH_CHANGELOG_TIMEOUT", raising=False)
    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: evidence)

    args = SimpleNamespace(
        generate_changelog=True,
        skip_changelog_ai=False,
        notes_file=None,
        changelog_file=str(tmp_path / "notes.md"),
        changelog_evidence_file=str(tmp_path / "notes.evidence.json"),
        changelog_prompt_file=str(tmp_path / "notes.prompt.txt"),
        changelog_provider=None,
        changelog_model=None,
        changelog_base_url=None,
        changelog_timeout=None,
    )

    try:
        release.maybe_refresh_changelog_draft("0.9.0", "v0.9.0", args)
    except release.ReleaseError as error:
        assert "no provider credentials were configured" in str(error)
        assert "manual draft scaffold" in "\n".join(error.next_steps)
    else:
        raise AssertionError("Expected missing configuration to raise ReleaseError")

    assert Path(args.changelog_evidence_file).is_file()
    assert Path(args.changelog_prompt_file).is_file()


def test_normalize_generated_changelog_parses_fences_and_validates_evidence() -> None:
    raw_response = """```markdown
## Release Notes

- Fix release notes [evidence:abc1234].
```"""

    markdown = release.normalize_generated_changelog(raw_response, {"abc1234"})

    assert markdown == "## Release Notes\n\n- Fix release notes [evidence:abc1234]."

    try:
        release.normalize_generated_changelog(
            "## Release Notes\n\n- Missing evidence.", {"abc1234"}
        )
    except release.ReleaseError as error:
        assert "must reference at least one evidence commit ID" in str(error)
    else:
        raise AssertionError("Expected invalid generated Markdown to raise ReleaseError")


def test_prepare_flow_writes_manual_changelog_draft_and_support_files(
    monkeypatch, tmp_path: Path
) -> None:
    evidence = sample_release_evidence()
    notes_path = tmp_path / "notes.md"
    args = SimpleNamespace(
        generate_changelog=False,
        skip_changelog_ai=False,
        notes_file=None,
        changelog_file=str(notes_path),
        changelog_evidence_file=str(tmp_path / "notes.evidence.json"),
        changelog_prompt_file=str(tmp_path / "notes.prompt.txt"),
        changelog_provider=None,
        changelog_model=None,
        changelog_base_url=None,
        changelog_timeout=None,
    )

    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: evidence)

    release.maybe_refresh_changelog_draft("0.9.0", "v0.9.0", args)

    notes_text = notes_path.read_text(encoding="utf-8")
    assert "## Release Notes" in notes_text
    assert "[evidence:111111111111]" in notes_text
    assert Path(args.changelog_evidence_file).is_file()
    assert Path(args.changelog_prompt_file).is_file()
    assert not release.changelog_approval_path(notes_path).exists()


def test_approved_changelog_is_invalidated_after_notes_edit(monkeypatch, tmp_path: Path) -> None:
    evidence = sample_release_evidence()
    notes_path = tmp_path / "approved-notes.md"
    notes_path.write_text(
        "## Release Notes\n\n- Reviewed release fix [evidence:111111111111].\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        notes_file=str(notes_path),
        changelog_file=None,
    )

    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: evidence)

    approved = release.approve_changelog("0.9.0", "v0.9.0", args)
    assert approved.approval_path.is_file()

    notes_path.write_text(
        "## Release Notes\n\n- Edited after approval [evidence:111111111111].\n",
        encoding="utf-8",
    )

    try:
        release.require_approved_changelog("0.9.0", "v0.9.0", args)
    except release.ReleaseError as error:
        assert "notes_sha256" in str(error)
    else:
        raise AssertionError("Expected edited notes to invalidate approval")


def test_approved_changelog_is_invalidated_after_release_evidence_changes(
    monkeypatch, tmp_path: Path
) -> None:
    evidence = sample_release_evidence()
    notes_path = tmp_path / "approved-notes.md"
    notes_path.write_text(
        "## Release Notes\n\n- Reviewed release fix [evidence:111111111111].\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        notes_file=str(notes_path),
        changelog_file=None,
    )

    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: evidence)
    release.approve_changelog("0.9.0", "v0.9.0", args)

    changed_evidence = dict(evidence)
    changed_evidence["target_commit"] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    changed_evidence["range"] = "v0.8.2..bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: changed_evidence)

    try:
        release.require_approved_changelog("0.9.0", "v0.9.0", args)
    except release.ReleaseError as error:
        assert "target_commit" in str(error)
        assert "evidence_sha256" in str(error)
    else:
        raise AssertionError("Expected changed evidence to invalidate approval")


def test_refresh_skips_support_files_for_approved_notes_file(monkeypatch, tmp_path: Path) -> None:
    evidence = sample_release_evidence()
    notes_path = tmp_path / "notes.md"
    evidence_path = tmp_path / "notes.evidence.json"
    prompt_path = tmp_path / "notes.prompt.txt"
    notes_path.write_text(
        "## Release Notes\n\n- Reviewed release fix [evidence:111111111111].\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        generate_changelog=False,
        skip_changelog_ai=False,
        notes_file=str(notes_path),
        changelog_file=None,
        changelog_evidence_file=str(evidence_path),
        changelog_prompt_file=str(prompt_path),
        changelog_provider=None,
        changelog_model=None,
        changelog_base_url=None,
        changelog_timeout=None,
    )

    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: evidence)
    release.approve_changelog("0.9.0", "v0.9.0", args)

    release.maybe_refresh_changelog_draft("0.9.0", "v0.9.0", args)

    assert not evidence_path.exists()
    assert not prompt_path.exists()
    assert notes_path.read_text(encoding="utf-8").startswith("## Release Notes")


def test_main_approve_changelog_is_local_and_does_not_prepare_release(
    monkeypatch, tmp_path: Path
) -> None:
    evidence = sample_release_evidence()
    notes_path = tmp_path / "notes.md"
    notes_path.write_text(
        "## Release Notes\n\n- Reviewed release fix [evidence:111111111111].\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        version="0.9.0",
        branch="main",
        allow_current_branch=False,
        skip_pull=False,
        skip_sync=False,
        skip_pre_push=False,
        gui_tests=False,
        installer=False,
        publish=False,
        yes=True,
        notes_file=str(notes_path),
        approve_changelog=True,
        changelog_file=None,
        changelog_evidence_file=None,
        changelog_prompt_file=None,
        generate_changelog=True,
        skip_changelog_ai=False,
        changelog_provider=None,
        changelog_model=None,
        changelog_base_url=None,
        changelog_timeout=None,
    )
    tag_checks: list[tuple[str, bool]] = []

    monkeypatch.setattr(release, "parse_args", lambda: args)
    monkeypatch.setattr(release, "ensure_repo_root", lambda: None)
    monkeypatch.setattr(release, "ensure_branch", lambda branch, allow: None)
    monkeypatch.setattr(release, "require_clean_tree", lambda: None)
    monkeypatch.setattr(release, "preflight", lambda parsed_args: None)
    monkeypatch.setattr(
        release,
        "require_local_tag_ready",
        lambda version, tag, *, check_remote=True: tag_checks.append((tag, check_remote)),
    )
    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: evidence)
    monkeypatch.setattr(
        release,
        "sync_branch",
        lambda branch, skip_pull: (_ for _ in ()).throw(AssertionError("unexpected sync")),
    )
    monkeypatch.setattr(
        release,
        "ensure_tag_available",
        lambda version, tag: (_ for _ in ()).throw(AssertionError("unexpected prepare")),
    )
    monkeypatch.setattr(
        release.release_changelog,
        "draft_changelog_markdown",
        lambda prompt, config: (_ for _ in ()).throw(AssertionError("unexpected AI call")),
    )

    assert release.main() == 0
    assert tag_checks == [("v0.9.0", False)]
    assert release.changelog_approval_path(notes_path).is_file()


def test_main_publish_refuses_without_approved_changelog(monkeypatch, tmp_path: Path) -> None:
    evidence = sample_release_evidence()
    notes_path = tmp_path / "notes.md"
    notes_path.write_text(
        "## Release Notes\n\n- Reviewed release fix [evidence:111111111111].\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        version="0.9.0",
        branch="main",
        allow_current_branch=False,
        skip_pull=False,
        skip_sync=False,
        skip_pre_push=False,
        gui_tests=False,
        installer=False,
        publish=True,
        yes=True,
        notes_file=str(notes_path),
        approve_changelog=False,
        changelog_file=None,
        changelog_evidence_file=None,
        changelog_prompt_file=None,
        generate_changelog=False,
        skip_changelog_ai=False,
        changelog_provider=None,
        changelog_model=None,
        changelog_base_url=None,
        changelog_timeout=None,
    )
    pushed: list[tuple[str, str]] = []

    monkeypatch.setattr(release, "parse_args", lambda: args)
    monkeypatch.setattr(release, "ensure_repo_root", lambda: None)
    monkeypatch.setattr(release, "ensure_branch", lambda branch, allow: None)
    monkeypatch.setattr(release, "require_clean_tree", lambda: None)
    monkeypatch.setattr(release, "preflight", lambda parsed_args: None)
    monkeypatch.setattr(release, "sync_branch", lambda branch, skip_pull: None)
    monkeypatch.setattr(release, "local_release_is_prepared", lambda version, tag: True)
    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: evidence)
    monkeypatch.setattr(release, "run", lambda cmd, **kwargs: "")
    monkeypatch.setattr(release, "confirm_publish", lambda yes, tag, branch: None)
    monkeypatch.setattr(release, "push_release", lambda branch, tag: pushed.append((branch, tag)))
    monkeypatch.setattr(release, "watch_release_workflow", lambda tag: None)
    monkeypatch.setattr(release, "verify_public_release", lambda version, tag, notes_file: None)

    assert release.main() == 1
    assert pushed == []


def test_main_publish_uses_approved_changelog_path(monkeypatch, tmp_path: Path) -> None:
    evidence = sample_release_evidence()
    notes_path = tmp_path / "notes.md"
    notes_path.write_text(
        "## Release Notes\n\n- Reviewed release fix [evidence:111111111111].\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        version="0.9.0",
        branch="main",
        allow_current_branch=False,
        skip_pull=False,
        skip_sync=False,
        skip_pre_push=False,
        gui_tests=False,
        installer=False,
        publish=True,
        yes=True,
        notes_file=str(notes_path),
        approve_changelog=False,
        changelog_file=None,
        changelog_evidence_file=None,
        changelog_prompt_file=None,
        generate_changelog=False,
        skip_changelog_ai=False,
        changelog_provider=None,
        changelog_model=None,
        changelog_base_url=None,
        changelog_timeout=None,
    )
    verified_notes: list[str] = []

    monkeypatch.setattr(release, "load_release_evidence", lambda version, tag: evidence)
    release.approve_changelog("0.9.0", "v0.9.0", args)

    monkeypatch.setattr(release, "parse_args", lambda: args)
    monkeypatch.setattr(release, "ensure_repo_root", lambda: None)
    monkeypatch.setattr(release, "ensure_branch", lambda branch, allow: None)
    monkeypatch.setattr(release, "require_clean_tree", lambda: None)
    monkeypatch.setattr(release, "preflight", lambda parsed_args: None)
    monkeypatch.setattr(release, "sync_branch", lambda branch, skip_pull: None)
    monkeypatch.setattr(release, "local_release_is_prepared", lambda version, tag: True)
    monkeypatch.setattr(release, "run", lambda cmd, **kwargs: "")
    monkeypatch.setattr(release, "confirm_publish", lambda yes, tag, branch: None)
    monkeypatch.setattr(release, "push_release", lambda branch, tag: None)
    monkeypatch.setattr(release, "watch_release_workflow", lambda tag: None)
    monkeypatch.setattr(
        release,
        "verify_public_release",
        lambda version, tag, notes_file: verified_notes.append(notes_file),
    )

    assert release.main() == 0
    assert verified_notes == [str(notes_path)]


def test_verify_public_release_applies_notes_file_to_github_release(
    monkeypatch, tmp_path: Path
) -> None:
    notes_path = tmp_path / "notes.md"
    notes_path.write_text("## Release Notes\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def fake_run(args, *, capture=False, check=True, env=None, strip=True):
        del capture, check, env, strip
        calls.append(tuple(args))
        if args[:3] == ["gh", "release", "view"]:
            return json.dumps(
                {
                    "assets": [
                        {"name": "MatchPatch-Setup-0.9.0.exe"},
                        {"name": "MatchPatch-macOS-arm64-0.9.0.dmg"},
                    ]
                }
            )
        return ""

    monkeypatch.setattr(release, "run", fake_run)

    release.verify_public_release("0.9.0", "v0.9.0", str(notes_path))

    assert calls[0] == (
        "gh",
        "release",
        "edit",
        "v0.9.0",
        "--title",
        "MatchPatch v0.9.0",
        "--notes-file",
        str(notes_path),
    )
