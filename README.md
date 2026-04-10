<div align="center">

# WorkflowVM

**将 GitHub Actions 化为可调度的云端 Python 沙盒**

[![License](https://img.shields.io/github/license/gitpetyr/workflowVM?color=blue)](https://github.com/gitpetyr/workflowVM/blob/main/LICENSE)
[![Workflow Status](https://github.com/gitpetyr/workflowVM/actions/workflows/release.yml/badge.svg)](https://github.com/gitpetyr/workflowVM/actions)
[![Release](https://img.shields.io/github/v/release/gitpetyr/workflowVM?label=Release&color=success)](https://github.com/gitpetyr/workflowVM/packages)
[![PyPI version](https://img.shields.io/pypi/v/workflowvm.svg?color=orange)](https://pypi.org/project/workflowvm/)

[![Docker Image version](https://ghcr-badge.egpl.dev/gitpetyr/workflowvm/latest_tag?color=%2344cc11&ignore=latest&label=docker+image+version&trim=)](https://github.com/gitpetyr/workflowVM/pkgs/container/workflowvm)
[![Docker Image size](https://ghcr-badge.egpl.dev/gitpetyr/workflowvm/size?color=%2344cc11&tag=latest&label=image+size&trim=)](https://github.com/gitpetyr/workflowVM/pkgs/container/workflowvm)
[![Last Commit](https://img.shields.io/github/last-commit/gitpetyr/workflowvm)](https://github.com/gitpetyr/workflowvm/commits/main)


[![LINUX DO](https://img.shields.io/badge/LINUX%20DO-Community-blue)](https://linux.do)

</div>

<br/>

WorkflowVM 通过 [rpyc](https://rpyc.readthedocs.io/) classic 模式，将 GitHub Actions Runner 变成可远程操控的 Python 环境。所有 Python 协议（`with`、`for`、运算符、`len()`、`bool()` 等）均透明支持，无需手动序列化。

## 核心特性

* **免费云算力**：无缝对接 GitHub Actions，零成本调度 Ubuntu Runner。
* **透明 RPC**：基于 rpyc NetRef，在本地像操作本地对象一样使用远端 Python 对象，上下文管理器、迭代器、运算符自动透传。
* **自动生命周期**：自动分配、保活和释放 Runner 资源。

**警告：请合理使用，使用本工具可能导致 github 账号被永久封禁。**

**警告：请合理使用，使用本工具可能导致 github 账号被永久封禁。**

**警告：请合理使用，使用本工具可能导致 github 账号被永久封禁。**

---

## 前置准备：GitHub Token

你需要一个具有特定权限的 **Classic PAT (Personal Access Token)**。
前往 [GitHub Developer Settings](https://github.com/settings/tokens) 生成 Token，并确保勾选以下权限：
* `repo` - 完整仓库访问权限（用于创建 runner 仓库）。
* `workflow` - 触发 `workflow_dispatch`（必需，用于调度 Runner）。

---

## 快速开始

### 1. 配置账号池
创建一个 `accounts.yml` 文件：

```yaml
accounts:
  - username: your-github-username
    token: ghp_YOUR_CLASSIC_PAT  # 必须包含 repo + workflow 权限
    runner_repo: wvm-runner      # 将自动创建此仓库
    max_concurrent: 5            # 最大并发 runner 数量

server:
  host: 0.0.0.0
  port: 8765
  api_token: "your-server-api-token"
  # ws_url: "wss://your-domain.com"  # 反代时配置；默认 ws://host:port
```

### 2. 初始化 Runner 仓库

```bash
workflowvm setup --config accounts.yml
```

> **提示**：`workflowvm serve` 启动时也会自动执行初始化检测。

### 3. 启动服务器

**选项 A：直接安装运行**
```bash
pip install workflowvm
workflowvm serve --config accounts.yml
```

**选项 B：使用 Docker**
```bash
docker compose up -d
```

### 4. SDK 调用示例

```python
from workflowvm import Controller

ctrl = Controller("wss://your-server:8765", token="your-server-api-token")
conn = ctrl.acquire(timeout=120, max_duration=300)

# 访问远端模块
os = conn.modules.os
print(os.system("whoami"))         # 在 GitHub Actions runner 上执行

# 上下文管理器（自动透明）
camoufox = conn.modules.camoufox
with camoufox.SyncCamoufox() as browser:
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())

conn.close()
```

rpyc 的 `async_()` 包装器可用于处理异步方法：

```python
import rpyc
async_fn = rpyc.async_(browser.some_async_method)
result = async_fn()
result.wait()
value = result.value
```

---

## 架构

```text
SDK (调用方)
  └─ Controller.acquire() → 返回 rpyc.Connection
        └─ 调度服务器 (WebSocket Server + 账号池 + Session 管理)
              └─ 调用 GitHub API (workflow_dispatch)
                    └─ 启动 GitHub Actions Ubuntu runner
                          └─ agent.py → 主动反连服务器，暴露 rpyc SlaveService
```

```
SDK ─── WebSocket ──→ Server ─── WebSocket ──→ Agent
       (acquire协商)   (字节隧道)              (rpyc classic SlaveService)
                  ←─── rpyc 协议字节流 ─────────
```

Server 仅负责 acquire 握手阶段，之后变为**纯字节隧道**，rpyc 协议端到端运行在 SDK 与 Agent 之间。SDK 通过 `rpyc.Connection` 直接访问 Agent 的 Python 环境。

---

## CLI 命令参考

| 命令 | 功能说明 |
| :--- | :--- |
| `workflowvm serve --config <file>` | 启动 WebSocket 调度服务器 |
| `workflowvm setup --config <file>` | 初始化并验证所有 Runner 仓库状态 |
| `workflowvm-agent --server <url> --token <tok> --duration <sec>` | 在 Runner 内运行 Agent（通常由 GitHub Workflow 自动执行） |

---

## 安全说明

rpyc classic 模式暴露完整 Python 环境（任意代码执行）。WorkflowVM 的使用场景是一次性 GitHub Actions Runner，这是可接受的——用户本来就完全控制 runner 环境。生产部署中，`api_token` 是唯一访问控制，请妥善保管。

---

## 测试

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## Linux DO

[![LINUX DO](https://img.shields.io/badge/LINUX%20DO-Community-blue)](https://linux.do)
