"""Inbox — newly-detected HF models waiting to be triaged into the matrix."""
from __future__ import annotations

import reflex as rx

from hf_dashboard.components.navbar import page_shell
from hf_dashboard.data.common import BACKEND_COLORS
from hf_dashboard.data.inbox_state import InboxItem, InboxState


# ---------------------------------------------------------------------------
# Manual-add form
# ---------------------------------------------------------------------------

def _add_form() -> rx.Component:
    return rx.cond(
        InboxState.show_add_form,
        rx.box(
            rx.vstack(
                rx.text(
                    "Add an HF model manually",
                    font_weight="700", color="#0F172A", font_size="0.92rem",
                ),
                rx.input(
                    placeholder="org/repo, e.g. nvidia/Llama-3.3-70B-Instruct-Eagle3",
                    value=InboxState.new_model_name,
                    on_change=InboxState.set_new_model_name,
                    font_family="monospace",
                ),
                rx.input(
                    placeholder="HuggingFace URL (optional — auto-built from name)",
                    value=InboxState.new_hf_url,
                    on_change=InboxState.set_new_hf_url,
                    font_family="monospace",
                ),
                rx.hstack(
                    rx.button(
                        rx.hstack(
                            rx.icon(tag="plus", size=14),
                            rx.text("Add"),
                            spacing="1",
                            align="center",
                        ),
                        on_click=InboxState.add_model_manually,
                        color_scheme="green",
                        size="2",
                    ),
                    rx.button(
                        "Cancel",
                        on_click=InboxState.toggle_add_form,
                        variant="soft",
                        size="2",
                    ),
                    spacing="2",
                ),
                spacing="2",
                align="stretch",
                width="100%",
            ),
            background="white",
            border="1px solid #E2E8F0",
            border_radius="0.75rem",
            padding="1.25rem",
            width="100%",
        ),
        rx.button(
            rx.hstack(
                rx.icon(tag="plus", size=14),
                rx.text("Manually add HF model"),
                spacing="1",
                align="center",
            ),
            on_click=InboxState.toggle_add_form,
            variant="soft",
            color_scheme="gray",
            size="2",
        ),
    )


# ---------------------------------------------------------------------------
# Per-card backend checkbox
# ---------------------------------------------------------------------------

def _card_support_badge(support_var) -> rx.Component:
    """Compact AI verdict badge for use on the inbox card."""
    return rx.match(
        support_var,
        ("yes",     rx.badge("HF: yes",     color_scheme="green", variant="soft", size="1")),
        ("unclear", rx.badge("HF: unclear", color_scheme="gray",  variant="soft", size="1")),
        rx.fragment(),
    )


def _backend_checkbox(item: InboxItem, index, backend: str, is_checked,
                      support_var, reason_var) -> rx.Component:
    color = BACKEND_COLORS.get(backend, "#475569")
    return rx.tooltip(
        rx.hstack(
            rx.checkbox(
                checked=is_checked,
                on_change=InboxState.toggle_backend(index, backend),
                size="2",
            ),
            rx.box(width="6px", height="6px", border_radius="50%", background=color),
            rx.text(
                backend.upper(),
                font_size="0.78rem",
                font_weight="700",
                color="#0F172A",
                letter_spacing="0.04em",
            ),
            _card_support_badge(support_var),
            spacing="2",
            align="center",
        ),
        content=reason_var,
    )


# ---------------------------------------------------------------------------
# Per-card S3 block (only rendered for models that need S3 upload)
# ---------------------------------------------------------------------------

def _s3_block(item: InboxItem, index) -> rx.Component:
    return rx.cond(
        item.requires_s3_upload,
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.icon(tag="triangle_alert", size=16, color="#D97706"),
                    rx.text(
                        "Eagle3 / speculative-decoding module — requires S3 upload before testing",
                        font_size="0.82rem",
                        color="#92400E",
                        font_weight="600",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.hstack(
                    rx.input(
                        placeholder="s3://your-bucket/path-to-weights",
                        value=item.s3_path,
                        on_change=lambda v: InboxState.set_s3_path(index, v),
                        font_family="monospace",
                        font_size="0.82rem",
                        flex="1",
                    ),
                    rx.hstack(
                        rx.checkbox(
                            checked=item.s3_uploaded,
                            on_change=InboxState.toggle_s3_uploaded(index),
                            size="2",
                        ),
                        rx.text(
                            "Uploaded",
                            font_size="0.82rem",
                            font_weight="600",
                            color="#0F172A",
                        ),
                        spacing="2",
                        align="center",
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                ),
                spacing="2",
                align="stretch",
                width="100%",
            ),
            padding="0.85rem 1rem",
            background="#FFFBEB",
            border="1px solid #FDE68A",
            border_radius="0.5rem",
            width="100%",
        ),
        rx.fragment(),
    )


# ---------------------------------------------------------------------------
# One card
# ---------------------------------------------------------------------------

def _card(item: InboxItem, index) -> rx.Component:
    return rx.box(
        rx.vstack(
            # Header: select checkbox + name + HF link + release date
            rx.hstack(
                rx.tooltip(
                    rx.checkbox(
                        checked=item.selected_for_trigger,
                        on_change=InboxState.toggle_select_for_trigger(index),
                        size="2",
                    ),
                    content="Include this model in the next batch Jenkins build",
                ),
                rx.text(
                    item.model_name,
                    font_family="monospace",
                    font_weight="700",
                    font_size="0.95rem",
                    color="#0F172A",
                    flex="1",
                ),
                rx.cond(
                    item.release_date != "",
                    rx.badge(
                        item.release_date,
                        color_scheme="gray", variant="soft", size="1",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    item.hf_url != "",
                    rx.link(
                        rx.button(
                            rx.hstack(
                                rx.icon(tag="external_link", size=14),
                                rx.text("View on HF"),
                                spacing="1",
                                align="center",
                            ),
                            variant="soft", color_scheme="blue", size="1",
                        ),
                        href=item.hf_url,
                        is_external=True,
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                width="100%",
            ),

            # Optional metadata row
            rx.cond(
                (item.architecture != "") | (item.param_count != "") | (item.source_collection != ""),
                rx.hstack(
                    rx.cond(
                        item.architecture != "",
                        rx.badge(
                            item.architecture,
                            color_scheme="indigo", variant="soft", size="1",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        item.param_count != "",
                        rx.badge(
                            item.param_count,
                            color_scheme="gray", variant="soft", size="1",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        item.source_collection != "",
                        rx.text(
                            "from " + item.source_collection,
                            font_size="0.72rem",
                            color="#94A3B8",
                        ),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                ),
                rx.fragment(),
            ),

            # Backend checkboxes
            rx.box(
                rx.vstack(
                    rx.text(
                        "TEST ON THESE BACKENDS",
                        font_size="0.68rem",
                        font_weight="700",
                        color="#94A3B8",
                        letter_spacing="0.08em",
                    ),
                    rx.hstack(
                        _backend_checkbox(item, index, "trtllm", item.test_trtllm,
                                          item.trtllm_support, item.trtllm_reason),
                        _backend_checkbox(item, index, "vllm",   item.test_vllm,
                                          item.vllm_support, item.vllm_reason),
                        _backend_checkbox(item, index, "sglang", item.test_sglang,
                                          item.sglang_support, item.sglang_reason),
                        spacing="5",
                        align="center",
                    ),
                    rx.cond(
                        item.has_analysis,
                        rx.fragment(),
                        rx.text(
                            "No AI analysis yet — click ‘Analyze all pending’ above, or "
                            "open ‘Generate test case’ to analyze this one.",
                            font_size="0.72rem",
                            color="#94A3B8",
                        ),
                    ),
                    spacing="2",
                    align="start",
                ),
                padding="0.85rem 1rem",
                background="#F8FAFC",
                border="1px solid #E2E8F0",
                border_radius="0.5rem",
                width="100%",
            ),

            # S3 block (only if requires_s3_upload)
            _s3_block(item, index),

            # Notes
            rx.input(
                placeholder="Notes (optional)…",
                value=item.notes,
                on_change=lambda v: InboxState.set_notes(index, v),
                font_size="0.82rem",
            ),

            # Action buttons
            rx.hstack(
                rx.button(
                    rx.hstack(
                        rx.icon(tag="code", size=14),
                        rx.text("Generate test case"),
                        spacing="1",
                        align="center",
                    ),
                    on_click=InboxState.open_generate(index),
                    color_scheme="indigo",
                    size="2",
                ),
                rx.button(
                    rx.hstack(
                        rx.icon(tag="check", size=14),
                        rx.text("Triage → Matrix"),
                        spacing="1",
                        align="center",
                    ),
                    on_click=InboxState.triage(index),
                    variant="soft",
                    color_scheme="green",
                    size="2",
                ),
                rx.button(
                    rx.hstack(
                        rx.icon(tag="skip_forward", size=14),
                        rx.text("Skip"),
                        spacing="1",
                        align="center",
                    ),
                    on_click=InboxState.skip(index),
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                ),
                rx.spacer(),
                rx.text(
                    "added " + item.created_at,
                    font_size="0.72rem",
                    color="#94A3B8",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),

            spacing="3",
            align="stretch",
            width="100%",
        ),
        background="white",
        border=rx.cond(
            item.selected_for_trigger,
            "2px solid #6366F1",
            "1px solid #E2E8F0",
        ),
        border_radius="0.75rem",
        padding="1.5rem",
        width="100%",
        box_shadow=rx.cond(
            item.selected_for_trigger,
            "0 0 0 3px rgba(99,102,241,0.12)",
            "none",
        ),
        transition="border 120ms ease, box-shadow 120ms ease",
    )


def _selection_bar() -> rx.Component:
    """Sticky action bar visible once ≥1 model is selected."""
    return rx.cond(
        InboxState.selected_count > 0,
        rx.box(
            rx.hstack(
                rx.icon(tag="check_check", size=18, color="#4F46E5"),
                rx.text(
                    InboxState.selected_count.to_string()
                    + " models selected for batch Jenkins build",
                    font_size="0.9rem",
                    font_weight="700",
                    color="#0F172A",
                ),
                rx.spacer(),
                rx.button(
                    rx.text("Clear", font_size="0.78rem"),
                    on_click=InboxState.clear_trigger_selection,
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                ),
                rx.link(
                    rx.button(
                        rx.hstack(
                            rx.icon(tag="play", size=14),
                            rx.text("Trigger build for selected"),
                            spacing="1",
                            align="center",
                        ),
                        color_scheme="green",
                        size="2",
                    ),
                    href=InboxState.trigger_url,
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            background="linear-gradient(to right, #EEF2FF, #E0E7FF)",
            border="1px solid #C7D2FE",
            border_radius="0.75rem",
            padding="0.85rem 1.25rem",
            width="100%",
            position="sticky",
            top="1rem",
            z_index="10",
        ),
        rx.fragment(),
    )



# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def _support_badge(support_var) -> rx.Component:
    """Render the per-backend AI verdict as a small colored badge.

    `support_var` is a Reflex Var holding "yes" / "unclear" / "".
    """
    return rx.match(
        support_var,
        ("yes",     rx.badge("HF: yes",     color_scheme="green",  variant="soft", size="1")),
        ("unclear", rx.badge("HF: unclear", color_scheme="gray",   variant="soft", size="1")),
        rx.fragment(),
    )


def _backend_row(label: str, checked, on_toggle, support_var, reason_var) -> rx.Component:
    """One backend row in the generator modal: checkbox + name + AI verdict + reason."""
    return rx.hstack(
        rx.checkbox(checked=checked, on_change=on_toggle, size="2"),
        rx.text(label, font_weight="700", font_size="0.85rem", min_width="60px"),
        _support_badge(support_var),
        rx.text(
            reason_var,
            font_size="0.78rem",
            color="#475569",
            flex="1",
            white_space="normal",
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _hf_card_meta() -> rx.Component:
    """Small grid showing what Claude extracted from the README beyond backends."""
    return rx.cond(
        InboxState.gen_card_analyzed,
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text("HF MODEL CARD", font_size="0.65rem", font_weight="700",
                            color="#94A3B8", letter_spacing="0.08em"),
                    rx.cond(
                        InboxState.gen_card_cached,
                        rx.badge("cached", color_scheme="blue", variant="soft", size="1"),
                        rx.badge("fresh", color_scheme="green", variant="soft", size="1"),
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.hstack(
                            rx.icon(tag="refresh_cw", size=12),
                            rx.text("Re-analyze"),
                            spacing="1",
                            align="center",
                        ),
                        on_click=InboxState.reanalyze_card,
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                        disabled=InboxState.gen_card_loading,
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                rx.hstack(
                    rx.cond(
                        InboxState.gen_card_architecture != "",
                        rx.badge(
                            "arch: " + InboxState.gen_card_architecture,
                            color_scheme="indigo", variant="soft", size="1",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        InboxState.gen_card_param_count != "",
                        rx.badge(
                            "params: " + InboxState.gen_card_param_count,
                            color_scheme="gray", variant="soft", size="1",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        InboxState.gen_card_quantization != "",
                        rx.badge(
                            "quant: " + InboxState.gen_card_quantization,
                            color_scheme="purple", variant="soft", size="1",
                        ),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                ),
                rx.cond(
                    InboxState.gen_card_notes != "",
                    rx.hstack(
                        rx.icon(tag="info", size=14, color="#475569"),
                        rx.text(
                            InboxState.gen_card_notes,
                            font_size="0.78rem",
                            color="#0F172A",
                            font_style="italic",
                        ),
                        spacing="2",
                        align="start",
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                align="stretch",
                width="100%",
            ),
            padding="0.65rem 0.85rem",
            background="#EFF6FF",
            border="1px solid #BFDBFE",
            border_radius="0.4rem",
            width="100%",
        ),
        rx.fragment(),
    )


def _git_action_bar() -> rx.Component:
    """Branch / commit info + Push button shown in the generator modal."""
    return rx.cond(
        InboxState.git_initialized,
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.icon(tag="git_branch", size=16, color="#475569"),
                    rx.text(
                        "BRANCH",
                        font_size="0.68rem",
                        font_weight="700",
                        color="#94A3B8",
                        letter_spacing="0.08em",
                    ),
                    rx.code(InboxState.git_current_branch, font_size="0.8rem"),
                    rx.cond(
                        InboxState.git_ahead > 0,
                        rx.badge(
                            InboxState.git_ahead.to_string() + " ahead",
                            color_scheme="orange",
                            variant="soft",
                            size="1",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        InboxState.git_has_uncommitted,
                        rx.badge(
                            "uncommitted changes",
                            color_scheme="red",
                            variant="soft",
                            size="1",
                        ),
                        rx.fragment(),
                    ),
                    rx.spacer(),
                    rx.link(
                        rx.button(
                            rx.hstack(
                                rx.icon(tag="external_link", size=12),
                                rx.text("View on GitHub"),
                                spacing="1",
                                align="center",
                            ),
                            variant="outline",
                            color_scheme="gray",
                            size="1",
                        ),
                        href=InboxState.git_branch_url,
                        is_external=True,
                    ),
                    rx.button(
                        rx.cond(
                            InboxState.push_running,
                            rx.hstack(
                                rx.spinner(size="1"),
                                rx.text("Pushing…"),
                                spacing="1",
                                align="center",
                            ),
                            rx.hstack(
                                rx.icon(tag="upload", size=14),
                                rx.text("Push to fork"),
                                spacing="1",
                                align="center",
                            ),
                        ),
                        on_click=InboxState.push_branch,
                        disabled=InboxState.push_running | (InboxState.git_ahead == 0),
                        color_scheme="indigo",
                        size="1",
                    ),
                    rx.link(
                        rx.button(
                            rx.hstack(
                                rx.icon(tag="play", size=14),
                                rx.text("Trigger test"),
                                spacing="1",
                                align="center",
                            ),
                            color_scheme="green",
                            size="1",
                        ),
                        href="/trigger?modelopt_branch=" + InboxState.git_current_branch,
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                rx.cond(
                    InboxState.git_last_commit_sha != "",
                    rx.hstack(
                        rx.text(
                            "Last commit:",
                            font_size="0.72rem",
                            color="#94A3B8",
                            font_weight="600",
                        ),
                        rx.code(InboxState.git_last_commit_sha, font_size="0.75rem"),
                        rx.text(
                            InboxState.git_last_commit_subject,
                            font_size="0.78rem",
                            color="#0F172A",
                            flex="1",
                            overflow="hidden",
                            text_overflow="ellipsis",
                            white_space="nowrap",
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                align="stretch",
                width="100%",
            ),
            padding="0.65rem 0.85rem",
            background="#F1F5F9",
            border="1px solid #CBD5E1",
            border_radius="0.4rem",
            width="100%",
        ),
        rx.cond(
            InboxState.git_status_error != "",
            rx.callout(
                "Working copy not initialized: " + InboxState.git_status_error,
                icon="circle_alert",
                color_scheme="orange",
            ),
            rx.fragment(),
        ),
    )


def _generate_modal() -> rx.Component:
    """Case generator modal: edit fields → preview unified diff → Apply."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                # Header
                rx.hstack(
                    rx.icon(tag="code", size=20, color="#475569"),
                    rx.heading(
                        "Generate test case",
                        size="4",
                        color="#0F172A",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    InboxState.gen_model_name,
                    font_family="monospace",
                    font_weight="700",
                    font_size="0.92rem",
                    color="#0F172A",
                ),
                rx.divider(),

                # HF model card analysis: shows loading spinner, then verdicts
                rx.cond(
                    InboxState.gen_card_loading,
                    rx.hstack(
                        rx.spinner(size="2"),
                        rx.text(
                            "Reading HuggingFace model card with Claude…",
                            font_size="0.85rem",
                            color="#475569",
                        ),
                        spacing="2",
                        align="center",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    InboxState.gen_card_error != "",
                    rx.callout(
                        "HF card analysis failed: " + InboxState.gen_card_error,
                        icon="circle_alert",
                        color_scheme="orange",
                    ),
                    rx.fragment(),
                ),
                _hf_card_meta(),

                # Editable fields row 1: backends — each row shows AI verdict
                rx.text(
                    "BACKENDS",
                    font_size="0.68rem",
                    font_weight="700",
                    color="#94A3B8",
                    letter_spacing="0.08em",
                ),
                rx.vstack(
                    _backend_row(
                        "trtllm",
                        InboxState.gen_backend_trtllm,
                        InboxState.toggle_gen_backend("trtllm"),
                        InboxState.gen_trtllm_support,
                        InboxState.gen_trtllm_reason,
                    ),
                    _backend_row(
                        "vllm",
                        InboxState.gen_backend_vllm,
                        InboxState.toggle_gen_backend("vllm"),
                        InboxState.gen_vllm_support,
                        InboxState.gen_vllm_reason,
                    ),
                    _backend_row(
                        "sglang",
                        InboxState.gen_backend_sglang,
                        InboxState.toggle_gen_backend("sglang"),
                        InboxState.gen_sglang_support,
                        InboxState.gen_sglang_reason,
                    ),
                    spacing="2",
                    align="stretch",
                    width="100%",
                ),

                # Row 2: tp_size + mini_sm
                rx.hstack(
                    rx.vstack(
                        rx.text(
                            "TENSOR_PARALLEL_SIZE",
                            font_size="0.68rem",
                            font_weight="700",
                            color="#94A3B8",
                            letter_spacing="0.08em",
                        ),
                        rx.input(
                            value=InboxState.gen_tp_size.to_string(),
                            on_change=InboxState.set_gen_tp_size,
                            font_family="monospace",
                            width="120px",
                        ),
                        spacing="1",
                        align="start",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text(
                                "MINI_SM",
                                font_size="0.68rem",
                                font_weight="700",
                                color="#94A3B8",
                                letter_spacing="0.08em",
                            ),
                            rx.hstack(
                                rx.checkbox(
                                    checked=InboxState.gen_omit_mini_sm,
                                    on_change=InboxState.toggle_gen_omit_mini_sm,
                                    size="1",
                                ),
                                rx.text(
                                    "omit field",
                                    font_size="0.7rem",
                                    color="#94A3B8",
                                ),
                                spacing="1",
                                align="center",
                            ),
                            spacing="3",
                            align="center",
                        ),
                        rx.input(
                            value=InboxState.gen_mini_sm_value.to_string(),
                            on_change=InboxState.set_gen_mini_sm_value,
                            font_family="monospace",
                            width="120px",
                            disabled=InboxState.gen_omit_mini_sm,
                        ),
                        spacing="1",
                        align="start",
                    ),
                    spacing="4",
                    align="start",
                ),

                # Target / notes line
                rx.cond(
                    InboxState.gen_target_function != "",
                    rx.hstack(
                        rx.text(
                            "Will edit ",
                            font_size="0.78rem",
                            color="#475569",
                        ),
                        rx.code(InboxState.gen_target_function, font_size="0.8rem"),
                        rx.text(" in ", font_size="0.78rem", color="#475569"),
                        rx.code(InboxState.gen_target_file, font_size="0.72rem"),
                        spacing="1",
                        align="center",
                        flex_wrap="wrap",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    InboxState.gen_notes != "",
                    rx.text(
                        InboxState.gen_notes,
                        font_size="0.78rem",
                        color="#0F172A",
                        font_style="italic",
                    ),
                    rx.fragment(),
                ),

                # Duplicate warning — only shown for PRE-EXISTING duplicates
                # (i.e. the model was already in the file before this modal
                # opened). After a successful Apply, the post-apply re-check
                # also sets `gen_already_exists_in` (since we just added it),
                # but in that case the green "Applied at HH:MM:SS" callout
                # below is the right signal — don't double-warn.
                rx.cond(
                    (InboxState.gen_already_exists_in != "")
                    & (InboxState.gen_applied_at == ""),
                    rx.callout(
                        "This model already has a case in "
                        + InboxState.gen_already_exists_in
                        + " — nothing to add. Click Skip on the inbox card if "
                        "you don't want it surfaced again.",
                        icon="info",
                        color_scheme="orange",
                    ),
                    rx.fragment(),
                ),

                # Error / success
                rx.cond(
                    InboxState.gen_error != "",
                    rx.callout(
                        InboxState.gen_error,
                        icon="circle_alert",
                        color_scheme="red",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    InboxState.gen_applied_at != "",
                    rx.callout(
                        rx.cond(
                            InboxState.gen_last_commit_sha != "",
                            "Applied + committed at "
                            + InboxState.gen_applied_at
                            + " · "
                            + InboxState.gen_last_commit_sha
                            + " "
                            + InboxState.gen_last_commit_subject,
                            "Applied to working copy at " + InboxState.gen_applied_at,
                        ),
                        icon="circle_check",
                        color_scheme="green",
                    ),
                    rx.fragment(),
                ),

                # Git branch status + push action
                _git_action_bar(),

                # Push action feedback
                rx.cond(
                    InboxState.push_message != "",
                    rx.callout(
                        InboxState.push_message,
                        icon=rx.cond(
                            InboxState.push_kind == "success",
                            "circle_check",
                            "circle_alert",
                        ),
                        color_scheme=rx.cond(
                            InboxState.push_kind == "success",
                            "green",
                            "red",
                        ),
                    ),
                    rx.fragment(),
                ),

                # Diff preview
                rx.text(
                    "UNIFIED DIFF",
                    font_size="0.68rem",
                    font_weight="700",
                    color="#94A3B8",
                    letter_spacing="0.08em",
                ),
                rx.box(
                    rx.text(
                        InboxState.gen_diff,
                        font_family="monospace",
                        font_size="0.75rem",
                        color="#0F172A",
                        white_space="pre",
                    ),
                    background="#0F172A11",
                    border="1px solid #E2E8F0",
                    border_radius="0.4rem",
                    padding="0.85rem 1rem",
                    width="100%",
                    max_height="40vh",
                    overflow="auto",
                ),

                # Actions
                rx.hstack(
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button(
                            "Close",
                            on_click=InboxState.close_generate,
                            variant="soft",
                        ),
                    ),
                    rx.button(
                        rx.hstack(
                            rx.icon(tag="file_plus", size=14),
                            rx.text("Apply to working copy"),
                            spacing="1",
                            align="center",
                        ),
                        on_click=InboxState.apply_generate,
                        color_scheme="green",
                        size="2",
                        disabled=InboxState.gen_already_exists_in != "",
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),

                spacing="3",
                align="stretch",
            ),
            max_width="900px",
            width="92vw",
        ),
        open=InboxState.gen_open,
        on_open_change=InboxState.close_generate,
    )


def inbox_page() -> rx.Component:
    body = rx.vstack(
        rx.vstack(
            rx.heading("Inbox", size="7", color="#0F172A"),
            rx.text(
                "Newly-detected HuggingFace models waiting to be triaged. ",
                "Pick which backends to test on each model, then click ",
                rx.code("Triage → Matrix"),
                " to add per-backend rows to the test matrix.",
                color="#64748B",
                font_size="0.92rem",
                max_width="780px",
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        _selection_bar(),
        _add_form(),
        rx.cond(
            InboxState.has_items,
            rx.vstack(
                rx.hstack(
                    rx.text(
                        InboxState.items_count.to_string()
                        + " model"
                        + rx.cond(InboxState.items_count == 1, "", "s")
                        + " awaiting triage",
                        font_size="0.85rem",
                        color="#475569",
                        font_weight="600",
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.cond(
                            InboxState.bulk_running,
                            rx.hstack(
                                rx.spinner(size="1"),
                                rx.text(InboxState.bulk_progress),
                                spacing="2",
                                align="center",
                            ),
                            rx.hstack(
                                rx.icon(tag="sparkles", size=14),
                                rx.text("Analyze all pending with Claude"),
                                spacing="1",
                                align="center",
                            ),
                        ),
                        on_click=InboxState.analyze_all_pending,
                        disabled=InboxState.bulk_running,
                        color_scheme="indigo",
                        variant="soft",
                        size="2",
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                rx.foreach(
                    InboxState.items,
                    lambda item, idx: _card(item, idx),
                ),
                spacing="3",
                align="stretch",
                width="100%",
            ),
            rx.callout(
                "Inbox is empty. New models will appear here once the upstream "
                "monitor pushes them — or you can add one manually with the "
                "button above.",
                icon="inbox",
                color_scheme="blue",
            ),
        ),
        _generate_modal(),
        spacing="4",
        align="stretch",
        width="100%",
        max_width="1100px",
        on_mount=InboxState.load,
    )
    return page_shell(body)
