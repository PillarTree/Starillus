"""Browser chrome widgets: buttons, text fields, tab bar, find bar,
status bar and modal dialogs (alert/confirm/prompt)."""

from __future__ import annotations

import time

from . import theme


class Button:
    def __init__(self, label, action=None, hint="", font=None):
        self.label = label
        self.action = action
        self.hint = hint
        self.x = self.y = self.w = self.h = 0
        self.hover = False
        self.pressed = False
        self.disabled = False

    def set_bounds(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    def contains(self, x, y):
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def render(self, r, font):
        if self.hover:
            r.rect(self.x, self.y, self.w, self.h, theme.ROW_HOVER)
        r.text(self.x + self.w // 2, self.y + max(0, (self.h - r.text_h(font)) // 2),
               self.label, theme.TEXT_DIM if self.disabled else theme.TEXT,
               font, anchor="ma")


class TextField:
    def __init__(self, placeholder="", font=None):
        self.text = ""
        self.placeholder = placeholder
        self.font = font
        self.x = self.y = self.w = self.h = 0
        self.focus = False
        self.cursor = 0
        self.sel_start = None
        self.sel_end = None
        self._drag = False
        self._blink_at = 0.0
        self.caret_on = True
        self.password = False

    def set_bounds(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    def contains(self, x, y):
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def set_text(self, text):
        self.text = text
        self.cursor = len(text)
        self.sel_start = self.sel_end = None

    def _display(self):
        return "•" * len(self.text) if self.password else self.text

    def caret_x(self, r):
        return self.x + 6 + r.text_w(self._display()[:self.cursor], self.font)

    def mouse_down(self, x, y, shift=False):
        rel = max(0, x - self.x - 6)
        self.cursor = self._index_at(rel)
        if shift:
            if self.sel_start is None:
                self.sel_start = self.cursor
                self.sel_end = self.cursor
            else:
                self.sel_start, self.sel_end = min(self.sel_start, self.cursor), \
                    max(self.sel_start, self.cursor)
        else:
            self.sel_start = self.sel_end = None
        self._drag = True
        self._blink_at = 0.0
        self.caret_on = True

    def mouse_drag(self, x, y):
        if not self._drag:
            return False
        rel = max(0, x - self.x - 6)
        idx = self._index_at(rel)
        if self.sel_start is None:
            self.sel_start = idx
        self.sel_end = idx
        self.cursor = idx
        return True

    def mouse_up(self):
        self._drag = False

    def _index_at(self, rel):
        s = self._display()
        best, best_d = 0, 10 ** 9
        for i in range(len(s) + 1):
            w = self.font.getbbox(s[:i])[2]
            d = abs(w - rel)
            if d < best_d:
                best_d = d
                best = i
        return best

    def selected_text(self):
        if self.sel_start is None or self.sel_end is None:
            return ""
        a, b = sorted((self.sel_start, self.sel_end))
        return self.text[a:b]

    def replace_selection(self, new_text):
        if self.sel_start is not None and self.sel_end is not None:
            a, b = sorted((self.sel_start, self.sel_end))
            self.text = self.text[:a] + new_text + self.text[b:]
            self.cursor = a + len(new_text)
        else:
            self.text = self.text[:self.cursor] + new_text + \
                self.text[self.cursor:]
            self.cursor += len(new_text)
        self.sel_start = self.sel_end = None

    def key(self, name, ch, mods=0):
        ctrl = bool(mods & 4)
        shift = bool(mods & 1)
        if name == "BackSpace":
            if self.sel_start is not None and self.sel_end is not None:
                self.replace_selection("")
            elif self.cursor > 0:
                self.text = self.text[:self.cursor - 1] + \
                    self.text[self.cursor:]
                self.cursor -= 1
        elif name == "Delete":
            if self.sel_start is not None and self.sel_end is not None:
                self.replace_selection("")
            elif self.cursor < len(self.text):
                self.text = self.text[:self.cursor] + \
                    self.text[self.cursor + 1:]
        elif name == "Left":
            if shift:
                self._extend_sel(self.cursor - 1)
            else:
                self.sel_start = self.sel_end = None
                self.cursor = max(0, self.cursor - 1)
        elif name == "Right":
            if shift:
                self._extend_sel(self.cursor + 1)
            else:
                self.sel_start = self.sel_end = None
                self.cursor = min(len(self.text), self.cursor + 1)
        elif name == "Home":
            self.cursor = 0
            if not shift:
                self.sel_start = self.sel_end = None
        elif name == "End":
            self.cursor = len(self.text)
            if not shift:
                self.sel_start = self.sel_end = None
        elif ctrl and name in ("A", "a"):
            self.sel_start, self.sel_end = 0, len(self.text)
            self.cursor = len(self.text)
        elif ch:
            if ctrl:
                return
            self.replace_selection(ch)
        self._blink_at = 0.0
        self.caret_on = True

    def _extend_sel(self, idx):
        idx = max(0, min(len(self.text), idx))
        if self.sel_start is None:
            self.sel_start = self.cursor
        self.sel_end = idx
        self.cursor = idx

    def tick(self):
        if self.focus:
            now = time.time()
            if now - self._blink_at > 0.5:
                self._blink_at = now
                self.caret_on = not self.caret_on
                return True
        return False

    def render(self, r):
        r.rect(self.x, self.y, self.w, self.h, theme.INPUT_BG)
        r.outline(self.x, self.y, self.w, self.h,
                  theme.INPUT_BORDER if not self.focus else theme.ACCENT)
        s = self._display()
        x = self.x + 6
        y = self.y + max(0, (self.h - r.text_h(self.font)) // 2)
        # selection
        if self.focus and self.sel_start is not None and self.sel_end is not None:
            a, b = sorted((self.sel_start, self.sel_end))
            wa = r.text_w(s[:a], self.font)
            wb = r.text_w(s[:b], self.font)
            r.rect(x + wa, y, wb - wa, r.text_h(self.font), theme.SELECT_FOC)
        if not s and not self.focus:
            r.text(x, y, self.placeholder, theme.TEXT_FAINT, self.font)
        else:
            r.text(x, y, s, theme.TEXT, self.font)
        if self.focus and self.caret_on and not self.sel_start:
            cx = self.caret_x(r)
            r.vline(cx, y, r.text_h(self.font), theme.ACCENT_HOT)


class TabBar:
    def __init__(self):
        self.tabs = []          # list of dicts: {label, title}
        self.active = 0
        self.plus_x = 0

    def tab_rect(self, i):
        x = theme.PAD
        for j in range(i):
            x += self._tab_w(j) + 2
        return (x, theme.PAD, self._tab_w(i), theme.TAB_H)

    def _tab_w(self, i):
        t = self.tabs[i]
        w = min(theme.MAX_TAB_W, max(theme.MIN_TAB_W,
                                     len(t["label"]) * 8 + 46))
        return w

    def hit(self, x, y):
        if y < theme.PAD or y >= theme.PAD + theme.TAB_H:
            return None
        for i in range(len(self.tabs)):
            rx, ry, rw, rh = self.tab_rect(i)
            if rx <= x < rx + rw:
                # close button?
                if x >= rx + rw - 22:
                    return ("close", i)
                return ("tab", i)
        if self.plus_x <= x < self.plus_x + 26:
            return ("plus", None)
        return None

    def render(self, r, font):
        for i, t in enumerate(self.tabs):
            rx, ry, rw, rh = self.tab_rect(i)
            active = i == self.active
            r.rect(rx, ry, rw, rh,
                   theme.TAB_ACTIVE if active else theme.TAB_INACTIVE)
            if not active:
                r.hline(rx, ry + rh - 1, rw, theme.PANEL_LINE)
            label = t["label"]
            if len(label) > 24:
                label = label[:22] + "…"
            r.text(rx + 8, ry + max(0, (rh - r.text_h(font)) // 2), label,
                   theme.TEXT if active else theme.TEXT_DIM, font)
            r.text(rx + rw - 16, ry + max(0, (rh - r.text_h(font)) // 2),
                   "×", theme.TEXT_DIM, font)
        # plus
        x = theme.PAD
        for j in range(len(self.tabs)):
            x += self._tab_w(j) + 2
        self.plus_x = x
        r.outline(x, theme.PAD, 26, theme.TAB_H, theme.PANEL_LINE)
        r.text(x + 13, theme.PAD + max(0, (theme.TAB_H - r.text_h(font)) // 2),
               "+", theme.TEXT_DIM, font, anchor="ma")


class StatusBar:
    def __init__(self):
        self.text = ""
        self.color = theme.TEXT_DIM
        self.right = ""
        self.right_color = theme.TEXT_DIM

    def render(self, r, w, h, font):
        y = h - theme.STATUSBAR_H
        r.rect(0, y, w, theme.STATUSBAR_H, theme.PANEL)
        r.hline(0, y, w, theme.PANEL_LINE)
        th = r.text_h(font)
        ty = y + max(0, (theme.STATUSBAR_H - th) // 2)
        r.text(theme.PAD, ty, self.text, self.color, font)
        if self.right:
            r.text(w - theme.PAD, ty, self.right, self.right_color, font,
                   anchor="ra")


class Dialog:
    """Modal overlay for alert/confirm/prompt."""

    def __init__(self, kind, message, default="", font=None, font_b=None):
        self.kind = kind        # alert | confirm | prompt
        self.message = message
        self.input = TextField(default, font=font) if kind == "prompt" else None
        self.font = font
        self.font_b = font_b
        self.result = None
        self.done = False
        self.x = self.y = self.w = self.h = 0
        self.ok_btn = Button("OK")
        self.cancel_btn = Button("Cancel") if kind != "alert" else None
        self.buttons = [self.ok_btn]
        if self.cancel_btn:
            self.buttons.append(self.cancel_btn)

    def layout(self, win_w, win_h, r):
        self.w = min(480, win_w - 80)
        self.h = 120 if self.kind == "alert" else 150
        self.x = (win_w - self.w) // 2
        self.y = (win_h - self.h) // 2
        by = self.y + self.h - 40
        bw = 76
        self.ok_btn.set_bounds(self.x + self.w - bw - 14, by, bw, 30)
        if self.cancel_btn:
            self.cancel_btn.set_bounds(self.x + self.w - bw * 2 - 22, by,
                                       bw, 30)
        if self.input:
            self.input.set_bounds(self.x + 18, by - 36, self.w - 36, 28)

    def render(self, r, win_w, win_h):
        self.layout(win_w, win_h, r)
        r.rect(0, 0, win_w, win_h, (15, 17, 21))
        r.rect(self.x, self.y, self.w, self.h, theme.PANEL)
        r.outline(self.x, self.y, self.w, self.h, theme.ACCENT)
        r.text(self.x + 18, self.y + 16, self.message, theme.TEXT, self.font)
        if self.input:
            self.input.render(r)
        self.ok_btn.render(r, self.font_b)
        if self.cancel_btn:
            self.cancel_btn.render(r, self.font_b)


class FindBar:
    def __init__(self, font=None):
        self.input = TextField("Find in page…", font=font)
        self.visible = False
        self.query = ""
        self.index = 0

    def set_bounds(self, x, y, w, h):
        self.input.set_bounds(x, y, w, h)

    def render(self, r):
        if self.visible:
            self.input.render(r)