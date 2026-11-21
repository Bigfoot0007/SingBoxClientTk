# SingBox Client

一个简单的 Python tkinter 图形界面客户端，用于管理 sing-box 代理连接。

## 依赖

GUI 本身 **零 pip 依赖**，只需要 Python + sing-box 内核（建议 1.12+，应用按新版
`rule_set`/DNS 格式生成配置）。首次启动时应用会自动做环境检查，缺什么会弹安装指引。

### macOS

- Python 3.8+（tkinter 自带）
- sing-box：`brew install sing-box`（应用内可一键打开终端执行）

### Windows

- Python 3.8+（python.org 安装包自带 tkinter）
- sing-box：从 [Releases](https://github.com/SagerNet/sing-box/releases) 下载
  `sing-box-<版本>-windows-amd64.zip`，解压出 `sing-box.exe` 放进任一 PATH 目录；
  用 scoop / chocolatey / winget 装的会被自动找到

### Linux

- Python 3.8+ 和 tkinter（多数发行版需单独装）：
  Debian/Ubuntu `sudo apt install python3-tk`，Fedora `sudo dnf install python3-tkinter`
- sing-box（amd64 示例）：
  ```bash
  ver=$(curl -s https://api.github.com/repos/SagerNet/sing-box/releases/latest | grep -oP '"tag_name":\s*"v\K[^"]+')
  curl -L "https://github.com/SagerNet/sing-box/releases/download/v$ver/sing-box-$ver-linux-amd64.tar.gz" -o /tmp/sing-box.tar.gz
  tar -xzf /tmp/sing-box.tar.gz -C /tmp
  sudo mv "/tmp/sing-box-$ver-linux-amd64/sing-box" /usr/local/bin/
  sudo chmod +x /usr/local/bin/sing-box
  ```

## 运行

```bash
python3 app.py
```

## 功能

- 添加/编辑/删除节点（支持 vless, vmess, shadowsocks, trojan）
- 支持 vless + reality（完整参数）
- 一键连接/断开
- 自动设置系统代理
- 三种路由模式：Geosite + GEOIP / 手动域名 / 全局代理
- DNS 分流（国内走阿里 DNS，国外走 Google DNS）
- 剪贴板批量导入 vless:// 链接
- 节点数据持久化（JSON 文件）

## 项目结构

```
SingBoxClientTk/
├── app.py                  # 主程序（tkinter GUI）
├── core/
│   ├── singbox.py          # sing-box 进程管理
│   ├── config.py           # 配置生成（含路由规则）
│   └── proxy.py            # 系统代理设置（macOS / Windows / Linux）
└── README.md
```

## 使用方法

1. 点击 **+ 添加** 手动添加节点
2. 或点击 **📋 导入** 从剪贴板批量粘贴 vless:// 链接
3. 选中节点后点击 **▶ 连接**
4. 已连接后，系统代理自动设置为 127.0.0.1:7890
5. 点击 **■ 断开** 停止代理并恢复系统设置

## 数据存储

节点配置保存在：
- macOS: `~/Library/Application Support/SingBoxClient/nodes.json`
- Linux: `~/.config/SingBoxClient/nodes.json`
- Windows: `%APPDATA%\SingBoxClient\nodes.json`
