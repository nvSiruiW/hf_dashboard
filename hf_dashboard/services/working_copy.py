"""Where the dashboard writes generated test cases.

Phase 2 of this module: the working copy is a real git clone of the user's
fork, maintained by `git_ops`. The file edits we generate land on the
`auto/add-cases` branch and get committed (`-s`) automatically.

The path resolution lives in `git_ops.fork_path()`. This module is a thin
file-IO façade so that callers (case_writer, inbox state) can stay
ignorant of git plumbing.
"""
from __future__ import annotations

from pathlib import Path

from hf_dashboard.services import git_ops


# Relative path inside the repo for the file we edit.
TEST_DEPLOY_REL = "tests/examples/llm_ptq/test_deploy.py"


def fork_path() -> Path:
    return git_ops.fork_path()


def test_deploy_path() -> Path:
    return fork_path() / TEST_DEPLOY_REL


def ensure_sandbox() -> tuple[Path, str | None]:
    """Make sure the working-copy file exists. Returns (path, error_or_None).

    Ensures the fork is cloned and the auto-cases branch is checked out, then
    confirms `test_deploy.py` is present. On bootstrap problems (clone failure,
    no network/credentials, etc.) we return a descriptive error string.
    """
    init = git_ops.ensure_clone()
    if not init.ok:
        return test_deploy_path(), init.out

    dest = test_deploy_path()
    if not dest.exists():
        return dest, (
            f"{dest} not found in the clone. The fork may not have this file "
            f"on branch {git_ops.auto_branch()}. Check the fork on GitHub."
        )
    return dest, None


def read_test_deploy() -> tuple[str, str | None]:
    path, err = ensure_sandbox()
    if err:
        return "", err
    try:
        return path.read_text(), None
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


def write_test_deploy(content: str) -> tuple[Path, str | None]:
    """Atomic write of the new content. Returns (path, error)."""
    path, err = ensure_sandbox()
    if err:
        return path, err
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content)
        tmp.replace(path)
        return path, None
    except Exception as e:
        return path, f"{type(e).__name__}: {e}"
