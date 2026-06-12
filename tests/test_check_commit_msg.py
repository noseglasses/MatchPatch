import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_commit_msg.py"
SPEC = importlib.util.spec_from_file_location("check_commit_msg", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check_commit_msg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_commit_msg)
validate_message = check_commit_msg.validate_message


def test_accepts_conventional_commit_subjects():
    assert validate_message("feat(gui): add progress dialog\n") is None
    assert validate_message("fix!: change normalized CSV schema\n") is None
    assert validate_message("chore(release): v0.2.0\n\nRelease notes") is None


def test_accepts_autosquash_and_git_generated_subjects():
    assert validate_message("fixup! fix: preserve output file path\n") is None
    assert validate_message("squash! docs(dev): explain hook setup\n") is None
    assert validate_message("Merge branch 'main' into feature\n") is None
    assert validate_message('Revert "feat: add experimental backend"\n') is None


def test_rejects_non_conventional_subjects():
    assert validate_message("Update docs\n") == "Use '<type>[optional scope][!]: <description>'."
    assert (
        validate_message("feat add dialog\n") == "Use '<type>[optional scope][!]: <description>'."
    )


def test_rejects_unknown_type():
    assert (
        validate_message("feature: add dialog\n")
        == "Unknown type 'feature'. Allowed types: build, chore, ci, docs, feat, fix, perf, refactor, revert, style, test."
    )


def test_ignores_comment_lines_before_subject():
    assert validate_message("# Please enter a message\n\nfix: handle empty CSV\n") is None
