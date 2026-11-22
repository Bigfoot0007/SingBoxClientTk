"""Environment checker — verifies prerequisites and offers installation."""
import platform
import subprocess
import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox

from .nogui import nogui_kwargs

SYSTEM = platform.system()
PYTHON_VERSION = sys.version_info


class CheckResult:
    OK = "ok"
    FAIL = "fail"
    INFO = "info"  # Not critical, but recommended


class EnvChecker:
    """Check if all prerequisites are met."""

    @staticmethod
    def check_python() -> dict:
        """Check Python version and tkinter."""
        result = {"status": CheckResult.OK, "message": ""}
        if PYTHON_VERSION.major < 3 or PYTHON_VERSION.minor < 8:
            result["status"] = CheckResult.FAIL
            result["message"] = f"需要 Python 3.8+, 当前: {PYTHON_VERSION.major}.{PYTHON_VERSION.minor}"
            return result
        try:
            import tkinter
            result["message"] = f"Python {sys.version.split()[0]} ✓"
        except ImportError:
            result["status"] = CheckResult.FAIL
            result["message"] = "tkinter 未安装"
        return result

    @staticmethod
    def _singbox_binary() -> str:
        """Locate the sing-box binary (PATH may be minimal when launched from Finder)."""
        import shutil
        found = shutil.which("sing-box")
        if found:
            return found
        candidates = []
        if SYSTEM == "Darwin":
            candidates = ["/opt/homebrew/bin/sing-box", "/usr/local/bin/sing-box"]
        elif SYSTEM == "Linux":
            candidates = ["/usr/local/bin/sing-box"]
        elif SYSTEM == "Windows":
            local = os.environ.get("LOCALAPPDATA", "")
            user = os.environ.get("USERPROFILE", "")
            candidates = [
                os.path.join(local, "Microsoft", "WinGet", "Links",
                             "sing-box.exe"),
                os.path.join(user, "scoop", "shims", "sing-box.exe"),
                r"C:\ProgramData\chocolatey\bin\sing-box.exe",
            ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return "sing-box"

    @staticmethod
    def check_singbox() -> dict:
        """Check if sing-box is installed and accessible."""
        result = {"status": CheckResult.OK, "message": "", "install_cmd": ""}
        try:
            proc = subprocess.run(
                [EnvChecker._singbox_binary(), "version"],
                capture_output=True, text=True, timeout=5,
                **nogui_kwargs()
            )
            if proc.returncode == 0:
                version_line = proc.stdout.strip().split("\n")[0]
                result["message"] = f"sing-box {version_line} ✓"
                result["status"] = CheckResult.OK
            else:
                result["status"] = CheckResult.FAIL
                result["message"] = "sing-box 执行失败"
        except FileNotFoundError:
            result["status"] = CheckResult.FAIL
            result["message"] = "未找到 sing-box"
            result["install_cmd"] = EnvChecker._singbox_install_cmd()
        except subprocess.TimeoutExpired:
            result["status"] = CheckResult.FAIL
            result["message"] = "sing-box 响应超时"
        return result

    @staticmethod
    def check_config_dir() -> dict:
        """Check if config directory is writable."""
        path = os.path.expanduser(
            "~/Library/Application Support/SingBoxClient"
            if SYSTEM == "Darwin"
            else "~/.config/SingBoxClient"
            if SYSTEM == "Linux"
            else "~/AppData/Roaming/SingBoxClient"
        )
        try:
            os.makedirs(path, exist_ok=True)
            test_file = os.path.join(path, ".test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            return {"status": CheckResult.OK, "message": "配置目录可写 ✓"}
        except Exception:
            return {"status": CheckResult.INFO, "message": "配置目录权限可能不足"}

    @staticmethod
    def _singbox_install_cmd() -> str:
        """Return installation command for sing-box."""
        if SYSTEM == "Darwin":
            return "brew install sing-box"
        elif SYSTEM == "Windows":
            return ("下载 releases 里的 sing-box-<版本>-windows-amd64.zip:\n"
                    "https://github.com/SagerNet/sing-box/releases\n"
                    "解压出 sing-box.exe,放入任一 PATH 目录\n"
                    "(设置 → 系统 → 编辑环境变量,或直接放进\n"
                    "C:\\Users\\你\\AppData\\Local\\Microsoft\\WinGet\\Links)\n"
                    "scoop / chocolatey 安装的也会被自动找到")
        elif SYSTEM == "Linux":
            return """ver=$(curl -s https://api.github.com/repos/SagerNet/sing-box/releases/latest | grep -oP '"tag_name":\\s*"v\\K[^"]+')
curl -L "https://github.com/SagerNet/sing-box/releases/download/v$ver/sing-box-$ver-linux-amd64.tar.gz" -o /tmp/sing-box.tar.gz
tar -xzf /tmp/sing-box.tar.gz -C /tmp
sudo mv "/tmp/sing-box-$ver-linux-amd64/sing-box" /usr/local/bin/
sudo chmod +x /usr/local/bin/sing-box"""
        return "未知系统"

    @staticmethod
    def run_all_checks() -> list:
        """Run all checks and return results."""
        checks = [
            ("Python & tkinter", EnvChecker.check_python()),
            ("sing-box", EnvChecker.check_singbox()),
            ("配置目录", EnvChecker.check_config_dir()),
        ]
        return checks


class EnvInstallDialog:
    """Dialog offering one-click installation."""

    def __init__(self, parent, results: list):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("环境检查")
        self.dialog.geometry("520x380")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.focus_set()

        ttk.Label(self.dialog, text="缺少运行环境，是否需要安装？",
                  font=("Helvetica", 11, "bold")).pack(pady=(12, 5))

        # Results tree
        tree = ttk.Treeview(self.dialog, columns=("status", "detail"),
                            show="tree headings", height=6)
        tree.heading("#0", text="检查项", anchor="w")
        tree.heading("status", text="状态")
        tree.heading("detail", text="详情")
        tree.column("#0", width=140)
        tree.column("status", width=60)
        tree.column("detail", width=280)
        tree.pack(fill="both", expand=True, padx=15, pady=5)

        # Populate results
        for name, result in results:
            icon = "✓" if result["status"] == CheckResult.OK else "✗"
            color = "green" if result["status"] == CheckResult.OK else "red"
            tree.insert("", "end", text=f"{icon} {name}",
                        values=(icon, result["message"]))

        # Install button
        has_fail = any(r["status"] == CheckResult.FAIL for _, r in results)
        if has_fail:
            self._build_install_buttons(tree, results)

    def _build_install_buttons(self, tree, results):
        """Build one-click install buttons."""
        frame = ttk.Frame(self.dialog)
        frame.pack(pady=10, fill="x", padx=15)

        # Find what needs installing
        needs_singbox = any(
            "sing-box" in name and r.get("status") == CheckResult.FAIL
            for name, r in results
        )

        if needs_singbox:
            ttk.Button(
                frame,
                text="🍺 一键安装 sing-box (brew)",
                command=self._install_singbox
            ).pack(side="left", padx=5)

            ttk.Button(
                frame,
                text="📋 复制安装命令",
                command=self._copy_install_cmd
            ).pack(side="left", padx=5)

        ttk.Button(frame, text="跳过（仅检查）", command=self.dialog.destroy).pack()
        ttk.Button(frame, text="重试", command=self._retry).pack(side="right", padx=5)

    def _install_singbox(self):
        """Attempt to install sing-box via brew."""
        if SYSTEM != "Darwin":
            messagebox.showinfo("提示", "当前系统不支持一键安装")
            return

        result = messagebox.askyesno("确认", "将执行:\nbrew install sing-box\n\n需要打开终端吗？")
        if not result:
            return

        # Open terminal and run brew install
        try:
            subprocess.Popen(
                ["open", "-a", "Terminal", "/usr/local/bin/bash"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self.dialog.destroy()
            messagebox.showinfo("提示", "请在终端中执行:\nbrew install sing-box\n\n完成后点击「重试」")
        except Exception as e:
            messagebox.showerror("错误", f"打开终端失败: {e}")

    def _copy_install_cmd(self):
        """Copy installation command to clipboard."""
        for _, result in EnvChecker.run_all_checks():
            if result.get("install_cmd"):
                self.dialog.clipboard_clear()
                self.dialog.clipboard_append(result["install_cmd"])
                self.dialog.update()
                messagebox.showinfo("已复制", "安装命令已复制到剪贴板")
                break

    def _retry(self):
        """Re-run checks."""
        results = EnvChecker.run_all_checks()
        for item in self.dialog.get("children")["!treeview"]:
            self.dialog.get("children")["!treeview"].delete(item)
        for name, result in results:
            icon = "✓" if result["status"] == CheckResult.OK else "✗"
            self.dialog.get("children")["!treeview"].insert(
                "", "end", text=f"{icon} {name}",
                values=(icon, result["message"]))
        has_fail = any(r["status"] == CheckResult.FAIL for _, r in results)
        if not has_fail:
            messagebox.showinfo("成功", "所有检查通过！")
            self.dialog.destroy()
