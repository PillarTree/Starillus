"""Minimal RFC 6455 WebSocket client for Pilot (threaded, event callbacks)."""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
import time
import urllib.parse

MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

CONNECTING = 0
OPEN = 1
CLOSING = 2
CLOSED = 3


class WSConnectError(Exception):
    pass


def _mask(data: bytes) -> bytes:
    key = os.urandom(4)
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ key[i % 4]
    return bytes(out), key


def _encode_frame(opcode: int, payload: bytes) -> bytes:
    header = bytearray()
    header.append(0x80 | opcode)
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", n)
    masked, key = _mask(payload)
    header += key
    return bytes(header) + masked


class WSConn:
    """A WebSocket connection with a background reader thread.

    Callbacks are invoked on the reader thread; they should hand the data
    to the JS engine's queue (see js.py) rather than touching the engine
    directly.
    """

    def __init__(self, url, on_open=None, on_message=None, on_close=None,
                 on_error=None, timeout=10.0):
        self.url = url
        self.on_open = on_open
        self.on_message = on_message
        self.on_close = on_close
        self.on_error = on_error
        self.timeout = timeout
        self.ready_state = CONNECTING
        self.sock = None
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._thread = None
        self.close_code = 1006
        self.close_reason = ""

    # -- lifecycle -------------------------------------------------------
    def connect(self):
        parts = urllib.parse.urlparse(self.url)
        scheme = parts.scheme.lower()
        if scheme not in ("ws", "wss"):
            raise WSConnectError(f"unsupported websocket scheme: {scheme}")
        port = parts.port or (443 if scheme == "wss" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        host = parts.hostname or "localhost"
        try:
            sock = socket.create_connection((host, port), timeout=self.timeout)
            if scheme == "wss":
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=host)
        except OSError as exc:
            raise WSConnectError(f"cannot connect to {host}:{port}: {exc}")
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Origin: null\r\n"
            "\r\n"
        )
        try:
            sock.sendall(req.encode("latin-1"))
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
        except OSError as exc:
            sock.close()
            raise WSConnectError(f"handshake failed: {exc}")
        head, _, rest = resp.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            sock.close()
            raise WSConnectError(f"handshake rejected: {status_line.decode('latin-1', 'replace')}")
        headers = {}
        for line in head.split(b"\r\n")[1:]:
            if b":" in line:
                k, _, v = line.partition(b":")
                headers[k.strip().lower()] = v.strip()
        accept = base64.b64encode(
            hashlib.sha1((key + MAGIC).encode()).digest()).decode()
        if headers.get(b"sec-websocket-accept", b"").decode() != accept:
            sock.close()
            raise WSConnectError("bad Sec-WebSocket-Accept")
        self.sock = sock
        self.ready_state = OPEN
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        if self.on_open:
            self.on_open(self)

    def send(self, message) -> bool:
        if self.ready_state != OPEN:
            return False
        if isinstance(message, str):
            payload = message.encode("utf-8")
            opcode = 0x1
        elif isinstance(message, (bytes, bytearray)):
            payload = bytes(message)
            opcode = 0x2
        else:
            payload = str(message).encode("utf-8")
            opcode = 0x1
        try:
            with self._lock:
                self.sock.sendall(_encode_frame(opcode, payload))
            return True
        except OSError:
            self._fail("send failed")
            return False

    def close(self, code=1000, reason=""):
        if self.ready_state == CLOSED:
            return
        self.ready_state = CLOSING
        try:
            payload = struct.pack("!H", code) + reason.encode("utf-8")[:123]
            with self._lock:
                self.sock.sendall(_encode_frame(0x8, payload))
        except OSError:
            pass

    def _reader(self):
        sock = self.sock
        buffer = b""
        try:
            while not self._closed.is_set():
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    frame, buffer = self._take_frame(buffer)
                    if frame is None:
                        break
                    self._handle(frame)
        except OSError:
            pass
        finally:
            self._teardown()

    def _take_frame(self, buffer):
        if len(buffer) < 2:
            return None, buffer
        b0, b1 = buffer[0], buffer[1]
        fin = b0 & 0x80
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        n = b1 & 0x7F
        off = 2
        if n == 126:
            if len(buffer) < 4:
                return None, buffer
            n = struct.unpack("!H", buffer[2:4])[0]
            off = 4
        elif n == 127:
            if len(buffer) < 10:
                return None, buffer
            n = struct.unpack("!Q", buffer[2:10])[0]
            off = 10
        mask_key = b""
        if masked:
            if len(buffer) < off + 4:
                return None, buffer
            mask_key = buffer[off:off + 4]
            off += 4
        if len(buffer) < off + n:
            return None, buffer
        payload = buffer[off:off + n]
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return (fin, opcode, payload), buffer[off + n:]

    def _handle(self, frame):
        fin, opcode, payload = frame
        if opcode == 0x9:  # ping -> pong
            try:
                with self._lock:
                    self.sock.sendall(_encode_frame(0xA, payload))
            except OSError:
                pass
            return
        if opcode == 0x8:  # close
            code, reason = 1005, ""
            if len(payload) >= 2:
                code = struct.unpack("!H", payload[:2])[0]
                reason = payload[2:].decode("utf-8", "replace")
            self.close_code = code
            self.close_reason = reason
            self.ready_state = CLOSED
            if self.on_close:
                self.on_close(self, code, reason)
            self._shutdown()
            return
        if opcode in (0x1, 0x2):  # text / binary
            text = None
            if opcode == 0x1:
                text = payload.decode("utf-8", "replace")
            if self.on_message:
                self.on_message(self, text, payload)
            return
        if opcode == 0xA:  # pong
            return

    def _fail(self, msg):
        self.ready_state = CLOSED
        if self.on_error:
            try:
                self.on_error(self, msg)
            except Exception:  # noqa: BLE001
                pass
        if self.on_close:
            self.on_close(self, 1006, msg)
        self._shutdown()

    def _shutdown(self):
        self._closed.set()
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def _teardown(self):
        if self.ready_state == OPEN:
            self.ready_state = CLOSED
            if self.on_close:
                self.on_close(self, 1006, "")
        elif self.ready_state == CONNECTING:
            self.ready_state = CLOSED
        self._shutdown()