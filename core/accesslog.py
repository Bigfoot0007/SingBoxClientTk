"""Access-log monitor — tails singbox.log while sing-box runs.

sing-box 1.14 logs each accepted connection as three INFO lines sharing a
connection id:

  +0800 2026-11-21 16:40:42 INFO [2678316759 0ms] inbound/mixed[mixed-in]: inbound connection from 127.0.0.1:52362
  +0800 2026-11-21 16:40:42 INFO [2678316759 2ms] inbound/mixed[mixed-in]: inbound connection to www.google.com:443
  +0800 2026-11-21 16:40:42 INFO [2678316759 2ms] outbound/vless[proxy]: outbound connection to www.google.com:443

These are correlated by id and re-emitted as one AccessEvent formatted as:

  2026-11-21 16:40:42 from 127.0.0.1:52362 accepted www.google.com:443 [mixed -> proxy]

Counts per destination host AND per (host, outbound) route feed the
summary pie (slices are route-colored); events feed the log box.
"""
import os
import re
import threading
from collections import OrderedDict

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LINE = re.compile(
    r"^\+\d{4} (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+INFO\s+"
    r"\[(\d+)\s+\d+ms\]\s+(?:inbound|outbound)/(\w+)\[([\w.-]+)\]:\s+"
    r"(inbound connection from|inbound connection to|"
    r"outbound connection to)\s+(\S+)")


def _host_of(dest: str) -> str:
    """Strip sing-box target prefixes and the port for aggregation."""
    for p in ("tcp:", "udp:", "//"):
        if dest.startswith(p):
            dest = dest[len(p):]
            break
    if dest.startswith("["):  # [::1]:443
        end = dest.find("]")
        return dest[:end + 1]
    host, sep, tail = dest.rpartition(":")
    return host if sep and tail.isdigit() else dest


class AccessEvent:
    __slots__ = ("line", "host", "out")

    def __init__(self, line, host, out):
        self.line = line
        self.host = host
        self.out = out


class AccessLogMonitor:
    def __init__(self, log_path: str):
        self.log_path = log_path
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._events = []       # drained by the UI
        self._counts = {}       # host -> connection count
        self._route_counts = {}  # (host, outbound) -> count
        self._conns = OrderedDict()  # id -> partial record (bounded)
        self.total = 0
        self._thread = None

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ── UI-facing (called from the main thread) ───────────────────────

    def drain(self) -> list:
        with self._lock:
            evs, self._events = self._events, []
        return evs

    def counts(self) -> dict:
        with self._lock:
            return dict(self._counts)

    def route_counts(self) -> dict:
        with self._lock:
            return dict(self._route_counts)

    # ── tail loop ─────────────────────────────────────────────────────

    def _loop(self):
        fh = None
        while not self._stop.is_set():
            try:
                if fh is None:
                    try:
                        fh = open(self.log_path, encoding="utf-8",
                                  errors="replace")
                        fh.seek(0, os.SEEK_END)  # monitor from "now"
                    except OSError:
                        self._stop.wait(1.0)
                        continue
                line = fh.readline()
                if not line:
                    try:
                        size = os.path.getsize(self.log_path)
                    except OSError:
                        size = -1
                    if fh.tell() > size:
                        # file truncated (sing-box restarted with 'w'):
                        # re-read the new session from its beginning
                        fh.close()
                        fh = None
                        with self._lock:
                            self._conns.clear()
                        continue
                    self._stop.wait(0.3)
                    continue
                self._feed(line)
            except OSError:
                if fh:
                    try:
                        fh.close()
                    except OSError:
                        pass
                fh = None
                self._stop.wait(1.0)
        if fh:
            try:
                fh.close()
            except OSError:
                pass

    def _feed(self, raw: str):
        m = _LINE.match(_ANSI.sub("", raw))
        if not m:
            return
        ts, cid, kind, tag, phase, target = m.groups()
        with self._lock:
            rec = self._conns.get(cid)
            if phase == "inbound connection from":
                rec = {"ts": ts, "src": target, "dest": None,
                       "inb": tag}
                self._conns[cid] = rec
                # bound the correlation table (abandoned connections)
                while len(self._conns) > 400:
                    self._conns.popitem(last=False)
            elif rec is not None and phase == "inbound connection to":
                rec["dest"] = target
            elif phase == "outbound connection to":
                if rec is None or not rec["dest"]:
                    return
                line = (f"{rec['ts']} from {rec['src']} accepted "
                        f"{rec['dest']} [{rec['inb']} -> {tag}]")
                host = _host_of(rec["dest"])
                self._counts[host] = self._counts.get(host, 0) + 1
                rk = (host, tag)
                self._route_counts[rk] = self._route_counts.get(rk, 0) + 1
                self.total += 1
                self._events.append(AccessEvent(line, host, tag))
                self._conns.pop(cid, None)
