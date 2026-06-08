"""State for the AI Analyzer page.

User pastes only the .out file path. Claude extracts environment + every
model under test. State holds those results as flat dicts (Reflex serializes
better that way) plus a flag set per row so the user can save the ones they
want into the matrix DB.
"""
from __future__ import annotations

from pathlib import Path

import reflex as rx

from hf_dashboard.data.common import SLURM_LOG_ROOT, job_id_from_path, resolve_job_input
from hf_dashboard.services import db, jenkins, log_analyzer


# Map AI verdict -> dashboard test_status used by the Matrix page.
_VERDICT_TO_STATUS = {
    "passed": "passed",
    "failed": "failed",
    "inconclusive": "broken",
}


class JenkinsParam(rx.Base):
    """One parameter row in the Jenkins-build panel."""
    name: str = ""
    value: str = ""


class ResultItem(rx.Base):
    """One row in the AI Analyzer's extracted-results list.

    Uses rx.Base so Reflex can do typed foreach over `list[ResultItem]`.

    `original_index` is the row's index in `AnalyzerState.results` and is
    used by handlers when the list is filtered (so foreach over a filtered
    list still toggles the correct row).
    """
    original_index: int = 0
    model_name: str = ""
    verdict: str = ""
    verdict_upper: str = ""
    reason: str = ""
    error_type: str = ""
    sample_output: str = ""
    selected: bool = True


class AnalyzerState(rx.State):
    # Inputs
    # job_input is what the user typed — a job ID like "191" or a full path.
    # resolved_path is the actual .out file path we work with.
    job_input: str = ""
    resolved_path: str = ""
    resolve_error: str = ""

    # Runtime state
    is_running: bool = False
    error_message: str = ""
    log_size_bytes: int = 0
    progress_message: str = ""
    expected_model_count: int = 0

    # Extracted environment (flat for easy Reflex rendering)
    env_backend: str = ""
    env_backend_version: str = ""
    env_gpu: str = ""
    env_gpu_count: int = 0
    env_docker_image: str = ""
    env_container_id: str = ""
    env_driver_version: str = ""
    env_cuda_version: str = ""
    env_node: str = ""
    env_job_id: str = ""
    env_extra_notes: str = ""

    # Filter for the results list: "all" / "passed" / "failed" / "inconclusive"
    verdict_filter: str = "all"

    # The release / modelopt version under test. Pre-filled from Jenkins build
    # params (`modelopt_version`) when available, but user can override before
    # saving so the matrix groups results correctly per release.
    save_release_version: str = ""

    # Was the current view populated from cached DB rows (vs. live AI analysis)?
    loaded_from_db: bool = False
    loaded_from_db_at: str = ""

    # Jenkins build info (populated when the input is a job ID and Jenkins is configured).
    jenkins_configured: bool = False
    jenkins_url: str = ""            # link to the build page
    jenkins_job_url: str = ""        # link to the Jenkins job
    jenkins_job_name: str = ""
    jenkins_build_number: str = ""
    jenkins_display_name: str = ""
    jenkins_result: str = ""         # SUCCESS / FAILURE / "" if still building
    jenkins_building: bool = False
    jenkins_triggered_by: str = ""
    jenkins_started_at: str = ""     # formatted timestamp
    jenkins_params: list[JenkinsParam] = []
    jenkins_error: str = ""          # populated when fetch failed

    # Overall summary
    summary: str = ""

    # Per-model results. Typed list so rx.foreach can dispatch.
    results: list[ResultItem] = []

    # Persistent save-status banner (visible until next analyze).
    save_status_message: str = ""
    save_status_kind: str = ""   # "" / "success" / "error"

    # Details modal state.
    detail_open: bool = False
    detail_model_name: str = ""
    detail_verdict: str = ""
    detail_verdict_upper: str = ""
    detail_reason: str = ""
    detail_error_type: str = ""
    detail_sample_output: str = ""

    slurm_root: str = SLURM_LOG_ROOT

    # --- Input handlers ----------------------------------------------------

    def set_job_input(self, v: str):
        """Update the input box, re-resolve to a real .out path, and refresh
        Jenkins info for that job id (best effort)."""
        self.job_input = v
        path, err = resolve_job_input(v)
        self.resolved_path = path
        self.resolve_error = err or ""
        # Refresh Jenkins side panel for the new job id.
        self._refresh_jenkins(path or "")

    def _refresh_jenkins(self, resolved_path: str):
        """Populate jenkins_* state from the resolved path's job id."""
        # Reset
        self.jenkins_configured = jenkins.is_configured()
        self.jenkins_url = ""
        self.jenkins_job_url = ""
        self.jenkins_job_name = ""
        self.jenkins_build_number = ""
        self.jenkins_display_name = ""
        self.jenkins_result = ""
        self.jenkins_building = False
        self.jenkins_triggered_by = ""
        self.jenkins_started_at = ""
        self.jenkins_params = []
        self.jenkins_error = ""

        if not self.jenkins_configured:
            return  # Quiet — UI shows a hint card instead.
        bnum = job_id_from_path(resolved_path)
        if not bnum:
            return  # Path wasn't recognized as <root>/<job_id>/... — skip silently.

        info, err = jenkins.get_build_info(bnum)
        if err:
            self.jenkins_error = err
            return
        if not info:
            return

        self.jenkins_url = info.url
        self.jenkins_job_url = info.job_url
        self.jenkins_job_name = info.job_name
        self.jenkins_build_number = info.build_number
        self.jenkins_display_name = info.display_name
        self.jenkins_result = info.result
        self.jenkins_building = info.building
        self.jenkins_triggered_by = info.triggered_by
        # Format timestamp as local-ish ISO (Jenkins gives epoch millis).
        if info.timestamp_ms:
            from datetime import datetime
            try:
                self.jenkins_started_at = datetime.fromtimestamp(
                    info.timestamp_ms / 1000
                ).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                self.jenkins_started_at = ""
        self.jenkins_params = [
            JenkinsParam(name=p.get("name") or "", value=p.get("value") or "")
            for p in info.parameters
        ]
        # Extract the release version from Jenkins build params if present.
        # Common parameter names we've seen: modelopt_version, release_version.
        for p in info.parameters:
            name = (p.get("name") or "").lower()
            if name in ("modelopt_version", "release_version", "release"):
                v = (p.get("value") or "").strip()
                if v and not self.save_release_version:
                    self.save_release_version = v
                break

    @rx.var
    def out_file_path(self) -> str:
        """Back-compat alias used by template strings and DB lookups."""
        return self.resolved_path

    def on_load(self):
        """Page mount hook — if ?path=... or ?job=... is in URL, prefill + load from DB."""
        try:
            params = self.router.page.params or {}
        except Exception:
            return
        if not isinstance(params, dict):
            return
        requested = (params.get("job") or params.get("path") or "").strip()
        if requested and requested != self.job_input:
            self.job_input = requested
            path, err = resolve_job_input(requested)
            self.resolved_path = path
            self.resolve_error = err or ""
            self._refresh_jenkins(path or "")
            if path:
                yield AnalyzerState.load_saved_for_path

    def _reset_results(self):
        self.error_message = ""
        self.env_backend = ""
        self.env_backend_version = ""
        self.env_gpu = ""
        self.env_gpu_count = 0
        self.env_docker_image = ""
        self.env_container_id = ""
        self.env_driver_version = ""
        self.env_cuda_version = ""
        self.env_node = ""
        self.env_job_id = ""
        self.env_extra_notes = ""
        self.summary = ""
        self.results = []
        self.log_size_bytes = 0
        self.progress_message = ""
        self.expected_model_count = 0
        self.save_status_message = ""
        self.save_status_kind = ""
        self.verdict_filter = "all"
        self.loaded_from_db = False
        self.loaded_from_db_at = ""

    # --- Actions -----------------------------------------------------------

    def analyze(self):
        """Read the .out file, send to Claude, store extracted analysis in state."""
        self._reset_results()

        path = self.out_file_path.strip()
        if not path:
            self.error_message = "Please provide a .out file path."
            yield rx.toast.error(self.error_message)
            return
        if not Path(path).is_file():
            self.error_message = f"File not found: {path}"
            yield rx.toast.error(self.error_message)
            return
        if not log_analyzer.api_key_configured():
            self.error_message = "NVIDIA_API_KEY is not set on the dashboard host."
            yield rx.toast.error(self.error_message)
            return

        self.is_running = True
        self.progress_message = "Reading log file…"
        yield

        try:
            _, total_size, model_count = log_analyzer.read_log_extracted(path)
            self.log_size_bytes = total_size
            self.expected_model_count = model_count
            self.progress_message = (
                f"Found {model_count} model{'s' if model_count != 1 else ''} in log. "
                f"Calling Claude via NVIDIA Inference…"
            )
            yield

            seen = 0
            for partial in log_analyzer.analyze_log_stream(path):
                # `partial` is a plain dict (possibly with partial / missing fields).
                env = partial.get("environment") or {}
                backend = env.get("backend") or ""
                if backend and not self.env_backend:
                    self.env_backend = backend
                    self.env_backend_version = env.get("backend_version") or ""
                    self.env_gpu = env.get("gpu") or ""
                    self.env_gpu_count = env.get("gpu_count") or 0
                    self.env_docker_image = env.get("docker_image") or ""
                    self.env_container_id = env.get("container_id") or ""
                    self.env_driver_version = env.get("driver_version") or ""
                    self.env_cuda_version = env.get("cuda_version") or ""
                    self.env_node = env.get("node") or ""
                    self.env_job_id = env.get("job_id") or ""
                    self.env_extra_notes = env.get("extra_notes") or ""

                all_models = partial.get("models") or []
                new_models = all_models[seen:]
                if new_models:
                    additions = []
                    next_idx = len(self.results)
                    for m in new_models:
                        verdict = (m.get("verdict") or "").strip()
                        # Skip rows that don't yet have a verdict assigned —
                        # the model is still streaming this entry.
                        if not verdict:
                            break
                        additions.append(
                            ResultItem(
                                original_index=next_idx + len(additions),
                                model_name=m.get("model_name") or "",
                                verdict=verdict,
                                verdict_upper=verdict.upper(),
                                reason=m.get("reason") or "",
                                error_type=m.get("error_type") or "",
                                sample_output=m.get("sample_output") or "",
                                selected=True,
                            )
                        )
                    if additions:
                        self.results = self.results + additions
                        seen += len(additions)

                summary = partial.get("summary") or ""
                if summary:
                    self.summary = summary

                if model_count:
                    self.progress_message = (
                        f"Streaming results: {seen}/{model_count} models received…"
                    )
                else:
                    self.progress_message = f"Streaming results: {seen} models received…"
                yield  # push current state to the browser

            n = len(self.results)
            self.progress_message = ""
            yield rx.toast.success(
                f"Found {n} model{'s' if n != 1 else ''} in log"
            )
        except FileNotFoundError as e:
            self.error_message = str(e)
            self.progress_message = ""
            yield rx.toast.error(f"File error: {e}")
        except Exception as e:
            self.error_message = f"{type(e).__name__}: {e}"
            self.progress_message = ""
            yield rx.toast.error(self.error_message)
        finally:
            self.is_running = False
            yield

    def toggle_selected(self, idx: int):
        """Toggle whether a particular result row gets saved on bulk save."""
        if 0 <= idx < len(self.results):
            new = list(self.results)
            old = new[idx]
            new[idx] = ResultItem(
                original_index=old.original_index,
                model_name=old.model_name,
                verdict=old.verdict,
                verdict_upper=old.verdict_upper,
                reason=old.reason,
                error_type=old.error_type,
                sample_output=old.sample_output,
                selected=not old.selected,
            )
            self.results = new

    def save_selected(self):
        """Upsert all selected rows into the hf_model_tests table."""
        from datetime import datetime

        if not self.results:
            self.save_status_message = "Nothing to save — run analysis first."
            self.save_status_kind = "error"
            yield rx.toast.error(self.save_status_message)
            return
        if self.env_backend == "unknown" or not self.env_backend:
            self.save_status_message = (
                "Backend was not detected from the log; cannot save without a backend."
            )
            self.save_status_kind = "error"
            yield rx.toast.error(self.save_status_message)
            return

        saved = 0
        skipped = 0
        errors: list[str] = []
        for row in self.results:
            if not row.selected:
                skipped += 1
                continue
            status = _VERDICT_TO_STATUS.get(row.verdict, "broken")
            try:
                db.upsert_test(
                    model_name=row.model_name,
                    backend=self.env_backend,
                    gpu_name=self.env_gpu,
                    release_version=self.save_release_version.strip(),
                    test_status=status,
                    out_file_path=self.out_file_path,
                    ai_verdict=row.verdict,
                    ai_reason=row.reason,
                    ai_full_analysis=row.sample_output,
                )
                saved += 1
            except Exception as e:
                errors.append(f"{row.model_name}: {type(e).__name__}: {e}")

        when = datetime.now().strftime("%H:%M:%S")
        parts = [f"Saved {saved} row{'s' if saved != 1 else ''} at {when}"]
        if skipped:
            parts.append(f"skipped {skipped} unchecked")
        if errors:
            parts.append(f"{len(errors)} failed: {errors[0]}")

        self.save_status_message = " · ".join(parts)
        self.save_status_kind = "error" if errors else "success"
        if errors:
            yield rx.toast.error(self.save_status_message)
        else:
            yield rx.toast.success(self.save_status_message)

    def open_detail(self, idx: int):
        """Open the details modal for one result row."""
        if 0 <= idx < len(self.results):
            r = self.results[idx]
            self.detail_model_name = r.model_name
            self.detail_verdict = r.verdict
            self.detail_verdict_upper = r.verdict_upper
            self.detail_reason = r.reason
            self.detail_error_type = r.error_type
            self.detail_sample_output = r.sample_output
            self.detail_open = True

    def close_detail(self):
        self.detail_open = False

    # --- Computed vars -----------------------------------------------------

    @rx.var
    def has_results(self) -> bool:
        return len(self.results) > 0

    @rx.var
    def log_size_human(self) -> str:
        if self.log_size_bytes == 0:
            return ""
        if self.log_size_bytes < 1024:
            return f"{self.log_size_bytes} B"
        if self.log_size_bytes < 1024 * 1024:
            return f"{self.log_size_bytes / 1024:.1f} KB"
        return f"{self.log_size_bytes / (1024 * 1024):.1f} MB"

    @rx.var
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.verdict == "passed")

    @rx.var
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.verdict == "failed")

    @rx.var
    def inconclusive_count(self) -> int:
        return sum(1 for r in self.results if r.verdict == "inconclusive")

    @rx.var
    def visible_results(self) -> list[ResultItem]:
        """Results list filtered by the current verdict filter."""
        if self.verdict_filter in ("", "all"):
            return self.results
        return [r for r in self.results if r.verdict == self.verdict_filter]

    @rx.var
    def saved_rows_count_for_path(self) -> int:
        """How many DB rows already exist for the currently-entered path."""
        path = (self.out_file_path or "").strip()
        if not path:
            return 0
        try:
            with db.get_conn() as conn:
                cur = conn.execute(
                    "SELECT COUNT(*) AS c FROM hf_model_tests WHERE out_file_path=?",
                    (path,),
                )
                row = cur.fetchone()
                return row["c"] if row else 0
        except Exception:
            return 0

    # --- Filter handlers ---------------------------------------------------

    def set_verdict_filter(self, v: str):
        self.verdict_filter = v

    def set_save_release_version(self, v: str):
        self.save_release_version = v

    # --- Load saved (no AI call) -------------------------------------------

    def load_saved_for_path(self):
        """Populate results from DB rows already saved for this .out path."""
        path = (self.out_file_path or "").strip()
        if not path:
            self.error_message = "Please enter a .out file path first."
            yield rx.toast.error(self.error_message)
            return

        with db.get_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM hf_model_tests WHERE out_file_path=? "
                "ORDER BY updated_at DESC",
                (path,),
            )
            rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            self.error_message = f"No saved results found for {path}."
            yield rx.toast.error(self.error_message)
            return

        self._reset_results()
        # Use the most recent backend/gpu seen as the env summary.
        latest = rows[0]
        self.env_backend = latest.get("backend") or ""
        self.env_gpu = latest.get("gpu_name") or ""
        self.env_gpu_count = 0  # not stored in DB
        self.loaded_from_db = True
        self.loaded_from_db_at = latest.get("updated_at") or ""
        self.summary = (
            f"Loaded from saved DB rows (last updated {self.loaded_from_db_at})"
        )

        self.results = [
            ResultItem(
                original_index=i,
                model_name=r["model_name"],
                verdict=(r["ai_verdict"] or r["test_status"] or ""),
                verdict_upper=(r["ai_verdict"] or r["test_status"] or "").upper(),
                reason=r["ai_reason"] or "",
                error_type="",
                sample_output=r["ai_full_analysis"] or "",
                selected=False,  # don't re-save what's already in DB
            )
            for i, r in enumerate(rows)
        ]
        yield rx.toast.success(f"Loaded {len(rows)} saved rows from DB")
