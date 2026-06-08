"""Trigger Build page.

Renders the parameter form for the `sirui_test_hf` Jenkins job. After Build
is clicked we POST to Jenkins, persist a row in `jenkins_runs`, and let the
background watcher take over (see services/runs_watcher.py).
"""
from __future__ import annotations

import reflex as rx

from hf_dashboard.components.navbar import page_shell
from hf_dashboard.data.trigger_state import TriggerState


def _field(label: str, control: rx.Component, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, font_size="0.78rem", font_weight="700", color="#475569"),
        control,
        rx.cond(hint != "",
                rx.text(hint, font_size="0.72rem", color="#94A3B8"),
                rx.fragment()),
        spacing="1",
        align="stretch",
        width="100%",
    )


def _section(title: str, *children) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.heading(title, size="4", color="#0F172A"),
            *children,
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


def _checkbox(label: str, checked, on_change) -> rx.Component:
    return rx.hstack(
        rx.checkbox(checked=checked, on_change=on_change, size="2"),
        rx.text(label, font_size="0.85rem", color="#0F172A", font_weight="600"),
        spacing="2",
        align="center",
    )


def trigger_page() -> rx.Component:
    body = rx.vstack(
        rx.vstack(
            rx.heading("Trigger test build", size="7", color="#0F172A"),
            rx.text(
                "Submit the sirui_test_hf Jenkins job with these parameters. ",
                "After it's queued, head over to the Runs page — the dashboard ",
                "will auto-poll Jenkins, pull the .out log when done, and write ",
                "results to the matrix tagged with the modelopt_version.",
                color="#64748B",
                font_size="0.92rem",
                max_width="780px",
            ),
            spacing="1",
            align="start",
            width="100%",
        ),

        _section(
            "Branch & versions",
            rx.grid(
                _field(
                    "modelopt_repo_owner",
                    rx.select(
                        TriggerState.repo_owner_options,
                        value=TriggerState.modelopt_repo_owner,
                        on_change=TriggerState.set_modelopt_repo_owner,
                        width="100%",
                    ),
                ),
                _field(
                    "test_branch",
                    rx.select(
                        TriggerState.test_branch_options,
                        value=TriggerState.test_branch,
                        on_change=TriggerState.set_test_branch,
                        width="100%",
                    ),
                    hint=("Branch of the modelopt-qa-scripts repo (Jenkinsfile + helpers). "
                          "Usually `main`. NOT the same as modelopt_branch."),
                ),
                _field(
                    "modelopt_version  *",
                    rx.input(
                        placeholder="e.g. 0.44.0rc2",
                        value=TriggerState.modelopt_version,
                        on_change=TriggerState.set_modelopt_version,
                        font_family="monospace",
                    ),
                    hint="Used as release_version when results are saved to the matrix",
                ),
                _field(
                    "baseline_modelopt",
                    rx.input(
                        value=TriggerState.baseline_modelopt,
                        on_change=TriggerState.set_baseline_modelopt,
                        font_family="monospace",
                    ),
                ),
                _field(
                    "modelopt_branch",
                    rx.select(
                        TriggerState.modelopt_branch_options,
                        value=TriggerState.modelopt_branch,
                        on_change=TriggerState.set_modelopt_branch,
                        width="100%",
                    ),
                    hint=("Branch of <owner>/Model-Optimizer to test. "
                          "Empty = use modelopt_version tag. "
                          "`auto/add-cases` is the dashboard's auto-cases branch."),
                ),
                _field(
                    "docker_image",
                    rx.vstack(
                        rx.input(
                            placeholder="nvcr.io/nvidia/...",
                            value=TriggerState.docker_image,
                            on_change=TriggerState.set_docker_image,
                            font_family="monospace",
                            width="100%",
                        ),
                        rx.hstack(
                            rx.foreach(
                                TriggerState.docker_image_options,
                                lambda opt: rx.button(
                                    opt,
                                    on_click=TriggerState.set_docker_image(opt),
                                    variant="soft",
                                    color_scheme="gray",
                                    size="1",
                                    font_family="monospace",
                                    font_size="0.7rem",
                                ),
                            ),
                            spacing="1",
                            flex_wrap="wrap",
                            width="100%",
                        ),
                        spacing="1",
                        align="stretch",
                        width="100%",
                    ),
                    hint="Type any image, or click a chip to fill a common preset.",
                ),
                columns="2", spacing="4", width="100%",
            ),
        ),

        _section(
            "Test selection",
            rx.grid(
                _field(
                    "test_suites",
                    rx.input(
                        value=TriggerState.test_suites,
                        on_change=TriggerState.set_test_suites,
                        font_family="monospace",
                    ),
                    hint="Comma-separated. Usually just `deploy_hf`.",
                ),
                _field(
                    "pattern  (pytest -k filter)",
                    rx.input(
                        placeholder="e.g. test_kimi or test_qwen",
                        value=TriggerState.pattern,
                        on_change=TriggerState.set_pattern,
                        font_family="monospace",
                    ),
                    hint="Empty = run all parametrized cases in the selected suites.",
                ),
                _field(
                    "test_level",
                    rx.input(
                        placeholder="(empty = long_running)",
                        value=TriggerState.test_level,
                        on_change=TriggerState.set_test_level,
                        font_family="monospace",
                    ),
                ),
                _field(
                    "start_from",
                    rx.input(
                        placeholder="(empty)",
                        value=TriggerState.start_from,
                        on_change=TriggerState.set_start_from,
                        font_family="monospace",
                    ),
                ),
                _field(
                    "random_sample_percent",
                    rx.input(
                        type="number",
                        value=TriggerState.random_sample_percent.to_string(),
                        on_change=TriggerState.set_random_sample_percent,
                    ),
                    hint="0 = no sampling, run all matched cases.",
                ),
                _field(
                    "user_flags",
                    rx.input(
                        placeholder="key1=v1,key2=v2",
                        value=TriggerState.user_flags,
                        on_change=TriggerState.set_user_flags,
                        font_family="monospace",
                    ),
                ),
                columns="2", spacing="4", width="100%",
            ),
        ),

        _section(
            "Hardware",
            rx.grid(
                _field(
                    "node",
                    rx.input(
                        value=TriggerState.node,
                        on_change=TriggerState.set_node,
                        font_family="monospace",
                    ),
                ),
                _field(
                    "gpu_type",
                    rx.input(
                        placeholder="e.g. spark",
                        value=TriggerState.gpu_type,
                        on_change=TriggerState.set_gpu_type,
                        font_family="monospace",
                    ),
                ),
                _field(
                    "non_slurm_gpu_devices",
                    rx.input(
                        placeholder="e.g. 0,1",
                        value=TriggerState.non_slurm_gpu_devices,
                        on_change=TriggerState.set_non_slurm_gpu_devices,
                        font_family="monospace",
                    ),
                ),
                _field(
                    "model_dir",
                    rx.input(
                        value=TriggerState.model_dir,
                        on_change=TriggerState.set_model_dir,
                        font_family="monospace",
                    ),
                ),
                columns="2", spacing="4", width="100%",
            ),
            _field(
                "slurm",
                rx.text_area(
                    value=TriggerState.slurm,
                    on_change=TriggerState.set_slurm,
                    font_family="monospace",
                    font_size="0.78rem",
                    rows="8",
                    width="100%",
                ),
                hint="Raw JSON object passed straight to the Jenkins job.",
            ),
        ),

        _section(
            "Misc / flags",
            rx.hstack(
                _checkbox("save_results",          TriggerState.save_results,          TriggerState.toggle_save_results),
                _checkbox("enable_trtbot",         TriggerState.enable_trtbot,         TriggerState.toggle_enable_trtbot),
                _checkbox("collect_only",          TriggerState.collect_only,          TriggerState.toggle_collect_only),
                spacing="5", align="center", flex_wrap="wrap",
            ),
            rx.hstack(
                _checkbox("gpu_mem_record",        TriggerState.gpu_mem_record,        TriggerState.toggle_gpu_mem_record),
                _checkbox("test_with_coverage",    TriggerState.test_with_coverage,    TriggerState.toggle_test_with_coverage),
                _checkbox("clean_workspace",       TriggerState.clean_workspace,       TriggerState.toggle_clean_workspace),
                _checkbox("debug_hold_container",  TriggerState.debug_hold_container,  TriggerState.toggle_debug_hold_container),
                spacing="5", align="center", flex_wrap="wrap",
            ),
            _field(
                "capture",
                rx.input(
                    value=TriggerState.capture,
                    on_change=TriggerState.set_capture,
                    font_family="monospace",
                ),
                hint="pytest --capture option value (tee-sys / no / sys / fd).",
            ),
        ),

        # Pre-flight banner: warn if modelopt_branch isn't yet pushed to fork.
        rx.cond(
            (TriggerState.modelopt_branch == TriggerState.git_current_branch)
            & (
                (TriggerState.git_ahead > 0)
                | ~TriggerState.git_remote_has_branch
            ),
            rx.callout(
                rx.cond(
                    ~TriggerState.git_remote_has_branch,
                    "Branch "
                    + TriggerState.git_current_branch
                    + " is not on the fork yet. Dashboard will auto-push before triggering.",
                    "Local branch is "
                    + TriggerState.git_ahead.to_string()
                    + " commit(s) ahead of origin. Dashboard will auto-push before triggering.",
                ),
                icon="info",
                color_scheme="blue",
            ),
            rx.fragment(),
        ),

        # Result feedback
        rx.cond(
            TriggerState.result_message != "",
            rx.callout(
                TriggerState.result_message,
                icon=rx.cond(
                    TriggerState.result_kind == "success",
                    "circle_check",
                    rx.cond(
                        TriggerState.result_kind == "error",
                        "circle_alert",
                        "info",
                    ),
                ),
                color_scheme=rx.cond(
                    TriggerState.result_kind == "success",
                    "green",
                    rx.cond(
                        TriggerState.result_kind == "error",
                        "red",
                        "blue",
                    ),
                ),
            ),
            rx.fragment(),
        ),

        # Trigger button bar
        rx.hstack(
            rx.spacer(),
            rx.link(
                rx.button(
                    rx.hstack(
                        rx.icon(tag="activity", size=14),
                        rx.text("Open Runs"),
                        spacing="1",
                        align="center",
                    ),
                    variant="soft",
                    color_scheme="gray",
                    size="3",
                ),
                href="/runs",
            ),
            rx.button(
                rx.cond(
                    TriggerState.triggering,
                    rx.hstack(
                        rx.spinner(size="1"),
                        rx.text("Triggering…"),
                        spacing="1",
                        align="center",
                    ),
                    rx.hstack(
                        rx.icon(tag="play", size=16),
                        rx.text("Build"),
                        spacing="1",
                        align="center",
                    ),
                ),
                on_click=TriggerState.trigger,
                disabled=TriggerState.triggering,
                color_scheme="green",
                size="3",
            ),
            spacing="2", width="100%",
        ),

        spacing="4",
        align="stretch",
        width="100%",
        max_width="1100px",
        on_mount=TriggerState.on_load,
    )
    return page_shell(body)
