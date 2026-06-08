"""Sidebar navigation. Layout mirrors modelopt-dashboard's navbar for visual consistency."""
from __future__ import annotations

import reflex as rx


def _nav_link(href: str, icon: str, text: str) -> rx.Component:
    is_active = rx.State.router.page.path == href
    is_parent_active = rx.cond(
        href != "/",
        rx.State.router.page.path.startswith(href + "/"),
        False,
    )
    return rx.link(
        rx.hstack(
            rx.icon(
                tag=icon,
                size=20,
                color=rx.cond(is_active | is_parent_active, "#76B900", "rgba(255,255,255,0.80)"),
            ),
            rx.text(
                text,
                color=rx.cond(is_active | is_parent_active, "#FFFFFF", "rgba(255,255,255,0.80)"),
            ),
            spacing="3",
            align="center",
        ),
        href=href,
        padding="0.75rem 1rem",
        border_radius="0.5rem",
        width="100%",
        background_color=rx.cond(
            is_active | is_parent_active, "rgba(118,185,0,0.10)", "transparent"
        ),
        border_left=rx.cond(
            is_active | is_parent_active, "3px solid #76B900", "3px solid transparent"
        ),
        font_weight=rx.cond(is_active | is_parent_active, "600", "400"),
        _hover={"background_color": "rgba(255,255,255,0.06)", "text_decoration": "none"},
        transition="background-color 150ms ease, border-color 150ms ease",
    )


def navbar() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.icon(tag="cpu", size=22, color="#76B900"),
            rx.text(
                "HF Test Dashboard",
                color="#FFFFFF",
                font_weight="700",
                font_size="1.05rem",
                letter_spacing="0.01em",
            ),
            spacing="3",
            align="center",
            padding="0.5rem 0.75rem 1.25rem 0.75rem",
        ),
        _nav_link("/", "home", "Home"),
        _nav_link("/inbox", "inbox", "Inbox"),
        _nav_link("/trigger", "play", "Trigger Build"),
        _nav_link("/runs", "activity", "Test Runs"),
        _nav_link("/matrix", "grid_3x3", "Test Matrix"),
        _nav_link("/analyzer", "sparkles", "AI Analyzer"),
        _nav_link("/history", "history", "History"),
        spacing="1",
        padding="1.25rem 1rem",
        background_color="#0F172A",
        width="240px",
        height="100vh",
        position="fixed",
        top="0",
        left="0",
        overflow_y="auto",
        align="stretch",
    )


def page_shell(body: rx.Component) -> rx.Component:
    """Wrap a page with the sidebar + main content area."""
    return rx.box(
        navbar(),
        rx.box(
            body,
            margin_left="240px",
            padding="2rem",
            min_height="100vh",
            background="#F8FAFC",
        ),
    )
