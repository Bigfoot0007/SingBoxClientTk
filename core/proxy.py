"""System proxy manager — cross-platform (macOS / Windows / Linux).

Before touching the system proxy, the previous settings are snapshotted
into proxy_state.json (in the app data dir). On disconnect — or when a
leftover proxy from a crashed session is detected at startup — those
settings are restored instead of blindly turning the proxy off. This
keeps other tools' proxies (e.g. a v2rayN-style 10808 setup) intact.
"""
import json
import os
import platform
import subprocess

SYSTEM = platform.system()  # "Darwin", "Windows", or "Linux"

_STATE_PATH = None  # set via set_state_dir(); proxy snapshot lives here


class ProxyManager:
    """Set and restore system proxy, works on macOS, Windows and Linux."""

    @staticmethod
    def set_state_dir(directory: str):
        global _STATE_PATH
        _STATE_PATH = os.path.join(directory, "proxy_state.json")

    # ── snapshot persistence ───────────────────────────────────────────

    @staticmethod
    def _save_state(state: dict):
        if not _STATE_PATH:
            return
        try:
            with open(_STATE_PATH, "w") as f:
                json.dump(state, f)
        except OSError:
            pass

    @staticmethod
    def _load_state():
        if not _STATE_PATH:
            return None
        try:
            with open(_STATE_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _drop_state():
        if _STATE_PATH:
            try:
                os.remove(_STATE_PATH)
            except OSError:
                pass

    # ── public API ─────────────────────────────────────────────────────

    @staticmethod
    def set_proxy(port: int):
        """Enable system proxy (snapshotting the previous settings)."""
        if SYSTEM == "Darwin":
            service = ProxyManager._macos_service()
            if not service:
                return False
            state = ProxyManager._macos_read(service)
            if not ProxyManager._macos_is_ours(state, port):
                ProxyManager._save_state({"macos": state})
            return ProxyManager._macos_set(port)
        elif SYSTEM == "Windows":
            state = ProxyManager._windows_read()
            if state.get("server") != f"127.0.0.1:{port}":
                ProxyManager._save_state({"windows": state})
            return ProxyManager._windows_set(port)
        elif SYSTEM == "Linux":
            state = ProxyManager._linux_read()
            if state.get("host") != "127.0.0.1" or state.get("port") != port:
                ProxyManager._save_state({"linux": state})
            return ProxyManager._linux_set(port)
        return False

    @staticmethod
    def clear_proxy():
        """Disable the proxy, restoring any snapshotted settings."""
        state = ProxyManager._load_state()
        if SYSTEM == "Darwin":
            service = ProxyManager._macos_service()
            if not service:
                return False
            if state and "macos" in state:
                ProxyManager._macos_write(service, state["macos"])
            else:
                ProxyManager._macos_clear()
        elif SYSTEM == "Windows":
            if state and "windows" in state:
                ProxyManager._windows_write(state["windows"])
            else:
                ProxyManager._windows_clear()
        elif SYSTEM == "Linux":
            if state and "linux" in state:
                ProxyManager._linux_write(state["linux"])
            else:
                ProxyManager._linux_clear()
        ProxyManager._drop_state()
        return True

    @staticmethod
    def cleanup_stale_proxy(port: int) -> bool:
        """Clear a leftover proxy from a crashed/killed session.

        Only acts when the current proxy points at this app
        (127.0.0.1:<port>). Restores the pre-connect snapshot if one was
        saved; otherwise just turns the proxy off. Proxies configured by
        the user or other tools are never touched.
        """
        if SYSTEM == "Darwin":
            service = ProxyManager._macos_service()
            if not service:
                return False
            if not ProxyManager._macos_is_ours(
                    ProxyManager._macos_read(service), port):
                return False
            ProxyManager.clear_proxy()  # restores snapshot if present
            return True
        elif SYSTEM == "Windows":
            state = ProxyManager._windows_read()
            if state.get("server") != f"127.0.0.1:{port}" or not state.get("enabled"):
                return False
            ProxyManager.clear_proxy()
            return True
        elif SYSTEM == "Linux":
            state = ProxyManager._linux_read()
            if (state.get("host") != "127.0.0.1"
                    or state.get("port") != port
                    or state.get("mode") != "manual"):
                return False
            ProxyManager.clear_proxy()
            return True
        return False

    @staticmethod
    def current_status() -> dict:
        """Current system proxy settings for display.

        Returns {} when unavailable, else {"web": {...}, "secure": {...}}
        with entries {"enabled": bool, "server": str, "port": int}.
        """
        if SYSTEM == "Darwin":
            service = ProxyManager._macos_service()
            if not service:
                return {}
            return ProxyManager._macos_read(service)
        elif SYSTEM == "Windows":
            raw = ProxyManager._windows_read()
            server, _, port = (raw.get("server") or "").partition(":")
            entry = {"enabled": raw.get("enabled", False),
                     "server": server,
                     "port": int(port) if port.isdigit() else 0}
            return {"web": entry, "secure": entry}
        elif SYSTEM == "Linux":
            raw = ProxyManager._linux_read()
            entry = {"enabled": raw.get("mode") == "manual",
                     "server": raw.get("host", ""),
                     "port": raw.get("port", 0)}
            return {"web": entry, "secure": entry}
        return {}

    @staticmethod
    def is_proxy_enabled() -> bool:
        """Check if the proxy is currently enabled."""
        if SYSTEM == "Darwin":
            return ProxyManager._macos_enabled()
        elif SYSTEM == "Windows":
            return ProxyManager._windows_enabled()
        return False

    # ── macOS ───────────────────────────────────────────────────────────

    @staticmethod
    def _macos_service() -> str | None:
        result = subprocess.run(
            ["/usr/sbin/networksetup", "-listallnetworkservices"],
            capture_output=True, text=True
        )
        services = [s.strip() for s in result.stdout.split("\n")
                    if s.strip() and not s.strip().startswith("*")]
        for s in services:
            if "Wi-Fi" in s:
                return s
        return services[0] if services else None

    @staticmethod
    def _macos_read(service: str) -> dict:
        """Read current web + secure web proxy settings."""
        state = {}
        for kind, flag in (("web", "-getwebproxy"),
                           ("secure", "-getsecurewebproxy")):
            result = subprocess.run(
                ["/usr/sbin/networksetup", flag, service],
                capture_output=True, text=True)
            out = result.stdout
            entry = {"enabled": "Enabled: Yes" in out, "server": "", "port": 0}
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Server:"):
                    entry["server"] = line.split(":", 1)[1].strip()
                elif line.startswith("Port:"):
                    try:
                        entry["port"] = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
            state[kind] = entry
        return state

    @staticmethod
    def _macos_is_ours(state: dict, port: int) -> bool:
        return any(e.get("enabled") and e.get("server") == "127.0.0.1"
                   and e.get("port") == port for e in state.values())

    @staticmethod
    def _macos_write(service: str, state: dict):
        """Write back a previously saved snapshot."""
        for kind, entry in state.items():
            if entry.get("enabled") and entry.get("server"):
                flag = ("-setsecurewebproxy" if kind == "secure"
                        else "-setwebproxy")
                subprocess.run(
                    ["/usr/sbin/networksetup", flag, service,
                     entry["server"], str(entry.get("port", 0))],
                    capture_output=True)
            else:
                flag = ("-setsecurewebproxystate" if kind == "secure"
                        else "-setwebproxystate")
                subprocess.run(
                    ["/usr/sbin/networksetup", flag, service, "off"],
                    capture_output=True)

    @staticmethod
    def _macos_set(port: int) -> bool:
        service = ProxyManager._macos_service()
        if not service:
            return False
        subprocess.run([
            "/usr/sbin/networksetup", "-setwebproxy",
            service, "127.0.0.1", str(port)
        ], capture_output=True)
        subprocess.run([
            "/usr/sbin/networksetup", "-setsecurewebproxy",
            service, "127.0.0.1", str(port)
        ], capture_output=True)
        return True

    @staticmethod
    def _macos_clear() -> bool:
        service = ProxyManager._macos_service()
        if not service:
            return False
        subprocess.run([
            "/usr/sbin/networksetup", "-setwebproxystate", service, "off"
        ], capture_output=True)
        subprocess.run([
            "/usr/sbin/networksetup", "-setsecurewebproxystate",
            service, "off"
        ], capture_output=True)
        return True

    @staticmethod
    def _macos_enabled() -> bool:
        service = ProxyManager._macos_service()
        if not service:
            return False
        result = subprocess.run(
            ["/usr/sbin/networksetup", "-getwebproxy", service],
            capture_output=True, text=True
        )
        return "Enabled: Yes" in result.stdout

    # ── Windows ─────────────────────────────────────────────────────────

    @staticmethod
    def _windows_broadcast():
        """Notify running apps that Internet Settings changed — registry
        edits alone are only picked up by some (IE/WinINet-based) apps."""
        try:
            import ctypes
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            ctypes.windll.user32.SendMessageTimeoutW(
                None, WM_SETTINGCHANGE, 0, "Internet Settings",
                SMTO_ABORTIFHUNG, 5000, None)
        except Exception:
            pass

    @staticmethod
    def _windows_read() -> dict:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_READ
            )
            try:
                enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            except FileNotFoundError:
                enable = 0
            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            except FileNotFoundError:
                server = ""
            try:
                override, _ = winreg.QueryValueEx(key, "ProxyOverride")
            except FileNotFoundError:
                override = ""
            winreg.CloseKey(key)
            return {"enabled": bool(enable), "server": server,
                    "override": override}
        except Exception:
            return {}

    @staticmethod
    def _windows_write(state: dict) -> bool:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD,
                              1 if state.get("enabled") else 0)
            if state.get("server"):
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ,
                                  state["server"])
            if state.get("override"):
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                                  state["override"])
            winreg.CloseKey(key)
            ProxyManager._windows_broadcast()
            return True
        except Exception:
            return False

    @staticmethod
    def _windows_set(port: int) -> bool:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ,
                              f"127.0.0.1:{port}")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                              "<local>")
            winreg.CloseKey(key)
            ProxyManager._windows_broadcast()
            return True
        except Exception:
            return False

    @staticmethod
    def _windows_clear() -> bool:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            ProxyManager._windows_broadcast()
            return True
        except Exception:
            return False

    @staticmethod
    def _windows_enabled() -> bool:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_READ
            )
            value, _ = winreg.QueryValueEx(key, "ProxyEnable")
            return bool(value)
        except Exception:
            return False

    # ── Linux ───────────────────────────────────────────────────────────

    @staticmethod
    def _gsettings_get(schema: str, key: str) -> str:
        r = subprocess.run(["gsettings", "get", schema, key],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""

    @staticmethod
    def _linux_read() -> dict:
        mode = ProxyManager._gsettings_get("org.gnome.system.proxy", "mode")
        host = ProxyManager._gsettings_get(
            "org.gnome.system.proxy.http", "host")
        port = ProxyManager._gsettings_get(
            "org.gnome.system.proxy.http", "port")
        return {
            "mode": mode.strip("'"),
            "host": host.strip("'"),
            "port": int(port.replace("uint32", "").strip() or 0)
                    if port else 0,
        }

    @staticmethod
    def _linux_write(state: dict) -> bool:
        try:
            subprocess.run([
                "gsettings", "set", "org.gnome.system.proxy",
                "mode", state.get("mode", "none")
            ], capture_output=True, check=True)
            if state.get("host"):
                subprocess.run([
                    "gsettings", "set", "org.gnome.system.proxy.http",
                    "host", state["host"]
                ], capture_output=True, check=True)
            if state.get("port"):
                subprocess.run([
                    "gsettings", "set", "org.gnome.system.proxy.http",
                    "port", str(state["port"])
                ], capture_output=True, check=True)
            return True
        except Exception:
            return False

    @staticmethod
    def _linux_set(port: int) -> bool:
        """Set proxy via environment variables (best-effort)."""
        os.environ["http_proxy"] = f"http://127.0.0.1:{port}"
        os.environ["https_proxy"] = f"http://127.0.0.1:{port}"
        # Try GNOME if available
        try:
            subprocess.run([
                "gsettings", "set",
                "org.gnome.system.proxy", "mode", "manual"
            ], capture_output=True, check=True)
            subprocess.run([
                "gsettings", "set",
                "org.gnome.system.proxy.http", "host", "127.0.0.1"
            ], capture_output=True, check=True)
            subprocess.run([
                "gsettings", "set",
                "org.gnome.system.proxy.http", "port", str(port)
            ], capture_output=True, check=True)
        except Exception:
            pass
        return True

    @staticmethod
    def _linux_clear() -> bool:
        os.environ.pop("http_proxy", None)
        os.environ.pop("https_proxy", None)
        try:
            subprocess.run([
                "gsettings", "set",
                "org.gnome.system.proxy", "mode", "none"
            ], capture_output=True, check=True)
        except Exception:
            pass
        return True
