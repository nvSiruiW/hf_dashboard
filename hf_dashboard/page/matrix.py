"""Test Matrix page: rows = HF models, columns = trtllm / vllm / sglang."""
from __future__ import annotations

import reflex as rx

from hf_dashboard.components.navbar import page_shell
from hf_dashboard.data.common import BACKEND_COLORS, STATUS_ICONS
from hf_dashboard.data.matrix_state import MatrixState


def _status_icon(status: str) -> rx.Component:
    """Render one of the canonical status icons. Uses rx.match for static dispatch."""
    return rx.match(
        status,
        ("passed",      rx.icon(tag="circle_check",   size=22, color=STATUS_ICONS["passed"][1])),
        ("failed",      rx.icon(tag="circle_x",       size=22, color=STATUS_ICONS["failed"][1])),
        ("running",     rx.icon(tag="loader_circle",  size=22, color=STATUS_ICONS["running"][1])),
        ("pending",     rx.icon(tag="circle_help",    size=22, color=STATUS_ICONS["pending"][1])),
        ("broken",      rx.icon(tag="triangle_alert", size=22, color=STATUS_ICONS["broken"][1])),
        rx.icon(tag="circle_minus", size=22, color=STATUS_ICONS["unsupported"][1]),
    )


def _backend_header(name: str) -> rx.Component:
    color = BACKEND_COLORS.get(name, "#475569")
    return rx.table.column_header_cell(
        rx.hstack(
            rx.box(width="8px", height="8px", border_radius="50%", background=color),
            rx.text(name.upper(), font_weight="700", font_size="0.85rem", color="#0F172A"),
            spacing="2",
            align="center",
        ),
        text_align="center",
        padding_y="0.75rem",
    )


def _cell(model: str, backend: str) -> rx.Component:
    key = f"{model}::{backend}"
    status = MatrixState.cells.get(key, "unsupported")
    reason = MatrixState.reasons.get(key, "")
    bug = MatrixState.bug_ids.get(key, "")
    return rx.table.cell(
        rx.tooltip(
            rx.hstack(
                _status_icon(status),
                rx.cond(
                    bug != "",
                    rx.badge(
                        rx.icon(tag="bug", size=12),
                        bug,
                        color_scheme="red",
                        variant="soft",
                        size="1",
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                justify="center",
            ),
            content=rx.cond(reason != "", reason, status),
        ),
        text_align="center",
        padding_y="0.5rem",
    )


def _summary_card(label: str, value, color: str, icon: str) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.icon(tag=icon, size=26, color=color),
            rx.vstack(
                rx.text(label, font_size="0.75rem", color="#64748B", font_weight="600"),
                rx.heading(value, size="6", color="#0F172A"),
                spacing="0",
                align="start",
            ),
            spacing="3",
            align="center",
        ),
        padding="1rem 1.25rem",
        background="white",
        border="1px solid #E2E8F0",
        border_radius="0.75rem",
        flex="1",
    )


def _row(model: str) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.text(model, font_family="monospace", font_size="0.85rem", color="#0F172A"),
            padding_y="0.5rem",
        ),
        _cell(model, "trtllm"),
        _cell(model, "vllm"),
        _cell(model, "sglang"),
        rx.table.cell(
            rx.tooltip(
                rx.button(
                    rx.icon(tag="trash_2", size=14),
                    on_click=MatrixState.open_delete_dialog(model),
                    variant="ghost",
                    color_scheme="red",
                    size="1",
                ),
                content="Delete this row (current release filter)",
            ),
            text_align="center",
            padding_y="0.5rem",
        ),
    )


def _delete_dialog() -> rx.Component:
    """Confirm dialog for delete-model action."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.heading("Delete matrix rows?", size="4", color="#0F172A"),
                rx.text(
                    "About to delete ",
                    rx.text.strong(MatrixState.delete_count_estimate.to_string()),
                    " row(s) for ",
                    rx.code(MatrixState.delete_model, font_size="0.85rem"),
                    rx.cond(
                        MatrixState.release_filter == "__ALL__",
                        rx.text(" across ALL releases.", as_="span"),
                        rx.cond(
                            MatrixState.delete_release == "",
                            rx.text(" in rows with no release tag.", as_="span"),
                            rx.fragment(),
                        ),
                    ),
                    rx.cond(
                        (MatrixState.release_filter != "__ALL__")
                        & (MatrixState.delete_release != ""),
                        rx.text(
                            " in release ",
                            rx.code(MatrixState.delete_release, font_size="0.85rem"),
                            ".",
                            as_="span",
                        ),
                        rx.fragment(),
                    ),
                    color="#0F172A",
                    font_size="0.9rem",
                ),
                rx.callout(
                    "This cannot be undone. The .out files on disk are NOT touched.",
                    icon="triangle_alert",
                    color_scheme="orange",
                ),
                rx.hstack(
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button(
                            "Cancel",
                            on_click=MatrixState.close_delete_dialog,
                            variant="soft",
                        ),
                    ),
                    rx.button(
                        rx.hstack(
                            rx.icon(tag="trash_2", size=14),
                            rx.text("Delete"),
                            spacing="1",
                            align="center",
                        ),
                        on_click=MatrixState.confirm_delete,
                        color_scheme="red",
                        size="2",
                    ),
                    spacing="2",
                    width="100%",
                ),
                spacing="3",
                align="stretch",
            ),
            max_width="500px",
            width="92vw",
        ),
        open=MatrixState.delete_open,
        on_open_change=MatrixState.close_delete_dialog,
    )


def matrix_page() -> rx.Component:
    body = rx.vstack(
        rx.hstack(
            rx.vstack(
                rx.heading("HF Model Test Matrix", size="7", color="#0F172A"),
                rx.text(
                    "Each model × backend cell shows the latest test verdict. Hover for the AI-derived reason.",
                    color="#64748B",
                    font_size="0.9rem",
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.button(
                rx.icon(tag="refresh_cw", size=16),
                "Refresh",
                on_click=MatrixState.refresh,
                variant="soft",
            ),
            width="100%",
            align="center",
        ),
        rx.hstack(
            _summary_card("Total tests", MatrixState.total, "#475569", "list"),
            _summary_card("Passed", MatrixState.passed, STATUS_ICONS["passed"][1], "circle_check"),
            _summary_card("Failed", MatrixState.failed, STATUS_ICONS["failed"][1], "circle_x"),
            _summary_card("Pending", MatrixState.pending, STATUS_ICONS["pending"][1], "circle_help"),
            spacing="3",
            width="100%",
        ),
        rx.hstack(
            rx.vstack(
                rx.text(
                    "RELEASE",
                    font_size="0.68rem",
                    font_weight="700",
                    color="#94A3B8",
                    letter_spacing="0.08em",
                ),
                rx.select(
                    MatrixState.release_options,
                    value=MatrixState.release_filter_label,
                    on_change=MatrixState.select_release_by_label,
                    width="240px",
                ),
                spacing="1",
                align="start",
            ),
            rx.vstack(
                rx.text(
                    "MODEL FILTER",
                    font_size="0.68rem",
                    font_weight="700",
                    color="#94A3B8",
                    letter_spacing="0.08em",
                ),
                rx.input(
                    placeholder="Filter models…",
                    value=MatrixState.filter_text,
                    on_change=MatrixState.set_filter_text,
                    width="320px",
                ),
                spacing="1",
                align="start",
            ),
            spacing="4",
            align="end",
        ),
        rx.box(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell(
                            rx.text("Model", font_weight="700", font_size="0.85rem", color="#0F172A"),
                            padding_y="0.75rem",
                        ),
                        _backend_header("trtllm"),
                        _backend_header("vllm"),
                        _backend_header("sglang"),
                        rx.table.column_header_cell(
                            rx.text("", font_weight="700"),
                            text_align="center",
                            width="64px",
                        ),
                    ),
                ),
                rx.table.body(
                    rx.foreach(MatrixState.visible_models, _row),
                ),
                variant="surface",
                size="2",
            ),
            background="white",
            border="1px solid #E2E8F0",
            border_radius="0.75rem",
            padding="0.5rem",
            width="100%",
        ),
        rx.cond(
            MatrixState.total == 0,
            rx.callout(
                "No tests yet for this release filter. Use the AI Analyzer to add results, "
                "or pick a different release in the dropdown above.",
                icon="info",
                color_scheme="blue",
            ),
            rx.fragment(),
        ),
        _delete_dialog(),
        spacing="4",
        align="stretch",
        width="100%",
        max_width="1200px",
        on_mount=MatrixState.load,
    )
    return page_shell(body)
