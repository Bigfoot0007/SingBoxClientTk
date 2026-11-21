# SingBox Client

一个简单的 Python tkinter 图形界面客户端，用于管理 sing-box 代理连接。

## 依赖

- Python 3.8+
- sing-box（通过 Homebrew 安装）
  ```bash
  brew install sing-box
  ```

**无其他依赖！** tkinter 随 Python 自带，无需 pip install。

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
│   └── proxy.py            # macOS 系统代理设置
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
