"""State for the Runs page.

Read-only view over `jenkins_runs`. A button lets the user kick the watcher
manually (in case they don't want to wait the next 30s tick).
"""
from __future__ import annotations

import reflex as rx

from hf_dashboard.services import db, jenkins as jenkins_read, runs_watcher


class RunItem(rx.Base):
    id: int = 0
    queue_id: int = 0
    build_number: int = 0
    build_number_str: str = ""
    job_name: str = ""
    branch: str = ""
    release_version: str = ""
    triggered_at: str = ""
    finished_at: str = ""
    duration_sec: int = 0
    status: str = ""
    log_path: str = ""
    analyzed_at: str = ""
    analyze_summary: str = ""
    notes: str = ""
    jenkins_url: str = ""

    # Pre-rendered duration string for the UI (Reflex can't format mid-render).
    duration_human: str = ""


def _format_duration(sec: int) -> str:
    if not sec:
        return ""
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


class RunsState(rx.State):
    items: list[RunItem] = []
    only_active: bool = False
    refreshing: bool = False

    def load(self):
        rows = db.list_runs(limit=200)
        if self.only_active:
            rows = [r for r in rows if r["status"] in ("queued", "building")]
        self.items = [self._to_item(r) for r in rows]

    @staticmethod
    def _to_item(r: dict) -> RunItem:
        bn = r.get("build_number") or 0
        jenkins_url = ""
        if bn:
            jenkins_url = jenkins_read.build_url(r.get("job_name") or "", bn)
        return RunItem(
            id=r["id"],
            queue_id=r.get("queue_id") or 0,
            build_number=bn,
            build_number_str=f"#{bn}" if bn else "(no build yet)",
            job_name=r.get("job_name") or "",
            branch=r.get("branch") or "",
            release_version=r.get("release_version") or "",
            triggered_at=r.get("triggered_at") or "",
            finished_at=r.get("finished_at") or "",
            duration_sec=r.get("duration_sec") or 0,
            duration_human=_format_duration(r.get("duration_sec") or 0),
            status=r.get("status") or "",
            log_path=r.get("log_path") or "",
            analyzed_at=r.get("analyzed_at") or "",
            analyze_summary=r.get("analyze_summary") or "",
            notes=r.get("notes") or "",
            jenkins_url=jenkins_url,
        )

    def toggle_only_active(self):
        self.only_active = not self.only_active
        self.load()

    def delete(self, run_id: int):
        """Delete one run record (won't touch Jenkins or .out files)."""
        n = db.delete_run(run_id)
        self.load()
        if n:
            yield rx.toast.success(f"Deleted run #{run_id}")
        else:
            yield rx.toast.error(f"Run #{run_id} not found")

    def poll_now(self):
        """Run one watcher pass synchronously, then reload."""
        self.refreshing = True
        yield
        try:
            runs_watcher.poll_once()
        except Exception as e:
            yield rx.toast.error(f"Polling failed: {type(e).__name__}: {e}")
        self.refreshing = False
        self.load()
        yield rx.toast.success("Polled Jenkins for active runs")

    @rx.var
    def has_items(self) -> bool:
        return len(self.items) > 0
