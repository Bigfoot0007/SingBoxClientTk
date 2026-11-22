"""Bundled sing-box engine — the installer ships its own copy.

CI downloads the official sing-box release binary into assets/ at build
time and the PyInstaller bundle carries it under `assets/`. On startup
we extract it to <workdir>/bin/ and run that, so users never have to
install sing-box — and the config format emitted by core/config.py
(1.14 contract) always matches the engine that consumes it.

When no bundled copy exists (source checkout without assets), the
helpers return "" and callers fall back to the system lookup.
"""
import os
import shutil
import sys

SINGBOX_VERSION = "1.14.4"  # bump together with core/config.py's contract
BIN_NAME = "sing-box.exe" if sys.platform == "win32" else "sing-box"


def bundled_source() -> str:
    """Bundled binary inside the app bundle (PyInstaller _MEIPASS) or,
    when running from source, the repo's assets/ — "" if neither."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = os.path.join(meipass, "assets", BIN_NAME)
        if os.path.exists(p):
            return p
    dev = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", BIN_NAME))
    return dev if os.path.exists(dev) else ""


def ensure_bundled(workdir: str) -> str:
    """Extract the bundled binary to <workdir>/bin/, keeping it current
    via a version stamp file. Returns the path to execute, or "" when
    nothing is bundled."""
    src = bundled_source()
    if not src:
        return ""
    dst = os.path.join(workdir, "bin", BIN_NAME)
    try:
        if os.path.exists(dst):
            try:
                with open(dst + ".ver", encoding="ascii") as f:
                    if f.read().strip() == SINGBOX_VERSION:
                        return dst
            except OSError:
                pass  # no/corrupt stamp — re-extract
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.remove(dst)  # fails on Windows if an orphan is still running
        except OSError:
            pass
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)
        with open(dst + ".ver", "w", encoding="ascii") as f:
            f.write(SINGBOX_VERSION)
        return dst
    except OSError:
        # Can't extract (read-only dir / exe in use) — run the bundle copy.
        return src
