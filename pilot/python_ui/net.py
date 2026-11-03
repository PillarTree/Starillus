"""URL fetching for Pilot: http(s) via urllib with a cookie jar, file://,
data: URIs and a basic PIL image cache."""

from __future__ import annotations

import base64
import io
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

from . import theme

_jar = CookieJar()
_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_jar),
    urllib.request.HTTPRedirectHandler(),
)
_opener.addheaders = [("User-Agent", theme.USER_AGENT)]


class FetchError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


_observer = None


def set_observer(fn):
    """Register a callable(method, url, status, ms, size) for the Network
    tab; pass None to unregister."""
    global _observer
    _observer = fn


def _notify(method, url, status, ms, size):
    if _observer is not None:
        try:
            _observer(method, url, status, ms, size)
        except Exception:  # noqa: BLE001
            pass


def normalize_url(text: str) -> str:
    """Turn an address-bar string into a usable URL."""
    text = text.strip()
    if not text:
        return text
    if "://" in text or text.startswith("pilot:"):
        return text
    if text.startswith("about:"):
        return text
    if re.match(r"^[a-zA-Z0-9.-]+(\.[a-zA-Z]{2,})?(:\d+)?(/|$)", text) and "." in text:
        return "http://" + text
    return text


def fetch(url: str, timeout: float = 12.0, post_data: bytes = None) -> tuple:
    """Fetch a URL, return (url, status, content_type, bytes).

    Raises FetchError on failure. Resolves redirects to the final URL.
    post_data enables POST with a request body (application/x-www-form-urlencoded).
    """
    url = normalize_url(url)
    scheme = urllib.parse.urlparse(url).scheme.lower()
    t0 = time.time()
    method = "POST" if post_data is not None else "GET"
    size = 0

    if scheme == "file":
        path = urllib.parse.urlparse(url).path
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            _notify(method, url, 404, (time.time() - t0) * 1000, 0)
            raise FetchError(404, f"file not found: {path} ({exc})") from exc
        ctype = "text/html"
        if path.endswith(".css"):
            ctype = "text/css"
        elif path.endswith((".png", ".gif", ".jpg", ".jpeg", ".webp", ".bmp", ".ico")):
            ctype = "image/" + path.rsplit(".", 1)[-1].lower()
        size = len(data)
        _notify(method, url, 200, (time.time() - t0) * 1000, size)
        return url, 200, ctype, data

    if scheme == "data":
        m = re.match(r"data:([^;,]*)(;base64)?,(.*)", url, re.S)
        if not m:
            _notify(method, url, 400, (time.time() - t0) * 1000, 0)
            raise FetchError(400, "malformed data: URI")
        ctype, is_b64, payload = m.groups()
        try:
            data = base64.b64decode(payload) if is_b64 else urllib.parse.unquote(payload)
        except Exception as exc:  # noqa: BLE001
            _notify(method, url, 400, (time.time() - t0) * 1000, 0)
            raise FetchError(400, f"bad data: URI ({exc})") from exc
        size = len(data)
        _notify(method, url, 200, (time.time() - t0) * 1000, size)
        return url, 200, ctype or "text/plain", data

    if scheme in ("http", "https"):
        try:
            req = urllib.request.Request(url, data=post_data,
                                         method="POST" if post_data
                                         is not None else None)
            if post_data is not None:
                req.add_header("Content-Type",
                               "application/x-www-form-urlencoded")
            with _opener.open(req, timeout=timeout) as resp:
                status = resp.status
                ctype = resp.headers.get_content_type() or "text/html"
                data = resp.read()
                size = len(data)
                _notify(method, resp.geturl(), status,
                        (time.time() - t0) * 1000, size)
                return resp.geturl(), status, ctype, data
        except urllib.error.HTTPError as exc:
            body = exc.read()
            _notify(method, exc.geturl(), exc.code,
                    (time.time() - t0) * 1000, len(body))
            return exc.geturl(), exc.code, exc.headers.get_content_type() or "text/plain", body
        except (urllib.error.URLError, OSError, ValueError) as exc:
            _notify(method, url, 0, (time.time() - t0) * 1000, 0)
            raise FetchError(0, f"cannot reach {url}: {exc}") from exc

    _notify(method, url, 0, (time.time() - t0) * 1000, 0)
    raise FetchError(0, f"unsupported scheme: {scheme}")


def resolve(base: str, href: str) -> str:
    if not href or href.strip() == "":
        return base
    href = href.strip()
    if href.startswith("#"):
        return base.split("#")[0] + href
    if href.startswith("pilot:") or href.startswith("about:"):
        return href
    if href.startswith(("http://", "https://", "file://", "data:")):
        return href
    if base.startswith("pilot:") or base.startswith("about:"):
        return href
    return urllib.parse.urljoin(base, href)


# ---------------------------------------------------------------------------
# Image cache
# ---------------------------------------------------------------------------
_IMG_CACHE: dict = {}


def load_image(url: str, timeout: float = 10.0):
    """Return a PIL image for a URL (cached), or None."""
    hit = _IMG_CACHE.get(url)
    if hit is not None:
        return hit
    img = None
    try:
        _url, status, ctype, data = fetch(url, timeout=timeout)
        if status >= 400:
            return None
        if ctype.startswith("image/"):
            img = __import__("PIL.Image", fromlist=["Image"]).open(
                io.BytesIO(data)).convert("RGBA")
    except Exception:  # noqa: BLE001
        img = None
    if len(_IMG_CACHE) > 256:
        _IMG_CACHE.clear()
    _IMG_CACHE[url] = img
    return img


def guess_encoding(data: bytes, ctype: str = "") -> str:
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    if m:
        try:
            return data.decode(m.group(1))
        except Exception:  # noqa: BLE001
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def url_basename(url: str) -> str:
    p = urllib.parse.urlparse(url).path
    name = os.path.basename(p) or "download"
    return urllib.parse.unquote(name) or "download"