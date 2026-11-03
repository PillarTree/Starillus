"""Software framebuffer rendered with Pillow.

All drawing goes into a Pillow image; the finished frame is uploaded to a
tkinter Label via ImageTk.PhotoImage. Clipping is supported for partial
redraws.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from . import theme

try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None


class Renderer:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.img = Image.new("RGB", (width, height), theme.BG)
        self._draw = ImageDraw.Draw(self.img)
        self._clip = (0, 0, width, height)
        self._saved_clips = []

    # -- frame lifecycle ----------------------------------------------------
    def begin_frame(self, bg=theme.BG):
        self.img.paste(bg, (0, 0, self.width, self.height))
        self._draw = ImageDraw.Draw(self.img)
        self._clip = (0, 0, self.width, self.height)
        self._saved_clips = []

    def pixel_bytes(self, depth=24) -> bytes:
        """Framebuffer as ZPixmap request data.

        X.Org expects 4 bytes/pixel (BGRX) for depth-24 drawables; the
        trailing byte is padding. depth 32 also uses BGRX.
        """
        rgb = self.img.tobytes()
        if _np is not None:
            arr = _np.frombuffer(rgb, dtype=_np.uint8)
            arr = arr.reshape(self.height, self.width, 3)
            out = _np.zeros((self.height, self.width, 4), dtype=_np.uint8)
            out[:, :, 0] = arr[:, :, 2]
            out[:, :, 1] = arr[:, :, 1]
            out[:, :, 2] = arr[:, :, 0]
            return out.tobytes()
        out = bytearray(len(rgb) * 4 // 3)
        o = 0
        for i in range(0, len(rgb), 3):
            out[o] = rgb[i + 2]
            out[o + 1] = rgb[i + 1]
            out[o + 2] = rgb[i]
            o += 4
        return bytes(out)

    # -- clipping -----------------------------------------------------------
    def push_clip(self, x, y, w, h):
        cx, cy, cw, ch = self._clip
        x = max(cx, x); y = max(cy, y)
        x2 = min(cx + cw, x + w); y2 = min(cy + ch, y + h)
        self._saved_clips.append(self._clip)
        self._clip = (x, y, max(0, x2 - x), max(0, y2 - y))

    def pop_clip(self):
        if self._saved_clips:
            self._clip = self._saved_clips.pop()

    def _intersect(self, x, y, w, h):
        cx, cy, cw, ch = self._clip
        x = max(cx, x); y = max(cy, y)
        x2 = min(cx + cw, x + w); y2 = min(cy + ch, y + h)
        return x, y, max(0, x2 - x), max(0, y2 - y)

    # -- primitives ---------------------------------------------------------
    def rect(self, x, y, w, h, fill):
        x, y, w, h = self._intersect(x, y, w, h)
        if w <= 0 or h <= 0:
            return
        self._draw.rectangle([x, y, x + w - 1, y + h - 1], fill=fill)

    def outline(self, x, y, w, h, color, width=1):
        x0, y0, w0, h0 = self._intersect(x, y, w, h)
        if w0 <= 0 or h0 <= 0:
            return
        self._draw.rectangle([x0, y0, x0 + w0 - 1, y0 + h0 - 1],
                             outline=color, width=width)

    def hline(self, x, y, w, color):
        x, y, w, h = self._intersect(x, y, w, 1)
        if w <= 0:
            return
        self._draw.line([(x, y), (x + w - 1, y)], fill=color)

    def vline(self, x, y, h, color):
        x, y, w, h = self._intersect(x, y, 1, h)
        if h <= 0:
            return
        self._draw.line([(x, y), (x, y + h - 1)], fill=color)

    def text(self, x, y, s, color=theme.TEXT, font=None, anchor="la"):
        if not s:
            return
        if font is None:
            from . import theme as t
            font = t.font("sans", "normal", "normal", 13)
        # Horizontal anchor adjustments
        if anchor == "ra":
            x -= self.text_w(s, font)
        elif anchor == "ma":
            x -= self.text_w(s, font) // 2
        # PIL draws with bounding-box top-left at (x, y); layout.py passes
        # run.y = top of text glyphs. Adjust so ink top lands at (x, y).
        left, top, _right, _bottom = font.getbbox(s)
        x0, y0 = int(x - left), int(y - top)
        cx, cy, cw, ch = self._clip
        x0 = max(cx, x0); y0 = max(cy, y0)
        if x0 >= cx + cw or y0 >= cy + ch:
            return
        self._draw.text((x0, y0), s, font=font, fill=color)

    def text_w(self, s, font) -> int:
        if not s:
            return 0
        return font.getbbox(s)[2]

    def text_h(self, font) -> int:
        a, d = font.getmetrics()
        return a + d

    def blit(self, img: Image.Image, x, y):
        x, y = int(round(x)), int(round(y))
        x0, y0, w, h = self._intersect(x, y, img.width, img.height)
        x0, y0, w, h = int(x0), int(y0), int(w), int(h)
        if w <= 0 or h <= 0:
            return
        box = (x0 - x, y0 - y, x0 - x + w, y0 - y + h)
        region = img.crop(box)
        if img.mode in ("RGBA", "LA"):
            self.img.paste(region, (x0, y0), region)
        else:
            self.img.paste(region, (x0, y0))