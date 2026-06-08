"""State for the Trigger Build page.

Mirrors the Jenkins job's parameter form. Defaults come from the user's most
recent successful build (191). A few fields are presented as dropdowns to
prevent typos for things like `modelopt_repo_owner` and `test_branch`.
"""
from __future__ import annotations

import json

import reflex as rx

from hf_dashboard.services import db, git_ops, jenkins_trigger


# Dropdown option sets — short curated lists. User can add more by editing the
# file or via a "(custom)" path later if needed.
DOCKER_IMAGE_OPTIONS = [
    "nvcr.io/nvidia/pytorch:26.03-py3",
    "nvcr.io/nvidia/tensorrt-llm/release:1.3.0rc12",
    "nvcr.io/nvidia/tensorrt-llm/release:1.3.0rc16",
]

REPO_OWNER_OPTIONS = ["noeyy-mino", "NVIDIA"]

# `test_branch` is the modelopt-qa-scripts repo branch (Jenkinsfile + scripts).
# Almost always `main` — kept as a dropdown for visibility and consistency.
TEST_BRANCH_OPTIONS = ["main", "dev"]

# `modelopt_branch` is the branch of `<owner>/Model-Optimizer` (the code under
# test). Empty falls back to the `modelopt_version` tag. The dashboard's
# auto-cases workflow pushes new pytest cases to `auto/add-cases`, so that's
# the most common explicit value.
# Radix Select forbids empty-string option values, so use a sentinel for
# "leave empty / fall back to modelopt_version tag". Converted back to "" in
# _build_params and setter.
MODELOPT_BRANCH_EMPTY = "(use modelopt_version tag)"
MODELOPT_BRANCH_OPTIONS = [MODELOPT_BRANCH_EMPTY, "auto/add-cases", "main"]


# Default slurm JSON — copied from build #191 params. Users rarely change it.
DEFAULT_SLURM = """{
  "partition": "b200@cr+mp-1000W/umbriel-b200@ts4/8gpu-224cpu-2048gb",
  "account": "swqa",
  "qos": "",
  "reservation": "",
  "time": "4:00:00",
  "nodes": 1,
  "gpus_per_node": 8,
  "cpus_per_task": 8,
  "modules": "",
  "enroot": false
}"""


class TriggerState(rx.State):
    # ── User-editable params ────────────────────────────────────────────
    node: str = "computelab-sirui"
    slurm: str = DEFAULT_SLURM
    docker_image: str = DOCKER_IMAGE_OPTIONS[0]
    modelopt_version: str = ""
    baseline_modelopt: str = "0.43.0rc1"
    test_level: str = ""
    modelopt_branch: str = MODELOPT_BRANCH_EMPTY  # branch of <owner>/Model-Optimizer ("(use modelopt_version tag)" sentinel = "")
    modelopt_repo_owner: str = REPO_OWNER_OPTIONS[0]
    test_branch: str = TEST_BRANCH_OPTIONS[0]  # branch of modelopt-qa-scripts
    test_suites: str = "deploy_hf"          # single-select for now (CSV if multi)
    gpu_type: str = ""
    non_slurm_gpu_devices: str = ""
    pattern: str = ""                       # pytest -k filter
    start_from: str = ""
    random_sample_percent: int = 0
    save_results: bool = True
    enable_trtbot: bool = False
    collect_only: bool = False
    capture: str = "tee-sys"
    gpu_mem_record: bool = False
    test_with_coverage: bool = False
    clean_workspace: bool = False
    debug_hold_container: bool = False
    user_flags: str = ""
    model_dir: str = "/mnt/models"

    # ── Runtime state ───────────────────────────────────────────────────
    triggering: bool = False
    result_message: str = ""        # success / error feedback
    result_kind: str = ""           # "" / "success" / "error"
    last_queue_url: str = ""
    last_run_id: int = 0

    # Pre-flight git status (refreshed on page mount + before each trigger)
    git_current_branch: str = ""
    git_ahead: int = 0
    git_remote_has_branch: bool = False
    git_has_uncommitted: bool = False

    # Dropdown option lists for UI
    docker_image_options: list[str] = list(DOCKER_IMAGE_OPTIONS)
    repo_owner_options: list[str] = list(REPO_OWNER_OPTIONS)
    test_branch_options: list[str] = list(TEST_BRANCH_OPTIONS)
    modelopt_branch_options: list[str] = list(MODELOPT_BRANCH_OPTIONS)

    # ── Setters (one per editable field) ─────────────────────────────────

    def set_node(self, v: str): self.node = v
    def set_slurm(self, v: str): self.slurm = v
    def set_docker_image(self, v: str): self.docker_image = v
    def set_modelopt_version(self, v: str): self.modelopt_version = v
    def set_baseline_modelopt(self, v: str): self.baseline_modelopt = v
    def set_test_level(self, v: str): self.test_level = v
    def set_modelopt_branch(self, v: str):
        v = (v or "").strip()
        self.modelopt_branch = v if v else MODELOPT_BRANCH_EMPTY
    def set_modelopt_repo_owner(self, v: str): self.modelopt_repo_owner = v
    def set_test_branch(self, v: str): self.test_branch = v
    def set_test_suites(self, v: str): self.test_suites = v
    def set_gpu_type(self, v: str): self.gpu_type = v
    def set_non_slurm_gpu_devices(self, v: str): self.non_slurm_gpu_devices = v
    def set_pattern(self, v: str): self.pattern = v
    def set_start_from(self, v: str): self.start_from = v
    def set_capture(self, v: str): self.capture = v
    def set_user_flags(self, v: str): self.user_flags = v
    def set_model_dir(self, v: str): self.model_dir = v

    def set_random_sample_percent(self, v: str):
        try:
            self.random_sample_percent = max(0, min(100, int(v)))
        except (TypeError, ValueError):
            pass

    def toggle_save_results(self): self.save_results = not self.save_results
    def toggle_enable_trtbot(self): self.enable_trtbot = not self.enable_trtbot
    def toggle_collect_only(self): self.collect_only = not self.collect_only
    def toggle_gpu_mem_record(self): self.gpu_mem_record = not self.gpu_mem_record
    def toggle_test_with_coverage(self): self.test_with_coverage = not self.test_with_coverage
    def toggle_clean_workspace(self): self.clean_workspace = not self.clean_workspace
    def toggle_debug_hold_container(self): self.debug_hold_container = not self.debug_hold_container

    def _refresh_git_status(self):
        st = git_ops.status()
        self.git_current_branch = st.current_branch
        self.git_ahead = st.ahead
        self.git_remote_has_branch = st.remote_branch_exists
        self.git_has_uncommitted = st.has_uncommitted

    def on_load(self):
        """Pre-fill `modelopt_version` from URL query params (when arriving from
        the Inbox modal's "Push & Trigger Test" button)."""
        try:
            params = self.router.page.params or {}
        except Exception:
            return
        if not isinstance(params, dict):
            return
        if (v := params.get("modelopt_version")) and not self.modelopt_version:
            self.modelopt_version = v.strip()
        if (v := params.get("test_branch")):
            self.test_branch = v.strip()
        if (v := params.get("modelopt_branch")):
            self.modelopt_branch = v.strip() or MODELOPT_BRANCH_EMPTY
        if (v := params.get("modelopt_repo_owner")):
            self.modelopt_repo_owner = v.strip()
        if (v := params.get("docker_image")):
            self.docker_image = v.strip()
        if (v := params.get("pattern")):
            self.pattern = v.strip()
        self._refresh_git_status()

    # ── Build the param dict + trigger ───────────────────────────────────

    def _build_params(self) -> dict[str, str]:
        """Mirror the Jenkins form. Booleans go as 'true' / 'false'."""
        return {
            "node": self.node,
            "slurm": self.slurm,
            "docker_image": self.docker_image,
            "modelopt_version": self.modelopt_version,
            "baseline_modelopt": self.baseline_modelopt,
            "test_level": self.test_level,
            "modelopt_branch": "" if self.modelopt_branch == MODELOPT_BRANCH_EMPTY else self.modelopt_branch,
            "modelopt_repo_owner": self.modelopt_repo_owner,
            "test_branch": self.test_branch,
            "test_suites": self.test_suites,
            "gpu_type": self.gpu_type,
            "non_slurm_gpu_devices": self.non_slurm_gpu_devices,
            "pattern": self.pattern,
            "start_from": self.start_from,
            "random_sample_percent": str(self.random_sample_percent),
            "save_results": "true" if self.save_results else "false",
            "enable_trtbot": "true" if self.enable_trtbot else "false",
            "collect_only": "true" if self.collect_only else "false",
            "capture": self.capture,
            "gpu_mem_record": "true" if self.gpu_mem_record else "false",
            "test_with_coverage": "true" if self.test_with_coverage else "false",
            "clean_workspace": "true" if self.clean_workspace else "false",
            "debug_hold_container": "true" if self.debug_hold_container else "false",
            "user_flags": self.user_flags,
            "model_dir": self.model_dir,
        }

    def trigger(self):
        if not jenkins_trigger.is_configured():
            self.result_message = "Jenkins is not configured (check ~/.hf_dashboard/env)."
            self.result_kind = "error"
            yield rx.toast.error(self.result_message)
            return
        if not self.modelopt_version.strip():
            self.result_message = "modelopt_version is required."
            self.result_kind = "error"
            yield rx.toast.error(self.result_message)
            return

        self.triggering = True
        self.result_kind = ""
        yield

        # Pre-flight: make sure `modelopt_branch` (the branch of the user's
        # fork that holds the new test cases) is actually on the remote, or
        # Jenkins will fail at SCM checkout with "couldn't find remote ref".
        # Only attempt auto-push when modelopt_branch matches the dashboard's
        # current branch (the one git_ops manages).
        self._refresh_git_status()
        effective_modelopt_branch = "" if self.modelopt_branch == MODELOPT_BRANCH_EMPTY else self.modelopt_branch
        if effective_modelopt_branch == self.git_current_branch and (
            self.git_ahead > 0 or not self.git_remote_has_branch
        ):
            self.result_message = (
                f"Auto-pushing {self.git_ahead} commit(s) to origin/"
                f"{self.git_current_branch} before triggering…"
            )
            yield
            push_res = git_ops.push()
            if not push_res.ok:
                self.triggering = False
                self.result_message = (
                    f"Cannot trigger: branch not on origin and auto-push failed. "
                    f"Details: {push_res.out.strip() or 'unknown error'}"
                )
                self.result_kind = "error"
                yield rx.toast.error(self.result_message)
                return
            self._refresh_git_status()

        params = self._build_params()
        result = jenkins_trigger.trigger_build(
            params, job_name=jenkins_trigger.default_job_name()
        )
        self.triggering = False

        if not result.ok:
            self.result_message = result.error
            self.result_kind = "error"
            yield rx.toast.error(result.error)
            return

        # Persist the run so the background watcher can poll it.
        run_id = db.insert_run(
            queue_id=result.queue_id,
            job_name=jenkins_trigger.default_job_name(),
            branch=self.test_branch,
            release_version=self.modelopt_version.strip(),
            status="queued",
            params_json=json.dumps(params),
        )
        self.last_run_id = run_id
        self.last_queue_url = result.queue_url
        self.result_message = (
            f"Triggered Jenkins build (queue #{result.queue_id}). "
            "Open the Runs page to watch progress — the dashboard will "
            "auto-pull the .out log and analyze it when the build finishes."
        )
        self.result_kind = "success"
        yield rx.toast.success(self.result_message)
