"""Layout engine: computed styles, box tree, inline text flow, tables,
forms and painting — all in pure Python/Pillow.

The document is turned into a tree of Boxes. Block boxes stack vertically;
inline content (text runs, spans, images, form controls) flows into lines
with greedy word wrapping. Interactive elements (links, controls, JS
handlers) are recorded as hit regions during layout so hit-testing and
scrolling-into-view work without re-painting.
"""

from __future__ import annotations

import re

from . import css, theme
from .html5 import BLOCK_ELEMS as BLOCK_ELEMS_DEFAULT

DEFAULT_TEXT = (28, 30, 34)

BLOCKISH = {"block", "list-item", "table", "table-row", "table-cell",
            "table-row-group", "table-header-group", "table-footer-group",
            "inline-block"}

FORM_TAGS = {"input", "textarea", "select", "button", "option", "optgroup"}
JS_EVENT_ATTRS = ("onclick", "ondblclick", "onchange", "oninput", "onkeydown",
                  "onkeyup", "onkeypress", "onsubmit", "onmouseover",
                  "onmouseout", "onfocus", "onblur", "onload", "onerror",
                  "onscroll")
FORM_CONTROL = {"input", "textarea", "select", "button"}
REPLACED = FORM_CONTROL | {"img"}

HEADING_SIZES = {"h1": 2.0, "h2": 1.5, "h3": 1.17, "h4": 1.0, "h5": 0.83,
                 "h6": 0.67}

NON_INHERITED = {
    "display", "width", "height", "background-color", "text-decoration",
    "vertical-align", "position", "float", "overflow", "z-index",
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "border-top-width", "border-right-width", "border-bottom-width",
    "border-left-width", "border-top-color", "border-right-color",
    "border-bottom-color", "border-left-color", "border-top-style",
    "border-right-style", "border-bottom-style", "border-left-style",
    "min-width", "max-width",
}

TRANSFORMS = {"uppercase", "lowercase", "capitalize"}

_FONT_FAMILY = {
    "sans-serif": "sans", "sans": "sans", "arial": "sans", "helvetica": "sans",
    "verdana": "sans", "tahoma": "sans", "trebuchet ms": "sans",
    "lucida": "sans", "system-ui": "sans", "segoe ui": "sans",
    "serif": "serif", "times": "serif", "times new roman": "serif",
    "georgia": "serif", "garamond": "serif", "palatino": "serif",
    "monospace": "mono", "mono": "mono", "courier": "mono",
    "courier new": "mono", "consolas": "mono", "menlo": "mono",
    "dejavu sans mono": "mono", "ui-monospace": "mono",
}

_HANDLER_RE = re.compile(r"^(on\w+)$")


def _is_handler_attr(name):
    return bool(_HANDLER_RE.match(name)) or name in JS_EVENT_ATTRS


class Box:
    __slots__ = ("node", "style", "kind", "children", "parent", "x", "y",
                 "w", "h", "lines", "marker", "colspan", "natural",
                 "control_text", "checked", "selected_index", "options",
                 "bg", "is_root", "hidden", "media_img", "media_state")

    def __init__(self, node, style, kind):
        self.node = node
        self.style = style
        self.kind = kind          # root|block|inline|table|table-row|table-cell
        self.children = []
        self.parent = None
        self.x = self.y = self.w = self.h = 0
        self.lines = []           # for blocks containing inline content
        self.marker = None        # list bullet / ol number text
        self.colspan = 1
        self.natural = 0.0        # natural content width (used by tables)
        self.control_text = ""
        self.checked = False
        self.selected_index = 0
        self.options = []
        self.bg = None
        self.is_root = False
        self.hidden = False
        self.media_img = None
        self.media_state = None

    def add(self, child):
        child.parent = self
        self.children.append(child)

    def content_x(self):
        s = self.style
        return (self.x + s["border-left-width"] + s["padding-left"])

    def content_y(self):
        s = self.style
        return (self.y + s["border-top-width"] + s["padding-top"])

    def content_w(self):
        s = self.style
        return self.w - s["border-left-width"] - s["border-right-width"] \
            - s["padding-left"] - s["padding-right"]

    def content_h(self):
        s = self.style
        return self.h - s["border-top-width"] - s["border-bottom-width"] \
            - s["padding-top"] - s["padding-bottom"]

    def interactive(self):
        node = self.node
        if node is None or not node.is_element:
            return False
        tag = node.tag_name()
        if tag in FORM_CONTROL or tag == "a":
            return True
        for k, v in node.attrs.items():
            if _is_handler_attr(k) and v:
                return True
        return False


class Line:
    __slots__ = ("runs", "y", "h", "baseline", "x0")

    def __init__(self):
        self.runs = []
        self.y = 0
        self.h = 0
        self.baseline = 0
        self.x0 = 0


class Run:
    __slots__ = ("text", "style", "node", "kind", "x", "y", "w", "h",
                 "font", "color", "img", "control", "box", "video")

    def __init__(self, text, style, node, kind="text"):
        self.text = text
        self.style = style
        self.node = node
        self.kind = kind          # text|space|img|control|br
        self.x = self.y = self.w = self.h = 0
        self.font = None
        self.color = None
        self.img = None
        self.control = None       # Box for controls
        self.box = None           # inline element box (a, span, ...)
        self.video = None


def default_style(base_size):
    return {
        "color": DEFAULT_TEXT,
        "background-color": None,
        "font-family": "sans",
        "font-size": base_size,
        "font-weight": "normal",
        "font-style": "normal",
        "text-align": "left",
        "text-decoration": "none",
        "text-transform": "none",
        "text-indent": 0.0,
        "line-height": None,
        "white-space": "normal",
        "display": "inline",
        "float": "none",
        "position": "static",
        "z-index": None,
        "overflow": "visible",
        "width": None, "height": None,
        "margin-top": 0.0, "margin-right": 0.0, "margin-bottom": 0.0,
        "margin-left": 0.0,
        "padding-top": 0.0, "padding-right": 0.0, "padding-bottom": 0.0,
        "padding-left": 0.0,
        "border-top-width": 0, "border-right-width": 0,
        "border-bottom-width": 0, "border-left-width": 0,
        "border-top-color": None, "border-right-color": None,
        "border-bottom-color": None, "border-left-color": None,
        "border-top-style": "none", "border-right-style": "none",
        "border-bottom-style": "none", "border-left-style": "none",
        "list-style-type": "disc",
        "vertical-align": "baseline",
        "min-width": 0.0, "max-width": 10 ** 9,
    }


class Layout:
    def __init__(self, document, viewport_w, ctx):
        self.document = document
        self.viewport_w = viewport_w
        self.ctx = ctx
        base = max(4, theme.BASE_FONT * getattr(ctx, "zoom", 1.0))
        self.base = base
        self.root = None
        self.regions = []       # [(x, y, w, h, node, kind)]
        self.node_boxes = {}    # id(node) -> (x, y, w, h) content rect
        self.rules = css.collect_rules(ctx.rules)
        self.visited = ctx.visited
        self._style_cache = {}

    # ------------------------------------------------------------------
    # Style resolution
    # ------------------------------------------------------------------
    def style_of(self, node, parent_style=None):
        key = id(node)
        cached = self._style_cache.get(key)
        if cached is not None:
            return cached
        if parent_style is None:
            parent_style = default_style(self.base)
        style = dict(parent_style)
        for k in NON_INHERITED:
            style[k] = default_style(self.base)[k]
        style["font-size"] = parent_style["font-size"]

        visited = False
        tag = node.tag_name()
        if tag == "a" and node.get("href"):
            visited = self.visited and self.visited_contains(node)
        decls = css.cascade(node, self.rules, node.get("style"), visited)

        size = style["font-size"]
        for prop, value in decls.items():
            v = value.strip().lower()
            if prop == "color":
                if v == "link":
                    style["color"] = theme.LINK if not visited else theme.LINK_VISITED
                else:
                    c = css.parse_color(v)
                    if c is not None:
                        style["color"] = c
            elif prop == "background-color":
                c = css.parse_color(v)
                style["background-color"] = c if c is not None else None
            elif prop == "background":
                c = css.parse_color(v)
                if c is not None:
                    style["background-color"] = c
            elif prop == "font-family":
                for fam in re.split(r",", value):
                    fam = fam.strip().strip("'\"").lower()
                    if fam in _FONT_FAMILY:
                        style["font-family"] = _FONT_FAMILY[fam]
                        break
            elif prop == "font-size":
                if v == "larger":
                    style["font-size"] = size * 1.2
                elif v == "smaller":
                    style["font-size"] = size * 0.83
                elif v.endswith("%"):
                    style["font-size"] = size * css.parse_number(v[:-1]) / 100
                else:
                    n = css.parse_length(v, base_px=size)
                    if n is not None:
                        style["font-size"] = n
            elif prop == "font-weight":
                if v in ("bold", "bolder") or re.match(r"^[5-9]00$", v):
                    style["font-weight"] = "bold"
                elif v in ("normal", "lighter") or re.match(r"^[1-4]00$", v):
                    style["font-weight"] = "normal"
            elif prop == "font-style":
                if v in ("italic", "oblique"):
                    style["font-style"] = "italic"
            elif prop == "text-align":
                if v in ("left", "center", "right", "justify"):
                    style["text-align"] = v
            elif prop == "text-decoration":
                if v == "none":
                    style["text-decoration"] = "none"
                elif "underline" in v:
                    style["text-decoration"] = "underline"
                elif "line-through" in v:
                    style["text-decoration"] = "line-through"
                elif "overline" in v:
                    style["text-decoration"] = "overline"
            elif prop == "text-transform":
                if v in TRANSFORMS:
                    style["text-transform"] = v
            elif prop == "text-indent":
                n = css.parse_length(v, base_px=size)
                if n is not None:
                    style["text-indent"] = n
            elif prop == "line-height":
                if v == "normal":
                    style["line-height"] = None
                else:
                    num = css.parse_number(v)
                    if num is not None:
                        style["line-height"] = size * num
                    else:
                        n = css.parse_length(v, base_px=size)
                        if n is not None:
                            style["line-height"] = n
            elif prop == "white-space":
                if v in ("normal", "pre", "nowrap", "pre-wrap"):
                    style["white-space"] = v
            elif prop == "display":
                if v in BLOCKISH:
                    style["display"] = "block"
                elif v == "none":
                    style["display"] = "none"
                elif v in ("inline", "inline-block"):
                    style["display"] = "inline"
            elif prop == "vertical-align":
                if v in ("top", "middle", "bottom", "baseline", "sub",
                         "super", "text-top", "text-bottom"):
                    style["vertical-align"] = v
            elif prop == "list-style-type":
                if v in ("disc", "circle", "square", "decimal", "none",
                         "lower-roman", "upper-roman", "lower-alpha",
                         "upper-alpha"):
                    style["list-style-type"] = v
            elif prop in ("width", "height", "min-width", "max-width"):
                if v == "auto":
                    style[prop] = None
                elif v.endswith("%"):
                    style[prop] = ("%", css.parse_number(v[:-1]) / 100)
                else:
                    n = css.parse_length(v, base_px=size)
                    style[prop] = n if n is not None else style.get(prop)
            elif prop == "margin":
                self._box_shorthand(style, "margin", v, size)
            elif prop == "padding":
                self._box_shorthand(style, "padding", v, size)
            elif prop == "border":
                self._border_shorthand(style, v, size)
            elif re.match(r"^border-(top|right|bottom|left)$", prop):
                side = prop.split("-")[1]
                self._border_shorthand(style, v, size, side)
            elif re.match(r"^margin-(top|right|bottom|left)$", prop):
                side = prop.split("-")[1]
                n = css.parse_length(v, base_px=size)
                if v.endswith("%"):
                    n = ("%", css.parse_number(v[:-1]) / 100)
                style["margin-" + side] = n if n is not None else 0.0
            elif re.match(r"^padding-(top|right|bottom|left)$", prop):
                side = prop.split("-")[1]
                n = css.parse_length(v, base_px=size)
                if v.endswith("%"):
                    n = ("%", css.parse_number(v[:-1]) / 100)
                style["padding-" + side] = n if n is not None else 0.0
            elif re.match(r"^border-(top|right|bottom|left)-(width|color|style)$", prop):
                side = prop.split("-")[1]
                sub = prop.split("-")[2]
                if sub == "width":
                    n = css.parse_length(v, base_px=size)
                    style[prop] = int(n) if n is not None else 0
                elif sub == "color":
                    c = css.parse_color(v)
                    style[prop] = c
                else:
                    style[prop] = v if v in ("solid", "dashed", "dotted",
                                             "double", "inset", "outset",
                                             "groove", "ridge") else "none"
        # display defaults per tag
        if tag in ("html", "body", "head"):
            style["display"] = "block"
        elif tag in ("script", "style", "link", "meta", "title", "head"):
            style["display"] = "none"
        elif tag in BLOCK_ELEMS_DEFAULT:
            if style["display"] == "inline":
                style["display"] = "block"
        if tag in ("table",):
            style["display"] = "table"
        if tag in ("tr",):
            style["display"] = "table-row"
        if tag in ("td", "th"):
            style["display"] = "table-cell"
        if tag == "li":
            if style["display"] == "inline":
                style["display"] = "block"
        if tag in HEADING_SIZES and not decls.get("font-size"):
            style["font-size"] = size * HEADING_SIZES[tag]
        if style["line-height"] is None:
            style["line-height"] = style["font-size"] * 1.25
        self._style_cache[key] = style
        return style

    def visited_contains(self, node):
        href = node.get("href")
        if href:
            from . import net
            return net.resolve(self.ctx.base_url or "", href) in self.visited
        return False

    def _box_shorthand(self, style, kind, v, size):
        vals = [css.parse_length(x.strip(), base_px=size) or 0.0
                for x in v.split()]
        pct = [x.strip() for x in v.split() if x.strip().endswith("%")]
        if len(vals) == 1:
            vals = vals * 4
        elif len(vals) == 2:
            vals = [vals[0], vals[1], vals[0], vals[1]]
        elif len(vals) == 3:
            vals = [vals[0], vals[1], vals[2], vals[1]]
        if len(vals) < 4:
            vals = (vals + [0.0] * 4)[:4]
        for side, val in zip(("top", "right", "bottom", "left"), vals):
            style[f"{kind}-{side}"] = val
        if pct:
            p = css.parse_number(pct[0].rstrip("%")) / 100
            style[f"{kind}-top"] = ("%", p)
            style[f"{kind}-bottom"] = ("%", p)
            style[f"{kind}-left"] = ("%", p)
            style[f"{kind}-right"] = ("%", p)

    def _border_shorthand(self, style, v, size, side=None):
        w = None
        c = None
        st = "solid"
        for tok in v.split():
            if re.match(r"^\d", tok):
                n = css.parse_length(tok, base_px=size)
                if n is not None:
                    w = int(n)
            elif css.parse_color(tok) is not None:
                c = css.parse_color(tok)
            elif tok in ("none", "hidden"):
                st = "none"
            else:
                st = tok
        sides = [side] if side else ["top", "right", "bottom", "left"]
        for s in sides:
            style[f"border-{s}-width"] = w if w is not None else \
                style.get(f"border-{s}-width", 0)
            if c is not None:
                style[f"border-{s}-color"] = c
            if st != "none" or w:
                style[f"border-{s}-style"] = st

    # ------------------------------------------------------------------
    # Box tree
    # ------------------------------------------------------------------
    def build(self):
        html_el = self.document.first("html") or self.document
        body = html_el.first("body")
        root_style = self.style_of(html_el, parent_style=None)
        self.root = Box(html_el, root_style, "root")
        self.root.is_root = True
        self.root.x = 0
        self.root.y = 0
        self.root.w = self.viewport_w
        bg = root_style["background-color"]
        self.root.bg = bg if bg is not None else (255, 255, 255)
        if body:
            self._layout_block(self.root, body)
        else:
            self._layout_block(self.root, self.document)
        self.root.h = self.root.content_y() + self._content_height(self.root)
        return self.root

    def _content_height(self, box):
        h = 0.0
        for c in box.children:
            h = max(h, c.y + c.h - box.content_y())
        for line in box.lines:
            h = max(h, line.y + line.h - box.content_y())
        s = box.style
        return h + s["padding-bottom"] + s["border-bottom-width"]

    def _layout_block(self, parent_box, node):
        style = self.style_of(node)
        box = Box(node, style, "block")
        parent_box.add(box)

        # width resolution
        avail = parent_box.content_w()
        w = style["width"]
        if isinstance(w, tuple):
            box.w = avail * w[1]
        elif w is not None:
            box.w = min(avail, w)
        else:
            box.w = avail
        mw = style["max-width"]
        if isinstance(mw, tuple):
            box.w = min(box.w, avail * mw[1])
        elif mw is not None:
            box.w = min(box.w, mw)

        # margins
        mt, mb = style["margin-top"], style["margin-bottom"]
        ml, mr = style["margin-left"], style["margin-right"]
        if isinstance(mt, tuple):
            mt = parent_box.content_w() * mt[1]
        if isinstance(mb, tuple):
            mb = parent_box.content_w() * mb[1]
        if isinstance(ml, tuple):
            ml = parent_box.content_w() * ml[1]
        if isinstance(mr, tuple):
            mr = parent_box.content_w() * mr[1]
        if isinstance(style["padding-left"], tuple):
            pass  # padding % handled at paint/measure time
        box.x = parent_box.content_x() + ml
        box.y = parent_box.content_y() + self._stack_y(parent_box) + mt
        box.w = max(1.0, box.w - ml - mr)
        if box.w <= 0:
            box.w = 1.0

        if node.tag_name() == "hr":
            self._layout_hr(box, parent_box)
            self._record(box)
            return

        if node.tag_name() == "li":
            box.marker = self._marker_for(node, style)

        if node.tag_name() == "table":
            self._layout_table(box, node)
            self._record(box)
            return

        if node.tag_name() in ("img", "video"):
            self._layout_media(box, node, parent_box)
            self._record(box)
            return

        if node.tag_name() in FORM_CONTROL:
            self._layout_control(box, node, parent_box)
            self._record(box)
            return

        # children: blocks vs inline flow
        inline_items = []
        inline_ok = node.tag_name() != "pre" or style["white-space"] == "normal"
        for child in node.children:
            if child.is_comment:
                continue
            if child.is_text:
                if child.text.strip():
                    inline_items.append(child)
                continue
            if not child.is_element:
                continue
            cstyle = self.style_of(child, style)
            if cstyle["display"] == "none" or child.get("hidden") is not None:
                continue
            if cstyle["display"] == "block":
                if inline_items:
                    self._layout_inline(box, inline_items, parent_box)
                    inline_items = []
                self._layout_block(box, child)
            else:
                inline_items.append(child)

        if inline_items:
            self._layout_inline(box, inline_items, parent_box)

        box.h = max(0.0, self._content_height(box))
        if style["height"]:
            if isinstance(style["height"], tuple):
                box.h = max(box.h, parent_box.content_h() * style["height"][1])
            else:
                box.h = max(box.h, style["height"])
        box.natural = self._natural_width(box)
        self._record(box)
        return box

    def _stack_y(self, parent_box):
        """Bottom of last laid-out child (for stacking inside parent)."""
        y = 0.0
        for c in parent_box.children:
            y = max(y, c.y + c.h - parent_box.content_y())
        for line in parent_box.lines:
            y = max(y, line.y + line.h - parent_box.content_y())
        return y

    def _marker_for(self, node, style):
        parent = node.parent
        if parent is None:
            return "•"
        kind = style["list-style-type"]
        if kind == "none":
            return None
        ptag = parent.tag_name()
        if ptag == "ol":
            n = 1
            for sib in parent.children:
                if sib is node:
                    break
                if sib.is_element and sib.tag_name() == "li":
                    n += 1
            return f"{n}."
        return {"disc": "•", "circle": "○", "square": "▪"}.get(kind, "•")

    # ------------------------------------------------------------------
    # Inline flow
    # ------------------------------------------------------------------
    def _collect_tokens(self, node, style, out, pre=False):
        """Flatten inline content into tokens: (text|obj, style, node)."""
        for child in node.children:
            if child.is_comment:
                continue
            if child.is_text:
                text = child.text
                if style["text-transform"] == "uppercase":
                    text = text.upper()
                elif style["text-transform"] == "lowercase":
                    text = text.lower()
                elif style["text-transform"] == "capitalize":
                    text = text.capitalize()
                if pre:
                    for chunk in text.split("\n"):
                        if chunk:
                            out.append((chunk, style, node))
                        out.append(("\n", style, node))
                    if out and out[-1][0] == "\n":
                        out.pop()
                    continue
                for word in text.split():
                    out.append((word, style, node))
                    out.append((" ", style, node))
                if out and out[-1][0] == " ":
                    out.pop()
                continue
            if not child.is_element:
                continue
            cstyle = self.style_of(child, style)
            if cstyle["display"] == "none" or child.get("hidden") is not None:
                continue
            tag = child.tag_name()
            if tag == "br":
                out.append(("br", cstyle, child))
                continue
            if tag in ("img", "video"):
                out.append(("media", cstyle, child))
                continue
            if tag in FORM_CONTROL:
                out.append(("ctl", cstyle, child))
                continue
            # nested inline element (span/a/b/i/...)
            self._collect_tokens(child, cstyle, out, pre)

    def _layout_inline(self, box, items, parent_box):
        style = box.style
        pre = style["white-space"] in ("pre", "pre-wrap")
        tokens = []
        for item in items:
            if item.is_text:
                text = item.text
                if style["text-transform"] == "uppercase":
                    text = text.upper()
                elif style["text-transform"] == "lowercase":
                    text = text.lower()
                if pre:
                    for chunk in text.split("\n"):
                        if chunk:
                            tokens.append((chunk, style, item))
                        tokens.append(("\n", style, item))
                    if tokens and tokens[-1][0] == "\n":
                        tokens.pop()
                    continue
                for word in text.split():
                    tokens.append((word, style, item))
                    tokens.append((" ", style, item))
                if tokens and tokens[-1][0] == " ":
                    tokens.pop()
            else:
                cstyle = self.style_of(item, style)
                if cstyle["display"] == "none" or item.get("hidden") is not None:
                    continue
                tag = item.tag_name()
                if tag == "br":
                    tokens.append(("br", cstyle, item))
                elif tag in ("img", "video"):
                    tokens.append(("media", cstyle, item))
                else:
                    self._collect_tokens(item, cstyle, tokens, pre)

        cx = box.content_x()
        cw = max(10.0, box.content_w())
        x = cx
        y = box.content_y()
        cur_y = y
        first_line = True
        line = Line()
        indent = style["text-indent"]
        used = indent
        x += indent
        space_w = 0.0
        # font for measuring spaces
        f0 = theme.font("sans", "normal", "normal", max(4, int(style["font-size"])))

        def make_run(tok):
            t, tstyle, tnode = tok
            size = max(4, int(round(tstyle["font-size"])))
            font = theme.font(tstyle["font-family"], tstyle["font-weight"],
                              tstyle["font-style"], size)
            if t == "br":
                return Run("", tstyle, tnode, "br")
            if t == "img":
                run = Run("", tstyle, tnode, "img")
                run.img = self._load_img(tnode, tstyle, box)
                w = tstyle["width"]
                if isinstance(w, tuple):
                    w = cw * w[1]
                elif w is not None:
                    w = w
                else:
                    w = run.img.size[0] if run.img else 16
                h = tstyle["height"]
                if isinstance(h, tuple):
                    h = box.content_h() * h[1]
                elif h is not None:
                    h = h
                else:
                    h = run.img.size[1] if run.img else 16
                if run.img and w > cw:
                    ratio = cw / w
                    w, h = cw, h * ratio
                run.w, run.h = w, h
                run.font = font
                return run
            if t == "media":
                run = Run("", tstyle, tnode, "img")
                if tnode.tag_name() == "video":
                    st = self.ctx.video_for(tnode)
                    img = st.snapshot()[0] if st is not None else None
                    if img is None:
                        img = self.ctx.video_frame(tnode)
                    run.img = img
                    run.video = st
                    nat = img.size if img else (320, 180)
                else:
                    run.img = self._load_img(tnode, tstyle, box)
                    nat = run.img.size if run.img else (16, 16)
                w = tstyle["width"]
                if isinstance(w, tuple):
                    w = cw * w[1]
                elif w is not None:
                    w = w
                else:
                    w = nat[0]
                h = tstyle["height"]
                if isinstance(h, tuple):
                    h = box.content_h() * h[1]
                elif h is not None:
                    h = h
                else:
                    h = nat[1]
                if w > cw:
                    ratio = cw / w
                    w, h = cw, h * ratio
                run.w, run.h = w, h
                run.font = font
                return run
            if t == "ctl":
                run = Run("", tstyle, tnode, "control")
                ctl = self._control_box(tnode, tstyle, box)
                run.control = ctl
                run.w, run.h = ctl.w, ctl.h
                run.font = font
                return run
            width = font.getbbox(t)[2]
            run = Run(t, tstyle, tnode, "space" if t == " " else "text")
            run.w = width
            run.h = font.getmetrics()[0] + font.getmetrics()[1]
            run.font = font
            return run

        def measure(tok):
            t, tstyle, tnode = tok
            if t == "br":
                return 0.0
            size = max(4, int(round(tstyle["font-size"])))
            font = theme.font(tstyle["font-family"], tstyle["font-weight"],
                              tstyle["font-style"], size)
            if t == "img":
                run = make_run(tok)
                return run.w
            if t == "media":
                run = make_run(tok)
                return run.w
            if t == "ctl":
                run = make_run(tok)
                return run.w
            return font.getbbox(t)[2]

        def flush():
            nonlocal line, x, used, cur_y
            if not line.runs:
                return
            line.y = cur_y
            self._layout_line(line, box, cx, cw, used)
            box.lines.append(line)
            cur_y += line.h
            line = Line()

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            t = tok[0]
            if t == "\n" or t == "br":
                flush()
                x = cx + indent
                used = indent
                first_line = False
                i += 1
                continue
            if t == " ":
                i += 1
                continue
            w = measure(tok)
            # word wrap: break long words
            if w > cw - 2:
                # hard-break the word
                tstyle = tok[1]
                size = max(4, int(round(tstyle["font-size"])))
                font = theme.font(tstyle["font-family"], tstyle["font-weight"],
                                  tstyle["font-style"], size)
                sub = t
                while sub:
                    fit = 0
                    for j in range(1, len(sub) + 1):
                        if font.getbbox(sub[:j])[2] <= cw - 2:
                            fit = j
                        else:
                            break
                    if fit <= 0:
                        fit = 1
                    if x + font.getbbox(sub[:fit])[2] > cx + cw and line.runs:
                        flush()
                        x = cx + indent
                        used = indent
                        first_line = False
                    if fit == 0:
                        break
                    run = make_run((sub[:fit], tstyle, tok[2]))
                    line.runs.append(run)
                    x += run.w
                    used += run.w
                    sub = sub[fit:]
                    if sub:
                        flush()
                        x = cx + indent
                        used = indent
                        first_line = False
                # trailing space run
                i += 1
                continue
            if x + w > cx + cw and line.runs:
                flush()
                x = cx + indent
                used = indent
                first_line = False
            run = make_run(tok)
            line.runs.append(run)
            x += run.w
            used += run.w
            i += 1
        flush()

    def _layout_line(self, line, box, cx, cw, used):
        runs = line.runs
        max_asc = max_des = 0.0
        max_h = 0.0
        for r in runs:
            if r.kind in ("img", "control"):
                max_h = max(max_h, r.h)
                continue
            asc, des = r.font.getmetrics()
            max_asc = max(max_asc, asc)
            max_des = max(max_des, des)
        lh = box.style["line-height"]
        line_h = max(max_h, max_asc + max_des)
        if lh:
            line_h = max(line_h, lh)
        line.h = line_h
        baseline = max_asc + (line_h - (max_asc + max_des)) / 2
        line.baseline = baseline
        # align: justify spreads spaces
        text_w = sum(r.w for r in runs if r.kind in ("text", "space"))
        extra = 0.0
        if box.style["text-align"] == "justify" and line_h > 0:
            nspaces = sum(1 for r in runs if r.kind == "space")
            if nspaces and text_w < cw - 4:
                extra = (cw - 4 - text_w) / nspaces
        elif box.style["text-align"] == "center":
            line.x0 = cx + max(0.0, (cw - text_w) / 2)
        elif box.style["text-align"] == "right":
            line.x0 = cx + max(0.0, cw - text_w)
        else:
            line.x0 = cx
        x = line.x0
        for r in runs:
            r.x = x
            if r.kind in ("img", "control"):
                r.y = line.y + max(0.0, (line_h - r.h) / 2)
            else:
                va = r.style["vertical-align"]
                if va == "sub":
                    r.y = line.y + baseline - r.font.getmetrics()[0] + \
                        r.font.getmetrics()[0] * 0.35
                elif va == "super":
                    r.y = line.y + baseline - r.font.getmetrics()[0] - \
                        r.font.getmetrics()[0] * 0.35
                else:
                    r.y = line.y + baseline - r.font.getmetrics()[0]
            r.color = r.style["color"]
            x += r.w
            if r.kind == "space":
                x += extra
            if r.kind in ("img", "control"):
                # record interactive region
                self.regions.append((r.x, r.y, r.w, r.h, r.node, r.kind))
                if r.node is not None and r.node.is_element:
                    self.node_boxes[id(r.node)] = (r.x, r.y, r.w, r.h)

    # ------------------------------------------------------------------
    # Replaced content & controls
    # ------------------------------------------------------------------
    def _load_img(self, node, style, box):
        src = node.get("src")
        if not src:
            return None
        from . import net
        url = net.resolve(self.ctx.base_url or "", src)
        return self.ctx.load_img(url)

    def _layout_media(self, box, node, parent_box):
        """Block-level img/video: intrinsic size from the media or attrs."""
        src = node.get("src")
        url = net.resolve(self.ctx.base_url or "", src) if src else ""
        if node.tag_name() == "video":
            st = self.ctx.video_for(node)
            img = st.first_frame() if st is not None else None
            box.media_state = st
            w = node.get("width")
            h = node.get("height")
            aw, ah = (img.size if img else (320, 180))
            if w:
                try:
                    aw = float(w)
                except ValueError:
                    pass
            if h:
                try:
                    ah = float(h)
                except ValueError:
                    pass
            if not img and not w and not h:
                aw, ah = 320, 180
        else:
            img = self._load_img(node, box.style, box)
            w = node.get("width")
            h = node.get("height")
            aw, ah = (img.size if img else (16, 16))
            if w:
                try:
                    aw = float(w)
                except ValueError:
                    pass
            if h:
                try:
                    ah = float(h)
                except ValueError:
                    pass
        box.media_img = img
        cw = max(10.0, parent_box.content_w())
        if aw > cw:
            ah = ah * cw / aw
            aw = cw
        box.w = max(1.0, aw)
        box.h = max(1.0, ah)
        self._record(box)
        return box

    def _control_box(self, node, style, parent_box):
        tag = node.tag_name()
        ctl = Box(node, style, "inline")
        font = theme.font(style["font-family"], style["font-weight"],
                          style["font-style"],
                          max(4, int(round(style["font-size"]))))
        lh = font.getmetrics()[0] + font.getmetrics()[1]
        if tag == "input":
            t = node.get("type", "text").lower()
            if t in ("checkbox", "radio"):
                ctl.w = ctl.h = 13.0
            else:
                chars = int(node.get("size", 20) or 20)
                ctl.w = max(30.0, chars * 8 + 14)
                ctl.h = lh + 8
                node.set("_field_type", "text")
        elif tag == "textarea":
            rows = int(node.get("rows", 2) or 2)
            cols = int(node.get("cols", 40) or 40)
            ctl.w = max(40.0, cols * 7 + 12)
            ctl.h = rows * lh + 8
            node.set("_field_type", "textarea")
        elif tag == "select":
            opts = [c for c in node.children if c.is_element and
                    c.tag_name() == "option"]
            ctl.options = [o.text_content() for o in opts]
            sel = 0
            for i, o in enumerate(opts):
                if o.get("selected") is not None:
                    sel = i
            ctl.selected_index = sel
            text = ctl.options[sel] if ctl.options else ""
            ctl.control_text = text
            ctl.w = max(50.0, font.getbbox(text)[2] + 26)
            ctl.h = lh + 8
            node.set("_field_type", "select")
        elif tag == "button":
            text = node.text_content().strip() or node.get("value", "")
            ctl.control_text = text
            ctl.w = max(30.0, font.getbbox(text)[2] + 22)
            ctl.h = lh + 8
            node.set("_field_type", "button")
        ctl.natural = ctl.w
        return ctl

    def _layout_control(self, box, node, parent_box):
        ctl = self._control_box(node, box.style, parent_box)
        box.w = ctl.w
        box.h = ctl.h
        box.control_text = ctl.control_text
        box.options = ctl.options
        box.selected_index = ctl.selected_index
        if node.get("checked") is not None:
            box.checked = True
        t = node.get("type", "text").lower()
        box.kind = "control"
        if t in ("checkbox", "radio"):
            box.kind = "checkbox"
        box.natural = box.w

    def _layout_hr(self, box, parent_box):
        box.h = 2.0
        box.natural = 0.0

    def _layout_table(self, box, node):
        rows = []
        for r in node.find_all("tr"):
            cells = [c for c in r.children if c.is_element and
                     c.tag_name() in ("td", "th")]
            rows.append((r, cells))
        if not rows:
            return
        ncols = max(len(cells) for _r, cells in rows)
        # measure natural widths
        col_w = [0.0] * ncols
        for _r, cells in rows:
            for i, cell in enumerate(cells):
                cstyle = self.style_of(cell)
                nat = self._measure_cell(cell, cstyle)
                if i < ncols:
                    col_w[i] = max(col_w[i], nat)
        avail = box.content_w()
        total = sum(col_w)
        if total > avail and total > 0:
            scale = avail / total
            col_w = [max(10.0, w * scale) for w in col_w]
        x = box.content_x()
        y = box.content_y()
        row_hs = []
        for r, cells in rows:
            rstyle = self.style_of(r)
            rbox = Box(r, rstyle, "table-row")
            rbox.x = x
            rbox.y = y
            rbox.w = sum(col_w)
            cx = x
            rmax_h = 0.0
            for i, cell in enumerate(cells):
                cstyle = self.style_of(cell)
                cbox = Box(cell, cstyle, "table-cell")
                cbox.x = cx
                cbox.y = y
                cbox.w = col_w[i] if i < ncols else col_w[-1]
                self._layout_cell(cbox)
                rmax_h = max(rmax_h, cbox.h)
                cx += col_w[i] if i < ncols else col_w[-1]
            for c in rbox.children:
                c.h = max(c.h, rmax_h)
            rbox.h = rmax_h
            box.add(rbox)
            y += rmax_h
        box.h = y - box.content_y() + 0.0

    def _measure_cell(self, cell, style):
        """Approximate natural width of a cell's content."""
        pad = style["padding-left"] + style["padding-right"]
        inline = True
        for c in cell.children:
            if c.is_element and self.style_of(c).get("display") == "block":
                inline = False
                break
        if not inline:
            w = 0.0
            for c in cell.children:
                if c.is_element:
                    w = max(w, self._measure_cell(c, self.style_of(c)))
            return w + pad + 4
        w = 0.0
        for c in cell.children:
            if c.is_text:
                font = theme.font(style["font-family"], style["font-weight"],
                                  style["font-style"],
                                  max(4, int(round(style["font-size"]))))
                for word in c.text.split():
                    w += font.getbbox(word)[2] + 4
        return w + pad + 4

    def _layout_cell(self, box):
        node = box.node
        inline_items = []
        for child in node.children:
            if child.is_comment:
                continue
            if child.is_text:
                if child.text.strip():
                    inline_items.append(child)
                continue
            if not child.is_element:
                continue
            cstyle = self.style_of(child, box.style)
            if cstyle["display"] == "none":
                continue
            if cstyle["display"] == "block":
                if inline_items:
                    self._layout_inline(box, inline_items, box)
                    inline_items = []
                self._layout_block(box, child)
            else:
                inline_items.append(child)
        if inline_items:
            self._layout_inline(box, inline_items, box)
        box.h = max(0.0, self._content_height(box)) + 4
        box.natural = self._natural_width(box)
        self._record(box)

    def _natural_width(self, box):
        """Natural (unwrapped) content width approximation for tables."""
        if box.lines:
            w = 0.0
            for line in box.lines:
                w = max(w, sum(r.w for r in line.runs))
            return w
        w = 0.0
        for c in box.children:
            w = max(w, c.w)
        return w

    # ------------------------------------------------------------------
    # Recording regions
    # ------------------------------------------------------------------
    def _record(self, box):
        node = box.node
        if node is None or not node.is_element:
            return
        tag = node.tag_name()
        x, y, w, h = box.x, box.y, box.w, box.h
        self.node_boxes[id(node)] = (x, y, w, h)
        if tag == "a" and node.get("href"):
            self.regions.append((x, y, w, h, node, "link"))
            return
        if tag in ("img", "video"):
            self.regions.append((x, y, w, h, node, tag))
            return
        if tag in FORM_CONTROL:
            self.regions.append((x, y, w, h, node, tag))
            return
        if box.interactive():
            self.regions.append((x, y, w, h, node, "element"))

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paint(self, r, ox, oy, vy=0):
        """Paint the document. ox/oy are pixel offsets in window space
        (oy = viewport_top - scroll); vy is the window y of the viewport top."""
        r.push_clip(0, vy, self.viewport_w, 10 ** 6)
        bg = self.root.bg
        r.rect(-ox, oy, self.viewport_w, 10 ** 6, bg)
        self._paint_box(r, self.root, ox, oy)
        r.pop_clip()

    def all_lines(self):
        out = []
        stack = [self.root]
        while stack:
            b = stack.pop()
            out.extend(b.lines)
            stack.extend(b.children)
        return out

    def _paint_box(self, r, box, ox, oy):
        if box.hidden:
            return
        if box is not self.root:
            r.push_clip(box.x, box.y, box.w, box.h)
        s = box.style
        bg = s["background-color"]
        if bg is not None:
            r.rect(box.x - ox, box.y + oy, box.w, box.h, bg)
        if box.bg is not None:
            r.rect(box.x - ox, box.y + oy, box.w, box.h, box.bg)
        self._paint_border(r, box, ox, oy)
        if box.media_img is not None or box.media_state is not None:
            img = box.media_img
            if box.media_state is not None:
                live, _p, _st, _d, _e = box.media_state.snapshot()
                if live is not None:
                    img = live
            if img is not None:
                r.blit(img, box.x - ox, box.y + oy)
        for line in box.lines:
            self._paint_line(r, line, ox, oy, s)
        if box.marker:
            font = theme.font(s["font-family"], s["font-weight"],
                              s["font-style"], max(4, int(round(s["font-size"]))))
            r.text(box.content_x() - 18 - ox, line_y(box) + oy, box.marker,
                   s["color"], font)
        for c in box.children:
            self._paint_box(r, c, ox, oy)
        if box is not self.root:
            r.pop_clip()

    def _paint_border(self, r, box, ox, oy):
        s = box.style
        sides = ("top", "right", "bottom", "left")
        for side in sides:
            wdt = s[f"border-{side}-width"]
            if wdt <= 0 or s[f"border-{side}-style"] == "none":
                continue
            col = s[f"border-{side}-color"] or s["color"]
            x, y, w, h = box.x, box.y, box.w, box.h
            if side == "top":
                r.rect(x - ox, y + oy, w, wdt, col)
            elif side == "bottom":
                r.rect(x - ox, y + h - wdt + oy, w, wdt, col)
            elif side == "left":
                r.rect(x - ox, y + oy, wdt, h, col)
            else:
                r.rect(x + w - wdt - ox, y + oy, wdt, h, col)

    def _paint_line(self, r, line, ox, oy, block_style):
        for run in line.runs:
            if run.kind == "br":
                continue
            if run.kind == "img":
                img = run.img
                if run.video is not None:
                    live, _pos, state, _dur, _err = run.video.snapshot()
                    if live is not None:
                        img = live
                if img is not None:
                    r.blit(img, run.x - ox, run.y + oy)
                continue
            if run.kind == "control":
                self._paint_control(r, run.control, run.x, run.y, ox, oy)
                continue
            if not run.text:
                continue
            r.text(run.x - ox, run.y + oy, run.text, run.color, run.font)
            dec = run.style["text-decoration"]
            if dec == "underline":
                r.hline(run.x - ox, run.y + oy + run.font.getmetrics()[0] + 1,
                        run.w, run.color)
            elif dec == "line-through":
                r.hline(run.x - ox, run.y + oy + int(run.h * 0.45),
                        run.w, run.color)
            elif dec == "overline":
                r.hline(run.x - ox, run.y + oy - 1, run.w, run.color)

    def _paint_control(self, r, ctl, x, y, ox, oy):
        node = ctl.node
        if node is None:
            return
        tag = node.tag_name()
        s = ctl.style
        font = theme.font(s["font-family"], s["font-weight"], s["font-style"],
                          max(4, int(round(s["font-size"]))))
        if tag == "input":
            t = node.get("type", "text").lower()
            if t in ("checkbox", "radio"):
                r.outline(x - ox, y + oy, 13, 13, (120, 120, 120))
                r.rect(x - ox, y + oy, 13, 13, (255, 255, 255))
                if ctl.checked:
                    if t == "radio":
                        r.rect(x - ox + 3, y + oy + 3, 7, 7, (60, 100, 170))
                    else:
                        r.text(x - ox + 1, y + oy + 1, "✓", (60, 100, 170), font)
                return
            r.rect(x - ox, y + oy, ctl.w, ctl.h, (255, 255, 255))
            r.outline(x - ox, y + oy, ctl.w, ctl.h, (110, 110, 110))
            val = node.get("value", "")
            r.text(x - ox + 4, y + oy + 2, val, (20, 20, 20), font)
            return
        if tag == "textarea":
            r.rect(x - ox, y + oy, ctl.w, ctl.h, (255, 255, 255))
            r.outline(x - ox, y + oy, ctl.w, ctl.h, (110, 110, 110))
            val = node.get("value", "")
            lh = font.getmetrics()[0] + font.getmetrics()[1]
            for i, ln in enumerate(val.split("\n")[:20]):
                r.text(x - ox + 4, y + oy + 3 + i * lh, ln, (20, 20, 20), font)
            return
        if tag == "select":
            r.rect(x - ox, y + oy, ctl.w, ctl.h, (235, 235, 235))
            r.outline(x - ox, y + oy, ctl.w, ctl.h, (110, 110, 110))
            r.rect(x - ox + ctl.w - 16, y + oy, 16, ctl.h, (200, 200, 200))
            r.text(x - ox + ctl.w - 12, y + oy + 1, "▼", (60, 60, 60), font)
            text = ctl.control_text
            r.text(x - ox + 4, y + oy + 2, text, (20, 20, 20), font)
            return
        # button
        r.rect(x - ox, y + oy, ctl.w, ctl.h, (228, 228, 232))
        r.outline(x - ox, y + oy, ctl.w, ctl.h, (110, 110, 110))
        text = ctl.control_text
        tw = r.text_w(text, font)
        r.text(x - ox + max(3.0, (ctl.w - tw) / 2), y + oy + 2, text,
               (20, 20, 20), font)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def content_height(self):
        return self.root.h

    def hit(self, x, y):
        for (rx, ry, rw, rh, node, kind) in reversed(self.regions):
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return node, kind
        return None, None

    def hover_regions(self, x, y):
        out = []
        for (rx, ry, rw, rh, node, kind) in self.regions:
            if rx <= x < rx + rw and ry <= y < ry + rh:
                out.append((node, kind))
        return out

    def node_rect(self, node):
        return self.node_boxes.get(id(node))


def line_y(box):
    """Y of the first line's top (for markers)."""
    if box.lines:
        return box.lines[0].y
    return box.content_y()