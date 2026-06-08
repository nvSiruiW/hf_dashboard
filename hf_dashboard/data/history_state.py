"""State for the Analysis History page.

Groups saved DB rows by their original `.out` file path and shows the most
recent verdict roll-up per file. Clicking an entry navigates to the Analyzer
page with that path pre-filled (and the saved rows preloaded).
"""
from __future__ import annotations

import os

import reflex as rx

from hf_dashboard.data.common import job_id_from_path
from hf_dashboard.services import db


class HistoryItem(rx.Base):
    out_file_path: str = ""
    job_id: str = ""           # extracted from the path (e.g. "191")
    file_basename: str = ""    # e.g. "slurm-2346484-deploy_hf.out"
    backend: str = ""
    gpu_name: str = ""
    last_updated: str = ""
    total_models: int = 0
    passed: int = 0
    failed: int = 0
    inconclusive: int = 0
    broken: int = 0


class HistoryState(rx.State):
    items: list[HistoryItem] = []
    filter_text: str = ""

    def set_filter_text(self, v: str):
        self.filter_text = v

    @rx.var
    def visible_items(self) -> list[HistoryItem]:
        if not self.filter_text:
            return self.items
        ft = self.filter_text.lower()
        return [i for i in self.items if ft in i.out_file_path.lower()]

    def load(self):
        """Group hf_model_tests rows by out_file_path."""
        with db.get_conn() as conn:
            cur = conn.execute(
                """
                SELECT
                    out_file_path,
                    MAX(backend)       AS backend,
                    MAX(gpu_name)      AS gpu_name,
                    MAX(updated_at)    AS last_updated,
                    COUNT(*)           AS total_models,
                    SUM(CASE WHEN test_status = 'passed' THEN 1 ELSE 0 END) AS passed,
                    SUM(CASE WHEN test_status = 'failed' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN ai_verdict  = 'inconclusive' THEN 1 ELSE 0 END) AS inconclusive,
                    SUM(CASE WHEN test_status = 'broken' AND ai_verdict != 'inconclusive' THEN 1 ELSE 0 END) AS broken
                FROM hf_model_tests
                WHERE out_file_path IS NOT NULL AND out_file_path != ''
                GROUP BY out_file_path
                ORDER BY last_updated DESC
                """
            )
            rows = cur.fetchall()

        self.items = [
            HistoryItem(
                out_file_path=r["out_file_path"] or "",
                job_id=job_id_from_path(r["out_file_path"] or ""),
                file_basename=os.path.basename(r["out_file_path"] or ""),
                backend=r["backend"] or "",
                gpu_name=r["gpu_name"] or "",
                last_updated=r["last_updated"] or "",
                total_models=r["total_models"] or 0,
                passed=r["passed"] or 0,
                failed=r["failed"] or 0,
                inconclusive=r["inconclusive"] or 0,
                broken=r["broken"] or 0,
            )
            for r in rows
        ]
