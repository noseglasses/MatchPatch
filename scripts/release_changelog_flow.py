"""Changelog draft and approval flow for MatchPatch releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import release_changelog
from release_support import ReleaseError, info

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REFERENCE_RE = re.compile(r"\b(?:evidence|commit):([0-9a-f]{7,40})\b", re.IGNORECASE)
VAGUE_FILLER_RE = re.compile(
    r"\b(?:"
    r"miscellaneous|"
    r"various(?:\s+(?:changes|fixes|improvements))?|"
    r"minor(?:\s+(?:changes|fixes|updates|improvements))?|"
    r"small(?:\s+(?:changes|fixes|updates|improvements))?|"
    r"assorted|"
    r"and more|"
    r"etc\.?"
    r")\b",
    re.IGNORECASE,
)
MAX_CHANGELOG_CHARS = 4000
MAX_CHANGELOG_NONEMPTY_LINES = 80
EvidenceLoader = Callable[[str, str], dict[str, object]]


@dataclass(frozen=True)
class ApprovedChangelog:
    """Approved changelog metadata bound to one release range and file content."""

    notes_path: Path
    approval_path: Path
    record: dict[str, object]


def validate_changelog_shape(markdown: str) -> str | None:
    lines = markdown.splitlines()
    first_content_line = next((line.strip() for line in lines if line.strip()), "")
    if not first_content_line:
        return "Changelog Markdown is empty."
    if not re.match(r"^#{1,2}\s+\S", first_content_line):
        return "Changelog Markdown must start with a level 1 or 2 heading."
    return None


def validate_changelog_length(
    markdown: str,
    *,
    max_chars: int = MAX_CHANGELOG_CHARS,
    max_nonempty_lines: int = MAX_CHANGELOG_NONEMPTY_LINES,
) -> str | None:
    if len(markdown) > max_chars:
        return f"Changelog Markdown is too long: {len(markdown)} characters (max {max_chars})."
    nonempty_lines = sum(1 for line in markdown.splitlines() if line.strip())
    if nonempty_lines > max_nonempty_lines:
        return (
            "Changelog Markdown has too many non-empty lines: "
            f"{nonempty_lines} (max {max_nonempty_lines})."
        )
    return None


def validate_changelog_filler(markdown: str) -> str | None:
    match = VAGUE_FILLER_RE.search(markdown)
    if match is None:
        return None
    return f"Changelog Markdown contains vague filler: {match.group(0)!r}."


def validate_changelog_evidence_references(
    markdown: str, evidence_commit_ids: set[str] | None = None
) -> str | None:
    if evidence_commit_ids is None:
        return None
    references = {match.group(1).lower() for match in EVIDENCE_REFERENCE_RE.finditer(markdown)}
    if not references:
        return "Changelog Markdown must reference at least one evidence commit ID."
    missing = sorted(ref for ref in references if ref not in evidence_commit_ids)
    if missing:
        return "Changelog Markdown references unknown evidence commit IDs: " + ", ".join(missing)
    return None


def validate_changelog_markdown(
    markdown: str, evidence_commit_ids: set[str] | None = None
) -> str | None:
    for validator in (
        validate_changelog_shape,
        validate_changelog_length,
        validate_changelog_filler,
        lambda text: validate_changelog_evidence_references(text, evidence_commit_ids),
    ):
        error = validator(markdown)
        if error is not None:
            return error
    return None


def changelog_paths(version: str) -> release_changelog.ChangelogPaths:
    base_dir = ROOT / "dist" / "release-notes"
    return release_changelog.ChangelogPaths(
        evidence_path=base_dir / f"matchpatch-v{version}.evidence.json",
        prompt_path=base_dir / f"matchpatch-v{version}.prompt.txt",
        notes_path=base_dir / f"matchpatch-v{version}.md",
    )


def changelog_approval_path(notes_path: Path) -> Path:
    return notes_path.with_suffix(".approved.json")


def resolve_changelog_paths(
    version: str, args: argparse.Namespace
) -> release_changelog.ChangelogPaths:
    defaults = changelog_paths(version)
    return release_changelog.ChangelogPaths(
        evidence_path=Path(args.changelog_evidence_file)
        if args.changelog_evidence_file
        else defaults.evidence_path,
        prompt_path=Path(args.changelog_prompt_file)
        if args.changelog_prompt_file
        else defaults.prompt_path,
        notes_path=resolve_draft_notes_path(version, args),
    )


def resolve_draft_notes_path(version: str, args: argparse.Namespace) -> Path:
    if args.changelog_file:
        return Path(args.changelog_file)
    if args.notes_file:
        return Path(args.notes_file)
    return changelog_paths(version).notes_path


def resolve_publish_notes_path(version: str, args: argparse.Namespace) -> Path:
    if args.notes_file:
        return Path(args.notes_file)
    return resolve_draft_notes_path(version, args)


def build_evidence_commit_ids(evidence: dict[str, object]) -> set[str]:
    commits = evidence.get("commits", [])
    if not isinstance(commits, list):
        return set()
    commit_ids = set()
    for commit in commits:
        if isinstance(commit, dict):
            short_commit = commit.get("short_commit")
            if isinstance(short_commit, str):
                commit_ids.add(short_commit.lower())
    return commit_ids


def resolve_changelog_ai_config(
    args: argparse.Namespace,
) -> release_changelog.ChangelogAIConfig | None:
    provider = args.changelog_provider or os.environ.get("MATCHPATCH_CHANGELOG_PROVIDER")
    if not provider:
        return None
    if provider != release_changelog.DEFAULT_PROVIDER:
        raise ReleaseError(
            f"Unsupported changelog provider: {provider}",
            next_steps=[
                f"Use `{release_changelog.DEFAULT_PROVIDER}` for the current implementation.",
                "Or run with `--skip-changelog-ai` to write the prompt and evidence files for manual drafting.",
            ],
        )

    model = args.changelog_model or os.environ.get(
        "MATCHPATCH_CHANGELOG_MODEL", release_changelog.DEFAULT_MODEL
    )
    base_url = args.changelog_base_url or os.environ.get(
        "MATCHPATCH_CHANGELOG_BASE_URL", release_changelog.DEFAULT_BASE_URL
    )
    api_key = os.environ.get("MATCHPATCH_CHANGELOG_API_KEY")
    timeout_value = (
        args.changelog_timeout
        if args.changelog_timeout is not None
        else os.environ.get(
            "MATCHPATCH_CHANGELOG_TIMEOUT", release_changelog.DEFAULT_TIMEOUT_SECONDS
        )
    )
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as error:
        raise ReleaseError(
            f"Invalid changelog timeout value: {timeout_value!r}",
            next_steps=[
                "Set `MATCHPATCH_CHANGELOG_TIMEOUT` to a number of seconds, for example `60`.",
            ],
        ) from error

    if not api_key:
        return None

    return release_changelog.ChangelogAIConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


def normalize_generated_changelog(response_text: str, evidence_commit_ids: set[str]) -> str:
    markdown = release_changelog.extract_markdown_from_response(response_text)
    error = validate_changelog_markdown(markdown, evidence_commit_ids)
    if error is not None:
        raise ReleaseError(
            f"Generated changelog Markdown failed validation: {error}",
            next_steps=[
                "Inspect the model response and the generated prompt.",
                "Edit the Markdown so it stays concise, starts with a heading, and references only evidence commits.",
            ],
        )
    return markdown


def serialize_evidence(evidence: dict[str, object]) -> str:
    return json.dumps(evidence, indent=2, sort_keys=True) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_manual_changelog_scaffold(
    notes_path: Path, evidence: dict[str, object], evidence_commit_ids: set[str]
) -> None:
    references = sorted(evidence_commit_ids)
    first_reference = references[0] if references else "reviewed"
    second_reference = references[1] if len(references) > 1 else first_reference
    previous_tag = evidence.get("previous_tag") or "initial release"
    commit_range = evidence.get("range", "")
    scaffold = "\n".join(
        [
            "## Release Notes",
            "",
            "<!-- Review and edit these notes before approval. -->",
            f"<!-- Release range: {previous_tag} -> {evidence.get('tag', '')} ({commit_range}) -->",
            f"- Replace this bullet with the most important reviewed change [evidence:{first_reference}].",
            f"- Add another reviewed user-facing change [evidence:{second_reference}].",
            "",
        ]
    )
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text(scaffold, encoding="utf-8")


def build_changelog_approval_record(
    version: str,
    tag: str,
    notes_path: Path,
    evidence: dict[str, object],
) -> dict[str, object]:
    notes_text = notes_path.read_text(encoding="utf-8")
    error = validate_changelog_markdown(notes_text, build_evidence_commit_ids(evidence))
    if error is not None:
        raise ReleaseError(
            f"Changelog Markdown failed validation: {error}",
            next_steps=[
                f"Edit {notes_path} so it starts with a heading, stays concise, and cites release evidence.",
                f"Re-run `scripts/release.py {version} --approve-changelog` once the notes are ready.",
            ],
        )

    evidence_text = serialize_evidence(evidence)
    return {
        "version": version,
        "tag": tag,
        "previous_tag": evidence.get("previous_tag"),
        "range": evidence.get("range"),
        "target_commit": evidence.get("target_commit"),
        "notes_sha256": sha256_text(notes_text),
        "evidence_sha256": sha256_text(evidence_text),
        "approved_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def approve_changelog(
    version: str,
    tag: str,
    args: argparse.Namespace,
    *,
    evidence_loader: EvidenceLoader,
) -> ApprovedChangelog:
    notes_path = resolve_publish_notes_path(version, args)
    if not notes_path.is_file():
        raise ReleaseError(
            f"Changelog file does not exist: {notes_path}",
            next_steps=[
                f"Prepare the release with `scripts/release.py {version}` to generate a draft first.",
                "Edit the generated Markdown, then re-run the approval command.",
            ],
        )

    evidence = evidence_loader(version, tag)
    approval_path = changelog_approval_path(notes_path)
    approval_record = build_changelog_approval_record(version, tag, notes_path, evidence)
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    approval_path.write_text(
        json.dumps(approval_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    info(f"Approved changelog {notes_path}")
    info(f"Wrote approval marker to {approval_path}")
    return ApprovedChangelog(
        notes_path=notes_path, approval_path=approval_path, record=approval_record
    )


def require_approved_changelog(
    version: str,
    tag: str,
    args: argparse.Namespace,
    *,
    evidence_loader: EvidenceLoader,
) -> ApprovedChangelog:
    notes_path = resolve_publish_notes_path(version, args)
    approval_path = changelog_approval_path(notes_path)
    if not notes_path.is_file():
        raise ReleaseError(
            f"Publishing requires a changelog Markdown file, but none was found at {notes_path}.",
            next_steps=[
                f"Prepare the release with `scripts/release.py {version}` to generate a draft.",
                f"Edit {notes_path} and approve it with `scripts/release.py {version} --approve-changelog`.",
            ],
        )
    if not approval_path.is_file():
        raise ReleaseError(
            f"Publishing requires an approved changelog, but {approval_path} was not found.",
            next_steps=[
                f"Review and edit {notes_path}.",
                f"Approve the exact notes with `scripts/release.py {version} --approve-changelog`.",
                "Re-run the publish command after approval succeeds.",
            ],
        )

    try:
        approval_record = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ReleaseError(
            f"Approved changelog marker is not valid JSON: {approval_path}",
            next_steps=[
                f"Delete or fix {approval_path}.",
                f"Re-approve the notes with `scripts/release.py {version} --approve-changelog`.",
            ],
        ) from error

    evidence = evidence_loader(version, tag)
    expected_record = build_changelog_approval_record(version, tag, notes_path, evidence)
    mismatches = [
        key
        for key in (
            "version",
            "tag",
            "previous_tag",
            "range",
            "target_commit",
            "notes_sha256",
            "evidence_sha256",
        )
        if approval_record.get(key) != expected_record.get(key)
    ]
    if mismatches:
        raise ReleaseError(
            "Approved changelog no longer matches the current release notes or release range: "
            + ", ".join(mismatches),
            next_steps=[
                f"Review {notes_path} and confirm it still matches release {tag}.",
                f"Re-approve it with `scripts/release.py {version} --approve-changelog`.",
                "Then re-run the publish command.",
            ],
        )

    return ApprovedChangelog(
        notes_path=notes_path, approval_path=approval_path, record=approval_record
    )


def maybe_refresh_changelog_draft(
    version: str,
    tag: str,
    args: argparse.Namespace,
    *,
    evidence_loader: EvidenceLoader,
) -> None:
    paths = resolve_changelog_paths(version, args)
    evidence = evidence_loader(version, tag)

    if args.notes_file:
        try:
            require_approved_changelog(version, tag, args, evidence_loader=evidence_loader)
        except ReleaseError:
            pass
        else:
            info(
                f"Using approved notes file {Path(args.notes_file)}; changelog draft refresh skipped"
            )
            return

    prompt = release_changelog.build_changelog_prompt(evidence)
    release_changelog.write_changelog_support_files(
        evidence,
        prompt,
        evidence_path=paths.evidence_path,
        prompt_path=paths.prompt_path,
    )
    evidence_commit_ids = build_evidence_commit_ids(evidence)

    approval_path = changelog_approval_path(paths.notes_path)
    approval_path.unlink(missing_ok=True)

    if args.generate_changelog:
        config = resolve_changelog_ai_config(args)
        if config is None:
            raise ReleaseError(
                "AI changelog generation was requested, but no provider credentials were configured.",
                next_steps=[
                    "Set `MATCHPATCH_CHANGELOG_PROVIDER=openai-compatible`.",
                    "Set `MATCHPATCH_CHANGELOG_API_KEY` to a valid API key.",
                    "Optionally set `MATCHPATCH_CHANGELOG_MODEL`, `MATCHPATCH_CHANGELOG_BASE_URL`, and `MATCHPATCH_CHANGELOG_TIMEOUT`.",
                    "Or rerun without `--generate-changelog` to create a manual draft scaffold.",
                    f"Review the generated prompt at {paths.prompt_path}.",
                    f"Review the evidence bundle at {paths.evidence_path}.",
                ],
            )

        info("Drafting release notes with the configured changelog provider")
        raw_markdown = release_changelog.draft_changelog_markdown(prompt, config)
        markdown = normalize_generated_changelog(raw_markdown, evidence_commit_ids)
        paths.notes_path.parent.mkdir(parents=True, exist_ok=True)
        paths.notes_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
        info(f"Wrote AI changelog draft to {paths.notes_path}")
        return

    write_manual_changelog_scaffold(paths.notes_path, evidence, evidence_commit_ids)
    info(f"Wrote changelog evidence to {paths.evidence_path}")
    info(f"Wrote changelog prompt to {paths.prompt_path}")
    info(f"Wrote manual changelog draft to {paths.notes_path}")
