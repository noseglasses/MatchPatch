"""AI changelog drafting helpers for MatchPatch releases."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEFAULT_PROVIDER = "openai-compatible"
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_PROMPT_CHARS = 8000
MAX_COMMITS = 8
MAX_FILES_PER_COMMIT = 6
MAX_BODY_LINES = 4
MAX_BODY_CHARS = 240
FENCED_MARKDOWN_RE = re.compile(r"```(?:markdown|md)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


class ChangelogAIError(RuntimeError):
    """The changelog AI provider could not be used."""


@dataclass(frozen=True)
class ChangelogAIConfig:
    """Configuration for an OpenAI-compatible changelog drafting provider."""

    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class ChangelogPaths:
    """Filesystem locations for changelog drafts and evidence."""

    evidence_path: Path
    prompt_path: Path
    notes_path: Path


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    return text[: max_chars - 3].rstrip() + "..."


def _format_numstat(stat: Mapping[str, Any]) -> str:
    path = str(stat.get("path", ""))
    insertions = stat.get("insertions")
    deletions = stat.get("deletions")
    insertions_text = "?" if insertions is None else str(insertions)
    deletions_text = "?" if deletions is None else str(deletions)
    return f"{path} (+{insertions_text}/-{deletions_text})"


def _format_commit_block(commit: Mapping[str, Any]) -> list[str]:
    short_commit = str(commit.get("short_commit") or commit.get("commit") or "")
    subject = _truncate_text(str(commit.get("subject", "")), 120)
    lines = [f"- Commit {short_commit}: {subject}"]

    changed_files = [str(path) for path in commit.get("changed_files", [])]
    if changed_files:
        files = ", ".join(changed_files[:MAX_FILES_PER_COMMIT])
        if len(changed_files) > MAX_FILES_PER_COMMIT:
            files += f", ... ({len(changed_files) - MAX_FILES_PER_COMMIT} more)"
        lines.append(f"  Files: {files}")

    diff_stat = [
        _format_numstat(stat)
        for stat in commit.get("diff_stat", [])[:MAX_FILES_PER_COMMIT]
        if isinstance(stat, Mapping)
    ]
    if diff_stat:
        lines.append(f"  Diff stat: {', '.join(diff_stat)}")

    body = str(commit.get("body") or "").strip()
    if body:
        body_lines = body.splitlines()[:MAX_BODY_LINES]
        body_text = "\n".join(body_lines)
        body_text = _truncate_text(body_text, MAX_BODY_CHARS)
        lines.append("  Body:")
        for body_line in body_text.splitlines():
            lines.append(f"    {body_line}")

    return lines


def build_changelog_prompt(
    evidence: Mapping[str, Any],
    *,
    max_chars: int = MAX_PROMPT_CHARS,
) -> str:
    """Build a bounded prompt for drafting release notes from evidence."""

    version = str(evidence.get("version", ""))
    tag = str(evidence.get("tag", ""))
    previous_tag = str(evidence.get("previous_tag") or "none")
    commit_range = str(evidence.get("range", ""))
    target_commit = str(evidence.get("target_commit", ""))
    commits = [commit for commit in evidence.get("commits", []) if isinstance(commit, Mapping)]

    lines = [
        "You are drafting MatchPatch release notes.",
        "Use only the supplied evidence.",
        "Write concise Markdown release notes.",
        "Return Markdown only, with no preamble or code fences.",
        "Prefer short headings and short bullets.",
        "Cite every factual bullet with an evidence reference like [evidence:SHORTSHA].",
        "Do not invent features, fixes, links, or claims.",
        "",
        f"Target version: {version}",
        f"Tag: {tag}",
        f"Previous tag: {previous_tag}",
        f"Commit range: {commit_range}",
        f"Target commit: {target_commit}",
        f"Evidence commits included: {min(len(commits), MAX_COMMITS)} of {len(commits)}",
        "",
        "Evidence summary:",
    ]

    for index, commit in enumerate(commits[:MAX_COMMITS], start=1):
        lines.append(f"Commit {index}:")
        lines.extend(_format_commit_block(commit))

    if len(commits) > MAX_COMMITS:
        lines.append(f"... {len(commits) - MAX_COMMITS} more commits omitted from the prompt ...")

    lines.extend(
        [
            "",
            "Suggested shape:",
            "## Release Notes",
            "- A concise highlight with evidence references.",
            "- Another bullet for the most user-visible changes.",
            "",
            "Stay brief. Keep the final note under the local validation limits.",
        ]
    )

    prompt = "\n".join(lines).strip() + "\n"
    if len(prompt) > max_chars:
        suffix = "\n\n[Prompt truncated to keep the local context bounded.]\n"
        prompt = prompt[: max_chars - len(suffix)].rstrip() + suffix
    return prompt


def write_changelog_support_files(
    evidence: Mapping[str, Any],
    prompt: str,
    *,
    evidence_path: Path,
    prompt_path: Path,
) -> None:
    """Write the evidence bundle and the prompt used to draft notes."""

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    prompt_path.write_text(prompt, encoding="utf-8")


def extract_markdown_from_response(response_text: str) -> str:
    """Extract Markdown from a model response."""

    text = response_text.strip()
    match = FENCED_MARKDOWN_RE.search(text)
    if match is not None:
        return match.group(1).strip()
    return text


def draft_changelog_markdown(
    prompt: str,
    config: ChangelogAIConfig,
) -> str:
    """Request a Markdown draft from an OpenAI-compatible chat completion API."""

    if config.provider != DEFAULT_PROVIDER:
        raise ChangelogAIError(f"Unsupported changelog provider: {config.provider}")

    request_body = json.dumps(
        {
            "model": config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You draft concise MatchPatch release notes using only the supplied "
                        "evidence."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.base_url.rstrip('/')}/chat/completions",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise ChangelogAIError(
            f"Changelog provider request failed with HTTP {error.code}: {error.reason}"
        ) from error
    except urllib.error.URLError as error:
        raise ChangelogAIError(f"Changelog provider request failed: {error.reason}") from error

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ChangelogAIError("Changelog provider response did not include choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise ChangelogAIError("Changelog provider response choice was not a mapping.")
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise ChangelogAIError("Changelog provider response did not include a message.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ChangelogAIError("Changelog provider response did not include Markdown content.")
    return content
