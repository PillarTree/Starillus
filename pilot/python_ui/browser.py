"""Pilot — a self-contained web browser in pure Python with a customtkinter UI.

Everything is software-rendered: HTML (tolerant parser) -> DOM -> CSS cascade
-> box layout -> Pillow framebuffer -> customtkinter CTkImage. JavaScript runs
through the built-in interpreter in js.py, with a DOM bridge, events and
timers. The browser chrome (tabs, address bar, buttons, status bar, find bar,
dialogs, context menu) is drawn with the same renderer into the framebuffer.

Usage:  python3 -m pilot [url]
"""

from __future__ import annotations

import os
import sys
import time
import traceback
import urllib.parse

import customtkinter as ctk
import tkinter as tk
from PIL import Image, ImageTk

from . import css, html5, js, layout as layout_mod, net, settings as settings_mod, theme, ui

try:
    from PIL import Image as _PILImage
    from PIL import ImageTk as _ImageTk
except Exception:  # pragma: no cover
    _PILImage = Image
    _ImageTk = ImageTk

KEYSYM_REV = {}  # kept for compatibility; ctk provides event.keysym directly
WM_DELETE_WINDOW = "WM_DELETE_WINDOW"

HOME_HTML = """<!doctype html>
<html><head><title>Pilot Home</title>
<style>
  body { font-family: sans-serif; text-align: center; margin-top: 80px;
         background: #f4f6fa; }
  h1 { font-size: 40px; color: #2b5d8f; margin-bottom: 4px; }
  .sub { color: #666; font-size: 18px; }
  .box { display: inline-block; margin-top: 40px; text-align: left;
         background: #fff; border: 1px solid #dde; padding: 20px 30px;
         border-radius: 8px; }
  li { margin: 8px 0; }
  a { color: #2b5d8f; }
  #clock { font-size: 22px; color: #333; margin: 30px 0; }
</style></head>
<body>
  <h1>Pilot</h1>
  <div class="sub">a hand-rolled browser — HTML, CSS, JS, no WebKit</div>
  <div id="clock"></div>
  <div class="box">
    <b>Try:</b>
    <ul>
      <li>Open a URL in the address bar (Ctrl+L), e.g. <a href="pilot://about">pilot://about</a></li>
      <li>Ctrl+T new tab · Ctrl+W close · Ctrl+Tab next · Ctrl+= zoom</li>
      <li>Ctrl+F find in page · Ctrl+R reload · Alt+←/→ history</li>
      <li>Links, buttons and this clock below are live JavaScript</li>
    </ul>
    <button onclick="document.getElementById('clock').innerText =
      new Date().toLocaleString()">Show time</button>
    <button onclick="demo()">Run demo</button>
  </div>
<script>
  function demo() {
    var el = document.getElementById('clock');
    var i = 0;
    var txt = ["Hello from Pilot's JS engine!", 'closures, objects, arrays',
               'setInterval, DOM events…', 'it really works'];
    el.style.color = 'rgb(43, 93, 143)';
    var t = setInterval(function () {
      el.innerText = txt[i % txt.length];
      i++;
      if (i > txt.length * 2) { clearInterval(t); el.innerText = 'tada 🎉'.replace(' 🎉',''); }
    }, 800);
    setTimeout(function () { el.style.color = '#c33'; }, 2400);
  }
  function tick() {
    var c = document.getElementById('clock');
    if (c) c.innerText = new Date().toLocaleString();
  }
  setInterval(tick, 1000);
  tick();
</script>
</body></html>"""

ABOUT_HTML = """<!doctype html>
<html><head><title>About Pilot</title>
<style>
  body { font-family: sans-serif; margin: 40px 60px; color: #223; }
  h1 { color: #2b5d8f; } kbd { background:#eef; padding: 1px 6px;
       border: 1px solid #ccd; border-radius: 3px; }
  table { border-collapse: collapse; } td { padding: 3px 14px 3px 0; }
</style></head>
<body>
<h1>About Pilot</h1>
<p>Pilot is a browser written from scratch in pure Python: a customtkinter
window, a software framebuffer, a tolerant HTML parser, a CSS cascade with
selectors, a box layout engine, and a JavaScript interpreter with a DOM
bridge — no WebKit, no GTK, no Qt.</p>
<table>
<tr><td><kbd>Ctrl+L</kbd></td><td>address bar</td></tr>
<tr><td><kbd>Ctrl+T</kbd> / <kbd>Ctrl+W</kbd></td><td>new / close tab</td></tr>
<tr><td><kbd>Ctrl+Tab</kbd> / <kbd>Ctrl+Shift+Tab</kbd></td><td>next / prev tab</td></tr>
<tr><td><kbd>Ctrl+1..9</kbd></td><td>jump to tab</td></tr>
<tr><td><kbd>Ctrl+R</kbd> / <kbd>F5</kbd></td><td>reload</td></tr>
<tr><td><kbd>Ctrl+=</kbd> / <kbd>Ctrl+-</kbd> / <kbd>Ctrl+0</kbd></td><td>zoom</td></tr>
<tr><td><kbd>Ctrl+F</kbd> / <kbd>Enter</kbd></td><td>find in page</td></tr>
<tr><td><kbd>Alt+←</kbd> / <kbd>Alt+→</kbd></td><td>back / forward</td></tr>
<tr><td>P</kbd>gUp / <kbd>P</kbd>gDn</td><td>scroll</td></tr>
<tr><td>wheel</td><td>scroll · click links · type in inputs</td></tr>
</table>
<p>Home: <a href="pilot://home">pilot://home</a> · Settings: <a href="pilot://settings">pilot://settings</a></p>
</body></html>"""

ERROR_HTML = """<!doctype html>
<html><head><title>{title}</title>
<style>
  body {{ font-family: sans-serif; margin: 80px auto; max-width: 560px;
         text-align: center; color: #222; }}
  h1 {{ font-size: 56px; color: #b33; margin-bottom: 0; }}
  .code {{ color: #888; font-size: 18px; }}
  .msg {{ margin-top: 24px; font-size: 16px; }}
  a {{ color: #2b5d8f; }}
</style></head>
<body>
<h1>{code}</h1>
<div class="code">{url}</div>
<div class="msg">{msg}</div>
<p><a href="pilot://home">Home</a></p>
</body></html>"""

SETTINGS_HTML = """<!doctype html>
<html><head><title>Pilot Settings</title>
<style>
  body { font-family: sans-serif; margin: 40px 60px; color: #223; }
  h1 { color: #2b5d8f; }
  label { display: block; margin: 12px 0; }
  .row { margin: 14px 0; }
  input[type=text], input[type=number] { width: 300px; }
  kbd { background:#eef; padding: 1px 6px; border: 1px solid #ccd;
        border-radius: 3px; }
  .hint { color: #777; font-size: 14px; margin-left: 8px; }
</style></head>
<body>
<h1>Pilot Settings</h1>
<form id="f">
  <div class="row">Home page
    <input type="text" id="home_url"><span class="hint">pilot://home, about:blank, http(s) URL</span>
  </div>
  <div class="row">New tab page
    <input type="text" id="new_tab_url">
  </div>
  <div class="row">Default zoom
    <input type="number" id="zoom" step="0.1" min="0.2" max="3">
  </div>
  <div class="row">Theme
    <select id="theme">
      <option value="dark">Dark</option>
      <option value="light">Light</option>
    </select>
  </div>
  <label><input type="checkbox" id="status_bar"> Show status bar</label>
  <label><input type="checkbox" id="javascript"> Enable JavaScript</label>
  <label><input type="checkbox" id="image_loading"> Load images</label>
  <div class="row">UI font size <input type="number" id="ui_font_size" min="10" max="18"></div>
  <div class="row"><button id="save">Save</button>
    <button id="reset">Reset to defaults</button></div>
</form>
<script>
  var ids = ['home_url', 'new_tab_url', 'zoom', 'theme', 'status_bar',
             'javascript', 'image_loading', 'ui_font_size'];
  function load() {
    for (var i = 0; i < ids.length; i++) {
      var el = document.getElementById(ids[i]);
      var v = pilotSettings.get(ids[i]);
      if (el.type == 'checkbox') el.checked = v;
      else el.value = v;
    }
  }
  function save() {
    for (var i = 0; i < ids.length; i++) {
      var el = document.getElementById(ids[i]);
      var v = el.type == 'checkbox' ? el.checked : el.value;
      pilotSettings.set(ids[i], v);
    }
    pilotSettings.save();
    document.getElementById('saved').innerText = 'Saved ✓';
  }
  document.getElementById('save').onclick = save;
  document.getElementById('reset').onclick = function () {
    for (var i = 0; i < ids.length; i++) {
      var el = document.getElementById(ids[i]);
      var v = pilotSettings.get(ids[i], true);
      if (el.type == 'checkbox') el.checked = v;
      else el.value = v;
    }
    save();
  };
  load();
</script>
<div id="saved"></div>
<p><a href="pilot://home">← Home</a></p>
</body></html>"""


# ---------------------------------------------------------------------------
# Per-tab bridge used by the JS engine and the layout engine
# ---------------------------------------------------------------------------
class PageCtx:
    def __init__(self, tab):
        self.tab = tab

    def __getattr__(self, name):
        # Delegate to the backing Tab for Layout/JS-engine attributes.
        return getattr(self.tab, name)

    def browser(self):
        return self.tab.browser

    def video_for(self, node):
        return self.tab.video_state(node)

    def video_frame(self, node):
        st = self.tab.video_state(node)
        return st.first_frame() if st is not None else None

    def video_reload(self, node):
        self.tab.video_reload(node)

    # -- JS engine bridge ---------------------------------------------------
    def log(self, msg):
        self.tab.browser.dev_log(str(msg))

    def relayout(self):
        self.tab.relayout_pending = True
        self.tab.browser.invalidate()

    def navigate(self, url, replace=False):
        self.tab.browser.load_url(url, self.tab, replace=replace)

    def document_node(self):
        return self.tab.doc

    def base_url(self):
        return self.tab.url

    def viewport_w(self):
        return self.tab.viewport_w

    def viewport_h(self):
        return self.tab.viewport_h

    def box_for(self, node):
        if self.tab.layout is None:
            return None
        return self.tab.layout.node_rect(node)

    def focus_element(self, node):
        self.tab.browser.focus_page_input(self.tab, node)

    def blur_element(self, node):
        self.tab.browser.blur_page_input(self.tab)

    def focus_document(self):
        self.tab.browser.focus_page_input(self.tab, None)

    def has_document_focus(self):
        return True

    def scroll_to(self, node):
        self.tab.browser.scroll_to_node(self.tab, node)

    def scroll_to_hash(self, frag):
        if not frag:
            self.tab.scroll = 0
            self.tab.browser.invalidate()
            return
        node = self.tab.doc.find_by_id(frag)
        if node:
            self.tab.browser.scroll_to_node(self.tab, node)

    def ui_alert(self, msg):
        self.tab.browser.show_dialog("alert", msg)

    def ui_confirm(self, msg):
        return self.tab.browser.show_dialog("confirm", msg)

    def ui_prompt(self, msg, default=""):
        return self.tab.browser.show_dialog("prompt", msg, default)

    def history_back(self):
        self.tab.browser.go_back(self.tab)

    def history_forward(self):
        self.tab.browser.go_forward(self.tab)

    def history_go(self, n):
        for _ in range(abs(n)):
            if n > 0:
                self.tab.browser.go_forward(self.tab)
            else:
                self.tab.browser.go_back(self.tab)

    def load_img(self, url):
        return net.load_image(url)

    def title_changed(self):
        self.tab.browser.update_tab_titles()

    def document_obj(self):
        return self.tab.engine._wrap_document()

    def location_obj(self):
        return self.tab.engine.location_obj()


class Tab:
    def __init__(self, browser, url):
        self.browser = browser
        self.url = url or theme.HOME_URL
        self.title = "New Tab"
        self.doc = None
        self.layout = None
        self.engine = None
        self.ctx = PageCtx(self)
        self.rules = []
        self.visited = browser.visited
        self.back_stack = []
        self.fwd_stack = []
        self.scroll = 0.0
        self.zoom = 1.0
        self.relayout_pending = False
        self.viewport_w = 1
        self.viewport_h = 1
        self.hover_node = None
        self.hover_kind = None
        self.focus_node = None
        self.focus_cursor = 0
        self.focus_caret_on = True
        self.focus_blink_at = 0.0
        self.find_query = ""
        self.find_matches = []
        self.find_index = 0
        self.loading = False
        self.loaded_at = 0.0
        self.videos = {}

    # -- loading ------------------------------------------------------------
    def load(self, url, post_data=None):
        self.loading = True
        self.close_videos()
        self.browser.status(f"Loading {url}…", theme.TEXT_DIM)
        self.browser.invalidate()
        base = url
        # Built-in pilot:// scheme serves internal pages.
        if url.startswith("pilot://"):
            path = url[len("pilot://"):]
            if path == "" or path == "home":
                html = HOME_HTML
            elif path == "about":
                html = ABOUT_HTML
            elif path == "settings":
                html = SETTINGS_HTML
            else:
                html = ERROR_HTML.format(
                    title="Not Found", code="404",
                    url=url, msg=f"Unknown pilot:// page: {path}")
            self.doc = html5.parse(html)
            self.finish_load(url, None)
            return
        try:
            final_url, status_code, ctype, data = net.fetch(url,
                                                            post_data=post_data)
        except net.FetchError as exc:
            self.show_error(url, exc.status or 0, str(exc))
            return
        if status_code >= 400:
            self.show_error(final_url, status_code, "HTTP " + str(status_code))
            return
        base = final_url
        if not ctype.startswith("text/") and not ctype.startswith(
                ("image/",)) and not ctype.startswith(("application/xhtml",
                                                       "application/xml")):
            if ctype.startswith("image/"):
                self.show_error(final_url, 0, "Image content — right-click to save",
                                inline=True)
                self.doc = html5.parse(
                    f'<html><body style="text-align:center">'
                    f'<img src="{final_url}"></body></html>')
                self.finish_load(final_url, "Image")
                return
            self.save_download(final_url, ctype, data)
            self.show_error(final_url, 0,
                            f"Downloaded {os.path.basename(urllib.parse.urlparse(final_url).path) or 'file'}")
            return
        text = net.guess_encoding(data, ctype)
        self.doc = html5.parse(text)
        self.finish_load(final_url, None)

    def show_error(self, url, code, msg, inline=False):
        self.doc = html5.parse(ERROR_HTML.format(
            title=f"{code} Error" if code else "Error",
            code=code or "!", url=urllib.parse.unquote(url)[:80],
            msg=msg))
        self.finish_load(url, f"{code} — {msg}" if not inline else msg)

    def save_download(self, url, ctype, data):
        name = net.url_basename(url)
        path = os.path.join(os.path.expanduser("~/Downloads"), name)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            n = 1
            base, ext = os.path.splitext(path)
            while os.path.exists(path):
                path = f"{base} ({n}){ext}"
                n += 1
            with open(path, "wb") as fh:
                fh.write(data)
            self.browser.status(f"Saved {name} ({len(data)} bytes)", theme.OK_GREEN)
        except OSError as exc:
            self.browser.status(f"Save failed: {exc}", theme.ERR_RED)

    # -- video --------------------------------------------------------------
    def video_state(self, node):
        from .video import VideoState, available
        key = id(node)
        st = self.videos.get(key)
        if st is not None:
            return st
        src = node.get("src")
        if not src:
            return None
        if not available():
            return None
        from . import net as _net
        url = _net.resolve(self.url or "", src)
        st = VideoState(url)
        self.videos[key] = st
        return st

    def video_frame(self, node):
        st = self.video_state(node)
        if st is None:
            return None
        return st.first_frame()

    def video_reload(self, node):
        key = id(node)
        st = self.videos.get(key)
        if st is not None:
            st.close()
            del self.videos[key]

    def video_for(self, node):
        return self.video_state(node)

    def video_frame(self, node):
        st = self.video_state(node)
        return st.first_frame() if st is not None else None

    def close_videos(self):
        for st in self.videos.values():
            st.close()
        self.videos.clear()

    def finish_load(self, final_url, title):
        self.url = final_url
        self.visited.add(final_url.split("#")[0])
        # stylesheets
        rules = []
        for node, href, css_text, _line in self.doc.stylesheets:
            try:
                if href:
                    from . import net as _n
                    _u, _s, _ct, data = _n.fetch(_n.resolve(final_url, href))
                    css_text = _n.guess_encoding(data, _ct)
                rules.extend(css.parse_stylesheet(css_text))
            except Exception as exc:  # noqa: BLE001
                self.browser.status(f"CSS error: {exc}", theme.WARN_YELLOW)
        self.rules = rules
        # JS engine
        self.engine = js.JSEngine(self.ctx)
        for node in self.doc.walk():
            node.js_engine = self.engine
        # scripts in document order
        for node, src, code, line in self.doc.scripts:
            try:
                if src:
                    from . import net as _n
                    _u, _s, _ct, data = _n.fetch(_n.resolve(final_url, src))
                    code = _n.guess_encoding(data, _ct)
                self.engine.run(code or "", line, src or "<script>")
            except Exception as exc:  # noqa: BLE001
                self.browser.status(f"Script error: {exc}", theme.ERR_RED)
        self.title = title or self._doc_title()
        self.browser.update_tab_titles()
        self.layout_build()
        try:
            self.engine.emit_dom("DOMContentLoaded", {})
        except Exception:  # noqa: BLE001
            pass
        self.loading = False
        self.loaded_at = time.time()
        self.browser.status(f"Loaded {final_url} — {self._doc_title()}",
                            theme.TEXT_DIM)

    def _doc_title(self):
        if self.doc is None:
            return ""
        titles = self.doc.find_all("title")
        return titles[0].text_content() if titles else ""

    def layout_build(self):
        from .layout import Layout
        self.layout = Layout(self.doc, self.viewport_w, self.ctx)
        self.layout.viewport_h = self.viewport_h
        self.layout.build()

    def max_scroll(self):
        if self.layout is None or self.layout.root is None:
            return 0.0
        return max(0.0, self.layout.root.h - self.viewport_h)

    def clamp_scroll(self):
        self.scroll = max(0.0, min(self.scroll, self.max_scroll()))

    def go_back(self, browser):
        if self.back_stack:
            self.fwd_stack.append(self.url)
            url = self.back_stack.pop()
            browser.load_url(url, self)

    def go_forward(self, browser):
        if self.fwd_stack:
            self.back_stack.append(self.url)
            url = self.fwd_stack.pop()
            browser.load_url(url, self)


# ---------------------------------------------------------------------------
# Pilot browser window (customtkinter frontend)
# ---------------------------------------------------------------------------
class Pilot:
    def __init__(self, start_url=None):
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.title("Pilot")
        self.root.geometry(f"{theme.SIZE_W}x{theme.SIZE_H}")

        self.settings = settings_mod.Settings()
        settings_mod.apply_to_theme()
        self.win_w = theme.SIZE_W
        self.win_h = theme.SIZE_H

        # The framebuffer display: a tk.Label showing the rendered Pillow image.
        self._image_label = tk.Label(self.root, bg="#1a1d23", bd=0, highlightthickness=0)
        self._image_label.pack(fill="both", expand=True)
        self._tk_image = None
        self._renderer = None

        self.tabs: list = []
        self.active = 0
        self.visited = set()
        self.status_text = ""
        self.status_color = theme.TEXT_DIM
        self.status_until = 0.0
        self.mode = "page"      # page | addr | find | dialog
        self.dialog = None
        self.menu = None
        self.drag_scrollbar = False
        self._dirty = True
        self._last_key = (0, 0.0)
        self._last_key_time = 0.0
        self.running = True
        self._last_layout = (0, 0)
        self.status_bar = ui.StatusBar()
        self.dev_open = False
        self.dev_tab = "console"
        self.dev_lines = []
        self.dev_input = ""
        self.dev_mode = False
        self.dev_scroll = 0
        self.dev_history = []
        self.dev_hist_idx = 0
        self.net_log = []
        net.set_observer(self._net_observe)

        self._init_graphics()
        self._init_widgets()
        self._bind_events()
        self._new_tab(start_url or self.settings.get("home_url"))
        self.redraw()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _bind_events(self):
        self.root.bind("<KeyPress>", self._on_key)
        self.root.bind("<Button-1>", lambda e: self._on_button_press(e, 1))
        self.root.bind("<Button-3>", lambda e: self._on_button_press(e, 3))
        self.root.bind("<Button-4>", lambda e: self._on_button_press(e, 4))
        self.root.bind("<Button-5>", lambda e: self._on_button_press(e, 5))
        self.root.bind("<ButtonRelease-1>", self._on_button_release)
        self.root.bind("<Motion>", self._on_motion)
        self.root.bind("<Configure>", self._on_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._image_label.bind("<KeyPress>", self._on_key)
        self._image_label.bind("<Button-1>", lambda e: self._on_button_press(e, 1))
        self._image_label.bind("<Button-3>", lambda e: self._on_button_press(e, 3))
        self._image_label.bind("<Button-4>", lambda e: self._on_button_press(e, 4))
        self._image_label.bind("<Button-5>", lambda e: self._on_button_press(e, 5))
        self._image_label.bind("<Motion>", self._on_motion)
        self._image_label.focus_set()

    def _on_close(self):
        self.running = False
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _init_graphics(self):
        self.font_ui = theme.font("sans", "normal", "normal", 13)
        self.font_ui_b = theme.font("sans", "bold", "normal", 13)
        self.font_mono = theme.font("mono", "normal", "normal", 12)
        self._new_renderer(self.win_w, self.win_h)

    def _new_renderer(self, width, height):
        from .render import Renderer
        self._renderer = Renderer(width, height)

    def _init_widgets(self):
        def btn(label, action, hint=""):
            b = ui.Button(label, action, hint, font=self.font_ui)
            return b
        self.buttons = [
            btn("←", "back", "Back (Alt+Left)"),
            btn("→", "forward", "Forward (Alt+Right)"),
            btn("↻", "reload", "Reload (F5)"),
            btn("⌂", "home", "Home"),
            btn("⚙", "settings", "Settings (Ctrl+,)"),
        ]
        self.addr = ui.TextField("Search or enter address", font=self.font_ui)
        self.addr_b = ui.Button("Go", "addr_go")
        self.tabbar = ui.TabBar()
        self.find_bar = ui.FindBar(font=self.font_ui)
        self.find_bar.input.font = self.font_ui

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _new_tab(self, url):
        tab = Tab(self, url)
        self.tabs.append(tab)
        self.active = len(self.tabs) - 1
        self.load_url(url, tab)
        self.mode = "page"
        self.addr.focus = False
        self._update_addr()
        self.invalidate()

    def _close_tab(self, idx):
        if len(self.tabs) <= 1:
            self.running = False
            try:
                self.root.destroy()
            except Exception:  # noqa: BLE001
                pass
            return
        self.tabs.pop(idx)
        if self.active >= len(self.tabs):
            self.active = len(self.tabs) - 1
        elif idx < self.active:
            self.active -= 1
        self.invalidate()

    def active_tab(self):
        if 0 <= self.active < len(self.tabs):
            return self.tabs[self.active]
        return None

    def update_tab_titles(self):
        """Sync Tab titles to the TabBar display list."""
        bar = self.tabbar
        # Ensure the bar has one entry per tab.
        while len(bar.tabs) < len(self.tabs):
            bar.tabs.append({"label": "New Tab", "title": "", "url": ""})
        while len(bar.tabs) > len(self.tabs):
            bar.tabs.pop()
        for i, tab in enumerate(self.tabs):
            bar.tabs[i]["title"] = tab.title or "New Tab"
            bar.tabs[i]["url"] = tab.url
            bar.tabs[i]["label"] = tab.title or "New Tab"
        self.invalidate()

    def invalidate(self):
        """Mark the frame as needing a redraw."""
        self._dirty = True

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def redraw(self):
        """Render one frame into the Pillow framebuffer and show it."""
        tab = self.active_tab()
        if tab and (self._renderer.width != self.win_w or
                    self._renderer.height != self.win_h):
            self._new_renderer(self.win_w, self.win_h)
            tab.relayout_pending = True

        r = self._renderer
        r.begin_frame()
        # page area
        py = theme.TABBAR_H + theme.NAVBAR_H
        if tab:
            vw = self.win_w
            vh = max(1, self.win_h - theme.TABBAR_H - theme.NAVBAR_H -
                     theme.STATUSBAR_H - self.dev_h() -
                     (theme.FIND_H + 8 if self.find_bar.visible else 0))
            if tab.viewport_w != vw or tab.viewport_h != vh or \
                    tab.relayout_pending:
                tab.viewport_w = vw
                tab.viewport_h = vh
                tab.layout_build()
            self._layout_chrome()
            r.rect(0, py, self.win_w,
                   self.win_h - py - theme.STATUSBAR_H - self.dev_h(),
                   theme.BG)
            self._paint_page(r, tab, py)
        # chrome
        self._draw_tabbar(r)
        self._draw_navbar(r)
        self._draw_statusbar(r)
        if self.find_bar.visible:
            self._draw_findbar(r)
        if self.dev_open:
            self._draw_devtools(r)
        if self.menu:
            self._draw_menu(r)
        if self.dialog and self.mode == "dialog":
            self.dialog.render(r, self.win_w, self.win_h)
        # upload to CTkLabel
        self._push_frame()

    def _push_frame(self):
        """Upload the rendered Pillow framebuffer to the tk.Label."""
        img = self._renderer.img
        tk_img = ImageTk.PhotoImage(img)
        self._tk_image = tk_img  # keep a reference (tkinter needs this)
        self._image_label.configure(image=tk_img)

    # ------------------------------------------------------------------
    # Chrome layout helpers (adapted from X11 version)
    # ------------------------------------------------------------------
    def _layout_chrome(self, force=False):
        if not force and (self.win_w, self.win_h) == self._last_layout:
            return
        self._last_layout = (self.win_w, self.win_h)
        x = theme.PAD
        y = theme.TABBAR_H + (theme.NAVBAR_H - theme.BTN_H) // 2
        for b in self.buttons:
            bw = self._renderer.text_w(b.label, self.font_ui) + 18
            b.set_bounds(x, y, bw, theme.BTN_H)
            x += bw + 4
        self.addr.set_bounds(x, y, self.win_w - x - 46, theme.ADDRBAR_H)
        self.addr_b.set_bounds(self.win_w - 42, y, 36, theme.BTN_H)
        self.find_bar.set_bounds(theme.PAD, theme.TABBAR_H + theme.NAVBAR_H + 4,
                                 min(340, self.win_w - 2 * theme.PAD),
                                 theme.FIND_H)
        tab = self.active_tab()
        if tab:
            tab.viewport_w = self.win_w
            tab.viewport_h = max(1, self.win_h - theme.TABBAR_H -
                                 theme.NAVBAR_H - theme.STATUSBAR_H -
                                 self.dev_h() -
                                 (theme.FIND_H + 8 if self.find_bar.visible
                                  else 0))

    def dev_h(self):
        return 190 if self.dev_open else 0

    def dev_y(self):
        return self.win_h - theme.STATUSBAR_H - self.dev_h()

    # ------------------------------------------------------------------
    # Painting (same as X11 version, operates on the Pillow renderer)
    # ------------------------------------------------------------------
    def _paint_page(self, r, tab, py):
        if not tab.layout:
            return
        r.push_clip(0, py, tab.viewport_w, tab.viewport_h)
        ox = 0
        oy = py - int(tab.scroll)
        tab.layout.paint(r, ox, oy, py)
        # focused input caret
        if tab.focus_node and tab.focus_node.tag_name() in ("input", "textarea") \
                and tab.focus_caret_on:
            self._paint_caret(r, tab, py, oy)
        # find highlights
        if tab.find_query:
            q = tab.find_query.lower()
            for line in tab.layout.all_lines():
                for run in line.runs:
                    if run.kind == "text" and q in run.text.lower():
                        r.rect(run.x - ox, run.y + oy, run.w, run.h,
                               (255, 224, 64))
                        r.text(run.x - ox, run.y + oy, run.text,
                               run.color, run.font)
        self._draw_scrollbar(r, tab, py)
        r.pop_clip()

    def _paint_caret(self, r, tab, py, oy):
        node = tab.focus_node
        rect = tab.layout.node_rect(node)
        if not rect:
            return
        x, y, w, h = rect
        font = self.font_ui
        val = node.get("value", "")
        caret_w = r.text_w(val[:tab.focus_cursor], font)
        cy = y + oy + 2
        r.vline(x + 6 + caret_w, cy, max(6, h - 8), (200, 40, 40))

    def _draw_scrollbar(self, r, tab, py):
        maxs = tab.max_scroll()
        if maxs <= 0:
            return
        vh = tab.viewport_h
        track = vh - 4
        thumb_h = max(24, int(track * vh / (vh + maxs)))
        frac = tab.scroll / maxs
        ty = py + 2 + int((track - thumb_h) * frac)
        sx = self.win_w - theme.SCROLL_W
        r.rect(sx, py, theme.SCROLL_W, vh, theme.PANEL)
        r.rect(sx + 1, ty, theme.SCROLL_W - 2, thumb_h, theme.SCROLL_THUMB)

    def _draw_tabbar(self, r):
        r.rect(0, 0, self.win_w, theme.TABBAR_H, theme.PANEL)
        r.hline(0, theme.TABBAR_H - 1, self.win_w, theme.PANEL_LINE)
        self.tabbar.render(r, self.font_ui)

    def _draw_navbar(self, r):
        y = theme.TABBAR_H
        r.rect(0, y, self.win_w, theme.NAVBAR_H, theme.PANEL)
        r.hline(0, y + theme.NAVBAR_H - 1, self.win_w, theme.PANEL_LINE)
        for b in self.buttons:
            b.render(r, self.font_ui)
        self.addr.render(r)
        self.addr_b.render(r, self.font_ui)

    def _draw_findbar(self, r):
        self.find_bar.render(r)

    def _draw_statusbar(self, r):
        tab = self.active_tab()
        self.status_bar.color = self.status_color
        parts = []
        if tab:
            if tab.loading:
                parts.append("…")
            parts.append(f"{(tab.scroll / tab.max_scroll() * 100) if tab.max_scroll() else 0:.0f}%")
            parts.append(f"{int(tab.zoom * 100)}%")
            if tab.find_query:
                parts.append(f"find {tab.find_index + 1}/{len(tab.find_matches)}")
        self.status_bar.right = "  ·  ".join(parts)
        self.status_bar.render(r, self.win_w, self.win_h, self.font_ui)

    def _draw_devtools(self, r):
        dy = self.dev_y()
        h = self.dev_h()
        r.rect(0, dy, self.win_w, h, theme.PANEL)
        r.hline(0, dy, self.win_w, theme.PANEL_LINE)
        x = 8
        for label, key in (("Console", "console"), ("Elements", "elements"),
                           ("Network", "network"), ("Sources", "sources")):
            w = r.text_w(label, self.font_ui) + 16
            if self.dev_tab == key:
                r.rect(x, dy + 2, w, 20, theme.SELECT_FOC)
            r.text(x + 8, dy + 4, label,
                   theme.TEXT if self.dev_tab == key else theme.TEXT_DIM,
                   self.font_ui)
            x += w
        body_y = dy + 26
        r.rect(0, body_y, self.win_w, h - 26, (20, 22, 26))
        if self.dev_tab == "console":
            self._draw_dev_console(r, body_y)
        elif self.dev_tab == "elements":
            self._draw_dev_elements(r, body_y)
        elif self.dev_tab == "network":
            self._draw_dev_network(r, body_y)
        elif self.dev_tab == "sources":
            self._draw_dev_sources(r, body_y)

    def _draw_dev_console(self, r, body_y):
        h = self.dev_h() - 26
        n = max(1, (h - 4) // 16)
        start = max(0, len(self.dev_lines) - n - self.dev_scroll)
        y = body_y + 2
        for i in range(start, min(len(self.dev_lines), start + n)):
            line = self.dev_lines[i]
            color = theme.TEXT
            if line.startswith("⚠"):
                color = (255, 200, 80)
            elif line.startswith("✖"):
                color = (255, 110, 110)
            r.text(6, y, line[:130], color, self.font_mono)
            y += 16
        r.hline(0, self.dev_y() + self.dev_h() - 22, self.win_w, (60, 64, 72))
        prompt = "› " + self.dev_input
        if self.dev_mode and int(time.time() * 2) % 2 == 0:
            prompt += "▍"
        r.text(6, self.dev_y() + self.dev_h() - 18, prompt,
               theme.TEXT, self.font_mono)

    def _draw_dev_elements(self, r, body_y):
        tab = self.active_tab()
        if not tab or tab.doc is None:
            return
        h = self.dev_h() - 26
        n = max(1, (h - 4) // 14)
        lines = []
        def walk(node, depth):
            if node.is_comment:
                return
            tag = node.tag_name()
            if tag:
                line = "  " * depth + "<" + tag
                for k, v in list(node.attrs.items())[:6]:
                    line += f" {k}=\"{v}\""
                lines.append(line + ">")
            elif node.text and node.text.strip():
                lines.append("  " * depth + repr(node.text.strip()[:60]))
            for c in node.children:
                walk(c, depth + 1)
        walk(tab.doc, 0)
        start = max(0, len(lines) - n - self.dev_scroll)
        y = body_y + 2
        for i in range(start, min(len(lines), start + n)):
            r.text(6, y, lines[i][:120], theme.TEXT, self.font_mono)
            y += 14

    def _draw_dev_network(self, r, body_y):
        h = self.dev_h() - 26
        n = max(1, (h - 4) // 14)
        start = max(0, len(self.net_log) - n - self.dev_scroll)
        y = body_y + 2
        for i in range(start, min(len(self.net_log), start + n)):
            method, url, status, ms, size = self.net_log[i]
            color = (120, 255, 120) if status < 400 else (255, 110, 110)
            r.text(6, y,
                   f"{method:4} {status:<4} {ms:6.0f}ms {size:>8}B  {url[:100]}",
                   color, self.font_mono)
            y += 14

    def _draw_dev_sources(self, r, body_y):
        tab = self.active_tab()
        if not tab or tab.doc is None:
            r.text(6, body_y + 2, "(no page loaded)", theme.TEXT_DIM,
                   self.font_mono)
            return
        h = self.dev_h() - 26
        n = max(1, (h - 4) // 14)
        lines = []
        for node, src, code, line in tab.doc.scripts:
            if src:
                lines.append(f"// {src}")
            if code:
                for i, c in enumerate(code.splitlines(), 1):
                    lines.append(f"{line + i - 1:4}  {c}")
        if not lines:
            lines = ["(no scripts)"]
        start = max(0, len(lines) - n - self.dev_scroll)
        y = body_y + 2
        for i in range(start, min(len(lines), start + n)):
            r.text(6, y, lines[i][:140], theme.TEXT, self.font_mono)
            y += 14

    def _draw_menu(self, r):
        m = self.menu
        r.rect(m["x"], m["y"], m["w"], m["h"], theme.PANEL)
        r.outline(m["x"], m["y"], m["w"], m["h"], theme.PANEL_LINE)
        y = m["y"]
        for i, (label, action, hint) in enumerate(m["items"]):
            if not action:
                r.hline(m["x"] + 8, y + 12, m["w"] - 16, theme.PANEL_LINE)
                y += 26
                continue
            if i == m["index"]:
                r.rect(m["x"] + 2, y, m["w"] - 4, 26, theme.SELECT_FOC)
            r.text(m["x"] + 10, y + 5, label,
                   theme.TEXT if action else theme.TEXT_FAINT, self.font_ui)
            if hint:
                r.text(m["x"] + m["w"] - 10, y + 5, hint, theme.TEXT_FAINT,
                       self.font_ui, anchor="ra")
            y += 26

    # ------------------------------------------------------------------
    # Network observer
    # ------------------------------------------------------------------
    def _net_observe(self, method, url, status, ms, size):
        self.net_log.append((method, url, status, ms, size))
        del self.net_log[:-300]
        if self.dev_open:
            self.invalidate()

    def dev_log(self, msg):
        self.dev_lines.append(str(msg))
        del self.dev_lines[:-600]
        if self.dev_open:
            self.invalidate()

    # ------------------------------------------------------------------
    # Address bar
    # ------------------------------------------------------------------
    def _update_addr(self):
        tab = self.active_tab()
        self.addr.set_text(tab.url if tab else "")

    def status(self, msg, color=theme.TEXT_DIM, until=0.0):
        self.status_text = msg
        self.status_color = color
        self.status_until = time.time() + until if until else 0.0
        self.invalidate()

    # ------------------------------------------------------------------
    # URL loading
    # ------------------------------------------------------------------
    def load_url(self, url, tab=None, replace=False):
        if tab is None:
            tab = self.active_tab()
        if tab is None:
            return
        tab.load(url)

    def go_back(self, tab=None):
        if tab is None:
            tab = self.active_tab()
        if tab:
            tab.go_back(self)

    def go_forward(self, tab=None):
        if tab is None:
            tab = self.active_tab()
        if tab:
            tab.go_forward(self)

    def reload(self):
        tab = self.active_tab()
        if tab:
            tab.load(tab.url)

    def home(self):
        self.load_url(self.settings.get("home_url"))

    def zoom(self, delta):
        tab = self.active_tab()
        if tab:
            tab.zoom = max(theme.ZOOM_MIN / 16.0,
                           min(theme.ZOOM_MAX / 16.0, tab.zoom + delta))
            tab.layout_build()
            self.invalidate()

    # ------------------------------------------------------------------
    # Page interaction
    # ------------------------------------------------------------------
    def page_hit(self, x, y):
        tab = self.active_tab()
        if not tab or not tab.layout:
            return None, None
        ly = y - theme.TABBAR_H - theme.NAVBAR_H + int(tab.scroll)
        return tab.layout.hit(x, ly)

    def on_page_click(self, x, y, button):
        tab = self.active_tab()
        if not tab:
            return
        node, kind = self.page_hit(x, y)
        if button == 4:  # wheel up
            tab.scroll -= 3 * 14
            tab.clamp_scroll()
            self.invalidate()
            return
        if button == 5:
            tab.scroll += 3 * 14
            tab.clamp_scroll()
            self.invalidate()
            return
        if button == 6:
            return
        if button == 7:
            return
        if button == 8:
            self.go_back(tab)
            return
        if button == 9:
            self.go_forward(tab)
            return
        if button == 3:
            self.open_menu(x, y)
            return
        if button != 1:
            return
        # clear page focus unless clicking an input
        was_focus = tab.focus_node
        if node is None:
            self.blur_page_input(tab)
            return
        tag = node.tag_name()

        if tag == "video":
            st = tab.video_state(node)
            if st is not None:
                st.toggle(self)
                self.invalidate()
            return

        if tag == "a":
            href = node.get("href", "")
            ev_data = {"clientX": x, "clientY": y, "button": 0}
            proceed = True
            if node.js_engine:
                proceed = node.js_engine.emit(node, "click", ev_data)
            if proceed and href:
                if href.startswith("#"):
                    tab.ctx.scroll_to_hash(href[1:])
                elif node.get("target", "").lower() == "_blank":
                    from . import net as _n
                    self._new_tab(_n.resolve(tab.url, href))
                else:
                    from . import net as _n
                    self.load_url(_n.resolve(tab.url, href), tab)
            self.invalidate()
            return

        if tag == "input":
            t = node.get("type", "text").lower()
            if t in ("checkbox", "radio"):
                if t == "radio":
                    self._clear_radio_group(node)
                if node.get("checked") is not None:
                    node.attrs.pop("checked", None)
                else:
                    node.set("checked", "checked")
                tab.relayout_pending = True
                if node.js_engine:
                    node.js_engine.emit(node, "click", {})
                    node.js_engine.emit(node, "change", {})
                self.invalidate()
                return
            if t in ("button", "submit", "reset"):
                if node.js_engine:
                    node.js_engine.emit(node, "click", {})
                if t == "submit":
                    self._submit_form(node)
                elif t == "reset":
                    self._reset_form(node)
                return
            if t in ("text", "password", "search", "email", "url",
                     "number", "tel", "date", "time"):
                self.focus_page_input(tab, node)
                rect = tab.layout.node_rect(node)
                if rect:
                    rel = x - rect[0] - 6
                    font = self.font_ui
                    val = node.get("value", "")
                    best, bd = 0, 10 ** 9
                    for i in range(len(val) + 1):
                        d = abs(font.getbbox(val[:i])[2] - rel)
                        if d < bd:
                            bd, best = d, i
                    tab.focus_cursor = best
                self.invalidate()
                return
            return

        if tag == "textarea":
            self.focus_page_input(tab, node)
            self.invalidate()
            return

        if tag == "select":
            opts = node.find_all("option")
            if opts:
                box = tab.layout.node_rect(node)
                idx = 0
                for i, o in enumerate(opts):
                    if o.get("selected") is not None:
                        idx = i
                idx = (idx + 1) % len(opts)
                for i, o in enumerate(opts):
                    if i == idx:
                        o.set("selected", "selected")
                    else:
                        o.attrs.pop("selected", None)
                if node.js_engine:
                    node.js_engine.emit(node, "click", {})
                    node.js_engine.emit(node, "change",
                                        {"value": opts[idx].text_content()})
                tab.relayout_pending = True
                self.invalidate()
            return

        if tag == "button":
            if node.js_engine:
                node.js_engine.emit(node, "click", {})
            self.invalidate()
            return

        if node.js_engine and self._has_js(node, "click"):
            node.js_engine.emit(node, "click",
                                {"clientX": x, "clientY": y, "button": 0})
            self.invalidate()
            return
        if was_focus and node is not was_focus:
            self.blur_page_input(tab)

    def _clear_radio_group(self, node):
        form = node
        while form.parent and form.tag_name() != "form":
            form = form.parent
        name = node.get("name")
        if not name:
            return
        for n in form.elements():
            if n.tag_name() == "input" and n.get("type") == "radio" and \
                    n.get("name") == name and n is not node:
                n.attrs.pop("checked", None)

    def _reset_form(self, node):
        form = node
        while form.parent and form.tag_name() != "form":
            form = form.parent
        for n in form.elements():
            if n.tag_name() != "input":
                continue
            t = n.get("type", "text").lower()
            if t in ("checkbox", "radio"):
                if n.get("checked") is not None and t == "checkbox":
                    pass
                n.attrs.pop("checked", None)
            elif t in ("text", "password", "search", "email", "url", "number"):
                default = n.get("value", "")
                n.set("value", default)
        tab = self.active_tab()
        if tab:
            tab.relayout_pending = True
            self.invalidate()

    def _submit_form(self, button_node):
        form = button_node
        while form.parent and form.tag_name() != "form":
            form = form.parent
        if form.tag_name() != "form":
            return
        action = form.get("action", "") or ""
        method = form.get("method", "get").lower()
        from . import net as _n
        base = self.active_tab().url if self.active_tab() else ""
        url = _n.resolve(base, action) if action else base
        fields = []
        for n in form.elements():
            if n.tag_name() != "input":
                continue
            t = n.get("type", "text").lower()
            name = n.get("name")
            if not name:
                continue
            if t in ("checkbox", "radio"):
                if n.get("checked") is not None:
                    fields.append((name, n.get("value", "on")))
            elif t not in ("button", "submit", "reset", "image"):
                fields.append((name, n.get("value", "")))
        for n in form.elements():
            if n.tag_name() == "textarea" and n.get("name"):
                fields.append((n.get("name"), n.get("value", "")))
            if n.tag_name() == "select" and n.get("name"):
                sel = [c for c in n.children if c.is_element and
                       c.tag_name() == "option" and c.get("selected") is not None]
                fields.append((n.get("name"),
                               (sel[0].get("value") or
                                sel[0].text_content().strip()) if sel else ""))
        query = urllib.parse.urlencode(fields)
        if method == "post":
            self._load_post(self.active_tab(), url, query.encode())
        else:
            self.load_url(url + (("?" + query) if query else ""),
                          self.active_tab())

    def _load_post(self, tab, url, body):
        tab.back_stack.append(tab.url)
        tab.fwd_stack.clear()
        tab.focus_node = None
        tab.load(url, post_data=body)
        self._update_addr()

    # ------------------------------------------------------------------
    # Focus management
    # ------------------------------------------------------------------
    def focus_page_input(self, tab, node):
        if tab.focus_node is node:
            return
        self.blur_page_input(tab)
        tab.focus_node = node
        tab.focus_cursor = len(node.get("value", ""))
        tab.focus_caret_on = True
        tab.focus_blink_at = 0.0
        self.invalidate()

    def blur_page_input(self, tab):
        tab.focus_node = None
        self.invalidate()

    # ------------------------------------------------------------------
    # Dialogs (alert / confirm / prompt)
    # ---------------------------------------------------------------------------
    MENU_ITEMS = [
        ("Back", "back", "Alt+Left"),
        ("Forward", "forward", "Alt+Right"),
        ("Reload", "reload", "F5"),
        ("", "", ""),
        ("New Tab", "new_tab", "Ctrl+T"),
        ("Duplicate Tab", "dup_tab", ""),
        ("Close Tab", "close_tab", "Ctrl+W"),
        ("", "", ""),
        ("Copy Address", "copy_addr", ""),
        ("Paste Address", "paste_addr", ""),
        ("", "", ""),
        ("Zoom In", "zoom_in", "Ctrl+="),
        ("Zoom Out", "zoom_out", "Ctrl+-"),
        ("Reset Zoom", "zoom_reset", "Ctrl+0"),
        ("", "", ""),
        ("Find in Page", "find", "Ctrl+F"),
        ("Home", "home", ""),
        ("About Pilot", "about", ""),
        ("Quit", "quit", "Ctrl+Q"),
    ]

    def open_menu(self, x, y):
        w = 230
        h = len(self.MENU_ITEMS) * 26
        self.menu = {"items": self.MENU_ITEMS, "x": min(x, self.win_w - w - 4),
                     "y": min(y, self.win_h - h - 4), "w": w, "h": h,
                     "index": None}
        self.mode = "menu"
        self.invalidate()

    def close_menu(self):
        self.menu = None
        self.mode = "page"
        self.invalidate()

    def menu_item_at(self, x, y):
        m = self.menu
        if not m or not (m["x"] <= x < m["x"] + m["w"] and
                         m["y"] <= y < m["y"] + m["h"]):
            return None
        idx = int((y - m["y"]) // 26)
        if 0 <= idx < len(m["items"]):
            return idx
        return None

    def _menu_activate(self, idx):
        items = self.menu["items"]
        self.menu = None
        if not (0 <= idx < len(items)):
            return
        label, action, hint = items[idx]
        if not action:
            return
        self._do_menu(action)
        self.invalidate()

    def _do_menu(self, action):
        tab = self.active_tab()
        if action == "back":
            self.go_back(tab)
        elif action == "forward":
            self.go_forward(tab)
        elif action == "reload":
            self.reload()
        elif action == "new_tab":
            self._new_tab(self.settings.get("new_tab_url") or
                          self.settings.get("home_url"))
        elif action == "dup_tab":
            if tab:
                self._new_tab(tab.url)
        elif action == "close_tab":
            self._close_tab(self.active)
        elif action == "copy_addr":
            if tab:
                self._x_copy(tab.url)
        elif action == "paste_addr":
            self._enter_addr(self._x_paste())
        elif action == "zoom_in":
            self.zoom(0.2)
        elif action == "zoom_out":
            self.zoom(-0.2)
        elif action == "zoom_reset":
            if tab:
                tab.zoom = 1.0
                tab.layout_build()
        elif action == "find":
            self.find_toggle()
        elif action == "home":
            self.home()
        elif action == "settings":
            self.load_url("pilot://settings")
        elif action == "about":
            self.load_url("pilot://about")
        elif action == "addr_go":
            self.load_url(self.addr.text)
        elif action == "quit":
            self.running = False

    def show_dialog(self, kind, message, default=""):
        d = ui.Dialog(kind, message, default, font=self.font_ui,
                      font_b=self.font_ui_b)
        if kind == "prompt":
            d.input.focus = True
        self.dialog = d
        self.mode = "dialog"
        self.invalidate()
        while self.running and self.dialog is d:
            self._tick()
            if self._dirty:
                self.redraw()
                self._dirty = False
            time.sleep(0.005)
            self.root.update_idletasks()
        return d.result

    def _dialog_confirm(self):
        d = self.dialog
        if not d:
            return
        if d.kind == "prompt":
            d.result = d.input.text
        else:
            d.result = True
        self.mode = "page"
        self.dialog = None
        self.invalidate()

    def _dialog_cancel(self):
        d = self.dialog
        if not d:
            return
        if d.kind == "confirm":
            d.result = False
        elif d.kind == "prompt":
            d.result = None
        else:
            d.result = True
        self.mode = "page"
        self.dialog = None
        self.invalidate()

    # ------------------------------------------------------------------
    # Event handlers (customtkinter)
    # ------------------------------------------------------------------
    def _on_key(self, event):
        # Only handle keys when the image label has focus (page mode)
        ks = event.keysym
        state = event.state
        ctrl = bool(state & 0x0004)
        alt = bool(state & 0x0008)
        shift = bool(state & 0x0001)
        ch = event.char or ""
        if len(ch) > 1 or not ch.isprintable():
            ch = ""

        if self.mode == "dialog" and self.dialog:
            self._key_dialog(ks, ch, ctrl)
            return
        if self.mode == "menu" and self.menu:
            self._key_menu(ks)
            return
        if self.mode == "find":
            self._key_find(ks, ch, ctrl)
            return
        if self.mode == "addr":
            self._key_addr(ks, ch, ctrl, shift)
            return
        if self.dev_open and self.dev_mode:
            self._key_dev(ks, ch, ctrl, shift, False)
            return
        self._key_page(ks, ch, ctrl, alt, shift, False)
        return "break"

    def _on_button_press(self, event, button):
        x, y = event.x, event.y
        if self.mode == "dialog" and self.dialog:
            d = self.dialog
            if d.ok_btn.contains(x, y):
                self._dialog_confirm()
            elif d.cancel_btn and d.cancel_btn.contains(x, y):
                self._dialog_cancel()
            elif d.input and d.input.contains(x, y):
                d.input.focus = True
                d.input.mouse_down(x, y)
            else:
                d.ok_btn.hover = False
                if d.cancel_btn:
                    d.cancel_btn.hover = False
            return
        if self.mode == "menu" and self.menu:
            idx = self.menu_item_at(x, y)
            if idx is not None and button == 1:
                self._menu_activate(idx)
            elif button == 3 or idx is None:
                self.close_menu()
            return

        # tab bar
        if y < theme.TABBAR_H:
            hit = self.tabbar.hit(x, y)
            if hit:
                kind, idx = hit
                if kind == "tab":
                    self.active = idx
                    self.update_tab_titles()
                    self._update_addr()
                    self.mode = "page"
                    self.invalidate()
                elif kind == "close":
                    self._close_tab(idx)
                elif kind == "plus":
                    self._new_tab(self.settings.get("new_tab_url") or
                                  self.settings.get("home_url"))
            return

        # navbar
        if y < theme.TABBAR_H + theme.NAVBAR_H:
            for b in self.buttons:
                if b.contains(x, y):
                    self._do_menu(b.action)
                    return
            if self.addr.contains(x, y):
                self.mode = "addr"
                self.addr.focus = True
                if button == 3:
                    self.open_menu(x, y)
                return
            if self.addr_b.contains(x, y):
                self.mode = "page"
                self.addr.focus = False
                self.load_url(self.addr.text)
                return
            return

        # find bar
        if self.find_bar.visible and y < theme.TABBAR_H + theme.NAVBAR_H + \
                theme.FIND_H + 8:
            if self.find_bar.input.contains(x, y):
                self.mode = "find"
                self.find_bar.input.focus = True
                self.find_bar.input.mouse_down(x, y, bool(state & 0x0001))
            return

        # scrollbar drag
        tab = self.active_tab()
        if tab and tab.max_scroll() > 0 and \
                x >= self.win_w - theme.SCROLL_W and \
                y >= theme.TABBAR_H + theme.NAVBAR_H and \
                y < self.win_h - theme.STATUSBAR_H - self.dev_h():
            self.drag_scrollbar = True
            self._scrollbar_to(y)
            return

        # devtools panel
        if self.dev_open and y >= self.dev_y():
            if button == 4:
                self.dev_scroll = min(self.dev_scroll + 2, 500)
            elif button == 5:
                self.dev_scroll = max(0, self.dev_scroll - 2)
            else:
                self._dev_click(x, y)
            self.invalidate()
            return

        # page
        self.on_page_click(x, y, button)

    def _on_button_release(self, event):
        self.drag_scrollbar = False
        self.addr.mouse_up()
        self.find_bar.input.mouse_up()

    def _on_motion(self, event):
        x, y = event.x, event.y
        tab = self.active_tab()
        changed = False
        if self.drag_scrollbar:
            self._scrollbar_to(y)
            return
        for b in self.buttons:
            hov = b.contains(x, y)
            if hov != b.hover:
                b.hover = hov
                changed = True
        if self.addr_b.contains(x, y) != self.addr_b.hover:
            self.addr_b.hover = not self.addr_b.hover
            changed = True
        if self.mode == "menu" and self.menu:
            idx = self.menu_item_at(x, y)
            if idx != self.menu["index"]:
                self.menu["index"] = idx
                changed = True
        # page hover
        if tab and y >= theme.TABBAR_H + theme.NAVBAR_H and \
                y < self.win_h - theme.STATUSBAR_H:
            node, kind = self.page_hit(x, y)
            if node is not tab.hover_node:
                tab.hover_node = node
                tab.hover_kind = kind
                changed = True
                if node and node.tag_name() == "a" and node.get("href"):
                    from . import net as _n
                    self.status(_n.resolve(tab.url, node.get("href")),
                                theme.ACCENT_HOT)
                else:
                    self.status("", theme.TEXT_DIM)
                try:
                    if node and node.tag_name() == "a":
                        self._image_label.configure(cursor="hand2")
                    else:
                        self._image_label.configure(cursor="")
                except Exception:  # noqa: BLE001
                    pass
        if changed:
            self.invalidate()

    def _on_configure(self, event):
        if (event.width, event.height) != (self.win_w, self.win_h):
            self.win_w = max(480, event.width)
            self.win_h = max(300, event.height)
            self._new_renderer(self.win_w, self.win_h)
            tab = self.active_tab()
            if tab:
                tab.layout_build()
            self.invalidate()

    def _scrollbar_to(self, y):
        tab = self.active_tab()
        if not tab:
            return
        maxs = tab.max_scroll()
        py = theme.TABBAR_H + theme.NAVBAR_H
        vh = tab.viewport_h
        track = vh - 4
        frac = (y - py - 2) / track if track > 0 else 0
        tab.scroll = maxs * frac
        tab.clamp_scroll()
        self.invalidate()

    def _dev_click(self, x, y):
        dy = self.dev_y()
        if y < dy + 22:
            xx = 8
            for label, key in (("Console", "console"), ("Elements", "elements"),
                               ("Network", "network"), ("Sources", "sources")):
                w = self._renderer.text_w(label, self.font_ui) + 16
                if xx <= x < xx + w:
                    self.dev_tab = key
                    self.dev_scroll = 0
                    self.invalidate()
                    return
                xx += w
            return
        if self.dev_tab == "console" and y >= self.dev_y() + self.dev_h() - 22:
            self.dev_mode = True
            self.invalidate()
            return
        self.dev_mode = False
        self.invalidate()

    # ------------------------------------------------------------------
    # Keyboard handlers (same logic as X11 version)
    # ------------------------------------------------------------------
    def _key_dialog(self, name, ch, ctrl):
        d = self.dialog
        if name in ("Return", "KP_Enter"):
            self._dialog_confirm()
        elif name == "Escape":
            self._dialog_cancel()
        elif d.kind == "prompt":
            d.input.key(name, ch, (4 if ctrl else 0))
            self.invalidate()

    def _key_menu(self, name):
        m = self.menu
        if name == "Escape":
            self.close_menu()
        elif name == "Up":
            m["index"] = m["index"] - 1 if m["index"] is not None else 0
            if m["index"] < 0:
                m["index"] = len(m["items"]) - 1
        elif name == "Down":
            m["index"] = (m["index"] + 1) if m["index"] is not None else 0
            if m["index"] >= len(m["items"]):
                m["index"] = 0
        elif name in ("Return", "KP_Enter"):
            if m["index"] is not None:
                self._menu_activate(m["index"])
        else:
            self.close_menu()
        self.invalidate()

    def _key_find(self, name, ch, ctrl):
        f = self.find_bar
        if name == "Escape":
            self.find_toggle()
            return
        if name in ("Return", "KP_Enter"):
            f.query = f.input.text
            self.compute_find(f.query)
            self.mode = "page"
            f.input.focus = False
            self.invalidate()
            return
        if ctrl and name in ("F", "f"):
            return
        old = f.input.text
        f.input.key(name, ch, (4 if ctrl else 0) | (1 if shift else 0))
        if f.input.text != old:
            f.query = f.input.text
            self.compute_find(f.query)
        self.invalidate()

    def _key_addr(self, name, ch, ctrl, shift):
        a = self.addr
        if name == "Escape":
            self.mode = "page"
            a.focus = False
            self._update_addr()
            self.invalidate()
            return
        if name in ("Return", "KP_Enter"):
            self.mode = "page"
            a.focus = False
            self.load_url(a.text)
            self.invalidate()
            return
        if ctrl and name in ("C", "c"):
            self._x_copy(a.selected_text() or a.text)
            return
        if ctrl and name in ("V", "v"):
            a.replace_selection(self._x_paste())
            self.invalidate()
            return
        if ctrl and name in ("A", "a"):
            a.key("A", "", 4)
            self.invalidate()
            return
        if ctrl and name in ("L", "l"):
            return
        a.key(name, ch, (4 if ctrl else 0) | (1 if shift else 0))
        self.invalidate()

    def _key_page(self, name, ch, ctrl, alt, shift, repeat):
        tab = self.active_tab()
        if tab is None:
            return
        if ctrl and name == "Q":
            self.running = False
            return
        if alt and name == "F4":
            self.running = False
            return
        if ctrl and name in ("T", "t") and not repeat:
            self._new_tab(self.settings.get("new_tab_url") or self.settings.get("home_url"))
            return
        if ctrl and name in ("W", "w") and not repeat:
            self._close_tab(self.active)
            return
        if ctrl and name == "L" and not repeat:
            self.mode = "addr"
            self.addr.focus = True
            self.addr.set_text(tab.url)
            self.invalidate()
            return
        if name in ("F12", "XF86Tools") and not repeat:
            self.dev_open = not self.dev_open
            self._layout_chrome(force=True)
            self.invalidate()
            return
        if (ctrl and shift and name in ("I", "i")) and not repeat:
            self.dev_open = not self.dev_open
            self._layout_chrome(force=True)
            self.invalidate()
            return
        if ctrl and name == "comma" and not repeat:
            self.load_url("pilot://settings")
            return
        if ctrl and name in ("R", "r") and not repeat:
            self.reload()
            return
        if name == "F5" and not repeat:
            self.reload()
            return
        if ctrl and name in ("F", "f") and not repeat:
            self.find_toggle()
            return
        if ctrl and name in ("=", "plus") and not repeat:
            self.zoom(0.2)
            return
        if ctrl and name == "minus" and not repeat:
            self.zoom(-0.2)
            return
        if ctrl and name == "0" and not repeat:
            tab.zoom = 1.0
            tab.layout_build()
            return
        if alt and name == "Left" and not repeat:
            self.go_back(tab)
            return
        if alt and name == "Right" and not repeat:
            self.go_forward(tab)
            return
        if ctrl and name == "Tab":
            delta = -1 if shift else 1
            self.active = (self.active + delta) % len(self.tabs)
            self._activate(self.active)
            return
        if ctrl and name in ("Prior", "Next"):
            delta = -1 if name == "Prior" else 1
            self.active = (self.active + delta) % len(self.tabs)
            self._activate(self.active)
            return
        if ctrl and name in [str(i) for i in range(1, 10)] and not repeat:
            idx = int(name) - 1
            if idx < len(self.tabs):
                self._activate(idx)
            return

        # page input focus
        if tab.focus_node and tab.focus_node.tag_name() in ("input", "textarea"):
            t = tab.focus_node.get("type", "text").lower()
            if t in ("text", "password", "search", "email", "url", "number",
                     "tel", "date", "time") or tab.focus_node.tag_name() == "textarea":
                node = tab.focus_node
                if name == "Return" or name == "KP_Enter":
                    self._submit_form(node)
                    return
                if name == "Escape":
                    self.blur_page_input(tab)
                    return
                if ctrl and name in ("C", "c"):
                    self._x_copy(self._page_selection())
                    return
                if ctrl and name in ("V", "v"):
                    self._page_insert(tab, self._x_paste())
                    return
                if ctrl and name in ("A", "a"):
                    tab.focus_cursor = len(node.get("value", ""))
                    return
                self._page_key(tab, name, ch, ctrl, shift)
                return

        # scrolling keys
        if name == "Prior":
            tab.scroll -= tab.viewport_h * 0.8
            tab.clamp_scroll()
            self.invalidate()
            return
        if name == "Next":
            tab.scroll += tab.viewport_h * 0.8
            tab.clamp_scroll()
            self.invalidate()
            return
        if name == "Home":
            tab.scroll = 0
            self.invalidate()
            return
        if name == "End":
            tab.scroll = tab.max_scroll()
            self.invalidate()
            return
        if name == "Up":
            tab.scroll -= 40
            tab.clamp_scroll()
            self.invalidate()
            return
        if name == "Down":
            tab.scroll += 40
            tab.clamp_scroll()
            self.invalidate()
            return

        if tab.focus_node and tab.focus_node.js_engine:
            tab.focus_node.js_engine.emit(tab.focus_node, "keydown",
                                          {"key": ch or name, "keyCode": 0})
            self.invalidate()
            return

    def _page_key(self, tab, name, ch, ctrl, shift):
        node = tab.focus_node
        if node is None:
            return
        val = node.get("value", "")
        cursor = tab.focus_cursor
        if name == "BackSpace":
            if cursor > 0:
                val = val[:cursor - 1] + val[cursor:]
                tab.focus_cursor = cursor - 1
        elif name == "Delete":
            val = val[:cursor] + val[cursor + 1:]
        elif name == "Left":
            tab.focus_cursor = max(0, cursor - 1)
        elif name == "Right":
            tab.focus_cursor = min(len(val), cursor + 1)
        elif name == "Home":
            tab.focus_cursor = 0
        elif name == "End":
            tab.focus_cursor = len(val)
        elif ch and not ctrl:
            val = val[:cursor] + ch + val[cursor:]
            tab.focus_cursor = cursor + len(ch)
        else:
            return
        node.set("value", val)
        tab.focus_caret_on = True
        tab.focus_blink_at = 0.0
        if node.js_engine:
            node.js_engine.emit(node, "input", {"value": val})
        tab.relayout_pending = True
        self.invalidate()

    def _page_selection(self):
        return ""

    def _page_insert(self, tab, text):
        node = tab.focus_node
        if node is None:
            return
        val = node.get("value", "")
        cursor = tab.focus_cursor
        val = val[:cursor] + text + val[cursor:]
        node.set("value", val)
        tab.focus_cursor = cursor + len(text)
        tab.relayout_pending = True
        self.invalidate()

    # ------------------------------------------------------------------
    # Clipboard (via xclip)
    # ------------------------------------------------------------------
    def _x_copy(self, text):
        if not text:
            return
        try:
            import subprocess
            subprocess.Popen(["xclip", "-selection", "clipboard"],
                             stdin=subprocess.PIPE,
                             text=True).communicate(text)
        except Exception:  # noqa: BLE001
            pass

    def _x_paste(self):
        try:
            import subprocess
            out = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                                 capture_output=True, text=True)
            return out.stdout if out.returncode == 0 else ""
        except Exception:  # noqa: BLE001
            return ""

    def _enter_addr(self, text):
        if text:
            self.mode = "addr"
            self.addr.set_text(text)
            self.invalidate()

    # ------------------------------------------------------------------
    # Find / zoom
    # ------------------------------------------------------------------
    def find_toggle(self):
        self.find_bar.visible = not self.find_bar.visible
        if self.find_bar.visible:
            self.mode = "find"
            self.find_bar.input.focus = True
            self.find_bar.input.set_text(self.find_bar.query)
        else:
            self.mode = "page"
            self.find_bar.input.focus = False
            self._clear_find()

    def _clear_find(self):
        tab = self.active_tab()
        if tab:
            tab.find_query = ""
            tab.find_matches = []
            tab.find_index = 0
        self.invalidate()

    def compute_find(self, query):
        tab = self.active_tab()
        if not tab:
            return
        tab.find_query = query
        tab.find_matches = []
        tab.find_index = 0
        if not query or not tab.layout:
            return
        q = query.lower()
        for line in tab.layout.all_lines():
            for run in line.runs:
                if run.kind == "text" and q in run.text.lower():
                    tab.find_matches.append((run.x, run.y, run.w, run.h))
        if tab.find_matches:
            self.find_next()
        else:
            self.status("No matches", theme.WARN_YELLOW, 2)

    def find_next(self, backwards=False):
        tab = self.active_tab()
        if not tab or not tab.find_query:
            return
        n = len(tab.find_matches)
        if not n:
            return
        tab.find_index = (tab.find_index + (-1 if backwards else 1)) % n
        x, y, w, h = tab.find_matches[tab.find_index]
        self.scroll_to_rect(tab, (x, y, w, h))

    def scroll_to_rect(self, tab, rect):
        x, y, w, h = rect
        vh = tab.viewport_h
        if y < tab.scroll:
            tab.scroll = max(0, y - 10)
        elif y + h > tab.scroll + vh:
            tab.scroll = min(tab.max_scroll(), y + h - vh + 10)
        tab.clamp_scroll()
        self.invalidate()

    # ------------------------------------------------------------------
    # Tick / main loop
    # ------------------------------------------------------------------
    def _tick(self):
        tab = self.active_tab()
        if tab and tab.engine:
            try:
                if tab.engine.tick():
                    tab.relayout_pending = True
                    self.invalidate()
            except Exception:  # noqa: BLE001
                pass
        if tab and tab.focus_node:
            now = time.time()
            if now - tab.focus_blink_at > 0.5:
                tab.focus_blink_at = now
                tab.focus_caret_on = not tab.focus_caret_on
                self.invalidate()
        elif self.addr.focus and self.addr.tick():
            self.invalidate()
        elif self.find_bar.input.focus and self.find_bar.input.tick():
            self.invalidate()
        if self.status_until and time.time() > self.status_until:
            self.status_text = ""
            self.status_color = theme.TEXT_DIM
            self.status_until = 0.0
            self.invalidate()

    def _tick_loop(self):
        if not self.running:
            return
        self._tick()
        if self._dirty:
            self.redraw()
            self._dirty = False
        self.root.after(20, self._tick_loop)

    def run(self):
        try:
            self._tick_loop()
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def main(argv=None):
    url = None
    if argv and len(argv) > 1:
        url = net.normalize_url(argv[1])
    app = Pilot(url)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
