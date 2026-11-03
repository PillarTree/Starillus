"""Starillus App Center UI.

A central graphical platform for browsing and installing applications
(APT, Flatpak and App Center submissions) with built-in anti-virus
scanning of every install.

Built with customtkinter so it matches the Pillarium 2.0 desktop shell
theme tokens exactly.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Any, Callable

import customtkinter as ctk

from . import theme as theme_module
from .catalog import App, AppCatalog
from .scanner import AntiVirusScanner


ctk.set_appearance_mode("dark")

APP_ID = "starillus-app-center"


class AppCenterApp(ctk.CTk):
    """The Starillus App Center window."""

    def __init__(self) -> None:
        super().__init__()

        self.theme = theme_module.THEME
        self.theme.apply_to_ctk()

        self.title("Starillus App Center")
        self.geometry("1000x700")
        self.minsize(800, 560)

        self.catalog = AppCatalog()
        self.scanner = AntiVirusScanner()
        self._selected: App | None = None
        self._worker_thread: threading.Thread | None = None

        self._build_layout()
        self._refresh_catalog()

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #
    def _build_layout(self) -> None:
        # Grid: header | sidebar + content
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=self.theme.get("surface"), height=64)
        header.grid(row=0, column=0, columnspan=2, sticky="nsew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Starillus App Center",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=self.theme.get("text"),
        ).grid(row=0, column=0, padx=20, pady=16, sticky="w")

        self.search = ctk.CTkEntry(
            header,
            placeholder_text="Search applications…",
            width=320,
            fg_color=self.theme.get("surface_alt"),
            border_color=self.theme.get("border"),
            text_color=self.theme.get("text"),
        )
        self.search.grid(row=0, column=1, padx=20, pady=16, sticky="e")
        self.search.bind("<Return>", lambda _e: self._on_search())

        # Sidebar (categories)
        self.sidebar = ctk.CTkScrollableFrame(
            self,
            fg_color=self.theme.get("panel"),
            width=220,
        )
        self.sidebar.grid(row=1, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(
            self.sidebar,
            text="Categories",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=self.theme.get("text_dim"),
        ).pack(anchor="w", padx=12, pady=(12, 8))

        self.all_button = ctk.CTkButton(
            self.sidebar,
            text="All",
            command=lambda: self._show_category("All"),
            fg_color=self.theme.get("accent"),
            hover_color=self.theme.get("accent_hover"),
            height=30,
        )
        self.all_button.pack(fill="x", padx=8, pady=(0, 4))

        self.category_buttons: dict[str, ctk.CTkButton] = {}
        for cat in self.catalog.categories():
            btn = ctk.CTkButton(
                self.sidebar,
                text=cat,
                command=lambda c=cat: self._show_category(c),
                fg_color="transparent",
                hover_color=self.theme.get("panel_hover"),
                text_color=self.theme.get("text_dim"),
                height=30,
                anchor="w",
            )
            btn.pack(fill="x", padx=8, pady=2)
            self.category_buttons[cat] = btn

        # Content area
        self.content = ctk.CTkScrollableFrame(
            self,
            fg_color=self.theme.get("background"),
        )
        self.content.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
        self.content.grid_columnconfigure(0, weight=1)

        self._empty_label = ctk.CTkLabel(
            self.content,
            text="No applications found.",
            text_color=self.theme.get("text_dim"),
        )

        # Status bar
        self.status = ctk.CTkLabel(
            self,
            text="Ready",
            text_color=self.theme.get("text_faint"),
            height=24,
            anchor="w",
        )
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8)

    # ------------------------------------------------------------------ #
    # Catalog / browsing
    # ------------------------------------------------------------------ #
    def _refresh_catalog(self) -> None:
        self.status.configure(text="Loading applications…")
        thread = threading.Thread(target=self._load_catalog, daemon=True)
        thread.start()

    def _load_catalog(self) -> None:
        self.catalog.scan()
        self.after(0, self._populate_sidebar)
        self.after(0, lambda: self._show_category("All"))

    def _populate_sidebar(self) -> None:
        for cat in self.catalog.categories():
            if cat not in self.category_buttons:
                btn = ctk.CTkButton(
                    self.sidebar,
                    text=cat,
                    command=lambda c=cat: self._show_category(c),
                    fg_color="transparent",
                    hover_color=self.theme.get("panel_hover"),
                    text_color=self.theme.get("text_dim"),
                    height=30,
                    anchor="w",
                )
                btn.pack(fill="x", padx=8, pady=2)
                self.category_buttons[cat] = btn

    def _show_category(self, category: str) -> None:
        self._clear_content()
        if category == "All":
            apps = self.catalog.apps
        else:
            apps = self.catalog.by_category(category)
        self._render_app_grid(apps)
        self.status.configure(text=f"{len(apps)} application(s)")

    def _on_search(self) -> None:
        query = self.search.get().strip()
        self._clear_content()
        if not query:
            self._show_category("All")
            return
        results = self.catalog.search(query)
        self._render_app_grid(results)
        self.status.configure(text=f"{len(results)} result(s) for “{query}”")

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self._selected = None

    def _render_app_grid(self, apps: list[App]) -> None:
        if not apps:
            self._empty_label.pack(expand=True)
            return

        row = 0
        col = 0
        max_cols = 4
        for app in apps:
            card = AppCard(
                self.content,
                app,
                theme=self.theme,
                on_select=self._on_app_select,
                on_install=self._on_app_install,
                scanner=self.scanner,
            )
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    # ------------------------------------------------------------------ #
    # App selection / details
    # ------------------------------------------------------------------ #
    def _on_app_select(self, app: App) -> None:
        self._selected = app
        self._clear_content()

        # Header bar with app name and install/remove button
        bar = ctk.CTkFrame(self.content, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(16, 8))
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            bar,
            text=app.name,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=self.theme.get("text"),
        ).pack(side="left", anchor="w")

        source_badge = ctk.CTkLabel(
            bar,
            text=f"{app.source.upper()}  •  {app.category}",
            font=ctk.CTkFont(size=11),
            text_color=self.theme.get("text_dim"),
        )
        source_badge.pack(side="right", anchor="e")

        # Install / remove action
        if app.installed:
            action_btn = ctk.CTkButton(
                bar,
                text="Remove",
                fg_color=self.theme.get("error"),
                hover_color="#c0392b",
                command=lambda: self._on_app_remove(app),
                width=110,
            )
        else:
            action_btn = ctk.CTkButton(
                bar,
                text="Install",
                fg_color=self.theme.get("success"),
                hover_color="#27ae60",
                command=lambda: self._on_app_install(app),
                width=110,
            )
        action_btn.pack(side="right", anchor="e", padx=(8, 0))

        # Description
        desc = ctk.CTkLabel(
            self.content,
            text=app.description or app.summary,
            font=ctk.CTkFont(size=13),
            text_color=self.theme.get("text"),
            wraplength=760,
            justify="left",
        )
        desc.pack(anchor="w", padx=16, pady=(8, 16))

        # Antivirus status
        av_text = "Anti-virus: clean" if app.antivirus_clean else f"Anti-virus: {app.antivirus_note}"
        av_label = ctk.CTkLabel(
            self.content,
            text=av_text,
            font=ctk.CTkFont(size=11),
            text_color=self.theme.get("success") if app.antivirus_clean else self.theme.get("error"),
        )
        av_label.pack(anchor="w", padx=16, pady=(0, 16))

    # ------------------------------------------------------------------ #
    # Install / remove
    # ------------------------------------------------------------------ #
    def _on_app_install(self, app: App) -> None:
        self._selected = app
        self._clear_content()
        self._render_install_panel(app)

    def _render_install_panel(self, app: App) -> None:
        panel = ctk.CTkFrame(
            self.content,
            fg_color=self.theme.get("surface"),
            corner_radius=self.theme.get("radius", 8) if isinstance(self.theme.get("radius", 8), int) else 8,
            border_width=1,
            border_color=self.theme.get("border"),
        )
        panel.pack(fill="both", expand=True, padx=16, pady=16)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            panel,
            text=f"Install {app.name}",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=self.theme.get("text"),
        ).pack(anchor="w", padx=20, pady=(20, 8))

        ctk.CTkLabel(
            panel,
            text=f"Source: {app.source}  •  {app.category}",
            text_color=self.theme.get("text_dim"),
        ).pack(anchor="w", padx=20, pady=(0, 16))

        # Scan first, then install
        self.status.configure(text="Scanning for threats…")
        scan_thread = threading.Thread(target=self._scan_and_install, args=(app,), daemon=True)
        scan_thread.start()

    def _scan_and_install(self, app: App) -> None:
        result = self.scanner.scan_package(app.id, app.source)
        self.after(0, lambda: self._after_scan(app, result))

    def _after_scan(self, app: App, result: Any) -> None:
        if not result.clean:
            self.status.configure(text="Install blocked: threats detected")
            self._show_alert(
                "Install blocked",
                f"Anti-virus detected threats in {app.name}: {result.note}",
                level="error",
            )
            self._on_app_select(app)
            return
        self.status.configure(text=f"Installing {app.name}…")
        thread = threading.Thread(target=self._install_app, args=(app,), daemon=True)
        thread.start()

    def _install_app(self, app: App) -> None:
        try:
            if app.source == "apt":
                self._apt_install(app.id)
            elif app.source == "flatpak":
                self._flatpak_install(app.id)
            elif app.source == "app-center":
                self._app_center_install(app.id)
            self.after(0, lambda: self._install_done(app, True, ""))
        except Exception as exc:  # pragma: no cover - runtime install errors
            self.after(0, lambda: self._install_done(app, False, str(exc)))

    def _apt_install(self, package: str) -> None:
        # Try graphical frontend first, fall back to apt-get via pkexec.
        for cmd in (["pkexec", "apt-get", "install", "-y", package],
                    ["apt-get", "install", "-y", package]):
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
                return
            except (OSError, subprocess.SubprocessError):
                continue
        raise RuntimeError(f"could not install apt package {package}")

    def _flatpak_install(self, app_id: str) -> None:
        for cmd in (["pkexec", "flatpak", "install", "-y", "flathub", app_id],
                    ["flatpak", "install", "-y", "flathub", app_id]):
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
                return
            except (OSError, subprocess.SubprocessError):
                continue
        raise RuntimeError(f"could not install flatpak {app_id}")

    def _app_center_install(self, app_ref: str) -> None:
        self.status.configure(text="App Center installs are resolved via apt/flatpak.")
        raise RuntimeError("app-center refs are installed through their native backend")

    def _on_app_remove(self, app: App) -> None:
        self.status.configure(text=f"Removing {app.name}…")
        thread = threading.Thread(target=self._remove_app, args=(app,), daemon=True)
        thread.start()

    def _remove_app(self, app: App) -> None:
        try:
            if app.source == "apt":
                subprocess.run(
                    ["pkexec", "apt-get", "remove", "-y", app.id],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            elif app.source == "flatpak":
                subprocess.run(
                    ["pkexec", "flatpak", "uninstall", "-y", app.id],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            self.after(0, lambda: self._install_done(app, True, ""))
        except Exception as exc:
            self.after(0, lambda: self._install_done(app, False, str(exc)))

    def _install_done(self, app: App, success: bool, error: str) -> None:
        self.catalog.scan()
        self._show_category("All")
        if success:
            self.status.configure(text=f"{app.name} installed successfully.")
        else:
            self.status.configure(text=f"Failed: {error}")
            self._show_alert("Install failed", error, level="error")

    def _show_alert(self, title: str, message: str, level: str = "info") -> None:
        alert = ctk.CTkToplevel(self)
        alert.title(title)
        alert.geometry("420x220")
        alert.transient(self)
        alert.grab_set()

        color = {
            "error": self.theme.get("error"),
            "warning": self.theme.get("warning"),
            "info": self.theme.get("info"),
        }.get(level, self.theme.get("text"))

        ctk.CTkLabel(
            alert,
            text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=color,
        ).pack(padx=20, pady=(20, 8))

        ctk.CTkLabel(
            alert,
            text=message,
            text_color=self.theme.get("text"),
            wraplength=360,
            justify="left",
        ).pack(padx=20, pady=(0, 16))

        ctk.CTkButton(
            alert,
            text="OK",
            command=alert.destroy,
            fg_color=self.theme.get("accent"),
            hover_color=self.theme.get("accent_hover"),
            width=90,
        ).pack(pady=(0, 20))


class AppCard(ctk.CTkFrame):
    """A single application card in the browse grid."""

    def __init__(
        self,
        master: Any,
        app: App,
        theme: theme_module.AppCenterTheme,
        on_select: Callable[[App], None],
        on_install: Callable[[App], None],
        scanner: AntiVirusScanner,
    ):
        super().__init__(
            master,
            fg_color=theme.get("surface"),
            corner_radius=theme.get("radius", 8) if isinstance(theme.get("radius", 8), int) else 8,
            border_width=1,
            border_color=theme.get("border"),
            width=200,
            height=260,
        )
        self.app = app
        self.theme = theme
        self.on_select = on_select
        self.on_install = on_install
        self.scanner = scanner
        self.grid_propagate(False)

        self._build_ui()
        self.bind("<Button-1>", lambda _e: self._on_click())
        for child in self.winfo_children():
            child.bind("<Button-1>", lambda _e: self._on_click())

    def _build_ui(self) -> None:
        # Icon placeholder
        icon = ctk.CTkLabel(
            self,
            text="[app]",
            font=ctk.CTkFont(size=32),
            text_color=self.theme.get("text_dim"),
            height=64,
        )
        icon.pack(padx=14, pady=(14, 8), fill="x")

        ctk.CTkLabel(
            self,
            text=self.app.name,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.theme.get("text"),
        ).pack(padx=10, pady=(0, 4), anchor="w")

        ctk.CTkLabel(
            self,
            text=self.app.summary or "",
            font=ctk.CTkFont(size=11),
            text_color=self.theme.get("text_dim"),
            wraplength=170,
            justify="left",
        ).pack(padx=10, pady=(0, 10), anchor="w")

        # Source / status row
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkLabel(
            row,
            text=self.app.source,
            font=ctk.CTkFont(size=10),
            text_color=self.theme.get("text_faint"),
        ).pack(side="left")

        if self.app.installed:
            ctk.CTkLabel(
                row,
                text="installed",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=self.theme.get("success"),
            ).pack(side="right")

    def _on_click(self) -> None:
        self.on_select(self.app)


def main() -> int:
    app = AppCenterApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
