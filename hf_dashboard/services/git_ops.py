"""Git operations against the user's fork of NVIDIA/TensorRT-Model-Optimizer.

Owns one local working copy that the dashboard treats as private — the user
shouldn't `cd` into it and do manual git operations because that fights this
module's bookkeeping.

Layout
======
    <fork_path>/                                  ← real git clone of the fork
    ├── .git/
    └── tests/examples/llm_ptq/test_deploy.py     ← edited by case_writer

Config
======
    MODELOPT_FORK_URL    Default: https://github.com/noeyy-mino/Model-Optimizer.git
    MODELOPT_FORK_PATH   Default: /localhome/local-siruiw/Model-Optimizer-fork
    MODELOPT_BASE_BRANCH Default: main
    MODELOPT_AUTO_BRANCH Default: auto/add-cases     ← single long-lived branch
    MODELOPT_REMOTE      Default: origin

    GITHUB_TOKEN         If set, gets injected into the HTTPS URL for pushes.
                         (Github requires a PAT for HTTPS push as of 2021.)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


DEFAULT_FORK_URL  = "https://github.com/noeyy-mino/Model-Optimizer.git"
DEFAULT_FORK_PATH = "/localhome/local-siruiw/Model-Optimizer-fork"
DEFAULT_BASE_BRANCH = "main"
DEFAULT_AUTO_BRANCH = "auto/add-cases"
DEFAULT_REMOTE      = "origin"


def fork_path() -> Path:
    return Path(os.environ.get("MODELOPT_FORK_PATH", DEFAULT_FORK_PATH))


def fork_url(with_token: bool = False) -> str:
    """Public URL, or URL with GITHUB_TOKEN injected if requested."""
    url = os.environ.get("MODELOPT_FORK_URL", DEFAULT_FORK_URL)
    if with_token:
        tok = os.environ.get("GITHUB_TOKEN", "").strip()
        if tok and url.startswith("https://github.com/"):
            url = url.replace("https://", f"https://{tok}@", 1)
    return url


def base_branch() -> str:
    return os.environ.get("MODELOPT_BASE_BRANCH", DEFAULT_BASE_BRANCH)


def auto_branch() -> str:
    return os.environ.get("MODELOPT_AUTO_BRANCH", DEFAULT_AUTO_BRANCH)


def remote() -> str:
    return os.environ.get("MODELOPT_REMOTE", DEFAULT_REMOTE)


# ---------------------------------------------------------------------------
# Low-level git
# ---------------------------------------------------------------------------

@dataclass
class GitResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    @property
    def out(self) -> str:
        return (self.stdout or "") + (("\n" + self.stderr) if self.stderr else "")


def _run(args: list[str], cwd: Path | None = None, env_overrides: dict | None = None) -> GitResult:
    env = os.environ.copy()
    # Force non-interactive: never prompt for credentials, fail fast instead.
    env["GIT_TERMINAL_PROMPT"] = "0"
    if env_overrides:
        env.update(env_overrides)
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as e:
        return GitResult(ok=False, stderr=f"git not installed: {e}", returncode=127)
    except subprocess.TimeoutExpired:
        return GitResult(ok=False, stderr="git command timed out after 120s", returncode=124)
    return GitResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
    )


# ---------------------------------------------------------------------------
# Bootstrap: clone if missing, ensure auto branch checked out
# ---------------------------------------------------------------------------

def is_git_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


def ensure_clone() -> GitResult:
    """Make sure `fork_path()` is a valid git clone of the fork, on the
    auto-add-cases branch. Idempotent.

    If the path exists but isn't a git repo (e.g. it's the old sandbox dir),
    we rename it to `<path>.sandbox-bak` before cloning to avoid losing files.
    """
    path = fork_path()
    if is_git_repo(path):
        # Existing clone — just make sure we're on the right branch.
        return ensure_branch()

    if path.exists():
        bak = path.with_name(path.name + ".sandbox-bak")
        if bak.exists():
            shutil.rmtree(bak)
        path.rename(bak)

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    url = fork_url(with_token=True)
    result = _run(["git", "clone", url, str(path)])
    if not result.ok:
        # Strip any embedded token from error output before surfacing.
        result.stderr = result.stderr.replace(url, "<fork-url>")
        return result
    return ensure_branch()


def ensure_branch() -> GitResult:
    """Check out the auto branch, creating it from base if needed."""
    path = fork_path()
    if not is_git_repo(path):
        return GitResult(ok=False, stderr=f"Not a git repo: {path}")

    branch = auto_branch()
    base = base_branch()
    rmt = remote()

    # Fetch the remote so origin/<base> is current.
    fetch = _run(["git", "fetch", rmt, base], cwd=path)
    # Fetch failure is non-fatal — could be offline / no token; we'll still try
    # to switch to a local copy of the branch.

    # If the branch exists locally, just switch to it.
    show = _run(["git", "rev-parse", "--verify", "--quiet", branch], cwd=path)
    if show.ok:
        sw = _run(["git", "checkout", branch], cwd=path)
        return sw

    # Otherwise create it. Prefer branching from origin/<base>; if that doesn't
    # exist (e.g. fetch failed) fall back to local <base>.
    track_target = f"{rmt}/{base}"
    has_remote_base = _run(
        ["git", "rev-parse", "--verify", "--quiet", track_target], cwd=path
    ).ok
    base_ref = track_target if has_remote_base else base
    co = _run(["git", "checkout", "-b", branch, base_ref], cwd=path)
    if not co.ok:
        # Last resort: just branch from HEAD.
        co = _run(["git", "checkout", "-b", branch], cwd=path)
    return co


# ---------------------------------------------------------------------------
# Editing helpers (used after case_writer writes the file)
# ---------------------------------------------------------------------------

def add_and_commit(
    file_paths: list[str | Path],
    message: str,
    signoff: bool = True,
) -> GitResult:
    """Stage the given paths and create one commit. No-op (returns ok=True)
    if there are no staged changes, so callers can be lazy and re-run after
    a redundant Apply.
    """
    path = fork_path()
    if not is_git_repo(path):
        return GitResult(ok=False, stderr=f"Not a git repo: {path}")

    rel_paths = []
    for p in file_paths:
        p = Path(p)
        try:
            rel_paths.append(str(p.resolve().relative_to(path.resolve())))
        except ValueError:
            return GitResult(ok=False, stderr=f"{p} is not inside {path}")

    add = _run(["git", "add", "--"] + rel_paths, cwd=path)
    if not add.ok:
        return add

    # Anything actually staged?
    staged = _run(["git", "diff", "--cached", "--quiet"], cwd=path)
    if staged.returncode == 0:
        # Nothing staged — return a benign no-op result. Callers see ok=True.
        return GitResult(ok=True, stdout="(no staged changes — nothing to commit)")

    args = ["git", "commit"]
    if signoff:
        args.append("-s")
    args += ["-m", message]
    return _run(args, cwd=path)


def push(force: bool = False) -> GitResult:
    """Push the auto branch to origin. Uses GITHUB_TOKEN if set.

    `force` is intentionally False by default. We never force-push to main.
    """
    path = fork_path()
    if not is_git_repo(path):
        return GitResult(ok=False, stderr=f"Not a git repo: {path}")

    branch = auto_branch()
    rmt = remote()

    # Temporarily set the remote URL with token injection (then restore).
    original = _run(["git", "remote", "get-url", rmt], cwd=path)
    if not original.ok:
        return GitResult(ok=False, stderr=f"Remote {rmt!r} not found")
    original_url = original.stdout.strip()
    push_url = fork_url(with_token=True)

    if push_url != original_url:
        _run(["git", "remote", "set-url", rmt, push_url], cwd=path)

    args = ["git", "push", "--set-upstream", rmt, branch]
    if force:
        args.insert(2, "--force-with-lease")
    result = _run(args, cwd=path)

    # Restore the public URL so `.git/config` doesn't end up with a token in it
    # on disk after a push.
    if push_url != original_url:
        _run(["git", "remote", "set-url", rmt, original_url], cwd=path)

    # Sanitize any echoed URL in output.
    result.stdout = result.stdout.replace(push_url, "<fork-url>")
    result.stderr = result.stderr.replace(push_url, "<fork-url>")
    return result


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

@dataclass
class BranchStatus:
    initialized: bool = False
    current_branch: str = ""
    last_commit_sha: str = ""
    last_commit_subject: str = ""
    ahead: int = 0          # commits ahead of origin/<auto_branch> (or origin/<base> if remote branch absent)
    behind: int = 0
    has_uncommitted: bool = False
    has_unpushed: bool = False
    remote_branch_exists: bool = False
    error: str = ""


def status() -> BranchStatus:
    path = fork_path()
    if not is_git_repo(path):
        return BranchStatus(initialized=False, error=f"{path} is not a git repo yet")

    cb = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    last = _run(["git", "log", "-1", "--pretty=format:%h\x1f%s"], cwd=path)

    sha, subject = "", ""
    if last.ok and "\x1f" in last.stdout:
        sha, subject = last.stdout.split("\x1f", 1)

    branch = cb.stdout.strip() if cb.ok else ""

    # Uncommitted changes?
    porc = _run(["git", "status", "--porcelain"], cwd=path)
    has_uncommitted = bool(porc.stdout.strip()) if porc.ok else False

    # Ahead/behind vs remote
    ahead = behind = 0
    has_unpushed = False
    remote_branch_exists = False
    if branch:
        # First check whether origin/<branch> exists at all. It won't on the
        # very first push, so we'd otherwise compute ahead=0 forever.
        check = _run(
            ["git", "rev-parse", "--verify", "--quiet", f"{remote()}/{branch}"],
            cwd=path,
        )
        remote_branch_exists = check.ok

        if remote_branch_exists:
            # Compare local HEAD to origin/<branch>.
            ab = _run(
                ["git", "rev-list", "--left-right", "--count",
                 f"{remote()}/{branch}...HEAD"],
                cwd=path,
            )
            if ab.ok:
                parts = ab.stdout.strip().split()
                if len(parts) == 2:
                    try:
                        behind = int(parts[0])
                        ahead = int(parts[1])
                    except ValueError:
                        pass
        else:
            # First-push case: count commits on the auto branch that aren't
            # already in origin/<base_branch>.
            ab = _run(
                ["git", "rev-list", "--count", f"{remote()}/{base_branch()}..HEAD"],
                cwd=path,
            )
            if ab.ok:
                try:
                    ahead = int(ab.stdout.strip())
                except ValueError:
                    pass

        has_unpushed = ahead > 0

    return BranchStatus(
        initialized=True,
        current_branch=branch,
        last_commit_sha=sha,
        last_commit_subject=subject,
        ahead=ahead,
        behind=behind,
        has_uncommitted=has_uncommitted,
        has_unpushed=has_unpushed,
        remote_branch_exists=remote_branch_exists,
    )


def branch_url() -> str:
    """Public github URL to the branch (no token)."""
    url = fork_url(with_token=False)
    if url.endswith(".git"):
        url = url[:-4]
    return f"{url}/tree/{auto_branch()}"
