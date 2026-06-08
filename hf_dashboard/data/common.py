"""Shared constants and small helpers.

Color scheme intentionally mirrors modelopt-dashboard so the two dashboards
feel consistent for QA users who switch between them.
"""
from __future__ import annotations

import glob
import os as _os

# Backends under test.
BACKENDS: list[str] = ["trtllm", "vllm", "sglang"]

BACKEND_COLORS: dict[str, str] = {
    "trtllm": "#667eea",
    "vllm":   "#F97316",
    "sglang": "#10B981",
}

# Canonical test statuses (matches modelopt-dashboard icon system).
STATUSES = ("passed", "failed", "running", "pending", "broken", "unsupported")

STATUS_ICONS: dict[str, tuple[str, str]] = {
    "passed":      ("circle_check",   "#059669"),
    "failed":      ("circle_x",       "#DC2626"),
    "running":     ("loader_circle",  "#3B82F6"),
    "pending":     ("circle_help",    "#F59E0B"),
    "broken":      ("triangle_alert", "#F97316"),
    "unsupported": ("circle_minus",   "#999999"),
}

# Default slurm log root. Each job lives at <root>/<job_id>/ and contains a
# `slurm-<slurm_id>-deploy_hf.out` file. Override via SLURM_LOG_ROOT env var.
SLURM_LOG_ROOT = _os.environ.get(
    "SLURM_LOG_ROOT",
    "/localhome/local-siruiw/myshare/workspace/slurm_logs/sirui_test_hf",
)


def resolve_job_input(value: str) -> tuple[str, str | None]:
    """Resolve a user input to a real .out file path.

    Accepts any of:
      - A pure job number, e.g. "191"          → finds first .out in <root>/191/
      - A full path to a .out file              → returned as-is
      - A directory path                        → finds first .out inside it

    Returns (resolved_path, error_message). On success error_message is None.
    On failure resolved_path is "" and error_message explains the problem.
    """
    v = (value or "").strip()
    if not v:
        return "", "Please enter a job ID or full path."

    # Pure job number — accept "191", "j191", "job191", "#191".
    digits = "".join(c for c in v if c.isdigit())
    looks_numeric = v == digits or v.lstrip("jJoObB#").strip() == digits
    if looks_numeric:
        if not digits:
            return "", f"Could not parse a job number from {v!r}."
        job_dir = _os.path.join(SLURM_LOG_ROOT, digits)
        if not _os.path.isdir(job_dir):
            return "", f"Job directory not found: {job_dir}"
        outs = sorted(glob.glob(_os.path.join(job_dir, "slurm-*-deploy_hf.out")))
        if not outs:
            outs = sorted(glob.glob(_os.path.join(job_dir, "*.out")))
        if not outs:
            return "", f"No .out file found in {job_dir}"
        return outs[-1], None  # newest by name (slurm id is monotonic)

    # Path: file or directory.
    if _os.path.isfile(v):
        return v, None
    if _os.path.isdir(v):
        outs = sorted(glob.glob(_os.path.join(v, "slurm-*-deploy_hf.out")))
        if not outs:
            outs = sorted(glob.glob(_os.path.join(v, "*.out")))
        if not outs:
            return "", f"No .out file found in directory {v}"
        return outs[-1], None

    return "", f"Path does not exist: {v}"


# The HF collection that contains speculative-decoding (Eagle3) modules — any
# model coming from this collection needs an S3 upload step before testing.
EAGLE3_COLLECTION_SLUG = "nvidia/speculative-decoding-modules"

# Name patterns used as a fallback when the source collection is unknown.
import re as _re
_EAGLE3_NAME_RE = _re.compile(r"(?i)(eagle\s*3|spec[_-]?dec|draft\b)")


def detect_eagle3(model_name: str, source_collection: str = "") -> bool:
    """Decide whether a model needs S3 upload before it can be tested.

    Prefers `source_collection` when given (the upstream monitor preserves
    which HF collection the model came from). Falls back to a regex on the
    model name otherwise.
    """
    if source_collection and source_collection.strip().lower() == EAGLE3_COLLECTION_SLUG.lower():
        return True
    return bool(_EAGLE3_NAME_RE.search(model_name or ""))


def job_id_from_path(path: str) -> str:
    """Best-effort extraction of the slurm log root job id from a full path.

    Returns "" if the path doesn't look like one of our slurm dirs.
    """
    if not path:
        return ""
    try:
        parent = _os.path.basename(_os.path.dirname(path))
        if parent.isdigit():
            return parent
    except Exception:
        pass
    return ""
