"""CSS: stylesheet parser, selector matching and the cascade.

Supports element/class/id/* selectors, [attr], [attr=val], descendant,
child and adjacent-sibling combinators, comma-separated selector lists,
!important, inline styles and the usual declarations (colors, background,
fonts, text, box model, display, borders).

Computed styles are plain dicts with lowercase hyphenated keys.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Colour parsing
# ---------------------------------------------------------------------------
NAMED = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "lime": (0, 255, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "cyan": (0, 255, 255), "aqua": (0, 255, 255),
    "magenta": (255, 0, 255), "fuchsia": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "purple": (128, 0, 128), "teal": (0, 128, 128),
    "navy": (0, 0, 128), "orange": (255, 165, 0), "pink": (255, 192, 203),
    "brown": (165, 42, 42), "gold": (255, 215, 0), "tan": (210, 180, 140),
    "khaki": (240, 230, 140), "ivory": (255, 255, 240), "beige": (245, 245, 220),
    "coral": (255, 127, 80), "crimson": (220, 20, 60), "indigo": (75, 0, 130),
    "lavender": (230, 230, 250), "orchid": (218, 112, 214), "plum": (221, 160, 221),
    "salmon": (250, 128, 114), "sienna": (160, 82, 45), "tomato": (255, 99, 71),
    "turquoise": (64, 224, 208), "violet": (238, 130, 238), "wheat": (245, 222, 179),
    "aliceblue": (240, 248, 255), "antiquewhite": (250, 235, 215),
    "azure": (240, 255, 255), "bisque": (255, 228, 196), "blanchedalmond": (255, 235, 205),
    "blueviolet": (138, 43, 226), "burlywood": (222, 184, 135), "cadetblue": (95, 158, 160),
    "chartreuse": (127, 255, 0), "chocolate": (210, 105, 30), "cornflowerblue": (100, 149, 237),
    "cornsilk": (255, 248, 220), "darkblue": (0, 0, 139), "darkcyan": (0, 139, 139),
    "darkgoldenrod": (184, 134, 11), "darkgray": (169, 169, 169), "darkgreen": (0, 100, 0),
    "darkkhaki": (189, 183, 107), "darkmagenta": (139, 0, 139), "darkolivegreen": (85, 107, 47),
    "darkorange": (255, 140, 0), "darkorchid": (153, 50, 204), "darkred": (139, 0, 0),
    "darksalmon": (233, 150, 122), "darkseagreen": (143, 188, 143), "darkslateblue": (72, 61, 139),
    "darkslategray": (47, 79, 79), "darkturquoise": (0, 206, 209), "darkviolet": (148, 0, 211),
    "deeppink": (255, 20, 147), "deepskyblue": (0, 191, 255), "dimgray": (105, 105, 105),
    "dodgerblue": (30, 144, 255), "firebrick": (178, 34, 34), "floralwhite": (255, 250, 240),
    "forestgreen": (34, 139, 34), "gainsboro": (220, 220, 220), "ghostwhite": (248, 248, 255),
    "goldenrod": (218, 165, 32), "greenyellow": (173, 255, 47), "honeydew": (240, 255, 240),
    "hotpink": (255, 105, 180), "indianred": (205, 92, 92), "lightblue": (173, 216, 230),
    "lightcoral": (240, 128, 128), "lightcyan": (224, 255, 255), "lightgoldenrodyellow": (250, 250, 210),
    "lightgray": (211, 211, 211), "lightgreen": (144, 238, 144), "lightpink": (255, 182, 193),
    "lightsalmon": (255, 160, 122), "lightseagreen": (32, 178, 170), "lightskyblue": (135, 206, 250),
    "lightslategray": (119, 136, 153), "lightsteelblue": (176, 196, 222), "lightyellow": (255, 255, 224),
    "limegreen": (50, 205, 50), "linen": (250, 240, 230), "mediumaquamarine": (102, 205, 170),
    "mediumblue": (0, 0, 205), "mediumorchid": (186, 85, 211), "mediumpurple": (147, 112, 219),
    "mediumseagreen": (60, 179, 113), "mediumslateblue": (123, 104, 238),
    "mediumspringgreen": (0, 250, 154), "mediumturquoise": (72, 209, 204),
    "mediumvioletred": (199, 21, 133), "midnightblue": (25, 25, 112), "mintcream": (245, 255, 250),
    "mistyrose": (255, 228, 225), "moccasin": (255, 228, 181), "navajowhite": (255, 222, 173),
    "oldlace": (253, 245, 230), "olivedrab": (107, 142, 35), "orangered": (255, 69, 0),
    "palegoldenrod": (238, 232, 170), "palegreen": (152, 251, 152), "paleturquoise": (175, 238, 238),
    "palevioletred": (219, 112, 147), "papayawhip": (255, 239, 213), "peachpuff": (255, 218, 185),
    "peru": (205, 133, 63), "powderblue": (176, 224, 230), "rebeccapurple": (102, 51, 153),
    "rosybrown": (188, 143, 143), "royalblue": (65, 105, 225), "saddlebrown": (139, 69, 19),
    "seagreen": (46, 139, 87), "seashell": (255, 245, 238), "skyblue": (135, 206, 235),
    "slateblue": (106, 90, 205), "slategray": (112, 128, 144), "snow": (255, 250, 250),
    "springgreen": (0, 255, 127), "steelblue": (70, 130, 180), "thistle": (216, 191, 216),
    "transparent": None,
}

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB = re.compile(r"rgba?\(\s*([\d.]+)\s*[, ]\s*([\d.]+)\s*[, ]\s*([\d.]+)"
                  r"(?:\s*[,/]\s*([\d.]+%?))?\s*\)")


def parse_color(value):
    """Return (r,g,b) or None for 'transparent'/invalid."""
    if value is None:
        return None
    v = value.strip().lower()
    if not v or v == "transparent" or v == "none":
        return None
    if v in NAMED:
        return NAMED[v]
    m = _HEX.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        r, g, b, a = (int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
        if a < 255:
            return None  # alpha colours fall back to no colour
        return (r, g, b)
    m = _RGB.match(v)
    if m:
        r, g, b = (max(0, min(255, int(float(x)))) for x in m.groups()[:3])
        a = m.group(4)
        if a is not None and float(a.rstrip("%")) / (100 if a.endswith("%") else 255) < 1:
            return None
        return (r, g, b)
    return None


# ---------------------------------------------------------------------------
# Lengths
# ---------------------------------------------------------------------------
_LEN = re.compile(r"^(-?[\d.]+)(px|em|rem|%|pt|ex)$")
_KEYWORD_SIZE = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16,
                 "large": 18, "x-large": 24, "xx-large": 32, "xxx-large": 48}


def parse_length(value, base_px=16):
    """Return px (float) or None."""
    if value is None:
        return None
    v = value.strip().lower()
    if v == "0":
        return 0.0
    if v in _KEYWORD_SIZE:
        return float(_KEYWORD_SIZE[v])
    m = _LEN.match(v)
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2)
    if unit == "px":
        return num
    if unit == "pt":
        return num * 4 / 3
    if unit in ("em", "rem", "ex"):
        return num * base_px
    return None  # % handled by caller


def parse_number(value):
    if value is None:
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Stylesheet parsing
# ---------------------------------------------------------------------------
class Rule:
    __slots__ = ("selectors", "declarations", "order")

    def __init__(self, selectors, declarations, order):
        self.selectors = selectors
        self.declarations = declarations
        self.order = order


_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)


def strip_comments(css):
    return _COMMENT.sub(" ", css)


def split_declarations(block):
    out = []
    for part in block.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        prop, _, value = part.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        if not prop or not value:
            continue
        important = value.rstrip().lower().endswith("!important")
        if important:
            value = value[:value.lower().rfind("!important")].strip()
        out.append((prop, value, important))
    return out


def _split_selectors(text):
    parts, depth, buf, out = 0, 0, "", []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            s = buf.strip()
            if s:
                out.append(s)
            buf = ""
        else:
            buf += ch
    s = buf.strip()
    if s:
        out.append(s)
    return out


def parse_stylesheet(css: str, order_offset: int = 0) -> list:
    rules = []
    css = strip_comments(css)
    order = order_offset
    for m in _RULE.finditer(css):
        sel_text, block = m.group(1), m.group(2)
        sel_text = sel_text.strip()
        if not sel_text:
            continue
        if sel_text.startswith("@"):
            continue  # @media / @font-face etc. ignored
        decls = split_declarations(block)
        if not decls:
            continue
        for s in _split_selectors(sel_text):
            rules.append(Rule([s], decls, order))
            order += 1
    return rules


# ---------------------------------------------------------------------------
# Selector model + matching
# ---------------------------------------------------------------------------
class Sel:
    __slots__ = ("tag", "cls", "id_", "attrs", "combinator")

    def __init__(self, tag=None, cls=None, id_=None, attrs=None, combinator=" "):
        self.tag = tag
        self.cls = cls
        self.id_ = id_
        self.attrs = attrs or []
        self.combinator = combinator  # " ", ">", "+"  (how this binds to parent)


_ATTR_RE = re.compile(r"^\[([\w-]+)(?:([~|^$*]?=)\s*\"?([^\"]*?)\"?)?\]$")


def parse_simple(part):
    """Parse one simple selector; return Sel."""
    sel = Sel()
    i, n = 0, len(part)
    buf = ""
    while i < n:
        ch = part[i]
        if ch == ".":
            sel.tag = sel.tag or buf or None
            buf = ""
            j = part.index(".", i)
            k = i + 1
            while k < n and part[k] not in ".#[ :":
                k += 1
            sel.cls = part[i + 1:k]
            i = k
        elif ch == "#":
            sel.tag = sel.tag or buf or None
            buf = ""
            k = i + 1
            while k < n and part[k] not in ".#[ :":
                k += 1
            sel.id_ = part[i + 1:k]
            i = k
        elif ch == "[":
            sel.tag = sel.tag or buf or None
            buf = ""
            k = i
            depth = 0
            while k < n:
                if part[k] == "[":
                    depth += 1
                elif part[k] == "]":
                    depth -= 1
                    if depth == 0:
                        k += 1
                        break
                k += 1
            m = _ATTR_RE.match(part[i:k])
            if m:
                name, op, val = m.groups()
                sel.attrs.append((name.lower(), op or "", val or ""))
            i = k
        else:
            buf += ch
            i += 1
    if buf:
        sel.tag = buf.lower()
    return sel


def split_complex(selector):
    """Split 'a > b.c[attr] + d' into [(simple, combinator), ...]."""
    parts, out = [], []
    buf, depth = "", 0
    for ch in selector:
        if ch in "([":
            depth += 1
            buf += ch
        elif ch in ")]":
            depth -= 1
            buf += ch
        elif depth == 0 and ch in ">+":
            if buf.strip():
                out.append((buf.strip(), " "))
            buf = ""
            out.append(("", ch))
        elif depth == 0 and ch == " ":
            if buf.strip():
                out.append((buf.strip(), " "))
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append((buf.strip(), " "))
    seq, comb = [], " "
    for item in out:
        if item[0] == "":
            comb = item[1]
        else:
            seq.append((item[0], comb))
            comb = " "
    return seq


def specificity(seq):
    a = b = c = 0
    for text, _comb in seq:
        s = parse_simple(text)
        if s.id_:
            a += 1
        if s.cls or s.attrs:
            b += 1
        if s.tag:
            c += 1
    return (a, b, c)


def _matches_simple(node, text):
    if node.tag is None or not node.is_element:
        return False
    s = parse_simple(text)
    if s.tag and s.tag != node.tag_name():
        return False
    if s.cls and s.cls not in node.classes():
        return False
    if s.id_ and node.get("id") != s.id_:
        return False
    for name, op, val in s.attrs:
        got = node.get(name)
        if op == "":
            if got is None:
                return False
        elif op == "=":
            if got != val:
                return False
        elif op == "~=":
            if val not in (got or "").split():
                return False
        elif op == "^=":
            if not (got or "").startswith(val):
                return False
        elif op == "$=":
            if not (got or "").endswith(val):
                return False
        elif op == "*=":
            if val not in (got or ""):
                return False
    return True


def matches(node, selector):
    """Does node match a full (possibly complex) selector? Returns bool."""
    seq = split_complex(selector)
    return _match_seq(node, seq)


def _match_seq(node, seq):
    if not seq:
        return False
    text, comb = seq[-1]
    if not _matches_simple(node, text):
        return False
    rest = seq[:-1]
    if not rest:
        return True
    ptext, pcomb = rest[-1]
    if comb == ">":
        parent = node.parent
        if parent and _match_seq(parent, rest):
            return True
        return False
    if comb == "+":
        idx = node.parent.children.index(node) if node.parent else -1
        if idx > 0 and _match_seq(node.parent.children[idx - 1], rest):
            return True
        return False
    anc = node.parent
    while anc:
        if _match_seq(anc, rest):
            return True
        anc = anc.parent
    return False


# ---------------------------------------------------------------------------
# UA + cascade
# ---------------------------------------------------------------------------
def ua_rules():
    """Default browser stylesheet as (selector, declarations) pairs."""
    return [
        ("html", [("color", "#d8dee9"), ("background-color", "#ffffff"),
                  ("font-family", "sans-serif"), ("font-size", "16px")]),
        ("body", [("margin", "8px")]),
        ("head, title, meta, link, style, script, template",
         [("display", "none")]),
        ("h1, h2, h3, h4, h5, h6, p, div, ul, ol, li, dl, dd, dt, "
         "blockquote, pre, table, tr, td, th, hr, form, fieldset, "
         "section, article, header, footer, nav, main, aside, figure, "
         "figcaption, address",
         [("display", "block")]),
        ("h1", [("font-size", "2em"), ("font-weight", "bold"),
                ("margin", "0.67em 0")]),
        ("h2", [("font-size", "1.5em"), ("font-weight", "bold"),
                ("margin", "0.83em 0")]),
        ("h3", [("font-size", "1.17em"), ("font-weight", "bold"),
                ("margin", "1em 0")]),
        ("h4", [("font-size", "1em"), ("font-weight", "bold"),
                ("margin", "1.33em 0")]),
        ("h5", [("font-size", "0.83em"), ("font-weight", "bold"),
                ("margin", "1.67em 0")]),
        ("h6", [("font-size", "0.67em"), ("font-weight", "bold"),
                ("margin", "2.33em 0")]),
        ("p", [("margin", "1em 0")]),
        ("a", [("color", "link"), ("text-decoration", "underline")]),
        ("ul, ol", [("padding-left", "40px"), ("margin", "1em 0")]),
        ("li", [("margin", "0")]),
        ("blockquote", [("margin", "1em 40px")]),
        ("pre", [("font-family", "monospace"), ("white-space", "pre"),
                 ("margin", "1em 0")]),
        ("code, kbd, samp, tt", [("font-family", "monospace")]),
        ("table", [("border-collapse", "collapse"), ("margin", "1em 0")]),
        ("td, th", [("padding", "2px 6px"), ("border", "1px solid #888")]),
        ("th", [("font-weight", "bold"), ("text-align", "center")]),
        ("caption", [("text-align", "center"), ("font-weight", "bold")]),
        ("hr", [("border", "1px inset"), ("margin", "0.5em 0")]),
        ("img", [("vertical-align", "baseline")]),
        ("strong, b", [("font-weight", "bold")]),
        ("em, i", [("font-style", "italic")]),
        ("u", [("text-decoration", "underline")]),
        ("s, strike, del", [("text-decoration", "line-through")]),
        ("big", [("font-size", "larger")]),
        ("small", [("font-size", "smaller")]),
        ("sub", [("font-size", "0.75em"), ("vertical-align", "sub")]),
        ("sup", [("font-size", "0.75em"), ("vertical-align", "super")]),
        ("center", [("text-align", "center")]),
        ("fieldset", [("border", "1px solid #888"), ("margin", "1em 0"),
                      ("padding", "6px 12px")]),
        ("legend", [("font-weight", "bold")]),
        ("input, textarea, select, button", [("font-family", "sans-serif")]),
        ("input[type=text], input[type=search], input[type=password], "
         "input[type=email], input[type=url], input[type=number], textarea",
         [("background-color", "#ffffff"), ("color", "#111")]),
        ("input[type=checkbox], input[type=radio]",
         [("width", "13px"), ("height", "13px"), ("margin", "0 4px")]),
        ("button, input[type=button], input[type=submit], input[type=reset]",
         [("background-color", "#e8e8e8"), ("border", "1px solid #888"),
          ("padding", "1px 10px")]),
        ("iframe", [("border", "0")]),
        ("mark", [("background-color", "#ffff00")]),
    ]


UA_RULES = ua_rules()


def collect_rules(stylesheet_rules):
    """(ua list + author list) -> (author_rules, order counter)."""
    rules = []
    order = 0
    for sel_text, decls in UA_RULES:
        rules.append(Rule([sel_text],
                          [(p, v, i) for p, v, i in
                           (d if len(d) == 3 else (d[0], d[1], False)
                            for d in decls)],
                          order))
        order += 1
    for rule in stylesheet_rules:
        rules.append(rule)
        order = max(order, rule.order)
    return rules


def cascade(node, rules, inline_style=None, visited=False):
    """Compute the winning declaration for every property of node.

    Returns {property: (value, important)} merged dict and the computed
    specificity so callers can resolve inheritance.
    """
    wins = {}
    best_spec = {}
    order = 0
    for rule in rules:
        for sel in rule.selectors:
            if matches(node, sel):
                spec = specificity(split_complex(sel))
                for prop, value, important in rule.declarations:
                    if important:
                        key = (True, spec, rule.order)
                    else:
                        key = (False, spec, rule.order)
                    cur = wins.get(prop)
                    if cur is None or key > cur[0]:
                        wins[prop] = (key, value)
    if inline_style:
        for prop, value, important in split_declarations(inline_style):
            key = (important, (1, 0, 0, 0), 10 ** 9)
            cur = wins.get(prop)
            if cur is None or key > cur[0]:
                wins[prop] = (key, value)
    out = {}
    for prop, (_key, value) in wins.items():
        out[prop] = value
    return out