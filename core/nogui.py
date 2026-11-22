"""Windows console suppression for subprocess calls.

A windowed app (PyInstaller console=False) has no console of its own, so
every console-subsystem child (sing-box.exe, tasklist, taskkill, …)
allocates a fresh VISIBLE one — the "cmd window flashes for a few
seconds" symptom. CREATE_NO_WINDOW starts the child with no console at
all. On macOS/Linux this is a no-op (GUI processes spawn children
without any terminal anyway).

Apply **nogui_kwargs() to EVERY subprocess.run/Popen that can execute on
Windows — one missed call site reintroduces the flashing window.
"""
import sys

CREATE_NO_WINDOW = 0x08000000


def nogui_kwargs() -> dict:
    return {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}
