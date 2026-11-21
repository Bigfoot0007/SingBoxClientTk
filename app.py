#!/usr/bin/env python3
"""SingBox Client — Simple sing-box GUI client for macOS/Linux/Windows."""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from tkinter import font as tkfont
import atexit
import json
import math
import os
import secrets
import socket
import subprocess
import sys
import threading
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.singbox import SingBoxManager
from core.config import ConfigGenerator
from core.proxy import ProxyManager
from core.check import EnvChecker, EnvInstallDialog
from core.diagnose import NodeDiagnostics
from core.stats import TrafficMonitor
from core.accesslog import AccessLogMonitor


# ── traffic chart theming (validated 2-series palette: blue=down, orange=up) ──
LIGHT_THEME = {"surface": "#fcfcfb", "ink": "#0b0b0b", "secondary": "#52514e",
               "muted": "#898781", "grid": "#e1e0d9", "baseline": "#c3c2b7",
               "up": "#eb6834", "down": "#2a78d6"}
DARK_THEME = {"surface": "#1a1a19", "ink": "#f0efec", "secondary": "#c3c2b7",
              "muted": "#898781", "grid": "#2c2c2a", "baseline": "#383835",
              "up": "#d95926", "down": "#3987e5"}

# Access-pie/log families: proxy = reds, direct = greens. Bases are the
# dataviz status steps (#d03b3b critical / #0ca30c good, both >=3:1 on
# their surfaces); the extra steps are same-hue lightness variants used
# to separate hosts WITHIN a family (sequential ramps).
PROXY_LIGHT = ["#d03b3b", "#e34948", "#a02c2c", "#ee8888", "#7a2323"]
PROXY_DARK = ["#d03b3b", "#e66767", "#a32e2e", "#f0a0a0", "#802020"]
DIRECT_LIGHT = ["#006300", "#2e9e2e", "#57b857", "#04701a", "#8fd08f"]
DIRECT_DARK = ["#0ca30c", "#3fbf3f", "#087a08", "#78d278", "#055c05"]


def _system_is_dark() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        return subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                              capture_output=True).returncode == 0
    except OSError:
        return False


def _fmt_rate(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / 1024 ** 2:.2f} MB/s"


def _fmt_rate_tick(bps: float) -> str:
    """Compact axis-tick variant (long labels clipped the 58px margin)."""
    if bps <= 0:
        return "0"
    if bps < 1024:
        return f"{bps:.0f} B"
    if bps < 1024 ** 2:
        return f"{bps / 1024:.0f} K" if bps >= 10240 else f"{bps/1024:.1f} K"
    return f"{bps / 1024 ** 2:.1f} M"


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1024.0
    e = math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if m * 10 ** e >= v:
            return m * 10 ** e
    return 10 ** (e + 1)


def _blend(fg: str, bg: str, bg_weight: float) -> str:
    f = tuple(int(fg[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(
        int(bi * bg_weight + fi * (1 - bg_weight))
        for bi, fi in zip(b, f))


class NodeDialog:
    """Dialog for adding/editing a node."""

    def __init__(self, parent, node_data=None):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("添加节点" if not node_data else "编辑节点")
        self.dialog.geometry("420x520")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.focus_set()

        if node_data:
            self.result = dict(node_data)

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self.dialog, padding=15)
        main.pack(fill="both", expand=True)

        # Type
        ttk.Label(main, text="协议类型:").grid(row=0, column=0, sticky="w", pady=2)
        self.type_var = tk.StringVar(value="vless")
        ttk.Combobox(main, textvariable=self.type_var,
                      values=["vless", "vmess", "shadowsocks", "trojan"],
                      state="readonly", width=25).grid(row=0, column=1, sticky="ew", pady=2)

        # Name
        ttk.Label(main, text="名称:").grid(row=1, column=0, sticky="w", pady=2)
        self.name_var = tk.StringVar(value=self.result.get("name", "") if self.result else "")
        ttk.Entry(main, textvariable=self.name_var, width=30).grid(row=1, column=1, sticky="ew", pady=2)

        # Server
        ttk.Label(main, text="服务器地址:").grid(row=2, column=0, sticky="w", pady=2)
        self.server_var = tk.StringVar(value=self.result.get("server", "") if self.result else "")
        ttk.Entry(main, textvariable=self.server_var, width=30).grid(row=2, column=1, sticky="ew", pady=2)

        # Port
        ttk.Label(main, text="端口:").grid(row=3, column=0, sticky="w", pady=2)
        self.port_var = tk.StringVar(value=str(self.result.get("port", 443)) if self.result else "443")
        ttk.Entry(main, textvariable=self.port_var, width=30).grid(row=3, column=1, sticky="ew", pady=2)

        # UUID (vless)
        ttk.Label(main, text="UUID:").grid(row=4, column=0, sticky="w", pady=2)
        self.uuid_var = tk.StringVar(value=self.result.get("uuid", "") if self.result else "")
        ttk.Entry(main, textvariable=self.uuid_var, width=30).grid(row=4, column=1, sticky="ew", pady=2)

        # SNI
        ttk.Label(main, text="SNI (server_name):").grid(row=5, column=0, sticky="w", pady=2)
        self.sni_var = tk.StringVar(value=self.result.get("sni", "") if self.result else "")
        ttk.Entry(main, textvariable=self.sni_var, width=30).grid(row=5, column=1, sticky="ew", pady=2)

        # Flow
        ttk.Label(main, text="Flow (可选):").grid(row=6, column=0, sticky="w", pady=2)
        self.flow_var = tk.StringVar(value=self.result.get("flow", "") if self.result else "")
        ttk.Entry(main, textvariable=self.flow_var, width=30).grid(row=6, column=1, sticky="ew", pady=2)

        # Encryption
        ttk.Label(main, text="Encryption:").grid(row=7, column=0, sticky="w", pady=2)
        self.encryption_var = tk.StringVar(value=self.result.get("encryption", "none") if self.result else "none")
        ttk.Combobox(main, textvariable=self.encryption_var,
                      values=["none", "xray-aead"],
                      state="readonly", width=25).grid(row=7, column=1, sticky="ew", pady=2)

        # Reality (public key)
        ttk.Label(main, text="Reality 公钥 (pbk):").grid(row=8, column=0, sticky="w", pady=2)
        self.pbk_var = tk.StringVar(value=self.result.get("reality", {}).get("public_key", "") if self.result else "")
        ttk.Entry(main, textvariable=self.pbk_var, width=30).grid(row=8, column=1, sticky="ew", pady=2)

        # Short ID
        ttk.Label(main, text="Short ID (sid):").grid(row=9, column=0, sticky="w", pady=2)
        self.sid_var = tk.StringVar(value=self.result.get("reality", {}).get("short_id", "") if self.result else "")
        ttk.Entry(main, textvariable=self.sid_var, width=30).grid(row=9, column=1, sticky="ew", pady=2)

        # Buttons
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(pady=15, fill="x")

        ttk.Button(btn_frame, text="保存", command=self._save).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="取消", command=self.dialog.destroy).pack(side="right", padx=5)

    def _save(self):
        name = self.name_var.get().strip()
        server = self.server_var.get().strip()
        if not name or not server:
            messagebox.showwarning("警告", "名称和服务器地址不能为空")
            return

        node = {
            "name": name,
            "type": self.type_var.get(),
            "server": server,
            "port": int(self.port_var.get()),
            "uuid": self.uuid_var.get().strip(),
            "sni": self.sni_var.get().strip() or None,
            "flow": self.flow_var.get().strip() or None,
            "encryption": self.encryption_var.get(),
        }

        pbk = self.pbk_var.get().strip()
        sid = self.sid_var.get().strip()
        if pbk:
            node["reality"] = {"public_key": pbk, "short_id": sid}

        self.result = node
        self.dialog.destroy()


class App:
    """Main application."""

    def __init__(self, root):
        self.root = root
        self.root.title("SingBox Client")
        self.root.geometry("560x680")
        self.root.resizable(True, True)

        # traffic chart state
        self.theme = DARK_THEME if _system_is_dark() else LIGHT_THEME
        self.stats_port = 39090  # avoid the classic clash 9090 clash
        self.stats_secret = secrets.token_hex(16)
        self.monitor = None
        self._chart_pts = []
        self._chart_geo = None
        self._tick_font = None
        self.node_latency = {}  # node id -> latency cell text
        self._connected_id = None  # node served by the live instance
        self._lat_timer = None     # periodic auto-measure
        self._diag_busy = False    # manual diagnose / test-all guard
        self._testall_busy = False
        self._was_connected = False  # persisted across launches

        # advanced (access-monitor) panel state
        self.advanced_open = False
        self.adv_frame = None
        self.adv_monitor = None
        self._adv_poll_timer = None

        # State
        self.nodes = self._load_nodes()
        self.selected_node_id = None
        workdir = os.path.dirname(self._get_config_path("nodes.json"))
        self.workdir = workdir
        self.singbox = SingBoxManager(workdir=workdir)
        ProxyManager.set_state_dir(workdir)
        self.config_gen = ConfigGenerator()
        self.config_gen.routing_mode = ConfigGenerator.ROUTING_GEO
        self._load_settings()
        self.running = False

        # Clean up after a previous crash/force-quit: kill an orphaned
        # sing-box (it would hold the proxy port) and clear the leftover
        # system proxy — but only if it points at us.
        cleaned_proc = self.singbox.reap_orphan()
        cleaned_proxy = ProxyManager.cleanup_stale_proxy(self.config_gen.mixed_port)
        self._startup_notice = (
            "检测到上次异常退出残留(sing-box 进程/系统代理),已自动清理"
            if (cleaned_proc or cleaned_proxy) else None)

        # UI setup
        self._setup_styles()
        self._build_ui()
        self._refresh_nodes()
        self.root.protocol("WM_DELETE_WINDOW", self._on_app_quit)
        if self._startup_notice:
            self.root.after(400, lambda: self._show_notice(
                self._startup_notice))
        # resume the connection state recorded at last quit
        if self._was_connected:
            if os.path.exists(self.singbox.binary) and self.selected_node_id:
                self.root.after(400, lambda: self._show_notice(
                    "上次退出时处于连接状态,正在自动连接…"))
                self.root.after(1200, self._autoconnect)
            else:
                self.root.after(400, lambda: self._show_notice(
                    "上次为连接状态,但缺少 sing-box 或节点,已跳过自动连接"))

        # Update status periodically
        self._refresh_sys_status()
        self.root.after(2000, self._update_status)
        # Redraw traffic chart every second
        self.root.after(1000, self._draw_chart)

    def _setup_styles(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Helvetica", 14, "bold"))
        style.configure("TPanedwindow", sashwidth=6, sashrelief="raised",
                        sashcursor="sb_h_double_arrow")
        style.configure("Status.TLabel", font=("Helvetica", 10))
        style.configure("Status.On.TLabel", foreground="green", font=("Helvetica", 10, "bold"))
        style.configure("Status.Off.TLabel", foreground="orange", font=("Helvetica", 10))
        # connected-state connect button: red label (Tk9's aqua theme
        # supports TButton -foreground — see theme aquaTheme.tcl), and
        # "●" is a font glyph so the dot scales with the button text
        style.configure("Disconnect.TButton", foreground="#d03b3b")

    BASE_W = 560   # left column width — never resized by the panel
    ADV_W = 342    # advanced panel strip (panel 330 + right gutter 12)

    def _win_width(self) -> int:
        return self.BASE_W + (self.ADV_W if self.advanced_open else 0)


    def _build_ui(self):
        # Paned container: left = main UI, right = advanced panel.
        # The sash between them is draggable (mouse) to resize both.
        # ttk's panedwindow has no minsize option, so a motion binding
        # clamps the split: left >= 420 px, panel >= 200 px.
        self.paned = ttk.Panedwindow(self.root, orient="horizontal")
        self.paned.pack(fill="both", expand=True)
        self.left = ttk.Frame(self.paned)
        self.paned.add(self.left, weight=1)
        self._sash_drag = False
        self._sash_clamp_pending = False
        self.MIN_LEFT, self.MIN_RIGHT = 420, 200
        self.paned.bind("<ButtonPress-1>", self._sash_press)
        self.paned.bind("<B1-Motion>", self._sash_motion)
        self.paned.bind("<ButtonRelease-1>",
                        lambda e: setattr(self, "_sash_drag", False))

        # === Top: Title bar ===
        title_frame = ttk.Frame(self.left)
        title_frame.pack(fill="x", padx=15, pady=(12, 0))

        ttk.Label(title_frame, text="SingBox Client", style="Title.TLabel").pack(side="left")

        # Status indicator
        self.status_label = ttk.Label(title_frame, text="● 未连接", style="Status.Off.TLabel")
        self.status_label.pack(side="right")

        # Inline notice bar (tooltip-style, closable) — sits between the
        # title and the node list when shown; no modal dialogs.
        self._notice_frame = None
        self._notice_timer = None
        self._title_frame = title_frame

        # === Middle: Node list ===
        list_frame = ttk.LabelFrame(self.left, text="节点列表", padding=8)
        list_frame.pack(fill="both", expand=True, padx=15, pady=8)

        self.node_tree = ttk.Treeview(list_frame, columns=("name", "info", "lat"),
                                      show="tree headings", height=8)
        self.node_tree.heading("#0", text="", anchor="w")
        self.node_tree.heading("name", text="名称")
        self.node_tree.heading("info", text="地址")
        self.node_tree.heading("lat", text="延迟")
        # Emoji glyph (~20px) + tree padding; 20px clips the icon
        self.node_tree.column("#0", width=36, stretch=False)
        self.node_tree.column("name", width=165)
        self.node_tree.column("info", width=158)
        self.node_tree.column("lat", width=64, stretch=False, anchor="e")
        self.node_tree.tag_configure("bad", foreground="#c0392b")
        # Whole-row background for the selected node: aqua's native
        # selection tint fades when the tree is unfocused and vanishes
        # after rebuilds — a tag row-paint is always visible.
        self.node_tree.tag_configure(
            "sel", background="#d5e6fa" if self.theme is LIGHT_THEME
            else "#2f4a6b")
        self.node_tree.pack(fill="both", expand=True)

        self.node_tree.bind("<<TreeviewSelect>>", self._on_select)
        self.node_tree.bind("<Double-1>", self._on_toggle)
        self.node_tree.bind("<Button-3>", self._show_context_menu)

        # === Traffic chart (last 15 minutes) ===
        chart_frame = ttk.LabelFrame(self.left, text="流量 · 最近 15 分钟",
                                     padding=6)
        chart_frame.pack(fill="x", padx=15, pady=(4, 8))

        self.chart_canvas = tk.Canvas(
            chart_frame, height=140, bg=self.theme["surface"],
            highlightthickness=1, highlightbackground=self.theme["grid"])
        self.chart_canvas.pack(fill="x")
        self.chart_canvas.bind("<Motion>", self._on_chart_motion)
        self.chart_canvas.bind("<Leave>", lambda e: self._set_chart_caption(None))

        self.caption_var = tk.StringVar(value="未连接 — 无流量采样")
        ttk.Label(chart_frame, textvariable=self.caption_var,
                  style="Status.TLabel").pack(anchor="w", pady=(2, 0))

        # === System status ===
        sys_frame = ttk.LabelFrame(self.left, text="系统状态", padding=(8, 3))
        sys_frame.pack(fill="x", padx=15, pady=(0, 8))
        self.sys_proxy_var = tk.StringVar(value="")
        self.sys_proc_var = tk.StringVar(value="")
        self.sys_bin_var = tk.StringVar(value="")
        for var in (self.sys_proxy_var, self.sys_proc_var, self.sys_bin_var):
            ttk.Label(sys_frame, textvariable=var,
                      style="Status.TLabel").pack(anchor="w")

        # Context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="编辑节点", command=self._edit_node)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="删除节点", command=self._delete_node, foreground="red")
        self.context_menu.add_separator()
        self.context_menu.add_command(label="删除所有", command=self._delete_all, foreground="red")

        # === Bottom: Controls ===
        control_frame = ttk.Frame(self.left)
        control_frame.pack(fill="x", padx=15, pady=(0, 12))

        # Routing mode
        routing_frame = ttk.LabelFrame(control_frame, text="路由模式", padding=(8, 4))
        routing_frame.pack(fill="x", pady=(0, 8))

        self.routing_var = tk.StringVar(value=ConfigGenerator.ROUTING_GEO)
        ttk.Radiobutton(routing_frame, text="Geosite + GEOIP", variable=self.routing_var,
                         value=ConfigGenerator.ROUTING_GEO).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(routing_frame, text="手动域名", variable=self.routing_var,
                         value=ConfigGenerator.ROUTING_MANUAL).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(routing_frame, text="全局代理", variable=self.routing_var,
                         value=ConfigGenerator.ROUTING_ALL).pack(side="left")

        # Mixed proxy port — inline, apply & persist on change
        ttk.Label(routing_frame, text="混合代理端口:").pack(side="left", padx=(16, 4))
        self.port_var = tk.StringVar(value=str(self.config_gen.mixed_port))
        port_spin = ttk.Spinbox(routing_frame, from_=1024, to=65535, width=7,
                                textvariable=self.port_var)
        port_spin.pack(side="left")
        for seq in ("<<Increment>>", "<<Decrement>>", "<KeyRelease>", "<FocusOut>"):
            port_spin.bind(seq, lambda e: self._on_port_change())
        self._port_apply_timer = None

        # Buttons
        btn_frame = ttk.Frame(self.left)
        btn_frame.pack(fill="x", padx=15, pady=(0, 12))

        self.connect_btn = ttk.Button(btn_frame, text="▶ 连接", command=self._toggle_connection)
        self.connect_btn.pack(side="left", padx=2, ipadx=10)

        ttk.Button(btn_frame, text="📋 导入", command=self._import_nodes).pack(side="left", padx=2, ipadx=10)
        self.diag_btn = ttk.Button(btn_frame, text="🩺 诊断", command=self._diagnose_node)
        self.diag_btn.pack(side="left", padx=2, ipadx=10)
        self.testall_btn = ttk.Button(btn_frame, text="🔍 全部测试", command=self._test_all)
        self.testall_btn.pack(side="left", padx=2, ipadx=10)

        self.adv_btn = ttk.Button(btn_frame, text="🔬 高级", command=self._toggle_advanced)
        self.adv_btn.pack(side="right", padx=2, ipadx=10)

    def _load_nodes(self) -> list:
        """Load nodes from config file."""
        config_path = self._get_config_path("nodes.json")
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
                nodes = data.get("nodes", [])
                for n in nodes:
                    n.setdefault("id", self._gen_id(n))
                return nodes
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_nodes(self):
        """Save nodes to config file."""
        config_path = self._get_config_path("nodes.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            json.dump({"nodes": self.nodes}, f, indent=2)

    def _gen_id(self, node):
        """Generate a simple unique ID for a node."""
        return f"{node.get('type', 'unknown')}_{node.get('server', '')}_{node.get('port', '')}"

    def _get_config_path(self, name):
        """Get the path to the app config directory."""
        if sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support/SingBoxClient")
        elif sys.platform == "linux":
            base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config/SingBoxClient"))
        else:
            base = os.path.expanduser("~/AppData/Roaming/SingBoxClient")
        return os.path.join(base, name)

    def _refresh_nodes(self):
        """Refresh the node tree display."""
        # Clear
        for item in self.node_tree.get_children():
            self.node_tree.delete(item)

        # Auto-select first before drawing icons, so the green dot is
        # correct on the very first paint.
        if not self.selected_node_id and self.nodes:
            self.selected_node_id = self.nodes[0].get("id", "node_0")

        def lat_of(n, i):
            return self.node_latency.get(n.get("id", f"node_{i}"), "--")

        for i, node in enumerate(self.nodes):
            node_id = node.get("id", f"node_{i}")
            info = f"{node.get('server', '?')}:{node.get('port', '?')}"
            icon = self._node_icon(node_id)
            lat = lat_of(node, i)
            self.node_tree.insert("", "end", iid=node_id,
                                  text=icon, tags=self._node_tags(node_id),
                                  values=(node.get("name", ""), info, lat))

        # Auto-size the list to the number of nodes (1..12 visible rows;
        # beyond that it scrolls) and refit the window so no empty space
        # is left under the list.
        if self.selected_node_id and self.node_tree.exists(self.selected_node_id):
            self.node_tree.selection_set(self.selected_node_id)
        else:
            self.selected_node_id = None
        self._save_settings()

        self.node_tree.configure(height=min(12, max(1, len(self.nodes))))
        self.root.update_idletasks()  # apply configure before measuring
        self.root.geometry(f"{self._win_width()}x{self.root.winfo_reqheight()}")

    def _node_tags(self, node_id) -> tuple:
        """Row tags: sel = selected row background, bad = failed test."""
        tags = []
        if node_id == self.selected_node_id:
            tags.append("sel")
        lat = self.node_latency.get(node_id, "--")
        if lat != "--" and not lat.endswith("ms"):
            tags.append("bad")
        return tuple(tags)

    def _node_icon(self, node_id) -> str:
        """Green dot = the node the live instance serves; while nothing
        is connected, the green marks the DEFAULT node (the one "connect"
        would use). Selection alone never turns a dot green when a
        connection is live."""
        if self.running:
            return "🟢" if node_id == self._connected_id else "⚪"
        return "🟢" if node_id == self.selected_node_id else "⚪"

    def _repaint_icons(self):
        for iid in self.node_tree.get_children():
            self.node_tree.item(iid, text=self._node_icon(iid))

    def _on_select(self, event):
        """Single click: only the row's selected background moves
        (connection and green dot untouched while connected)."""
        selection = self.node_tree.selection()
        if not selection:
            return
        new_id = selection[0]
        if new_id == self.selected_node_id:
            return
        old_id = self.selected_node_id
        self.selected_node_id = new_id
        for iid in (old_id, new_id):
            if iid and self.node_tree.exists(iid):
                self.node_tree.item(iid, tags=self._node_tags(iid))
        if not self.running:
            self._repaint_icons()  # no live link: green follows the default
        self._save_settings()

    def _on_toggle(self, event):
        """Double-click on a node row:

        - nothing connected          -> connect to that node
        - connected to another node  -> disconnect, then connect to it
        - connected to this very node-> disconnect (toggle off)
        The green dot lands on the new node only once the connection is
        actually up (_on_connected repaints).
        """
        row = self.node_tree.identify_row(event.y)
        if not row:
            return
        if self.running and self._connected_id == row:
            self._do_stop()
            return
        was_running = self.running
        self.node_tree.selection_set(row)
        # <<TreeviewSelect>> is queued, not synchronous — apply the
        # selection right now so selected_node_id is already current.
        self._on_select(None)
        if self.selected_node_id != row:
            return  # selection rejected (stale row?)
        if was_running:
            # _do_stop's _on_disconnected lands via after(0) — queue the
            # new start after it so the disconnect can't clobber state.
            self._do_stop()
            self.root.after(100, self._do_start)
        else:
            self._do_start()

    def _show_context_menu(self, event):
        """Show context menu on right-click."""
        item = self.node_tree.identify_row(event.y)
        if item:
            self.node_tree.selection_set(item)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _add_node(self):
        """Open dialog to add a new node."""
        dlg = NodeDialog(self.root)
        self.root.wait_window(dlg.dialog)
        if dlg.result:
            node = dlg.result
            node["id"] = self._gen_id(node)
            self.nodes.append(node)
            self.selected_node_id = node["id"]
            self._save_nodes()
            self._refresh_nodes()

    def _edit_node(self):
        """Open dialog to edit selected node."""
        selection = self.node_tree.selection()
        if not selection:
            return
        node_id = selection[0]
        node = next((n for n in self.nodes if n.get("id") == node_id), None)
        if not node:
            return
        dlg = NodeDialog(self.root, node)
        self.root.wait_window(dlg.dialog)
        if dlg.result:
            node.update(dlg.result)
            self._save_nodes()
            self._refresh_nodes()

    def _delete_node(self):
        """Delete selected node."""
        selection = self.node_tree.selection()
        if not selection:
            return
        if not messagebox.askyesno("确认", "确定删除此节点？"):
            return
        node_id = selection[0]
        self.nodes = [n for n in self.nodes if n.get("id") != node_id]
        if self.selected_node_id == node_id:
            self.selected_node_id = self.nodes[0].get("id") if self.nodes else None
        self._save_nodes()
        self._refresh_nodes()

    def _delete_all(self):
        """Delete all nodes."""
        if not self.nodes:
            return
        if not messagebox.askyesno("确认", "确定删除所有节点？"):
            return
        self.nodes.clear()
        self.selected_node_id = None
        self._save_nodes()
        self._refresh_nodes()

    # ── latency testing ───────────────────────────────────────────────

    def _measure_connected(self):
        """Auto-measure the connected node's latency (periodic)."""
        self._lat_timer = None
        if not self.running:
            return
        if self._diag_busy or self._testall_busy:
            self._lat_timer = self.root.after(10000, self._measure_connected)
            return
        node = next((n for n in self.nodes
                     if n.get("id") == self._connected_id), None)
        if not node:
            return
        diag = NodeDiagnostics(self.singbox.binary, self.workdir,
                               diag_port=self.config_gen.mixed_port + 10000)

        def worker():
            try:
                res = diag.run(node)
            except Exception:
                res = {"verdict": "error"}
            self._post_ui(lambda: self._auto_lat_done(node, res))

        threading.Thread(target=worker, daemon=True).start()

    def _post_ui(self, fn):
        """Thread-safe UI hop that tolerates a shutdown race."""
        try:
            self.root.after(0, fn)
        except (RuntimeError, tk.TclError):
            pass  # window already closing

    def _auto_lat_done(self, node, res):
        if self.running and node.get("id") == self._connected_id:
            self._set_lat(node.get("id"), self._latency_text(res))
            self._lat_timer = self.root.after(60000, self._measure_connected)

    def _set_lat(self, node_id, text):
        self.node_latency[node_id] = text
        if self.node_tree.exists(node_id):
            self.node_tree.set(node_id, "lat", text)
            self.node_tree.item(node_id, tags=self._node_tags(node_id))

    @staticmethod
    def _latency_text(res):
        v = res.get("verdict")
        if v == "healthy":
            return f"{int(res['latency'] * 1000)} ms"
        return {"stale_params": "参数失效", "offline": "离线"}.get(v, "异常")

    def _test_all(self):
        """Test response time of every node (sequential, background)."""
        if not self.nodes:
            messagebox.showwarning("提示", "没有节点可测试")
            return
        self._testall_busy = True
        self.testall_btn.state(["disabled"])
        diag = NodeDiagnostics(self.singbox.binary, self.workdir,
                               diag_port=self.config_gen.mixed_port + 10000)
        nodes = list(self.nodes)
        total = len(nodes)

        def worker():
            summary = {"healthy": 0, "stale_params": 0, "offline": 0,
                       "error": 0}
            for i, node in enumerate(nodes, 1):
                self.root.after(
                    0, lambda i=i, total=total: self.testall_btn.config(
                        text=f"测试中 {i}/{total}"))
                try:
                    res = diag.run(node)
                except Exception:
                    res = {"verdict": "error"}
                summary[res.get("verdict", "error")] = \
                    summary.get(res.get("verdict", "error"), 0) + 1
                text = self._latency_text(res)
                self.root.after(0, lambda n=node, t=text:
                                self._set_lat(n.get("id"), t))
            self.root.after(0, lambda: self._test_all_done(summary, total))

        threading.Thread(target=worker, daemon=True).start()

    def _test_all_done(self, summary, total):
        self._testall_busy = False
        self.testall_btn.config(text="🔍 全部测试")
        self.testall_btn.state(["!disabled"])
        parts = []
        for key, label in (("healthy", "正常"), ("stale_params", "参数失效"),
                           ("offline", "离线"), ("error", "异常")):
            if summary.get(key):
                parts.append(f"{summary[key]} {label}")
        messagebox.showinfo("测试完成",
                            f"{total} 个节点:" + " · ".join(parts))

    def _diagnose_node(self):
        """Diagnose selected node in an isolated sing-box instance."""
        if not self.selected_node_id:
            messagebox.showwarning("提示", "请先选择一个节点")
            return
        node = next((n for n in self.nodes
                     if n.get("id") == self.selected_node_id), None)
        if not node:
            return
        self._diag_busy = True
        self.diag_btn.state(["disabled"])
        diag = NodeDiagnostics(self.singbox.binary, self.workdir,
                               diag_port=self.config_gen.mixed_port + 10000)

        def worker():
            try:
                res = diag.run(node)
            except Exception as e:
                res = {"verdict": "error", "detail": f"诊断异常: {e}",
                       "steps": []}
            self.root.after(0, lambda res=res: self._show_diagnosis(node, res))

        threading.Thread(target=worker, daemon=True).start()

    def _show_diagnosis(self, node, res):
        self._diag_busy = False
        self.diag_btn.state(["!disabled"])
        self._set_lat(node.get("id"), self._latency_text(res))
        titles = {"healthy": "✅ 节点健康",
                  "stale_params": "⚠️ 参数已失效",
                  "offline": "❌ 节点离线",
                  "error": "⚠️ 诊断异常"}
        title = titles.get(res.get("verdict"), "诊断结果")
        body = (f"{node.get('name', '?')} "
                f"({node.get('server')}:{node.get('port')})\n\n"
                + res.get("detail", ""))
        steps = res.get("steps") or []
        if steps:
            body += "\n\n步骤:\n" + "\n".join("• " + s for s in steps)
        kind = res.get("verdict")
        if kind == "healthy":
            messagebox.showinfo(title, body)
        elif kind == "error":
            messagebox.showerror(title, body)
        else:
            messagebox.showwarning(title, body)

    def _import_nodes(self):
        """Import nodes from clipboard."""
        dialog = tk.Toplevel(self.root)
        dialog.title("导入节点")
        dialog.geometry("450x300")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="粘贴 vless:// 链接（一行一个）", wraplength=400).pack(pady=(10, 5))
        text = tk.Text(dialog, wrap="word", height=8, width=50)
        text.pack(fill="both", expand=True, padx=15, pady=5)

        # Auto-paste from clipboard
        try:
            clipboard = dialog.clipboard_get()
            if "vless://" in clipboard:
                text.insert("1.0", clipboard)
        except tk.TclError:
            pass

        def do_import():
            raw = text.get("1.0", "end-1c")
            imported = self._parse_vless_urls(raw)
            if not imported:
                messagebox.showwarning("提示", "未解析到有效节点")
                return
            for node in imported:
                node["id"] = self._gen_id(node)
                self.nodes.append(node)
            if not self.selected_node_id:
                self.selected_node_id = self.nodes[0]["id"]
            self._save_nodes()
            self._refresh_nodes()
            messagebox.showinfo("成功", f"已导入 {len(imported)} 个节点")
            dialog.destroy()

        ttk.Button(dialog, text="导入", command=do_import).pack(pady=10)
        ttk.Button(dialog, text="取消", command=dialog.destroy).pack()

    def _parse_vless_urls(self, text: str) -> list:
        """Parse vless:// URLs."""
        lines = [l.strip() for l in text.split("\n") if l.strip().startswith("vless://")]
        nodes = []
        for url in lines:
            try:
                node = self._parse_vless_url(url)
                if node:
                    nodes.append(node)
            except Exception:
                pass
        return nodes

    def _parse_vless_url(self, url: str) -> dict | None:
        """Parse a single vless:// URL."""
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            query = {k: v[0] for k, v in params.items()}

            # Get server and port
            hostname = parsed.hostname or ""
            port = int(parsed.port or 443)
            user = parsed.username or ""  # This is the UUID
            # The user part before @ is the UUID

            name = parsed.fragment or f"{hostname}:{port}"

            reality = {}
            if query.get("pbk"):
                reality = {
                    "public_key": query["pbk"],
                    "short_id": query.get("sid", "")
                }

            node = {
                "type": "vless",
                "name": name,
                "server": hostname,
                "port": port,
                "uuid": user,
                "sni": query.get("sni") or query.get("servername"),
                "flow": query.get("flow"),
                "encryption": query.get("encryption", "none"),
            }
            if reality:
                node["reality"] = reality
            if query.get("type") and query["type"] != "tcp":
                node["transport"] = query["type"]
                node["path"] = query.get("path")
                node["host"] = query.get("host")

            return node
        except Exception:
            return None

    def _toggle_connection(self):
        """Toggle connection state."""
        if self.running:
            self._do_stop()
        else:
            self._do_start()

    def _do_start(self):
        """Start sing-box and enable proxy."""
        if not self.selected_node_id:
            messagebox.showwarning("提示", "请先选择一个节点")
            return
        selected = next((n for n in self.nodes
                         if n.get("id") == self.selected_node_id), None)
        self._connected_id = self.selected_node_id

        # Generate config (routing mode read live from the UI)
        self.config_gen.routing_mode = self.routing_var.get()
        config = self.config_gen.generate(
            self.nodes, self.selected_node_id,
            stats_port=self.stats_port, stats_secret=self.stats_secret)
        config_path = self._get_config_path("config.json")
        self.config_gen.save(config, config_path)

        # Validate before launching, so mistakes surface as a dialog
        ok, msg = self.singbox.check_config(config_path)
        if not ok:
            messagebox.showerror("配置错误", f"sing-box 配置检查失败:\n{msg}")
            return

        # Start sing-box in a thread; verify it actually stays up
        def run_singbox():
            try:
                self.singbox.start(config_path)
                import time
                time.sleep(2)
                if self.singbox.is_running:
                    self.root.after(0, self._on_connected)
                else:
                    # sing-box died right away (dead node, rule-set
                    # download failure, ...) — show its log, undo proxy
                    ProxyManager.clear_proxy()
                    err = self.singbox.last_error()
                    node_name = (selected.get("name")
                                 if selected else self.selected_node_id)
                    self.root.after(
                        0,
                        lambda err=err, name=node_name: messagebox.showerror(
                            "启动失败",
                            f"sing-box 启动失败 — 节点「{name}」"
                            f"可能已失效,请换节点或更新订阅:\n{err}"))
            except Exception as e:
                ProxyManager.clear_proxy()
                self.root.after(0, lambda e=e: messagebox.showerror(
                    "错误", f"启动失败: {e}"))

        # Enable proxy
        ProxyManager.set_proxy(self.config_gen.mixed_port)

        # Start in background thread
        threading.Thread(target=run_singbox, daemon=True).start()

    def _do_stop(self):
        """Stop sing-box; _on_disconnected restores the proxy (once)."""
        self.singbox.stop()
        self.root.after(0, self._on_disconnected)

    def _autoconnect(self):
        if not self.running and self._was_connected:
            self._do_start()

    def _on_app_quit(self):
        """Normal quit: if connected, tear down cleanly — stop sing-box
        and RESTORE the pre-connect system proxy — then record whether
        the app was connected so the next launch resumes that state."""
        was = self.running
        if was:
            self.singbox.stop()
            ProxyManager.clear_proxy()
            self.running = False
        self._was_connected = was
        self._save_settings()
        self.root.destroy()

    def _connected_name(self) -> str:
        """Display name of the node the live instance actually serves."""
        node = next((n for n in self.nodes
                     if n.get("id") == self._connected_id), None)
        if node is None:  # instance adopted from outside — best guess
            node = next((n for n in self.nodes
                         if n.get("id") == self.selected_node_id), None)
        return node.get("name", "") if node else ""

    def _on_connected(self):
        self.running = True
        self._was_connected = True
        self._save_settings()
        name = self._connected_name()
        self.status_label.config(
            text=f"● 已连接 · {name}" if name else "● 已连接",
            style="Status.On.TLabel")
        self.connect_btn.config(text="● 断开", style="Disconnect.TButton")
        self._repaint_icons()  # green now marks the live node only
        if self.monitor is None:
            self.monitor = TrafficMonitor(self.stats_port, self.stats_secret)
            self.monitor.start()
        self.caption_var.set("采样中 · 悬停曲线查看历史速率")
        # auto-measure the connected node's latency (first after 2 s,
        # then every 60 s while connected)
        if self._lat_timer is None:
            self._lat_timer = self.root.after(2000, self._measure_connected)

    def _on_disconnected(self):
        was_running = self.running
        self.running = False
        self._was_connected = False
        self._save_settings()
        # Restore the proxy here rather than in _do_stop: this path also
        # fires when sing-box dies on its own, and clear_proxy consumes
        # its snapshot — so it must run exactly once per cycle.
        if was_running:
            ProxyManager.clear_proxy()
        self.status_label.config(text="● 未连接", style="Status.Off.TLabel")
        self.connect_btn.config(text="▶ 连接", style="TButton")
        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None
            self._chart_pts = []
        if self._lat_timer is not None:
            self.root.after_cancel(self._lat_timer)
            self._lat_timer = None
        self._connected_id = None
        self._repaint_icons()  # green falls back to the default node
        self.caption_var.set("未连接 — 无流量采样")

    def _update_status(self):
        """Periodic status update."""
        if self.singbox.is_running and not self.running:
            self._on_connected()
        elif not self.singbox.is_running and self.running:
            self._on_disconnected()
        if self.running:  # keep the node name fresh (edits / adoption)
            name = self._connected_name()
            self.status_label.config(
                text=f"● 已连接 · {name}" if name else "● 已连接")
        self._refresh_sys_status()
        self.root.after(3000, self._update_status)

    def _refresh_sys_status(self):
        """Refresh the system-status panel (proxy / process / binary)."""
        port = self.config_gen.mixed_port

        def fmt(entry):
            if not entry or not entry.get("enabled"):
                return "关闭"
            where = f"{entry.get('server', '?')}:{entry.get('port', '?')}"
            ours = (entry.get("server") == "127.0.0.1"
                    and entry.get("port") == port)
            return f"开启 → {where}({'本应用' if ours else '外部工具'})"

        st = ProxyManager.current_status()
        web, sec = st.get("web"), st.get("secure")
        if web is None:
            self.sys_proxy_var.set("系统代理: 无法读取")
        elif web == sec:
            self.sys_proxy_var.set(f"系统代理: {fmt(web)}")
        else:
            self.sys_proxy_var.set(
                f"系统代理: HTTP {fmt(web)}  |  HTTPS {fmt(sec)}")

        pids = self.singbox.running_pids()
        if pids:
            mine = " · 含本会话" if self.singbox.is_running else ""
            self.sys_proc_var.set(
                "sing-box 进程: 运行中 (PID "
                + ", ".join(str(p) for p in pids[:4]) + f"){mine}")
        else:
            self.sys_proc_var.set("sing-box 进程: 未运行")

        self.sys_bin_var.set(f"sing-box: {self.singbox.binary} · "
                             f"v{self.singbox.get_version()}")

    # ── traffic chart ─────────────────────────────────────────────────

    WINDOW = 900  # seconds

    def _draw_chart(self):
        if not self.root.winfo_exists():
            return
        c = self.chart_canvas
        th = self.theme
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        R, T, B = 10, 22, 18
        now = time.monotonic()
        raw = self.monitor.snapshot() if self.monitor else []
        pts = [(now - t, up, dn) for (t, up, dn) in raw
               if now - t <= self.WINDOW]
        self._chart_pts = pts
        vmax = max((max(u, d) for _, u, d in pts), default=0)
        ymax = _nice_max(vmax)

        # left margin sized to the widest tick label — fixed 58 px used
        # to clip labels like "512.0 KB/s" at the canvas edge
        ticks = [_fmt_rate_tick(ymax * i / 4) for i in range(5)]
        if self._tick_font is None:
            self._tick_font = tkfont.Font(family="Menlo", size=9)
        tw = max(self._tick_font.measure(t) for t in ticks)
        L = max(58, tw + 14)
        pw, ph = w - L - R, h - T - B
        if pw >= 40 and ph >= 30:
            self._chart_geo = (L, T, pw, ph, now)

            # y grid + rate labels (recessive)
            for i in range(5):
                y = T + ph - ph * i / 4
                if i:
                    c.create_line(L, y, w - R, y, fill=th["grid"])
                c.create_text(L - 6, y, anchor="e", fill=th["muted"],
                              font=("Menlo", 9), text=ticks[i])
            c.create_line(L, T + ph, w - R, T + ph, fill=th["baseline"])

            # x grid every 3 minutes
            for m in range(6):
                x = L + pw * m / 5
                if m:
                    c.create_line(x, T, x, T + ph, fill=th["grid"])
                c.create_text(x, T + ph + 9, anchor="center", fill=th["muted"],
                              font=("Helvetica", 8),
                              text="现在" if m == 5 else f"{15 - 3 * m}分")

            # series: down (slot 1, blue) then up (slot 2, orange)
            for key, col in (("down", th["down"]), ("up", th["up"])):
                coords = [(L + pw * (1 - age / self.WINDOW),
                           T + ph - ph * min(v, ymax) / ymax)
                          for (age, up, dn) in pts
                          for v in (dn if key == "down" else up,)]
                if len(coords) >= 2:
                    area = (coords + [(coords[-1][0], T + ph),
                                      (coords[0][0], T + ph)])
                    c.create_polygon(area, fill=_blend(col, th["surface"], .85),
                                     outline="")
                    c.create_line(coords, fill=col, width=2,
                                  capstyle="round", joinstyle="round")
                    lx, ly = coords[-1]
                    c.create_oval(lx - 3, ly - 3, lx + 3, ly + 3, fill=col,
                                  outline=th["surface"], width=1)

            # legend + live values (direct label of the latest only)
            up, dn = self.monitor.current() if self.monitor else (0, 0)
            x0 = L
            for col, mark, val in ((th["down"], "下行", dn),
                                   (th["up"], "上行", up)):
                c.create_rectangle(x0, 5, x0 + 10, 15, fill=col, outline="")
                c.create_text(x0 + 14, 10, anchor="w", fill=th["secondary"],
                              font=("Helvetica", 9),
                              text=f"↓ {mark} {_fmt_rate(val)}"
                              if mark == "下行" else f"↑ {mark} {_fmt_rate(val)}")
                x0 += 140

            if not pts:
                c.create_text(w / 2, (T + ph / 2), fill=th["muted"],
                              font=("Helvetica", 10),
                              text="暂无流量数据(刚连接时正常)")
        self.root.after(1000, self._draw_chart)

    def _on_chart_motion(self, event):
        geo = self._chart_geo
        if not geo or not self._chart_pts:
            return
        L, T, pw, ph, now = geo
        if not (L <= event.x <= L + pw):
            return
        age = (1 - (event.x - L) / pw) * self.WINDOW
        age = max(0.0, min(float(self.WINDOW), age))
        best = min(self._chart_pts, key=lambda p: abs(p[0] - age))
        mins, secs = int(best[0]) // 60, int(best[0]) % 60
        self._set_chart_caption(
            f"{mins}分{secs:02d}秒前 · ↓ {_fmt_rate(best[2])} · "
            f"↑ {_fmt_rate(best[1])}")

    def _set_chart_caption(self, text):
        if text is None:
            if self.monitor and self.monitor.error:
                text = f"采样异常: {self.monitor.error}"
            elif self.running:
                text = "采样中 · 悬停曲线查看历史速率"
            else:
                text = "未连接 — 无流量采样"
        self.caption_var.set(text)

    # ── inline notices (replaced the old startup modal) ──────────────

    def _show_notice(self, text, duration=12000):
        th = self.theme
        self._hide_notice()
        bar_bg = _blend(th["up"], th["surface"], .82)
        bar = tk.Frame(self.left, bg=bar_bg, highlightthickness=1,
                       highlightbackground=th["grid"], bd=1)
        tk.Label(bar, text="ⓘ " + text, bg=bar_bg, fg=th["ink"],
                 font=("Helvetica", 10)).pack(side="left", padx=8, pady=5)
        close = tk.Label(bar, text="✕", bg=bar_bg, fg=th["secondary"],
                         font=("Helvetica", 10, "bold"), cursor="hand2")
        close.pack(side="right", padx=(4, 10))
        close.bind("<Button-1>", lambda e: self._hide_notice())
        bar.pack(fill="x", padx=15, pady=(0, 6), after=self._title_frame)
        self._notice_frame = bar
        self._notice_timer = self.root.after(duration, self._hide_notice)

    def _hide_notice(self):
        if self._notice_timer is not None:
            self.root.after_cancel(self._notice_timer)
            self._notice_timer = None
        if self._notice_frame is not None:
            self._notice_frame.destroy()
            self._notice_frame = None

    # ── advanced panel: live access monitor (pie summary + log tail) ──

    def _sash_press(self, event):
        # aqua's identify() never returns "sash" (the band is tagged "0"),
        # so hit-test geometrically against the sash position instead.
        self._sash_drag = (self.adv_frame is not None
                           and abs(event.x - self.paned.sashpos(0)) <= 8)

    def _sash_motion(self, event):
        """Clamp the draggable split so neither pane gets crushed.

        The clamp must run AFTER ttk's own sash binding has moved the
        bar for this event (instance bindings run before class ones),
        hence after_idle.
        """
        if not self._sash_drag or self._sash_clamp_pending:
            return
        self._sash_clamp_pending = True
        self.root.after_idle(self._clamp_sash)

    def _clamp_sash(self):
        self._sash_clamp_pending = False
        if not self._sash_drag:
            return
        pos = self.paned.sashpos(0)
        lo = self.MIN_LEFT
        hi = max(lo + 1, self.paned.winfo_width() - self.MIN_RIGHT)
        if pos < lo or pos > hi:
            self.paned.sashpos(0, max(lo, min(hi, pos)))

    def _toggle_advanced(self):
        if self.advanced_open:
            self._close_advanced()
        else:
            self._open_advanced()

    def _open_advanced(self):
        self.advanced_open = True
        self.adv_btn.config(text="✖ 收起")
        th = self.theme

        self.adv_frame = ttk.Frame(self.paned, padding=(8, 0, 4, 0))
        self.paned.add(self.adv_frame, weight=1)

        pie_frame = ttk.LabelFrame(self.adv_frame, text="访问主机汇总",
                                   padding=6)
        pie_frame.pack(fill="x")
        self.pie_canvas = tk.Canvas(pie_frame, width=self.ADV_W - 40,
                                    height=210, bg=th["surface"],
                                    highlightthickness=1,
                                    highlightbackground=th["grid"])
        self.pie_canvas.pack(fill="x")
        self.adv_count_var = tk.StringVar(value="")
        ttk.Label(pie_frame, textvariable=self.adv_count_var,
                  style="Status.TLabel").pack(anchor="w", pady=(2, 0))

        log_frame = ttk.LabelFrame(self.adv_frame, text="访问日志", padding=6)
        log_frame.pack(fill="both", expand=True, pady=(8, 8))
        self.log_text = tk.Text(
            log_frame, width=40, height=14, wrap="word", state="disabled",
            font=("Menlo", 9), bg=th["surface"], fg=th["ink"],
            insertbackground=th["ink"], relief="flat", padx=4, pady=3)
        # line colors follow the pie's route families
        proxy_fam = PROXY_DARK if th is DARK_THEME else PROXY_LIGHT
        direct_fam = DIRECT_DARK if th is DARK_THEME else DIRECT_LIGHT
        self.log_text.tag_configure("rt_proxy", foreground=proxy_fam[0])
        self.log_text.tag_configure("rt_direct", foreground=direct_fam[0])
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        self.root.geometry(f"{self._win_width()}x{self.root.winfo_height()}")
        # initial split: left keeps its exact BASE_W, panel gets ADV_W
        self.root.update_idletasks()
        try:
            self.paned.sashpos(0, self.BASE_W)
        except tk.TclError:
            pass  # sash not realized yet — panes fall back to weights

        # Monitoring starts when the panel opens and stops when it closes
        self.adv_monitor = AccessLogMonitor(self.singbox.log_path)
        self.adv_monitor.start()
        self._adv_poll()

    def _close_advanced(self):
        self.advanced_open = False
        self.adv_btn.config(text="🔬 高级")
        if self._adv_poll_timer is not None:
            self.root.after_cancel(self._adv_poll_timer)
            self._adv_poll_timer = None
        if self.adv_monitor is not None:
            self.adv_monitor.stop()
            self.adv_monitor = None
        if self.adv_frame is not None:
            self.paned.forget(self.adv_frame)
            self.adv_frame.destroy()
            self.adv_frame = None
        self.root.geometry(f"{self.BASE_W}x{self.root.winfo_height()}")

    def _adv_poll(self):
        if not self.advanced_open:
            return
        mon = self.adv_monitor
        if mon is not None:
            events = mon.drain()
            if events:
                t = self.log_text
                t.config(state="normal")
                for ev in events:
                    rt = "rt_direct" if ev.out == "direct" else "rt_proxy"
                    t.insert("end", ev.line + "\n", (rt,))
                # bound the buffer so long sessions stay responsive
                last = int(t.index("end-1c").split(".")[0])
                if last > 600:
                    t.delete("1.0", f"{last - 500}.0")
                t.see("end")
                t.config(state="disabled")
            self._draw_pie()
        self._adv_poll_timer = self.root.after(700, self._adv_poll)

    MAX_SLICES = 7  # + "其他" fold → at most 8 pie slices (palette slots)

    def _draw_pie(self):
        if not self.advanced_open or self.adv_monitor is None:
            return
        c = self.pie_canvas
        th = self.theme
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60:
            return
        # slices keyed by (host, outbound): colors follow the ROUTE
        # (direct = green family, everything proxied = red family)
        route_counts = self.adv_monitor.route_counts()
        counts = self.adv_monitor.counts()
        total = sum(route_counts.values())
        self.adv_count_var.set(
            f"共 {total} 次连接 · {len(counts)} 个主机")
        if not total:
            hint = ("未连接 — 点“连接”后开始记录"
                    if not self.running else "暂无访问记录")
            c.create_text(w / 2, h / 2, fill=th["muted"],
                          font=("Helvetica", 10), text=hint)
            return

        items = sorted(route_counts.items(), key=lambda kv: -kv[1])
        slices = items[:self.MAX_SLICES]
        rest = items[self.MAX_SLICES:]
        if rest:
            slices.append((("其他", ""), sum(v for _, v in rest)))

        def color_for(key, idx_p, idx_d):
            host, out = key
            if host == "其他":
                return th["muted"], idx_p, idx_d
            if out == "direct":
                fam = DIRECT_DARK if th is DARK_THEME else DIRECT_LIGHT
                return fam[idx_d % len(fam)], idx_p, idx_d + 1
            fam = PROXY_DARK if th is DARK_THEME else PROXY_LIGHT
            return fam[idx_p % len(fam)], idx_p + 1, idx_d

        r = min(h / 2 - 10, 72)
        cx, cy = r + 22, h / 2
        ang = 90.0  # start at 12 o'clock, sweep clockwise
        ip = idg = 0
        for key, v in slices:
            span = 360.0 * v / total
            col, ip, idg = color_for(key, ip, idg)
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=ang,
                         extent=-span, fill=col, outline=th["surface"],
                         width=2, style="pie")
            ang -= span

        # legend: host + route + count + share (identity never rides
        # color alone — the 代理/直连 word names what the hue encodes)
        lx = cx + r + 16
        ip = idg = 0
        row = 0
        for (key, v) in slices:
            col, ip, idg = color_for(key, ip, idg)
            y = max(8, cy - r) + row * 19
            if y > h - 8:
                break
            c.create_rectangle(lx, y - 4, lx + 10, y + 6, fill=col,
                               outline="")
            host, out = key
            name = host if len(host) <= 18 else host[:17] + "…"
            route = "" if host == "其他" else (" · 代理" if out != "direct"
                                               else " · 直连")
            c.create_text(lx + 15, y + 1, anchor="w", fill=th["secondary"],
                          font=("Helvetica", 9),
                          text=f"{name}{route}  {v} ({v / total * 100:.0f}%)")
            row += 1

    # ── mixed proxy port: change = validate + persist (+ live re-apply) ──

    def _on_port_change(self):
        """Debounced after every spinbox edit."""
        if self._port_apply_timer:
            self.root.after_cancel(self._port_apply_timer)
        self._port_apply_timer = self.root.after(600, self._apply_port)

    def _apply_port(self):
        self._port_apply_timer = None
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            return  # transient invalid text while typing
        if not 1024 <= port <= 65535:
            return  # keep last valid value until user fixes it
        if port == self.config_gen.mixed_port:
            return
        self.config_gen.mixed_port = port
        self._save_settings()
        if self.running:
            # re-apply live: sing-box + system proxy on the new port
            self._do_stop()
            self._do_start()

    def _load_settings(self):
        try:
            with open(self._get_config_path("settings.json")) as f:
                data = json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            return
        try:
            port = int(data.get("mixed_port", 7890))
            if 1024 <= port <= 65535:
                self.config_gen.mixed_port = port
        except (TypeError, ValueError):
            pass
        # restore last selected node (validated; stale id -> first)
        sel = data.get("selected_node_id")
        if sel and any(n.get("id") == sel for n in self.nodes):
            self.selected_node_id = sel
        self._was_connected = bool(data.get("was_connected", False))

    def _save_settings(self):
        path = self._get_config_path("settings.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"mixed_port": self.config_gen.mixed_port,
                           "selected_node_id": self.selected_node_id,
                           "was_connected": self._was_connected}, f)
        except OSError:
            pass

    def mainloop(self):
        self.root.mainloop()


def _instance_lock_path() -> str:
    """Socket/pid lock lives next to the app data, like the other state."""
    from core.check import EnvChecker  # noqa: F401 (path helper parity)
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/SingBoxClient")
    elif sys.platform.startswith("linux"):
        base = os.environ.get("XDG_CONFIG_HOME",
                              os.path.expanduser("~/.config/SingBoxClient"))
    else:
        base = os.path.expanduser("~/AppData/Roaming/SingBoxClient")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "single_instance")


def _acquire_single_instance(base_path):
    """Enforce exactly one main UI.

    Returns a listening socket on success; on a second launch it pokes
    the running instance (which lifts its window) and returns None, so
    the caller exits quietly. A stale lock from a dead process is
    cleared and rebound.
    """
    if sys.platform == "win32":
        # pid-file fallback: alive owner wins; stale file gets taken over
        path = base_path + ".pid"
        try:
            with open(path) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            if subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True).stdout.strip():
                return None
        except (OSError, ValueError):
            pass
        with open(path, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(lambda: os.remove(path)
                        if os.path.exists(path) else None)
        return True

    path = base_path + ".sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(path)
    except OSError:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(path)   # a live instance answers
            probe.close()
            return None
        except OSError:
            pass                  # stale socket file from a dead process
        try:
            os.unlink(path)
            s.bind(path)
        except OSError:
            return None
    s.listen(2)
    s.setblocking(False)
    atexit.register(lambda: os.path.exists(path) and os.unlink(path))
    return s


def main():
    lock_path = _instance_lock_path()
    lock = _acquire_single_instance(lock_path)
    if lock is None:
        return  # a main UI already exists (it lifts itself); exit quietly

    root = tk.Tk()
    root.title("SingBoxClient")

    # SIGTERM (kills, logouts): exit through Tk so atexit frees the lock
    import signal as _signal

    def _term(_sig, _frm):
        if root.winfo_exists():
            root.destroy()
    try:
        _signal.signal(_signal.SIGTERM, _term)
    except (ValueError, OSError):
        pass

    if not isinstance(lock, bool):
        def poll_wake():
            """Second launch pokes the socket: bring our UI to front."""
            try:
                conn, _ = lock.accept()
                conn.close()
                root.deiconify()
                root.lift()
                root.attributes("-topmost", True)
                root.after(300, lambda: root.attributes("-topmost", False))
                root.focus_force()
            except (BlockingIOError, OSError):
                pass
            if root.winfo_exists():
                root.after(600, poll_wake)
        root.after(600, poll_wake)

    # Run environment checks
    results = EnvChecker.run_all_checks()
    has_fail = any(r["status"] == "fail" for _, r in results)

    if has_fail:
        env_dlg = EnvInstallDialog(root, results)
        root.wait_window(env_dlg.dialog)  # Wait for dialog to close

    app = App(root)
    app.mainloop()


if __name__ == "__main__":
    main()
