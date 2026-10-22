"""The Chrome native-messaging host ``in.ira.mac``: a relay, and nothing more.

Chrome starts this process when the Ira extension connects, and talks to it
over stdin and stdout in length-prefixed JSON frames. The host passes every
frame to the daemon's Unix socket and back. It holds no token, opens no
network connection, and keeps running (retrying the socket every few
seconds) for as long as Chrome keeps the port open, so the extension stays
connected while the daemon restarts.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

from ira_mac.frames import MAX_TO_CHROME, FrameError, encode, read_frame, write_frame

log = logging.getLogger("ira_mac.host")

RETRY_SECONDS = 2.0


class Relay:
    def __init__(
        self,
        path: Path,
        chrome_in: BinaryIO,
        chrome_out: BinaryIO,
        *,
        retry_seconds: float = RETRY_SECONDS,
    ) -> None:
        self.path = path
        self.chrome_in = chrome_in
        self.chrome_out = chrome_out
        self.retry_seconds = retry_seconds
        self._sock: socket.socket | None = None
        self._sock_lock = threading.Lock()
        self._out_lock = threading.Lock()
        self._hello: Any = None  # the extension's hello, told again to each daemon
        self.done = threading.Event()

    def _to_chrome(self, message: Any) -> None:
        with self._out_lock:
            write_frame(self.chrome_out, message, MAX_TO_CHROME)

    def _daemon_loop(self) -> None:
        """Keep a connection to the daemon, and copy its frames to Chrome."""
        while not self.done.is_set():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(str(self.path))
            except OSError:
                time.sleep(self.retry_seconds)
                continue
            with self._sock_lock:
                self._sock = sock
                if self._hello is not None:
                    try:
                        sock.sendall(encode(self._hello))
                    except OSError:
                        pass
            log.info("connected to the daemon")
            stream = sock.makefile("rb")
            try:
                while not self.done.is_set():
                    message = read_frame(stream)
                    if message is None:
                        break
                    try:
                        self._to_chrome(message)
                    except FrameError:
                        log.warning("a frame for Chrome was over 1 MB; dropped")
            except (OSError, FrameError):
                pass
            finally:
                with self._sock_lock:
                    self._sock = None
                sock.close()
            log.info("the daemon went away; retrying")

    def run(self) -> int:
        """Relay until Chrome closes the port (end of stdin)."""
        threading.Thread(target=self._daemon_loop, name="daemon", daemon=True).start()
        try:
            while True:
                message = read_frame(self.chrome_in)
                if message is None:
                    return 0
                with self._sock_lock:
                    if isinstance(message, dict) and message.get("type") == "hello":
                        self._hello = message
                    sock = self._sock
                if sock is None:
                    continue  # the daemon is not up; requests only come from it anyway
                try:
                    sock.sendall(encode(message))
                except OSError:
                    pass
        except FrameError as exc:
            log.warning("bad frame from Chrome: %s", exc)
            return 1
        finally:
            self.done.set()


def main(path: Path) -> int:
    # Chrome reads stdout as frames: nothing else may be written to it.
    return Relay(path, sys.stdin.buffer, sys.stdout.buffer).run()
