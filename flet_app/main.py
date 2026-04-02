"""Windows File Search App - Flet version."""

import flet as ft
from ui import build_ui


def main(page: ft.Page):
    page.title = "File Search (Flet)"
    page.window.width = 800
    page.window.height = 600
    build_ui(page)


if __name__ == "__main__":
    ft.app(target=main)
