"""Windows File Search App - Flet version."""

import flet as ft
from ui import build_ui


def main(page: ft.Page):
    page.title = "ESDH File Scanner (Flet)"
    page.window.width = 1250
    page.window.height = 800
    build_ui(page)


if __name__ == "__main__":
    ft.app(target=main)
