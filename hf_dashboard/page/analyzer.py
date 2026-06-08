"""AI Analyzer page.

User pastes a .out path -> Claude extracts environment + every model under
test -> dashboard shows one card per model with verdict, reason, and a
sample of the model's normal output -> user picks which rows to save into
the matrix DB.
"""
from __future__ import annotations

import reflex as rx

from hf_dashboard.components.navbar import page_shell
from hf_dashboard.data.analyzer_state import AnalyzerState
from hf_dashboard.data.common import BACKEND_COLORS, STATUS_ICONS


# Verdict -> (icon, color, badge color scheme)
_VERDICT_VISUAL = {
    "passed":       ("circle_check",   STATUS_ICONS["passed"][1],  "green"),
    "failed":       ("circle_x",       STATUS_ICONS["failed"][1],  "red"),
    "inconclusive": ("triangle_alert", STATUS_ICONS["broken"][1],  "orange"),
}


# ---------------------------------------------------------------------------
# Top input panel: just the .out path
# ---------------------------------------------------------------------------

def _input_panel() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon(tag="file_text", size=22, color="#475569"),
                rx.heading("Job log", size="4", color="#0F172A"),
                spacing="2",
                align="center",
            ),
            rx.text(
                "Enter a slurm job ID (e.g. ",
                rx.code("191"),
                ") and we'll find its `.out` file automatically. ",
                "You can also paste a full path if it lives elsewhere.",
                color="#64748B",
                font_size="0.85rem",
            ),
            rx.input(
                placeholder="Job ID (e.g. 191) — or a full .out path",
                value=AnalyzerState.job_input,
                on_change=AnalyzerState.set_job_input,
                font_family="monospace",
                font_size="0.92rem",
                width="100%",
            ),
            # Resolved path / error display
            rx.cond(
                AnalyzerState.resolved_path != "",
                rx.hstack(
                    rx.icon(tag="circle_check", size=14, color="#059669"),
                    rx.text(
                        "Resolved to: ",
                        font_size="0.75rem",
                        color="#64748B",
                    ),
                    rx.text(
                        AnalyzerState.resolved_path,
                        font_family="monospace",
                        font_size="0.75rem",
                        color="#0F172A",
                    ),
                    spacing="1",
                    align="center",
                ),
                rx.cond(
                    AnalyzerState.resolve_error != "",
                    rx.hstack(
                        rx.icon(tag="circle_alert", size=14, color="#DC2626"),
                        rx.text(
                            AnalyzerState.resolve_error,
                            font_size="0.78rem",
                            color="#DC2626",
                        ),
                        spacing="1",
                        align="center",
                    ),
                    rx.fragment(),
                ),
            ),
            rx.text(
                f"Default slurm root: {AnalyzerState.slurm_root}",
                font_size="0.7rem",
                color="#94A3B8",
            ),
            rx.hstack(
                rx.button(
                    rx.cond(
                        AnalyzerState.is_running,
                        rx.hstack(
                            rx.spinner(size="1"),
                            rx.text("Analyzing…"),
                            spacing="2",
                            align="center",
                        ),
                        rx.hstack(
                            rx.icon(tag="sparkles", size=16),
                            rx.text("Run AI analysis"),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    on_click=AnalyzerState.analyze,
                    disabled=AnalyzerState.is_running,
                    color_scheme="green",
                    size="3",
                ),
                rx.cond(
                    AnalyzerState.saved_rows_count_for_path > 0,
                    rx.button(
                        rx.hstack(
                            rx.icon(tag="database", size=16),
                            rx.text(
                                f"Load {AnalyzerState.saved_rows_count_for_path} saved rows"
                            ),
                            spacing="2",
                            align="center",
                        ),
                        on_click=AnalyzerState.load_saved_for_path,
                        disabled=AnalyzerState.is_running,
                        variant="soft",
                        color_scheme="blue",
                        size="3",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    AnalyzerState.log_size_human != "",
                    rx.text(
                        f"Log size: {AnalyzerState.log_size_human}",
                        font_size="0.78rem",
                        color="#94A3B8",
                    ),
                    rx.fragment(),
                ),
                spacing="3",
                align="center",
                flex_wrap="wrap",
            ),
            rx.cond(
                AnalyzerState.progress_message != "",
                rx.hstack(
                    rx.spinner(size="1"),
                    rx.text(
                        AnalyzerState.progress_message,
                        color="#0F172A",
                        font_size="0.85rem",
                    ),
                    spacing="2",
                    align="center",
                    padding="0.6rem 0.85rem",
                    background="#EFF6FF",
                    border="1px solid #BFDBFE",
                    border_radius="0.5rem",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.cond(
                AnalyzerState.error_message != "",
                rx.callout(
                    AnalyzerState.error_message,
                    icon="circle_alert",
                    color_scheme="red",
                ),
                rx.fragment(),
            ),
            spacing="3",
            align="stretch",
            width="100%",
        ),
        background="white",
        border="1px solid #E2E8F0",
        border_radius="0.75rem",
        padding="1.5rem",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Environment card
# ---------------------------------------------------------------------------

def _env_chip(label: str, value, color: str = "#475569") -> rx.Component:
    return rx.cond(
        value != "",
        rx.hstack(
            rx.text(label, font_size="0.7rem", font_weight="700",
                    color="#94A3B8", letter_spacing="0.05em"),
            rx.text(value, font_size="0.88rem", font_weight="600", color=color),
            spacing="2",
            align="center",
        ),
        rx.fragment(),
    )


def _backend_badge(backend) -> rx.Component:
    return rx.match(
        backend,
        ("trtllm", rx.badge("TRTLLM", color_scheme="indigo", variant="soft", size="2")),
        ("vllm",   rx.badge("VLLM",   color_scheme="orange", variant="soft", size="2")),
        ("sglang", rx.badge("SGLANG", color_scheme="green",  variant="soft", size="2")),
        rx.badge("UNKNOWN", color_scheme="gray", variant="soft", size="2"),
    )


def _environment_panel() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon(tag="server", size=20, color="#475569"),
                rx.heading("Environment", size="4", color="#0F172A"),
                rx.spacer(),
                rx.cond(
                    AnalyzerState.loaded_from_db,
                    rx.badge(
                        rx.hstack(
                            rx.icon(tag="database", size=12),
                            rx.text("from DB cache"),
                            spacing="1",
                            align="center",
                        ),
                        color_scheme="blue", variant="soft", size="1",
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # Row 1: backend + backend version + GPU + GPU count
            rx.hstack(
                _backend_badge(AnalyzerState.env_backend),
                rx.cond(
                    AnalyzerState.env_backend_version != "",
                    rx.badge(
                        f"v{AnalyzerState.env_backend_version}",
                        color_scheme="indigo", variant="outline", size="2",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    AnalyzerState.env_gpu != "",
                    rx.badge(
                        rx.hstack(
                            rx.icon(tag="cpu", size=12),
                            rx.text(AnalyzerState.env_gpu),
                            spacing="1",
                            align="center",
                        ),
                        color_scheme="cyan", variant="soft", size="2",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    AnalyzerState.env_gpu_count > 0,
                    rx.badge(
                        f"x{AnalyzerState.env_gpu_count}",
                        color_scheme="gray", variant="soft", size="2",
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            # Row 2: chip details — container, driver, cuda, node, job
            rx.hstack(
                _env_chip("DOCKER",  AnalyzerState.env_docker_image),
                _env_chip("CONTAINER", AnalyzerState.env_container_id),
                spacing="5",
                flex_wrap="wrap",
            ),
            rx.hstack(
                _env_chip("DRIVER",  AnalyzerState.env_driver_version),
                _env_chip("CUDA",    AnalyzerState.env_cuda_version),
                _env_chip("NODE",    AnalyzerState.env_node),
                _env_chip("JOB ID",  AnalyzerState.env_job_id),
                spacing="5",
                flex_wrap="wrap",
            ),
            _env_chip("NOTES", AnalyzerState.env_extra_notes),
            rx.cond(
                AnalyzerState.summary != "",
                rx.box(
                    rx.text(AnalyzerState.summary, color="#0F172A",
                            font_size="0.88rem", line_height="1.5"),
                    padding="0.75rem 1rem",
                    background="#F8FAFC",
                    border_left="3px solid #76B900",
                    border_radius="0.4rem",
                    width="100%",
                ),
                rx.fragment(),
            ),
            spacing="3",
            align="stretch",
            width="100%",
        ),
        background="white",
        border="1px solid #E2E8F0",
        border_radius="0.75rem",
        padding="1.5rem",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Per-model result card
# ---------------------------------------------------------------------------

def _verdict_visual(verdict, kind: str):
    """Return the right icon / color / scheme / bg / label based on the verdict var."""
    if kind == "icon":
        return rx.match(verdict,
            ("passed",       "circle_check"),
            ("failed",       "circle_x"),
            ("inconclusive", "triangle_alert"),
            "circle_help",
        )
    if kind == "color":
        return rx.match(verdict,
            ("passed",       _VERDICT_VISUAL["passed"][1]),
            ("failed",       _VERDICT_VISUAL["failed"][1]),
            ("inconclusive", _VERDICT_VISUAL["inconclusive"][1]),
            "#94A3B8",
        )
    if kind == "scheme":
        return rx.match(verdict,
            ("passed",       "green"),
            ("failed",       "red"),
            ("inconclusive", "orange"),
            "gray",
        )
    if kind == "preview_bg":
        # Tinted backgrounds for the output / error preview box.
        return rx.match(verdict,
            ("passed",       "#F0FDF4"),  # green-50
            ("failed",       "#FEF2F2"),  # red-50
            ("inconclusive", "#FFF7ED"),  # orange-50
            "#F8FAFC",                    # slate-50
        )
    if kind == "preview_label":
        return rx.match(verdict,
            ("passed",       "OUTPUT PREVIEW"),
            ("failed",       "ERROR EVIDENCE"),
            ("inconclusive", "LOG EXCERPT"),
            "OUTPUT PREVIEW",
        )


def _result_card(item, index) -> rx.Component:
    """Render one model result. `item` is a Var pointing at a ResultItem row."""
    icon = _verdict_visual(item.verdict, "icon")
    color = _verdict_visual(item.verdict, "color")
    scheme = _verdict_visual(item.verdict, "scheme")

    return rx.box(
        rx.vstack(
            # Header row: checkbox + icon + model name + verdict badge + details button
            rx.hstack(
                rx.checkbox(
                    checked=item.selected,
                    on_change=AnalyzerState.toggle_selected(index),
                    size="2",
                ),
                rx.icon(tag=icon, size=24, color=color),
                rx.text(
                    item.model_name,
                    font_family="monospace",
                    font_weight="700",
                    font_size="0.92rem",
                    color="#0F172A",
                    flex="1",
                ),
                rx.badge(
                    item.verdict_upper,
                    color_scheme=scheme,
                    variant="solid",
                    size="2",
                ),
                rx.cond(
                    item.error_type != "",
                    rx.badge(
                        item.error_type,
                        color_scheme="red",
                        variant="soft",
                        size="1",
                    ),
                    rx.fragment(),
                ),
                rx.button(
                    rx.hstack(
                        rx.icon(tag="search", size=14),
                        rx.text("Details"),
                        spacing="1",
                        align="center",
                    ),
                    on_click=AnalyzerState.open_detail(index),
                    variant="soft",
                    size="1",
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            # Reason
            rx.text(
                item.reason,
                font_size="0.85rem",
                color="#475569",
                line_height="1.5",
            ),
            # Sample output preview (clamped to ~4 lines; full content lives in the dialog).
            # Color follows the verdict: green for passed, red for failed, orange for inconclusive.
            rx.cond(
                item.sample_output != "",
                rx.box(
                    rx.vstack(
                        rx.text(
                            _verdict_visual(item.verdict, "preview_label"),
                            font_size="0.68rem",
                            font_weight="700",
                            color="#94A3B8",
                            letter_spacing="0.08em",
                        ),
                        rx.text(
                            item.sample_output,
                            font_family="monospace",
                            font_size="0.78rem",
                            color="#0F172A",
                            white_space="pre-wrap",
                            display="-webkit-box",
                            style={
                                "-webkit-line-clamp": "4",
                                "-webkit-box-orient": "vertical",
                                "overflow": "hidden",
                            },
                        ),
                        spacing="1",
                        align="start",
                        width="100%",
                    ),
                    padding="0.65rem 0.85rem",
                    background=_verdict_visual(item.verdict, "preview_bg"),
                    border_left="3px solid",
                    border_left_color=color,
                    border_radius="0.4rem",
                    width="100%",
                ),
                rx.fragment(),
            ),
            spacing="3",
            align="stretch",
            width="100%",
        ),
        background="white",
        border="1px solid #E2E8F0",
        border_left_width="4px",
        border_left_color=color,
        border_radius="0.6rem",
        padding="1.1rem 1.25rem",
        width="100%",
    )


def _details_dialog() -> rx.Component:
    """Modal showing the full reason + complete output / error for one row."""
    verdict_color = rx.match(
        AnalyzerState.detail_verdict,
        ("passed",       _VERDICT_VISUAL["passed"][1]),
        ("failed",       _VERDICT_VISUAL["failed"][1]),
        ("inconclusive", _VERDICT_VISUAL["inconclusive"][1]),
        "#94A3B8",
    )
    verdict_scheme = rx.match(
        AnalyzerState.detail_verdict,
        ("passed",       "green"),
        ("failed",       "red"),
        ("inconclusive", "orange"),
        "gray",
    )
    evidence_bg = rx.match(
        AnalyzerState.detail_verdict,
        ("passed",       "#F0FDF4"),
        ("failed",       "#FEF2F2"),
        ("inconclusive", "#FFF7ED"),
        "#F8FAFC",
    )
    evidence_border = rx.match(
        AnalyzerState.detail_verdict,
        ("passed",       "#BBF7D0"),
        ("failed",       "#FECACA"),
        ("inconclusive", "#FED7AA"),
        "#E2E8F0",
    )
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.hstack(
                    rx.text(
                        AnalyzerState.detail_model_name,
                        font_family="monospace",
                        font_weight="700",
                        font_size="1rem",
                        color="#0F172A",
                        flex="1",
                    ),
                    rx.badge(
                        AnalyzerState.detail_verdict_upper,
                        color_scheme=verdict_scheme,
                        variant="solid",
                        size="2",
                    ),
                    rx.cond(
                        AnalyzerState.detail_error_type != "",
                        rx.badge(
                            AnalyzerState.detail_error_type,
                            color_scheme="red",
                            variant="soft",
                            size="1",
                        ),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                rx.divider(),
                rx.text("REASON", font_size="0.7rem", font_weight="700",
                        color="#94A3B8", letter_spacing="0.08em"),
                rx.box(
                    rx.text(AnalyzerState.detail_reason, color="#0F172A",
                            font_size="0.9rem", line_height="1.5"),
                    padding="0.75rem 1rem",
                    background="#F8FAFC",
                    border_left="3px solid",
                    border_left_color=verdict_color,
                    border_radius="0.4rem",
                    width="100%",
                ),
                rx.cond(
                    AnalyzerState.detail_sample_output != "",
                    rx.vstack(
                        rx.text(
                            rx.cond(
                                AnalyzerState.detail_verdict == "failed",
                                "ERROR EVIDENCE FROM LOG",
                                "ALL PROMPTS & GENERATED TEXT",
                            ),
                            font_size="0.7rem", font_weight="700",
                            color="#94A3B8", letter_spacing="0.08em",
                        ),
                        rx.box(
                            rx.text(
                                AnalyzerState.detail_sample_output,
                                font_family="monospace",
                                font_size="0.78rem",
                                color="#0F172A",
                                white_space="pre-wrap",
                            ),
                            padding="0.75rem 1rem",
                            background=evidence_bg,
                            border="1px solid",
                            border_color=evidence_border,
                            border_left="3px solid",
                            border_left_color=verdict_color,
                            border_radius="0.4rem",
                            width="100%",
                            max_height="55vh",
                            overflow_y="auto",
                        ),
                        spacing="1",
                        align="stretch",
                        width="100%",
                    ),
                    rx.fragment(),
                ),
                rx.hstack(
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button("Close", on_click=AnalyzerState.close_detail,
                                  variant="soft"),
                    ),
                    width="100%",
                ),
                spacing="3",
                align="stretch",
            ),
            max_width="900px",
            width="90vw",
        ),
        open=AnalyzerState.detail_open,
        on_open_change=AnalyzerState.close_detail,
    )


# ---------------------------------------------------------------------------
# Results panel (env card + counters + per-model cards + bulk save)
# ---------------------------------------------------------------------------

def _summary_pill(label: str, value, color: str, icon: str,
                  filter_key: str = "") -> rx.Component:
    """Summary pill. If filter_key is given, clicking it toggles the verdict filter."""
    is_active = AnalyzerState.verdict_filter == filter_key
    return rx.box(
        rx.hstack(
            rx.icon(tag=icon, size=18, color=color),
            rx.text(label, font_size="0.78rem", color="#475569", font_weight="600"),
            rx.text(value, font_size="1rem", color="#0F172A", font_weight="700"),
            spacing="2",
            align="center",
        ),
        on_click=AnalyzerState.set_verdict_filter(filter_key) if filter_key else None,
        cursor=rx.cond(filter_key != "", "pointer", "default"),
        padding="0.4rem 0.7rem",
        border_radius="0.5rem",
        border=rx.cond(
            is_active,
            f"2px solid {color}",
            "2px solid transparent",
        ),
        background=rx.cond(is_active, f"{color}14", "transparent"),
        transition="background 120ms ease, border-color 120ms ease",
        _hover=rx.cond(
            filter_key != "",
            {"background": "#F1F5F9"},
            {},
        ),
    )


def _jenkins_param_row(p) -> rx.Component:
    return rx.hstack(
        rx.text(
            p.name,
            font_family="monospace",
            font_size="0.78rem",
            font_weight="700",
            color="#475569",
            min_width="180px",
            max_width="240px",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.text(
            p.value,
            font_family="monospace",
            font_size="0.78rem",
            color="#0F172A",
            flex="1",
            white_space="pre-wrap",
            word_break="break-all",
        ),
        spacing="3",
        align="start",
        width="100%",
        padding_y="0.25rem",
    )


def _jenkins_result_badge() -> rx.Component:
    """Color-coded badge for the build's overall result."""
    return rx.cond(
        AnalyzerState.jenkins_building,
        rx.badge(
            rx.hstack(
                rx.spinner(size="1"),
                rx.text("BUILDING"),
                spacing="1",
                align="center",
            ),
            color_scheme="blue", variant="soft", size="2",
        ),
        rx.match(
            AnalyzerState.jenkins_result,
            ("SUCCESS",  rx.badge("SUCCESS",  color_scheme="green",  variant="solid", size="2")),
            ("FAILURE",  rx.badge("FAILURE",  color_scheme="red",    variant="solid", size="2")),
            ("UNSTABLE", rx.badge("UNSTABLE", color_scheme="orange", variant="solid", size="2")),
            ("ABORTED",  rx.badge("ABORTED",  color_scheme="gray",   variant="solid", size="2")),
            rx.fragment(),
        ),
    )


def _jenkins_panel() -> rx.Component:
    """Section showing Jenkins build info + parameters + jump-link."""
    return rx.cond(
        AnalyzerState.jenkins_url != "",
        # ── Have build info: show full panel.
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.icon(tag="git_branch", size=20, color="#475569"),
                    rx.heading("Jenkins build", size="4", color="#0F172A"),
                    _jenkins_result_badge(),
                    rx.cond(
                        AnalyzerState.jenkins_triggered_by != "",
                        rx.badge(
                            "by " + AnalyzerState.jenkins_triggered_by,
                            color_scheme="gray", variant="soft", size="1",
                        ),
                        rx.fragment(),
                    ),
                    rx.spacer(),
                    rx.link(
                        rx.button(
                            rx.hstack(
                                rx.icon(tag="external_link", size=14),
                                rx.text(
                                    AnalyzerState.jenkins_job_name
                                    + " "
                                    + AnalyzerState.jenkins_display_name
                                ),
                                spacing="1",
                                align="center",
                            ),
                            variant="soft", color_scheme="blue", size="2",
                        ),
                        href=AnalyzerState.jenkins_url,
                        is_external=True,
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                rx.cond(
                    AnalyzerState.jenkins_started_at != "",
                    rx.text(
                        "Started " + AnalyzerState.jenkins_started_at,
                        font_size="0.78rem",
                        color="#94A3B8",
                    ),
                    rx.fragment(),
                ),
                rx.divider(),
                rx.cond(
                    AnalyzerState.jenkins_params.length() == 0,
                    rx.text(
                        "Build has no parameters.",
                        font_size="0.85rem", color="#94A3B8",
                    ),
                    rx.vstack(
                        rx.text(
                            "BUILD PARAMETERS",
                            font_size="0.68rem",
                            font_weight="700",
                            color="#94A3B8",
                            letter_spacing="0.08em",
                        ),
                        rx.box(
                            rx.foreach(AnalyzerState.jenkins_params, _jenkins_param_row),
                            background="#F8FAFC",
                            border="1px solid #E2E8F0",
                            border_radius="0.4rem",
                            padding="0.65rem 0.85rem",
                            width="100%",
                        ),
                        spacing="1",
                        align="stretch",
                        width="100%",
                    ),
                ),
                spacing="3",
                align="stretch",
                width="100%",
            ),
            background="white",
            border="1px solid #E2E8F0",
            border_radius="0.75rem",
            padding="1.5rem",
            width="100%",
        ),
        # ── No Jenkins info: show appropriate hint.
        rx.cond(
            AnalyzerState.jenkins_error != "",
            rx.callout(
                "Jenkins lookup failed: " + AnalyzerState.jenkins_error,
                icon="circle_alert",
                color_scheme="orange",
            ),
            rx.cond(
                ~AnalyzerState.jenkins_configured,
                rx.callout(
                    "Add JENKINS_BASE_URL / JENKINS_USER / JENKINS_TOKEN to "
                    "~/.hf_dashboard/env to see build parameters and a jump-link here.",
                    icon="info",
                    color_scheme="gray",
                ),
                rx.fragment(),
            ),
        ),
    )


def _results_panel() -> rx.Component:
    return rx.cond(
        AnalyzerState.has_results,
        rx.vstack(
            _environment_panel(),
            rx.box(
                rx.hstack(
                    rx.heading("Models found in log", size="4", color="#0F172A"),
                    rx.spacer(),
                    _summary_pill("all", AnalyzerState.results.length(),
                                  "#475569", "list", filter_key="all"),
                    _summary_pill("passed", AnalyzerState.passed_count,
                                  STATUS_ICONS["passed"][1], "circle_check",
                                  filter_key="passed"),
                    _summary_pill("failed", AnalyzerState.failed_count,
                                  STATUS_ICONS["failed"][1], "circle_x",
                                  filter_key="failed"),
                    _summary_pill("inconclusive", AnalyzerState.inconclusive_count,
                                  STATUS_ICONS["broken"][1], "triangle_alert",
                                  filter_key="inconclusive"),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                rx.foreach(
                    AnalyzerState.visible_results,
                    lambda item, _idx: _result_card(item, item.original_index),
                ),
                rx.cond(
                    AnalyzerState.save_status_message != "",
                    rx.callout(
                        AnalyzerState.save_status_message,
                        icon=rx.cond(
                            AnalyzerState.save_status_kind == "success",
                            "circle_check",
                            "circle_alert",
                        ),
                        color_scheme=rx.cond(
                            AnalyzerState.save_status_kind == "success",
                            "green",
                            "red",
                        ),
                    ),
                    rx.fragment(),
                ),
                rx.hstack(
                    rx.vstack(
                        rx.text(
                            "RELEASE / MODELOPT VERSION",
                            font_size="0.68rem",
                            font_weight="700",
                            color="#94A3B8",
                            letter_spacing="0.08em",
                        ),
                        rx.input(
                            placeholder="e.g. 0.44.0rc2 (auto-filled from Jenkins)",
                            value=AnalyzerState.save_release_version,
                            on_change=AnalyzerState.set_save_release_version,
                            font_family="monospace",
                            width="280px",
                        ),
                        spacing="1",
                        align="start",
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.hstack(
                            rx.icon(tag="database", size=16),
                            rx.text("Save selected to matrix"),
                            spacing="2",
                            align="center",
                        ),
                        on_click=AnalyzerState.save_selected,
                        color_scheme="green",
                        size="3",
                    ),
                    spacing="3",
                    align="end",
                    width="100%",
                ),
                background="white",
                border="1px solid #E2E8F0",
                border_radius="0.75rem",
                padding="1.5rem",
                width="100%",
                # vstack inside via display flex column gap
                display="flex",
                flex_direction="column",
                row_gap="1rem",
            ),
            spacing="4",
            width="100%",
        ),
        rx.box(
            rx.vstack(
                rx.icon(tag="info", size=32, color="#94A3B8"),
                rx.text(
                    "Paste a .out file path above and click \"Run AI analysis\".",
                    color="#64748B",
                    font_size="0.9rem",
                ),
                rx.text(
                    "Claude will detect the backend, GPU, and every model tested in the log, "
                    "then judge pass / fail for each — no need to fill anything else.",
                    color="#94A3B8",
                    font_size="0.82rem",
                    text_align="center",
                    max_width="560px",
                ),
                spacing="3",
                align="center",
            ),
            background="white",
            border="1px dashed #CBD5E1",
            border_radius="0.75rem",
            padding="3rem 1.5rem",
            width="100%",
            text_align="center",
        ),
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def analyzer_page() -> rx.Component:
    body = rx.vstack(
        rx.vstack(
            rx.heading("AI Result Analyzer", size="7", color="#0F172A"),
            rx.text(
                "Drop in a slurm .out file. Claude extracts the environment and every "
                "model tested, judges pass / fail per model, and lets you save the rows "
                "to the test matrix in one click.",
                color="#64748B",
                font_size="0.92rem",
                max_width="780px",
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        _input_panel(),
        _jenkins_panel(),
        _results_panel(),
        _details_dialog(),
        spacing="4",
        align="stretch",
        width="100%",
        max_width="1100px",
        on_mount=AnalyzerState.on_load,
    )
    return page_shell(body)
