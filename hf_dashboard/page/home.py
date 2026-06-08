"""Landing page."""
from __future__ import annotations

import reflex as rx

from hf_dashboard.components.navbar import page_shell


def _feature_card(icon: str, title: str, body: str, href: str, color: str) -> rx.Component:
    return rx.link(
        rx.box(
            rx.vstack(
                rx.box(
                    rx.icon(tag=icon, size=26, color="white"),
                    background=color,
                    padding="0.65rem",
                    border_radius="0.6rem",
                    width="fit-content",
                ),
                rx.heading(title, size="4", color="#0F172A"),
                rx.text(body, color="#64748B", font_size="0.88rem", line_height="1.5"),
                spacing="3",
                align="start",
            ),
            background="white",
            border="1px solid #E2E8F0",
            border_radius="0.85rem",
            padding="1.5rem",
            height="100%",
            _hover={"transform": "translateY(-2px)", "border_color": color, "box_shadow": "0 8px 24px rgba(15,23,42,0.06)"},
            transition="all 150ms ease",
        ),
        href=href,
        text_decoration="none",
    )


def home_page() -> rx.Component:
    body = rx.vstack(
        rx.vstack(
            rx.heading("HuggingFace Test Dashboard", size="8", color="#0F172A"),
            rx.text(
                "Track HF model deployment tests across TensorRT-LLM, vLLM, and SGLang. AI-assisted log analysis, pass/fail tracking, NVBug integration.",
                color="#64748B",
                font_size="1rem",
                max_width="780px",
            ),
            spacing="2",
            align="start",
            width="100%",
            padding_bottom="0.5rem",
        ),
        rx.grid(
            _feature_card(
                "grid_3x3",
                "Test Matrix",
                "Model × backend grid showing latest pass / fail status. Filter by model name; click through to see AI-derived failure reasons.",
                "/matrix",
                "#667eea",
            ),
            _feature_card(
                "sparkles",
                "AI Analyzer",
                "Paste a slurm `.out` path. Claude reads the log tail, classifies pass/fail, and explains why — then writes the verdict to the matrix.",
                "/analyzer",
                "#10B981",
            ),
            columns="2",
            spacing="4",
            width="100%",
        ),
        rx.box(
            rx.vstack(
                rx.heading("Workflow", size="4", color="#0F172A"),
                rx.ordered_list(
                    rx.list_item("Slack alert fires for a newly released HF model."),
                    rx.list_item("Add test cases to the deploy harness; for eagle3 models, upload weights to S3."),
                    rx.list_item("Trigger the Jenkins job; results land in /localhome/.../slurm_logs/."),
                    rx.list_item("Open the AI Analyzer, paste the .out path, and let Claude classify pass / fail."),
                    rx.list_item("Verdict saves to the Test Matrix. File NVBug for fails; track until resolution."),
                    spacing="2",
                    color="#475569",
                    font_size="0.92rem",
                ),
                spacing="3",
                align="start",
            ),
            background="white",
            border="1px solid #E2E8F0",
            border_radius="0.85rem",
            padding="1.5rem",
            width="100%",
        ),
        spacing="5",
        align="stretch",
        width="100%",
        max_width="1100px",
    )
    return page_shell(body)
