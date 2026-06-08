"""Runs page — lists every Jenkins build the dashboard has triggered, plus
its current status (queued / building / done / analyzed)."""
from __future__ import annotations

import reflex as rx

from hf_dashboard.components.navbar import page_shell
from hf_dashboard.data.runs_state import RunItem, RunsState


def _status_badge(status_var) -> rx.Component:
    return rx.match(
        status_var,
        ("queued",   rx.badge("QUEUED",   color_scheme="gray",   variant="soft", size="2")),
        ("building", rx.badge(
            rx.hstack(rx.spinner(size="1"), rx.text("BUILDING"), spacing="1", align="center"),
            color_scheme="blue", variant="soft", size="2",
        )),
        ("SUCCESS",  rx.badge("SUCCESS",  color_scheme="green",  variant="solid", size="2")),
        ("FAILURE",  rx.badge("FAILURE",  color_scheme="red",    variant="solid", size="2")),
        ("UNSTABLE", rx.badge("UNSTABLE", color_scheme="orange", variant="solid", size="2")),
        ("ABORTED",  rx.badge("ABORTED",  color_scheme="gray",   variant="solid", size="2")),
        ("ANALYZED", rx.badge("ANALYZED", color_scheme="indigo", variant="solid", size="2")),
        ("ERROR",    rx.badge("ERROR",    color_scheme="red",    variant="soft",  size="2")),
        rx.badge(status_var, color_scheme="gray", variant="soft", size="2"),
    )


def _row(item: RunItem) -> rx.Component:
    return rx.box(
        rx.vstack(
            # Header line
            rx.hstack(
                _status_badge(item.status),
                rx.text(
                    item.job_name + " " + item.build_number_str,
                    font_family="monospace",
                    font_weight="700",
                    font_size="0.9rem",
                    color="#0F172A",
                ),
                rx.cond(
                    item.branch != "",
                    rx.badge("branch: " + item.branch, color_scheme="indigo",
                             variant="soft", size="1"),
                    rx.fragment(),
                ),
                rx.cond(
                    item.release_version != "",
                    rx.badge("release: " + item.release_version, color_scheme="purple",
                             variant="soft", size="1"),
                    rx.fragment(),
                ),
                rx.spacer(),
                rx.cond(
                    item.jenkins_url != "",
                    rx.link(
                        rx.button(
                            rx.hstack(
                                rx.icon(tag="external_link", size=12),
                                rx.text("Jenkins"),
                                spacing="1",
                                align="center",
                            ),
                            variant="outline", color_scheme="gray", size="1",
                        ),
                        href=item.jenkins_url,
                        is_external=True,
                    ),
                    rx.fragment(),
                ),
                rx.tooltip(
                    rx.button(
                        rx.icon(tag="trash_2", size=12),
                        on_click=RunsState.delete(item.id),
                        variant="ghost",
                        color_scheme="red",
                        size="1",
                    ),
                    content="Delete this run record (Jenkins build itself is not affected)",
                ),
                spacing="2",
                align="center",
                width="100%",
                flex_wrap="wrap",
            ),
            # Timing line
            rx.hstack(
                rx.text("triggered " + item.triggered_at,
                        font_size="0.75rem", color="#94A3B8"),
                rx.cond(
                    item.finished_at != "",
                    rx.text("· finished " + item.finished_at,
                            font_size="0.75rem", color="#94A3B8"),
                    rx.fragment(),
                ),
                rx.cond(
                    item.duration_human != "",
                    rx.text("· " + item.duration_human,
                            font_size="0.75rem", color="#94A3B8"),
                    rx.fragment(),
                ),
                spacing="1",
                align="center",
                flex_wrap="wrap",
            ),
            # Log + analysis summary
            rx.cond(
                item.log_path != "",
                rx.text(
                    item.log_path,
                    font_size="0.72rem",
                    color="#475569",
                    font_family="monospace",
                ),
                rx.fragment(),
            ),
            rx.cond(
                item.analyze_summary != "",
                rx.box(
                    rx.text(
                        item.analyze_summary,
                        font_family="monospace",
                        font_size="0.74rem",
                        color="#0F172A",
                        white_space="pre-wrap",
                    ),
                    background="#F0FDF4",
                    border_left="3px solid #059669",
                    border_radius="0.4rem",
                    padding="0.5rem 0.75rem",
                    max_height="180px",
                    overflow="auto",
                ),
                rx.fragment(),
            ),
            rx.cond(
                item.notes != "",
                rx.callout(
                    item.notes,
                    icon="circle_alert",
                    color_scheme="orange",
                ),
                rx.fragment(),
            ),
            spacing="2",
            align="stretch",
            width="100%",
        ),
        background="white",
        border="1px solid #E2E8F0",
        border_radius="0.6rem",
        padding="1rem 1.25rem",
        width="100%",
    )


def runs_page() -> rx.Component:
    body = rx.vstack(
        rx.vstack(
            rx.heading("Test runs", size="7", color="#0F172A"),
            rx.text(
                "Every Jenkins build triggered from this dashboard. A background ",
                "thread polls Jenkins every 30 seconds — when a build finishes, ",
                "the .out log is auto-pulled from /localhome/.../slurm_logs/, ",
                "analyzed by Claude, and per-model results land on the Test Matrix.",
                color="#64748B",
                font_size="0.92rem",
                max_width="780px",
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        rx.hstack(
            rx.hstack(
                rx.checkbox(
                    checked=RunsState.only_active,
                    on_change=RunsState.toggle_only_active,
                    size="2",
                ),
                rx.text("Only active (queued / building)",
                        font_size="0.85rem", color="#0F172A"),
                spacing="2", align="center",
            ),
            rx.spacer(),
            rx.button(
                rx.cond(
                    RunsState.refreshing,
                    rx.hstack(rx.spinner(size="1"), rx.text("Polling…"),
                              spacing="1", align="center"),
                    rx.hstack(rx.icon(tag="refresh_cw", size=14),
                              rx.text("Poll Jenkins now"),
                              spacing="1", align="center"),
                ),
                on_click=RunsState.poll_now,
                disabled=RunsState.refreshing,
                variant="soft", color_scheme="indigo", size="2",
            ),
            spacing="2", align="center", width="100%",
        ),
        rx.cond(
            RunsState.has_items,
            rx.vstack(
                rx.foreach(RunsState.items, _row),
                spacing="3", align="stretch", width="100%",
            ),
            rx.callout(
                "No runs yet. Trigger one from the Trigger page or from the "
                "‘Push & Trigger Test’ button on an Inbox model card.",
                icon="info",
                color_scheme="blue",
            ),
        ),
        spacing="4",
        align="stretch",
        width="100%",
        max_width="1200px",
        on_mount=RunsState.load,
    )
    return page_shell(body)
