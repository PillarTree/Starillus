"""Minimal <video> support: ffmpeg frame extraction with a player thread."""

from __future__ import annotations

import io
import shutil
import subprocess
import threading
import urllib.parse

_PAUSED = 0
_PLAYING = 1
_ENDED = 2
_ERROR = 3

_FRAME_STEP = 0.5


def available() -> bool:
    return shutil.which("ffmpeg") is not None


def _local_path(url: str):
    p = urllib.parse.urlparse(url)
    if p.scheme in ("", "file"):
        return urllib.parse.unquote(p.path)
    return None


def probe_duration(url: str) -> float:
    path = _local_path(url)
    if path is None or shutil.which("ffprobe") is None:
        return 0.0
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, timeout=8.0, text=True)
        return float(out.stdout.strip() or 0.0)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def extract_frame(url: str, t: float):
    """Return a PIL RGBA image of the video at time t, or None."""
    path = _local_path(url)
    if path is None:
        return None
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=20.0)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return __import__("PIL.Image", fromlist=["Image"]).open(
            io.BytesIO(proc.stdout)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


class VideoState:
    """Shared state for one <video> element. The player thread mutates
    img/pos; the main thread only reads them under the lock."""

    def __init__(self, url):
        self.url = url
        self.lock = threading.Lock()
        self.img = None
        self.pos = 0.0
        self.duration = probe_duration(url)
        self.state = _PAUSED
        self.thread = None
        self.error = None
        self._stop = threading.Event()

    def play(self, browser):
        with self.lock:
            if self.state == _ENDED:
                self.pos = 0.0
            self.state = _PLAYING
            if self.thread and self.thread.is_alive():
                return
            self._stop.clear()
            self.thread = threading.Thread(
                target=self._run, args=(browser,), daemon=True)
            self.thread.start()

    def pause(self):
        with self.lock:
            self.state = _PAUSED

    def toggle(self, browser):
        with self.lock:
            playing = self.state == _PLAYING
        if playing:
            self.pause()
        else:
            self.play(browser)
        return not playing

    def seek(self, t):
        with self.lock:
            self.pos = max(0.0, float(t))
            if self.state == _ENDED:
                self.state = _PAUSED

    def snapshot(self):
        with self.lock:
            return self.img, self.pos, self.state, self.duration, self.error

    def first_frame(self):
        """Ensure we have a poster frame (first frame at current position)."""
        with self.lock:
            if self.img is not None or self.state == _ERROR:
                return self.img
            t = self.pos
        img = extract_frame(self.url, t)
        with self.lock:
            if self.img is None and img is not None:
                self.img = img
            return self.img

    def _run(self, browser):
        while not self._stop.is_set():
            with self.lock:
                if self.state != _PLAYING:
                    return
                t = self.pos
            img = extract_frame(self.url, t)
            with self.lock:
                if self.state != _PLAYING:
                    return
                if img is not None:
                    self.img = img
                    self.pos = t + _FRAME_STEP
                    if self.duration and self.pos >= self.duration:
                        self.pos = self.duration
                        self.state = _ENDED
                else:
                    self.state = _ERROR
                    self.error = "no frame"
            try:
                browser.invalidate()
            except Exception:  # noqa: BLE001
                return
            self._stop.wait(_FRAME_STEP)

    def close(self):
        self._stop.set()
        with self.lock:
            self.state = _PAUSED
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)