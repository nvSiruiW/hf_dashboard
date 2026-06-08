"""State for the Test Matrix page.

Loads rows from `hf_model_tests` filtered by the currently-selected release
version, and exposes them as a {model: {backend: status}} nested dict so the
table cells can look up status in O(1) by composite key.
"""
from __future__ import annotations

import reflex as rx

from hf_dashboard.data.common import BACKENDS
from hf_dashboard.services import db


# Special filter value meaning "show all releases / no release filter applied".
ALL_RELEASES = "__ALL__"


class MatrixState(rx.State):
    models: list[str] = []
    # Flat key "<model>::<backend>" -> status.
    cells: dict[str, str] = {}
    bug_ids: dict[str, str] = {}
    reasons: dict[str, str] = {}
    # Counts for the summary header.
    total: int = 0
    passed: int = 0
    failed: int = 0
    pending: int = 0
    # Filters
    filter_text: str = ""
    release_filter: str = ALL_RELEASES   # release dropdown value

    # All releases ever seen in DB, for the dropdown.
    available_releases: list[str] = []

    backends: list[str] = list(BACKENDS)

    # Delete-confirm modal state
    delete_open: bool = False
    delete_model: str = ""
    delete_release: str = ""
    delete_count_estimate: int = 0

    # --- Setters ---------------------------------------------------------

    def set_filter_text(self, value: str):
        self.filter_text = value

    def set_release_filter(self, value: str):
        self.release_filter = value or ALL_RELEASES
        self.load()

    # --- Data loading ----------------------------------------------------

    def load(self):
        # All distinct releases first (so the dropdown stays populated even
        # when the current filter is selecting an empty set).
        raw_releases = db.list_release_versions()
        # Replace blank with a friendlier label for display, but keep "" as the
        # internal value (matches the DB).
        self.available_releases = raw_releases

        rows = db.list_tests()
        if self.release_filter != ALL_RELEASES:
            rows = [r for r in rows
                    if (r.get("release_version") or "") == self.release_filter]

        models_seen: dict[str, None] = {}
        cells: dict[str, str] = {}
        bugs: dict[str, str] = {}
        reasons: dict[str, str] = {}
        counts = {"passed": 0, "failed": 0, "pending": 0, "running": 0,
                  "broken": 0, "unsupported": 0}
        for r in rows:
            m = r["model_name"]
            b = r["backend"]
            status = (r.get("test_status") or "pending").lower()
            key = f"{m}::{b}"
            models_seen.setdefault(m, None)
            cells[key] = status
            bugs[key] = (r.get("bug_id") or "")
            reasons[key] = (r.get("ai_reason") or "")
            counts[status] = counts.get(status, 0) + 1

        self.models = list(models_seen.keys())
        self.cells = cells
        self.bug_ids = bugs
        self.reasons = reasons
        self.total = len(rows)
        self.passed = counts["passed"]
        self.failed = counts["failed"]
        self.pending = counts["pending"] + counts["running"]

    def refresh(self):
        self.load()
        return rx.toast.success("Refreshed", duration=1200)

    # --- Delete-row workflow --------------------------------------------

    def open_delete_dialog(self, model_name: str):
        """Open a confirm dialog for deleting all rows of a given model in
        the currently-filtered release."""
        # Count what we're about to delete so the confirm has real numbers.
        release = "" if self.release_filter == ALL_RELEASES else self.release_filter
        all_rows = db.list_tests()
        rows = [
            r for r in all_rows
            if r["model_name"] == model_name
            and (self.release_filter == ALL_RELEASES
                 or (r.get("release_version") or "") == release)
        ]
        self.delete_model = model_name
        self.delete_release = "" if self.release_filter == ALL_RELEASES else release
        self.delete_count_estimate = len(rows)
        self.delete_open = True

    def close_delete_dialog(self):
        self.delete_open = False
        self.delete_model = ""
        self.delete_release = ""
        self.delete_count_estimate = 0

    def confirm_delete(self):
        model_name = self.delete_model
        if not model_name:
            return
        if self.release_filter == ALL_RELEASES:
            n = db.delete_tests_for_model(model_name)
        else:
            n = db.delete_tests_for_model(model_name, self.delete_release)
        self.close_delete_dialog()
        self.load()
        yield rx.toast.success(
            f"Deleted {n} row{'s' if n != 1 else ''} for {model_name}"
        )

    # --- Computed --------------------------------------------------------

    @rx.var
    def visible_models(self) -> list[str]:
        if not self.filter_text:
            return self.models
        ft = self.filter_text.lower()
        return [m for m in self.models if ft in m.lower()]

    @rx.var
    def release_filter_label(self) -> str:
        """Display string for the currently-selected release."""
        if self.release_filter == ALL_RELEASES:
            return "All releases"
        return self.release_filter or "(no release tag)"

    @rx.var
    def release_options(self) -> list[str]:
        """Dropdown items: 'All releases' + each known release. We translate
        the user's pick back to release_filter via set_release_filter."""
        opts = ["All releases"]
        for r in self.available_releases:
            opts.append(r if r else "(no release tag)")
        return opts

    def select_release_by_label(self, label: str):
        """Map the dropdown label back to the internal release_filter value."""
        if label == "All releases":
            self.set_release_filter(ALL_RELEASES)
        elif label == "(no release tag)":
            self.set_release_filter("")
        else:
            self.set_release_filter(label)
