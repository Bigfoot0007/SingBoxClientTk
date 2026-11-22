"""Sing-box process manager — cross-platform."""
import subprocess
import os
import signal
import platform

from .nogui import nogui_kwargs


class SingBoxManager:
    """Start, stop, and restart sing-box."""

    def __init__(self, binary_path=None, workdir=None):
        if binary_path:
            self.binary = binary_path
        elif platform.system() == "Darwin":
            self.binary = "/opt/homebrew/bin/sing-box"
        elif platform.system() == "Linux":
            self.binary = "/usr/local/bin/sing-box"
        else:
            # Windows — sing-box.exe should be in current dir or PATH
            self.binary = "sing-box.exe"
        # Working directory: rule-set/geo caches are stored here,
        # so they survive restarts (otherwise they'd litter the CWD).
        self.workdir = workdir
        self.log_path = os.path.join(workdir or ".", "singbox.log")
        self.pid_path = os.path.join(workdir or ".", "singbox.pid")
        self._process = None
        self._log_file = None
        self._version = None

    def get_version(self) -> str:
        """Binary version, read once and cached."""
        if self._version is None:
            try:
                r = subprocess.run([self.binary, "version"],
                                   capture_output=True, text=True,
                                   timeout=5, **nogui_kwargs())
                if r.returncode == 0:
                    line = r.stdout.strip().splitlines()[0]
                    self._version = line.replace("sing-box version", "").strip()
                else:
                    self._version = "执行失败"
            except (OSError, subprocess.TimeoutExpired):
                self._version = "未找到"
        return self._version

    def running_pids(self) -> list:
        """PIDs of ALL `sing-box ... run` processes on this machine
        (not just the one this session started)."""
        if platform.system() == "Windows":
            return [self._process.pid] if self.is_running else []
        try:
            # -x: match the process NAME exactly; a -f cmdline match would
            # also hit shells whose command text mentions "sing-box run".
            out = subprocess.run(["pgrep", "-x", "sing-box"],
                                 capture_output=True, text=True,
                                 timeout=5).stdout
            return [int(x) for x in out.split()]
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []

    @property
    def is_running(self):
        if self._process is None:
            return False
        return self._process.poll() is None

    def check_config(self, config_path: str):
        """Validate a config file. Returns (ok, message)."""
        cmd = [self.binary, "check"]
        if self.workdir:
            cmd += ["-D", self.workdir]
        cmd += ["-c", config_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=30, **nogui_kwargs())
            if proc.returncode == 0:
                return True, ""
            msg = (proc.stderr or proc.stdout or "").strip()
            return False, msg or "sing-box check 失败"
        except FileNotFoundError:
            return False, f"找不到 sing-box: {self.binary}"
        except subprocess.TimeoutExpired:
            return False, "sing-box check 超时"

    def start(self, config_path: str):
        """Start sing-box with the given config."""
        if self.is_running:
            self.stop()

        cmd = [self.binary]
        if self.workdir:
            cmd += ["-D", self.workdir]
        cmd += ["run", "-c", config_path]

        # Capture stdout/stderr so startup errors (e.g. reality failure,
        # bad rule-set download) can be surfaced in the UI.
        self._log_file = open(self.log_path, "w", encoding="utf-8")
        # CREATE_NO_WINDOW beats the old STARTUPINFO/SW_HIDE trick:
        # hiding still flashes a console for a frame; not allocating one
        # never shows anything (no-op on macOS/Linux).
        kwargs = dict(stdout=self._log_file, stderr=self._log_file,
                      **nogui_kwargs())
        self._process = subprocess.Popen(cmd, **kwargs)

        # Remember the PID so a crashed/exited session's orphaned sing-box
        # can be reaped on next startup (it would otherwise hold port 7890).
        try:
            with open(self.pid_path, "w") as f:
                f.write(str(self._process.pid))
        except OSError:
            pass

    def reap_orphan(self) -> bool:
        """Terminate a sing-box left running by a previous session.

        Returns True if an orphan was found and terminated. Safe to call
        at startup; the PID is verified to actually be sing-box in case
        it was recycled by the OS.
        """
        if platform.system() == "Windows":
            return self._reap_orphan_windows()
        killed = False
        try:
            with open(self.pid_path) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)  # alive?
                if self._is_singbox(pid):
                    os.kill(pid, signal.SIGTERM)
                    killed = True
            except OSError:
                pass  # not alive
        except (OSError, ValueError):
            pass  # no/stale pid file — fall through to the cmdline scan
        try:
            os.remove(self.pid_path)
        except OSError:
            pass

        # Fallback: orphans from sessions that predate (or overwrote) the
        # pid file — any sing-box whose command line references our workdir
        # (config.json and diagnose.json both live there).
        if self.workdir:
            try:
                out = subprocess.run(
                    ["pgrep", "-f", f"sing-box.*{self.workdir}"],
                    capture_output=True, text=True, timeout=5).stdout
                for line in out.split():
                    try:
                        p = int(line)
                        if self._is_singbox(p):
                            os.kill(p, signal.SIGTERM)
                            killed = True
                    except (ValueError, OSError):
                        pass
            except Exception:
                pass
        return killed

    def _reap_orphan_windows(self) -> bool:
        """Windows has no pgrep — trust the pid file, but verify via
        tasklist that the (possibly recycled) pid really is sing-box."""
        try:
            with open(self.pid_path) as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            return False
        try:
            try:
                out = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                    capture_output=True, text=True, timeout=5,
                    **nogui_kwargs()).stdout
                if "sing-box" in out.lower():
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                   capture_output=True, timeout=5,
                                   **nogui_kwargs())
                    return True
            except Exception:
                pass
        finally:
            try:
                os.remove(self.pid_path)
            except OSError:
                pass
        return False

    @staticmethod
    def _is_singbox(pid: int) -> bool:
        try:
            out = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=5).stdout
            return "sing-box" in out
        except Exception:
            return False

    def last_error(self, max_lines: int = 5) -> str:
        """Return the tail of the sing-box log (for error dialogs)."""
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            return "\n".join(lines[-max_lines:]) or "无输出"
        except OSError:
            return "无法读取日志"

    def stop(self):
        """Stop sing-box."""
        if self._process and self.is_running:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        if self._log_file:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None
        try:
            os.remove(self.pid_path)  # clean stop → nothing to reap
        except OSError:
            pass

    def restart(self, config_path: str):
        """Restart sing-box."""
        self.stop()
        self.start(config_path)
