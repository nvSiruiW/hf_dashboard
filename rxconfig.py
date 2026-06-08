import reflex as rx

config = rx.Config(
    app_name="hf_dashboard",
    show_built_with_reflex=False,
    plugins=[
        rx.plugins.TailwindV4Plugin(),
    ],
    disable_plugins=["reflex.plugins.sitemap.SitemapPlugin"],
)
