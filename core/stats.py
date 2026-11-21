"""Traffic monitor — samples sing-box's Clash API /traffic endpoint.

sing-box streams one JSON line per second: {"up": <B/s>, "down": <B/s>}.
Samples land in a fixed-window ring buffer (default: last 15 minutes).
"""
import http.client
import json
import threading
import time
from collections import deque

WINDOW_SECONDS = 900  # 15 minutes


class TrafficMonitor:
    def __init__(self, port: int, secret: str, window: int = WINDOW_SECONDS):
        self.port = port
        self.secret = secret
        self.window = window
        self.samples = deque(maxlen=window + 60)  # (mono_ts, up_bps, down_bps)
        self.error = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def snapshot(self) -> list:
        """Samples still inside the window (oldest first)."""
        cutoff = time.monotonic() - self.window
        return [s for s in list(self.samples) if s[0] >= cutoff]

    def current(self):
        s = list(self.samples)
        return (s[-1][1], s[-1][2]) if s else (0, 0)

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                                  timeout=5)
                conn.request("GET", "/traffic", headers={
                    "Authorization": f"Bearer {self.secret}"})
                resp = conn.getresponse()
                if resp.status != 200:
                    self.error = f"clash-api HTTP {resp.status}"
                    conn.close()
                    self._stop.wait(3)
                    continue
                self.error = None
                while not self._stop.is_set():
                    line = resp.readline()  # HTTPResponse supports readline
                    if not line:
                        break  # stream closed (sing-box stopping?)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    self.samples.append((time.monotonic(),
                                         int(obj.get("up", 0)),
                                         int(obj.get("down", 0))))
                try:
                    conn.close()
                except OSError:
                    pass
            except OSError as e:
                self.error = str(e)
            if self._stop.is_set():
                return
            self._stop.wait(2)  # reconnect backoff
