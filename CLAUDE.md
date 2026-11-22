# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

SingBoxClientTk — a personal sing-box GUI client (VLESS/Reality proxy manager), Python/tkinter, **zero pip deps (stdlib only)**. Flow: `nodes.json` → `core/config.py` generates sing-box JSON → subprocess `sing-box -D <data dir> run` → system proxy set on 127.0.0.1:<mixed_port> (mixed inbound). Nodes are added by pasting `vless://` links (📋 导入).

- `core/diagnose.py` (`NodeDiagnostics`, the 🩺 诊断 button) gives a three-state verdict — TCP reachable → isolated `sing-box run` on a temp port (`mixed_port + 10000`, `diagnose.json`, ROUTING_ALL so rule-set downloads can't interfere) → HTTPS probe through it, classified from `diagnose.log`: `reality verification failed` ⇒ `stale_params` (server rotated keys, re-subscribe), unreachable/timeout ⇒ `offline`, else `error`. Diagnose configs never enable clash_api (avoids port clashes with the live instance). The same diagnosis powers the 延迟 column, the 60 s auto-measure of the connected node, and 全部测试.
- Advanced panel (🔬 高级): the UI lives in a `ttk.Panedwindow` (horizontal); opening it adds a second pane, window grows 560→902 with the sash at BASE_W=560; the sash is **drag-resizable** (ttk has no minsize/`paneconfigure` — a ButtonPress/B1-Motion binding hit-tests |x−sashpos|≤8 and clamps via `after_idle`, since instance bindings run before ttk's sash class binding: left ≥420 px, panel ≥200 px). On close the pane is `forget()`-ten and width restored. Opening starts `core/accesslog.py` (`AccessLogMonitor`) which tails `singbox.log` from EOF; sing-box 1.14 does NOT emit old `accepted` lines — each connection is 3 INFO lines correlated by the `[id Nms]` field (`inbound connection from/to` + `outbound connection to`, ANSI colors stripped) and re-emitted as `ts from SRC accepted DEST [inb-tag -> out-tag]`. Pie slices are keyed by **(registrable domain, outbound) route** (`registrable_domain()` collapses subdomains; 3-label rule for `com.cn`-style ccTLDs) and colored by ROUTE: direct = green family, proxied = red family (`PROXY_LIGHT/DARK` + `DIRECT_LIGHT/DARK` ramps based on the dataviz status steps `#d03b3b` critical / `#0ca30c`+`#006300` good; same-hue steps separate domains); ≤7 slices + gray "其他 · N 条路由" (a fold, not "unknown"); **hovering a slice** shows its folded members (`_pie_motion`/`_slice_at`, hit-test = clockwise angle from 12 o'clock). Below the pie: a rule-estimate traffic-mix line (`classify()` keyword tables `_TELEMETRY_KEYS/_SYSTEM_KEYS/_CONTENT_KEYS` → 遥测/回传·系统后台·内容/CDN·应用使用) plus a hard **bare-IP sentinel** (`is_ip_literal` → "IP直连 N", beaconing indicator); the keyword tables in `core/accesslog.py` are user-tunable. The legend names the route (· 代理 / · 直连) so color never carries it alone, and log lines use Text tags `rt_proxy`/`rt_direct` in the same base colors. Monitoring runs only while the panel is open; `sing-box start()` truncates the log on reconnect — the tailer detects truncation (`tell > filesize`) and re-opens from 0.
- Live traffic chart: `core/stats.py` (`TrafficMonitor`) uses sing-box's Clash API — configs connect with `experimental.clash_api.external_controller` = `127.0.0.1:39090` + a per-session random `secret`; `/traffic` streams one `{"up":..,"down":..}` B/s JSON per second. Ring buffer (900 s) redrawn every 1 s on a tkinter Canvas in `app.py::_draw_chart`; axis ticks are compact (`_fmt_rate_tick`) with a font-measured dynamic left margin. Palette is the dataviz reference palette (down=blue slot1, up=orange slot2; `LIGHT_THEME`/`DARK_THEME` matched to canvas surfaces `#fcfcfb`/`#1a1a19`, picked at startup via `AppleInterfaceStyle`). The clash port deliberately avoids 9090 (common in other clash tools).
- Bundled engine: the installers ship their own sing-box — CI (build.yml) downloads the official `sing-box-1.14.4-<asset>` release into `assets/sing-box(.exe)` before PyInstaller, the spec embeds it as data under `assets/` (upx_exclude — UPX on a Go binary corrupts it), and `core/bundled_bin.py` extracts it to `<data dir>/bin/` at startup with a `.ver` stamp file. `SingBoxManager`/`EnvChecker` prefer the bundled binary over any system install, so end users never install sing-box and the config contract can't drift. Bumping the engine = change `SINGBOX_VERSION` in `core/bundled_bin.py`, the version in `build.yml`, and the config contract together. Running from source without `assets/sing-box` falls back to the system lookup (dev-only).
- Single instance: `main()` binds `<data dir>/single_instance.sock` (AF_UNIX; pid-file fallback on Windows). A second launch pokes the socket and exits silently; the running instance's `poll_wake` lifts its window. SIGTERM exits through Tk so atexit frees the lock.
- Inline notices replace modals for non-blocking status (`App._show_notice`: closable toast under the title bar, 12 s auto-hide).
- Node-list status dot: 🟢 marks the node the live instance serves — or, while disconnected, the default (selected) node. Single click only moves the row-selection background (never the dot or the connection while connected); double-clicking disconnects + connects that node (same row = plain disconnect). `_do_start` is queued `after(100)` behind `_do_stop`'s after(0) `_on_disconnected` so the disconnect can't clobber state. Proxy snapshot restore lives in `_on_disconnected`, not `_do_stop` — it must also fire when sing-box dies on its own, and `clear_proxy()` consumes its snapshot so it runs exactly once per connect cycle.

## Commands

```bash
python3 app.py                                  # run from source (the dev loop)
pyinstaller --noconfirm SingBoxClient.spec      # rebuild dist/SingBoxClient.app
codesign --force --deep --sign - dist/SingBoxClient.app   # ad-hoc sign after rebuild
python3 make_icon.py                            # regenerate assets/AppIcon.icns (PNG→iconutil)
# distribution dmg (arm64-only; ad-hoc signed — recipients right-click→Open once):
cp -R dist/SingBoxClient.app /tmp/sbc-stage && ln -s /Applications /tmp/sbc-stage/Applications
hdiutil create -volname "SingBox Client" -srcfolder /tmp/sbc-stage -ov -format UDZO dist/SingBoxClient-<ver>.dmg
sing-box check -D "$HOME/Library/Application Support/SingBoxClient" \
  -c "$HOME/Library/Application Support/SingBoxClient/config.json"   # validate generated config
```

**`dist/` is a stale build of the source.** A fix that works under `python3 app.py` is not testable in the packaged `.app` until rebuilt.

`.github/workflows/build.yml` + `installer.iss` build Windows (Inno Setup) / Linux (tar.gz) / macOS (dmg) artifacts on GitHub Actions tags or manual dispatch — PyInstaller cannot cross-compile. The repo's GitHub remote is `git@github.com:Bigfoot0007/SingBoxClientTk.git` (private); pushing a `v*` tag triggers the 3-OS build.

Windows specifics (code paths already handle them): system proxy via winreg HKCU Internet Settings + a `WM_SETTINGCHANGE` "Internet Settings" broadcast after every write (`core/proxy.py::_windows_broadcast`); `reap_orphan` uses pid-file + `tasklist`/`taskkill` (`_reap_orphan_windows`, no pgrep); dark mode reads `AppsUseLightTheme`; sing-box lookup tries winget-links / scoop shims / choco; single instance = pid-file (no AF_UNIX). The spec is platform-gated: `icon` is `assets/AppIcon.ico` (PNG-embedded ICO, stdlib-generated by `make_icon.py`) on win32 and BUNDLE only builds on darwin — keep that gate or the Windows CI job dies on `.icns`. Every subprocess call that can run on Windows must pass `**nogui_kwargs()` (`core/nogui.py`, CREATE_NO_WINDOW): a windowed app has no console, so each bare console-subsystem child (sing-box check/run, tasklist, diagnose run, version probe) flashes a visible cmd window; `startupinfo/SW_HIDE` is NOT enough (still flashes).

There are no tests and no linter. Verification is end-to-end without the GUI:

```bash
# 1. generate a config headlessly (see core/config.py), 2. run sing-box, 3. probe the port
sing-box -D "$HOME/Library/Application Support/SingBoxClient" run -c <config.json> &
curl -x http://127.0.0.1:7890 -o /dev/null -w "%{http_code}\n" https://www.google.com/generate_204   # expect 204 via proxy
curl -x http://127.0.0.1:7890 -o /dev/null -w "%{http_code}\n" https://www.baidu.com                  # expect 200 direct (GEO mode)
```

## Critical constraint: sing-box version contract

The installed sing-box (**1.14.4**, Homebrew, `/opt/homebrew/bin/sing-box`) **rejected large parts of the pre-1.12 config format**; generating a config for an older sing-box is the single most common cause of "连接不上 with no visible error". The generator in `core/config.py` encodes these rules — keep them if sing-box is upgraded:

- `route.rules` **cannot** use `geoip:`/`geosite:` fields — removed in 1.12.0. Use `route.rule_set` (remote `.srs` from SagerNet/sing-geoip) + `{"rule_set": "geoip-cn", ...}`.
- Legacy DNS server format (`{"address": "tls://..."}`) removed in 1.14.0. New format: `{"type": "tls", "server": "8.8.8.8"}`, system resolver is `{"type": "local"}`.
- A `type: local` DNS server must **not** carry `"detour": "direct"` — 1.14 errors with "detour to an empty direct outbound makes no sense".
- `route.default_domain_resolver: "local"` is mandatory (FATAL otherwise on 1.14).
- `download_detour` on remote rule-sets is deprecated (WARN; removed in 1.16) — leave as-is on 1.14, the replacement field does not parse there.
- `sing-box run` is launched with `-D <app data dir>`; GEO-mode startup downloads rule sets through the proxy (~5 s first time), so a dead node makes even config startup FATAL.

sing-box exits FATAL on these mistakes and `Popen` still succeeds — `_do_start` runs `sing-box check` first and samples the process 2 s after start to surface the real error (`SingBoxManager.last_error()` reads `singbox.log`). Preserve that pattern when touching connect logic.

## Data & runtime state

- Nodes/config/logs live in `~/Library/Application Support/SingBoxClient/` (`nodes.json`, `config.json`, `settings.json`, `proxy_state.json`, `singbox.log`, `single_instance.sock`, `bin/sing-box` (extracted bundled engine); `~/.config/SingBoxClient` on Linux, `%APPDATA%\SingBoxClient` on Windows). `settings.json` persists `mixed_port`, `selected_node_id` and `was_connected` (即改即存).
- The system proxy is real macOS state (`networksetup` toggles web/secure web proxy for the first "Wi-Fi" service). The machine may also run another proxy tool (baseline observed: enabled `127.0.0.1:10808`, xray listening) — never clear/overwrite it blindly, and verify `enabled`, not just the port field, when inspecting: networksetup keeps stale Server/Port values while disabled. `ProxyManager` snapshots the previous proxy into `proxy_state.json` before connecting and restores it on disconnect; at startup `App.__init__` reaps an orphaned sing-box (`SingBoxManager.reap_orphan()`: pid file, else `pgrep -f` on our config path) and `cleanup_stale_proxy()` restores the snapshot — but only when the leftover proxy points at `127.0.0.1:<own port>`. Keep that match guard: other tools' proxies must never be touched.
- Quit/resume: `root.protocol("WM_DELETE_WINDOW")` → `App._on_app_quit` — if connected, stops sing-box + restores the proxy snapshot, then records `was_connected` (the running state at quit) into `settings.json` (also updated live by `_on_connected`/`_on_disconnected`). Next launch auto-reconnects (`_autoconnect` after ~1.2 s) when the flag is set — skipped with a toast if sing-box or a node is missing. Worker→UI hops go through `App._post_ui` so shutdown races can't raise.
- `core/check.py` resolves the sing-box binary by absolute path because a Finder-launched app gets a minimal PATH — `which sing-box` fails there while everything still works.
- Reality nodes rotate server-side: a saved node can die (`reality verification failed` in sing-box log) with nothing wrong in the code. Test the node, not just the app, before debugging config generation.
