"""Background polling thread that drives the Jenkins → log → AI → matrix loop.

Started lazily by `start_watcher()` at app boot. One thread per process, polls
every `POLL_INTERVAL_SEC` seconds.

For each row in `jenkins_runs` with status in ('queued', 'building'):
  - If queued and we don't have build_number → resolve via queue API.
  - If running and we have a build_number → ask Jenkins for build status.
  - If Jenkins says done → find the .out log on disk, run AI analysis,
    write per-(model × backend) rows into `hf_model_tests`, mark run
    'ANALYZED'.

Any error that comes up gets stored on the run row in `notes` and the run
moves to status 'ERROR' so it stops being polled.
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from hf_dashboard.services import db, jenkins_trigger, log_analyzer


SLURM_LOG_ROOT_DEFAULT = (
    "/localhome/local-siruiw/myshare/workspace/slurm_logs/sirui_test_hf"
)
POLL_INTERVAL_SEC = 30


_VERDICT_TO_STATUS = {
    "passed": "passed",
    "failed": "failed",
    "inconclusive": "broken",
}


# ---------------------------------------------------------------------------
# Public: start the watcher (idempotent)
# ---------------------------------------------------------------------------

_thread_started = False
_thread_lock = threading.Lock()


def start_watcher() -> None:
    """Idempotently start the background polling thread. Safe to call from
    multiple places — only the first call spawns a thread."""
    global _thread_started
    with _thread_lock:
        if _thread_started:
            return
        _thread_started = True
        t = threading.Thread(
            target=_poll_loop,
            name="hf_dashboard.runs_watcher",
            daemon=True,
        )
        t.start()


def _poll_loop() -> None:
    print("[runs_watcher] started", flush=True)
    while True:
        try:
            poll_once()
        except Exception as e:  # never let the loop die
            print(f"[runs_watcher] unhandled error: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_INTERVAL_SEC)


def poll_once() -> None:
    """One pass over active runs. Public so the UI can trigger a manual poll."""
    for run in db.list_active_runs():
        try:
            _process_one(run)
        except Exception as e:
            print(
                f"[runs_watcher] error on run {run.get('id')}: {type(e).__name__}: {e}",
                flush=True,
            )
            db.update_run(
                run["id"],
                status="ERROR",
                notes=f"{type(e).__name__}: {e}",
            )


# ---------------------------------------------------------------------------
# Per-run state machine
# ---------------------------------------------------------------------------

def _process_one(run: dict) -> None:
    run_id = run["id"]
    job_name = run["job_name"]
    build_number = run.get("build_number")
    status = (run.get("status") or "").strip().lower()

    if not build_number:
        # Still in the queue — try to resolve.
        q = run.get("queue_id")
        if not q:
            db.update_run(run_id, status="ERROR", notes="No queue_id or build_number stored.")
            return
        bn, err, qs = jenkins_trigger.queue_to_build_number(q)
        if err:
            # If the queue entry expired we'll never resolve it. Mark error.
            db.update_run(run_id, status="ERROR", notes=err)
            return
        if bn is None:
            return  # still pending — try again next tick
        db.update_run(
            run_id,
            build_number=bn,
            status="building",
            started_at=datetime.utcnow().isoformat(timespec="seconds"),
        )
        return  # next tick we'll poll the build itself

    # Resolved: poll the build for completion.
    data, err = jenkins_trigger.get_build_status(job_name, build_number)
    if err:
        # Transient / not-yet-existing — leave run as-is and retry next tick.
        # Only mark ERROR for permanent errors (e.g. auth).
        if "auth" in (err or "").lower():
            db.update_run(run_id, status="ERROR", notes=err)
        return
    if data is None:
        return

    is_building = bool(data.get("building"))
    result = (data.get("result") or "").strip().upper() if not is_building else ""

    # Pre-extract started_at and duration_ms for display.
    if is_building:
        if status != "building":
            db.update_run(run_id, status="building")
        return

    # Build finished. Persist outcome + look for the log.
    duration_ms = int(data.get("duration") or 0)
    log_path, log_err = _find_log(build_number)

    update_fields = {
        "status": result or "UNKNOWN",
        "finished_at": datetime.utcnow().isoformat(timespec="seconds"),
        "duration_sec": duration_ms // 1000 if duration_ms else 0,
    }
    if log_path:
        update_fields["log_path"] = str(log_path)
    if log_err:
        update_fields["notes"] = log_err

    db.update_run(run_id, **update_fields)

    # Auto-analyze + save to matrix.
    if log_path and result in ("SUCCESS", "FAILURE", "UNSTABLE"):
        _analyze_and_persist(run_id, log_path, run)


def _find_log(build_number: int) -> tuple[Path | None, str | None]:
    """Locate the .out file for a Jenkins build number under the slurm log root."""
    root = Path(os.environ.get("SLURM_LOG_ROOT", SLURM_LOG_ROOT_DEFAULT))
    job_dir = root / str(build_number)
    if not job_dir.exists():
        return None, f"Slurm log directory not found: {job_dir}"
    # Prefer the canonical name; fall back to any .out.
    candidates = sorted(glob.glob(str(job_dir / "slurm-*-deploy_hf.out")))
    if not candidates:
        candidates = sorted(glob.glob(str(job_dir / "*.out")))
    if not candidates:
        return None, f"No .out file under {job_dir}"
    return Path(candidates[-1]), None


def _analyze_and_persist(run_id: int, log_path: Path, run: dict) -> None:
    """Run Claude on the log + write per-model results into `hf_model_tests`.

    Mirrors what the Analyzer page does interactively, but headless.
    """
    print(f"[runs_watcher] analyzing {log_path} for run {run_id}", flush=True)
    try:
        analysis = log_analyzer.analyze_log(log_path)
    except Exception as e:
        db.update_run(
            run_id,
            status="ERROR",
            notes=f"AI analysis failed: {type(e).__name__}: {e}",
        )
        return

    env = analysis.environment
    release_version = (run.get("release_version") or "").strip()
    gpu = env.gpu or ""
    backend = env.backend or ""

    saved = failed = 0
    summary_lines = []
    for m in analysis.models:
        if not backend:
            # Can't write a row without knowing the backend.
            continue
        status = _VERDICT_TO_STATUS.get(m.verdict, "broken")
        try:
            db.upsert_test(
                model_name=m.model_name,
                backend=backend,
                gpu_name=gpu,
                release_version=release_version,
                test_status=status,
                out_file_path=str(log_path),
                ai_verdict=m.verdict,
                ai_reason=m.reason,
                ai_full_analysis=m.sample_output,
                job_name=run.get("job_name"),
                build_number=str(run.get("build_number")) if run.get("build_number") else None,
            )
            saved += 1
            summary_lines.append(f"  {status:10s} {m.model_name}")
        except Exception as e:
            failed += 1
            summary_lines.append(f"  ERROR      {m.model_name}: {e}")

    summary = (
        f"{saved} models written ({failed} errors). "
        f"Backend={backend} GPU={gpu} Release={release_version}.\n"
        + "\n".join(summary_lines)
    )

    db.update_run(
        run_id,
        status="ANALYZED",
        analyzed_at=datetime.utcnow().isoformat(timespec="seconds"),
        analyze_summary=summary,
    )
    print(f"[runs_watcher] run {run_id}: wrote {saved} rows to matrix", flush=True)
