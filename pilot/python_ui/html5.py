"""Tolerant HTML parser that builds a DOM tree (pure stdlib).

Uses html.parser for tokenisation but repairs structure: auto-closes
<p>, <li>, <td>, <option>... as browsers do, drops misplaced tags,
handles void elements and keeps <script>/<style> bodies as raw text.
"""

from __future__ import annotations

from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}

# tags that implicitly close an open element of the same name
IMPLICIT_CLOSE = {
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "p": {"p"},
    "option": {"option", "optgroup"},
    "optgroup": {"optgroup"},
    "tr": {"tr", "td", "th"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "thead": {"tbody", "tfoot"},
    "tbody": {"tbody", "thead"},
    "tfoot": {"tbody"},
}

# block-level elements: a stray closing tag for these is simply ignored
# when the matching open tag is not on the stack (prevents tree corruption)
OPTIONAL_END = {"html", "head", "body", "p", "li", "dt", "dd", "option",
                "tr", "td", "th", "thead", "tbody", "tfoot", "colgroup",
                "caption", "ul", "ol", "dl", "table", "select", "form"}

RAW_TEXT = {"script", "style", "textarea", "title"}

BLOCK_ELEMS = {
    "html", "head", "body", "div", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot",
    "tr", "td", "th", "caption", "form", "fieldset", "blockquote", "pre",
    "hr", "br", "article", "section", "aside", "header", "footer", "nav",
    "main", "figure", "figcaption", "address", "center", "menu", "details",
}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text", "comment",
                 "is_element", "is_text", "is_comment", "line", "js_engine",
                 "scripts", "stylesheets")

    def __init__(self, tag=None, attrs=None, text="", comment=False,
                 is_text=False, line=0):
        self.tag = tag
        self.attrs = attrs if attrs is not None else {}
        self.children: list = []
        self.parent = None
        self.text = text
        self.comment = comment
        self.is_element = tag is not None
        self.is_text = is_text
        self.is_comment = comment
        self.line = line

    # -- helpers ------------------------------------------------------------
    def get(self, key, default=None):
        return self.attrs.get(key.lower(), default)

    def set(self, key, value):
        self.attrs[key.lower()] = value

    def id(self):
        return self.attrs.get("id")

    def classes(self):
        return self.attrs.get("class", "").split()

    def tag_name(self):
        return self.tag.lower() if self.tag else ""

    def is_block(self):
        return self.is_element and self.tag_name() in BLOCK_ELEMS

    def text_content(self) -> str:
        if self.is_text:
            return self.text
        out = []
        for c in self.children:
            out.append(c.text_content())
        return "".join(out)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def elements(self):
        for n in self.walk():
            if n.is_element:
                yield n

    def find_all(self, tag):
        tag = tag.lower()
        return [n for n in self.elements() if n.tag_name() == tag]

    def find_by_id(self, id_):
        for n in self.elements():
            if n.get("id") == id_:
                return n
        return None

    def first(self, tag):
        for n in self.elements():
            if n.tag_name() == tag:
                return n
        return None

    def remove(self):
        if self.parent:
            self.parent.children.remove(self)
        self.parent = None

    def append(self, child):
        child.remove()
        child.parent = self
        self.children.append(child)

    def insert(self, index, child):
        child.remove()
        child.parent = self
        self.children.insert(index, child)

    def next_element(self):
        n = self
        while n:
            if n.parent:
                idx = n.parent.children.index(n)
                for sib in n.parent.children[idx + 1:]:
                    if sib.is_element:
                        return sib
                n = n.parent
            else:
                return None
        return None


def _merge_text(node):
    """Merge adjacent text nodes (after parser runs)."""
    out = []
    for c in node.children:
        if c.is_text and out and out[-1].is_text:
            out[-1].text += c.text
            c.parent = None
        else:
            out.append(c)
    node.children = out
    for c in node.children:
        if c.children:
            _merge_text(c)


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.document = Node(tag="#document")
        self.stack = [self.document]
        self._line = 1
        self._in_raw = None
        self._raw_buf = []
        self.scripts = []  # list of (node, src, code, line) in document order
        self.stylesheets = []  # list of (node, href_or_None, css, line)
        self.links = []

    # -- helpers ------------------------------------------------------------
    @property
    def top(self):
        return self.stack[-1]

    def close_to(self, tag):
        """Pop elements until a matching open tag is found; return it or None."""
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag_name() == tag:
                node = self.stack[i]
                del self.stack[i:]
                return node
        return None

    def _append(self, node):
        self.top.children.append(node)
        node.parent = self.top

    # -- raw-text capture (script/style bodies) -----------------------------
    def _capture(self, tag, attrs):
        self._in_raw = tag
        self._raw_tag = tag
        self._raw_attrs = attrs
        self._raw_buf = []
        self._raw_node = Node(tag=tag, attrs=attrs, line=self._line)

    def _finish_raw(self, name, line):
        node = self._raw_node
        self._append(node)
        if name == "script":
            src = node.get("src")
            if src:
                self.scripts.append((node, src, None, line))
            elif "".join(self._raw_buf).strip():
                self.scripts.append((node, None, "".join(self._raw_buf), line))
        elif name == "style":
            css = "".join(self._raw_buf)
            if css.strip():
                self.stylesheets.append((node, None, css, line))
        self._in_raw = None
        self._raw_node = None

    # -- HTMLParser callbacks -------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._in_raw is not None:
            return  # raw text: content is data until matching end tag
        attrs = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link" and attrs.get("rel", "").lower().split() and \
                "stylesheet" in attrs["rel"].lower():
            self._append(Node(tag=tag, attrs=attrs, line=self._line))
            return
        if tag in RAW_TEXT:
            self._capture(tag, attrs)
            return
        if tag in IMPLICIT_CLOSE:
            for opener in sorted(IMPLICIT_CLOSE[tag]):
                n = self.close_to(opener)
                if n is not None:
                    break
        if tag == "body" and self.top.tag_name() in ("head", "title"):
            self.close_to("head")
        node = Node(tag=tag, attrs=attrs, line=self._line)
        self._append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        attrs = {k.lower(): (v or "") for k, v in attrs}
        self._append(Node(tag=tag, attrs=attrs, line=self._line))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._in_raw is not None:
            if tag == self._in_raw:
                self._finish_raw(tag, self._line)
            return
        node = self.close_to(tag)
        if node is None and tag in OPTIONAL_END:
            return  # stray close tag: ignore

    def handle_data(self, data):
        if self._in_raw is not None:
            self._raw_buf.append(data)
            return
        if data.strip() == "" and self.top.tag_name() not in ("pre", "textarea"):
            return
        if data.strip():
            self._append(Node(text=data, is_text=True, line=self._line))

    def handle_comment(self, data):
        self._append(Node(text=data, comment=True, is_comment=True,
                          line=self._line))

    def handle_pi(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_entityref(self, name):
        pass

    def handle_charref(self, name):
        pass

    def error(self, message):
        pass


def parse(html: str) -> Node:
    p = _Parser()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - never crash on hostile markup
        pass
    if p._in_raw is not None:
        try:
            p._finish_raw(p._in_raw, p._line)
        except Exception:  # noqa: BLE001
            pass
    doc = p.document

    # ensure html/head/body scaffolding
    html_el = doc.first("html")
    if html_el is None:
        html_el = Node(tag="html")
        doc.insert(0, html_el)
    head = html_el.first("head")
    body = html_el.first("body")
    if head is None:
        head = Node(tag="head")
        html_el.insert(0, head)
    if body is None:
        body = Node(tag="body")
        html_el.append(body)

    # a body nested inside head (missing </head>) must move to html level
    if body.parent is not html_el:
        for n in html_el.elements():
            if n.tag_name() == "body" and n is not body:
                body = n
                break
        if body.parent is not html_el:
            body.remove()
            html_el.append(body)

    # move stray top-level elements into body
    stray = [c for c in doc.children if c is not html_el]
    had_real_body = any(c.is_element and c.tag_name() == "body"
                        for c in stray)
    if had_real_body:
        body.remove()  # drop the scaffolding body; real one takes over
    for c in stray:
        c.remove()
        if c.is_comment:
            doc.append(c)
        elif c.is_element and c.tag_name() == "body":
            if had_real_body:
                body = c
                html_el.append(c)
            else:
                body.append(c)
        elif c.tag_name() in ("meta", "title", "link", "style", "base"):
            head.append(c)
        else:
            body.append(c)

    _merge_text(doc)
    doc.scripts = p.scripts
    doc.stylesheets = p.stylesheets
    return doc