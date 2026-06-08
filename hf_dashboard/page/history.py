"""Analysis History page.

Lists past .out files analyzed, with per-file pass/fail counts and a
'Load in analyzer' link that takes you to the analyzer with the path
pre-filled.
"""
from __future__ import annotations

import reflex as rx

from hf_dashboard.components.navbar import page_shell
from hf_dashboard.data.common import STATUS_ICONS
from hf_dashboard.data.history_state import HistoryItem, HistoryState
from hf_dashboard.services import jenkins as jenkins_svc


def _count_pill(value, color: str, icon: str) -> rx.Component:
    return rx.hstack(
        rx.icon(tag=icon, size=14, color=color),
        rx.text(value, font_size="0.85rem", color="#0F172A", font_weight="600"),
        spacing="1",
        align="center",
    )


def _job_label(item: HistoryItem) -> rx.Component:
    """Prominent job-id label + filename as subtitle."""
    return rx.hstack(
        rx.cond(
            item.job_id != "",
            rx.box(
                rx.text(
                    "JOB",
                    font_size="0.62rem",
                    font_weight="700",
                    color="#94A3B8",
                    letter_spacing="0.08em",
                ),
                rx.heading(
                    item.job_id,
                    size="6",
                    color="#0F172A",
                    line_height="1",
                ),
                padding="0.35rem 0.65rem",
                background="#F1F5F9",
                border="1px solid #E2E8F0",
                border_radius="0.5rem",
                min_width="68px",
                text_align="center",
            ),
            rx.fragment(),
        ),
        rx.vstack(
            rx.text(
                item.file_basename,
                font_family="monospace",
                font_size="0.88rem",
                font_weight="700",
                color="#0F172A",
            ),
            rx.text(
                item.out_file_path,
                font_size="0.7rem",
                color="#94A3B8",
                font_family="monospace",
            ),
            spacing="1",
            align="start",
        ),
        spacing="3",
        align="center",
    )


def _backend_badge(backend) -> rx.Component:
    return rx.match(
        backend,
        ("trtllm", rx.badge("TRTLLM", color_scheme="indigo", variant="soft", size="1")),
        ("vllm",   rx.badge("VLLM",   color_scheme="orange", variant="soft", size="1")),
        ("sglang", rx.badge("SGLANG", color_scheme="green",  variant="soft", size="1")),
        rx.fragment(),
    )


def _row(item: HistoryItem) -> rx.Component:
    open_href = rx.cond(
        item.job_id != "",
        "/analyzer?job=" + item.job_id,
        "/analyzer?path=" + item.out_file_path,
    )
    # Jenkins job-name + base URL are read once at server start (env vars).
    jenkins_job_name = jenkins_svc.default_job_name()
    jenkins_base = jenkins_svc.base_url()
    jenkins_configured = bool(jenkins_base)
    return rx.box(
        rx.hstack(
            # Left: job id + filename + meta
            rx.vstack(
                _job_label(item),
                rx.hstack(
                    _backend_badge(item.backend),
                    rx.cond(
                        item.gpu_name != "",
                        rx.badge(item.gpu_name, color_scheme="cyan",
                                 variant="soft", size="1"),
                        rx.fragment(),
                    ),
                    rx.text(
                        f"updated {item.last_updated}",
                        font_size="0.72rem",
                        color="#94A3B8",
                    ),
                    spacing="2",
                    align="center",
                ),
                spacing="2",
                align="start",
                flex="1",
            ),
            # Middle: count pills
            rx.hstack(
                _count_pill(item.total_models, "#475569", "list"),
                _count_pill(item.passed, STATUS_ICONS["passed"][1], "circle_check"),
                _count_pill(item.failed, STATUS_ICONS["failed"][1], "circle_x"),
                rx.cond(
                    item.inconclusive > 0,
                    _count_pill(item.inconclusive, STATUS_ICONS["broken"][1],
                                "triangle_alert"),
                    rx.fragment(),
                ),
                spacing="3",
                align="center",
            ),
            # Right: actions
            rx.hstack(
                rx.cond(
                    jenkins_configured & (item.job_id != ""),
                    rx.link(
                        rx.button(
                            rx.hstack(
                                rx.icon(tag="git_branch", size=14),
                                rx.text("Jenkins"),
                                spacing="1",
                                align="center",
                            ),
                            variant="outline",
                            color_scheme="gray",
                            size="2",
                        ),
                        href=f"{jenkins_base}/job/{jenkins_job_name}/" + item.job_id + "/",
                        is_external=True,
                    ),
                    rx.fragment(),
                ),
                rx.link(
                    rx.button(
                        rx.hstack(
                            rx.icon(tag="external_link", size=14),
                            rx.text("Open in Analyzer"),
                            spacing="1",
                            align="center",
                        ),
                        variant="soft",
                        color_scheme="blue",
                        size="2",
                    ),
                    href=open_href,
                ),
                spacing="2",
                align="center",
            ),
            spacing="4",
            align="center",
            width="100%",
        ),
        background="white",
        border="1px solid #E2E8F0",
        border_radius="0.6rem",
        padding="1rem 1.25rem",
        width="100%",
        _hover={"border_color": "#CBD5E1", "box_shadow": "0 2px 8px rgba(15,23,42,0.04)"},
        transition="all 120ms ease",
    )


def history_page() -> rx.Component:
    body = rx.vstack(
        rx.vstack(
            rx.heading("Analysis History", size="7", color="#0F172A"),
            rx.text(
                "Every .out file you've analyzed and saved, grouped by file path. "
                "Click a row to reopen the saved results without re-running the AI.",
                color="#64748B",
                font_size="0.9rem",
                max_width="780px",
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        rx.input(
            placeholder="Filter by path…",
            value=HistoryState.filter_text,
            on_change=HistoryState.set_filter_text,
            width="100%",
            max_width="420px",
        ),
        rx.cond(
            HistoryState.items.length() == 0,
            rx.callout(
                "No saved analyses yet. Run an analysis and click 'Save selected to matrix' first.",
                icon="info",
                color_scheme="blue",
            ),
            rx.vstack(
                rx.foreach(HistoryState.visible_items, _row),
                spacing="2",
                width="100%",
            ),
        ),
        spacing="4",
        align="stretch",
        width="100%",
        max_width="1200px",
        on_mount=HistoryState.load,
    )
    return page_shell(body)
