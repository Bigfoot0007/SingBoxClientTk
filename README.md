# SingBox Client

一个简单的 Python tkinter 图形界面客户端，用于管理 sing-box 代理连接。

## 依赖

**安装包用户：无需安装 sing-box。** 安装包自带 sing-box 1.14.4 引擎（Go 单文件，
构建时从官方 Release 拉取），运行时解包到应用数据目录的 `bin/` 下执行——
内核版本与应用生成的配置格式永远匹配。装好即用。

源码运行（开发者）才需要关心内核：GUI 本身 **零 pip 依赖**，Python + tkinter
即可；sing-box 优先找 `assets/sing-box(.exe)`（放一份即可），找不到再退回系统
安装（PATH / Homebrew / scoop 等）。macOS 示例：

```bash
ver=1.14.4; arch=darwin-arm64   # Linux 用 linux-amd64；Windows 下载 zip 取 sing-box.exe
curl -L "https://github.com/SagerNet/sing-box/releases/download/v$ver/sing-box-$ver-$arch.tar.gz" -o /tmp/sb.tgz
tar -xzf /tmp/sb.tgz -C /tmp
cp "/tmp/sing-box-$ver-$arch/sing-box" assets/ && chmod +x assets/sing-box
```

各平台 Python/tkinter：

- **macOS**：Python 3.8+（tkinter 自带）
- **Windows**：Python 3.8+（python.org 安装包自带 tkinter）
- **Linux**：Python 3.8+，tkinter 多数发行版需单独装：
  Debian/Ubuntu `sudo apt install python3-tk`，Fedora `sudo dnf install python3-tkinter`

## 运行

```bash
python3 app.py
```

## 功能

- 添加/编辑/删除节点（支持 vless, vmess, shadowsocks, trojan）
- 支持 vless + reality（完整参数）；📋 剪贴板批量导入 vless:// 链接
- 一键连接/断开；自动设置并在断开/退出时恢复系统代理，混合端口可修改（默认 7890）
- 状态点 🟢 标记当前连接所在节点（未连接时标记默认节点）；**双击节点**直接连接/切换，单击只选中
- 三种路由模式：Geosite + GEOIP / 手动域名 / 全局代理；GEO 规则集随包携带一份（`.srs`），
  全新安装断网也能启动，联网后按周期自动远程更新并缓存（cache.db）
- DNS 分流（国内走阿里 DNS，国外走 Google DNS）
- 🩺 诊断：节点三态判定（健康 / Reality 密钥已轮换 / 离线）；🔍 全部测试；延迟列 + 已连接节点每 60 s 自动复测
- 🔬 高级面板：访问日志实时滚动 + 访问汇总饼图（**按域归组**，代理红/直连绿，悬停切片查看折叠明细）+ 自动结论行（遥测/系统后台/内容/应用占比 + IP 直连哨兵），中间竖条可拖动调宽
- 流量图：近 15 分钟上/下行速率曲线（Clash API），悬停查看历史
- 自带 sing-box 1.14.4 引擎（安装包免安装；源码运行可放 `assets/` 或复用系统安装）
- 启动环境检查：缺运行环境时给一键安装/复制命令指引
- 单实例保障：重复启动只唤起已有窗口
- 优雅退出：退出时恢复系统代理；下次启动按退出时的连接状态自动重连
- 内嵌 toast 提示（不打断操作）；自动适配系统深色/浅色主题（macOS / Windows）
- 节点数据持久化（JSON 文件，即改即存）

## 项目结构

```
SingBoxClientTk/
├── app.py                  # 主程序（tkinter GUI）
├── core/
│   ├── singbox.py          # sing-box 进程管理（含孤儿进程回收）
│   ├── config.py           # 配置生成（rule_set 路由 / DNS 分流）
│   ├── proxy.py            # 系统代理设置（macOS / Windows / Linux）
│   ├── diagnose.py         # 节点三态诊断（🩺）
│   ├── accesslog.py        # 访问日志解析与汇总（🔬）
│   ├── stats.py            # Clash API 流量采集（流量图）
│   ├── bundled_bin.py      # 内置 sing-box 引擎解包与版本戳
│   └── check.py            # 环境检查与安装指引
├── assets/                 # 应用图标（icns / ico / png）
├── .github/workflows/      # CI：三平台安装包 + 自动发布 Release
├── installer.iss           # Windows Inno Setup 脚本
└── README.md
```

## 安装包

推送 `vX.Y.Z` tag 会触发 GitHub Actions 构建三个平台的安装包并自动发布到
[Releases](../../releases)（macOS dmg 仅 Apple Silicon；均为 ad-hoc 签名，
macOS 首次需右键→打开，Windows 首次有 SmartScreen 提示）。

## 使用方法

1. 点击 **+ 添加** 手动添加节点
2. 或点击 **📋 导入** 从剪贴板批量粘贴 vless:// 链接
3. 选中节点后点击 **▶ 连接**（或直接双击该节点；已连接时双击另一节点会切换过去）
4. 已连接后，系统代理自动设置为 127.0.0.1:7890（端口可在界面上改，即改即存）
5. 点击 **● 断开** 停止代理并恢复系统设置

## 数据存储

节点配置保存在：
- macOS: `~/Library/Application Support/SingBoxClient/nodes.json`
- Linux: `~/.config/SingBoxClient/nodes.json`
- Windows: `%APPDATA%\SingBoxClient\nodes.json`
