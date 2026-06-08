"""HF Test Dashboard — Reflex app entry. Registers routes."""
from __future__ import annotations

import reflex as rx

from hf_dashboard.page.analyzer import analyzer_page
from hf_dashboard.page.history import history_page
from hf_dashboard.page.home import home_page
from hf_dashboard.page.inbox import inbox_page
from hf_dashboard.page.matrix import matrix_page
from hf_dashboard.page.runs import runs_page
from hf_dashboard.page.trigger import trigger_page
from hf_dashboard.services import runs_watcher

# Spawn the background watcher thread once per process. Polls Jenkins every
# 30s for active builds, auto-runs AI analysis on finished ones.
runs_watcher.start_watcher()


app = rx.App(
    style={
        "font_family": "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif",
        "background": "#F8FAFC",
    },
)

app.add_page(home_page, route="/", title="HF Test Dashboard")
app.add_page(inbox_page, route="/inbox", title="Inbox · HF Dashboard")
app.add_page(trigger_page, route="/trigger", title="Trigger Build · HF Dashboard")
app.add_page(runs_page, route="/runs", title="Test Runs · HF Dashboard")
app.add_page(matrix_page, route="/matrix", title="Test Matrix · HF Dashboard")
app.add_page(analyzer_page, route="/analyzer", title="AI Analyzer · HF Dashboard")
app.add_page(history_page, route="/history", title="History · HF Dashboard")
