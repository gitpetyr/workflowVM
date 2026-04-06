<div align="center">

# WorkflowVM

**将 GitHub Actions 免费 Ubuntu Runner 化身为可调度的云端 Python 沙盒**

[![License](https://img.shields.io/github/license/gitpetyr/workflowVM?color=blue)](https://github.com/gitpetyr/workflowVM/blob/main/LICENSE)
[![Workflow Status](https://github.com/gitpetyr/workflowVM/actions/workflows/release.yml/badge.svg)](https://github.com/gitpetyr/workflowVM/actions)
[![Release](https://img.shields.io/github/v/release/gitpetyr/workflowVM?label=Release&color=success)](https://github.com/gitpetyr/workflowVM/packages)
[![PyPI version](https://img.shields.io/pypi/v/workflowvm.svg?color=orange)](https://pypi.org/project/workflowvm/)

[![Docker Image version](https://ghcr-badge.egpl.dev/gitpetyr/workflowvm/latest_tag?color=%2344cc11&ignore=latest&label=docker+image+version&trim=)](https://github.com/gitpetyr/workflowVM/pkgs/container/workflowvm)
[![Docker Image size](https://ghcr-badge.egpl.dev/gitpetyr/workflowvm/size?color=%2344cc11&tag=latest&label=image+size&trim=)](https://github.com/gitpetyr/workflowVM/pkgs/container/workflowvm)
[![Last Commit](https://img.shields.io/github/last-commit/gitpetyr/workflowvm)](https://github.com/gitpetyr/workflowvm/commits/main)

</div>

<br/>

WorkflowVM 允许你通过 WebSocket 远程对象协议，从服务器端**透明地**操作远程 Python 环境。轻松调度 GitHub 算力池进行沙盒测试、分布式任务或其他高并发场景。

## 核心特性

* **免费云算力**：无缝对接 GitHub Actions，零成本调度 Ubuntu Runner。
* **透明 RPC 调用**：像操作本地对象一样，在本地代码中直接操作远端 Python 环境（包含内置函数与模块导入）。
* **自动生命周期**：内置连接保活机制，自动分配、保活和释放 Runner 资源。

---

## 前置准备：GitHub Token

你需要一个具有特定权限的 **Classic PAT (Personal Access Token)**。
前往 [GitHub Developer Settings](https://github.com/settings/tokens) 生成 Token，并确保勾选以下权限：
* `repo` - 完整仓库访问权限（用于创建 runner 仓库）。
* `workflow` - 触发 `workflow_dispatch`（必需，用于调度 Runner）。

---

## 快速开始

### 1. 配置账号池
创建一个 `accounts.yml` 文件，配置你的 GitHub 账号信息与服务端设置：

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
  # ws_url: "wss://your-domain.com"  # 反代时配置，agent 用此地址反连；默认 ws://host:port
```

### 2. 初始化 Runner 仓库
使用 CLI 工具自动初始化（自动为 `accounts.yml` 中的每个账号创建仓库并推送 workflow 文件）：

```bash
workflowvm setup --config accounts.yml
```
> **提示**：`workflowvm serve` 启动时也会自动执行此初始化检测。

### 3. 启动服务器
你可以选择通过原生 Python 或 Docker 启动调度服务器：

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
服务启动后，就可以在你的 Python 代码中无缝调用云端沙盒了：

```python
import workflowvm

# 连接到你的调度服务器
ctrl = workflowvm.Controller(
    "wss://your-server:8765",
    token="your-server-api-token",
)

# 申请分配一个云端沙盒实例
vm = ctrl.acquire(timeout=120, max_duration=300)

# ----------------- 透明远程对象操作 -----------------
# 1. 导入远程模块（使用 _AgentRoot 提供的无 dunder 别名 import_）
vm.os = vm.import_("os")
print(vm.os.system("whoami"))      # 在 GitHub Actions runner 上执行并打印结果

# 2. 直接使用内置函数（open, print 等均被透传）
f = vm.open("/etc/hostname")       
content = f.read()
print(vm._repr(content))           # 输出类似: 'runner-hostname\n'

# 释放资源
vm.release()

# ----------------- 推荐：使用 with 语句自动管理 -----------------
with ctrl.acquire(timeout=120, max_duration=300) as vm:
    result = vm.import_("platform")
    print(vm._repr(result.system()))
```

---

## 架构设计与底层机制

WorkflowVM 的架构采用典型的 C/S 配合反向连接模型：

```text
SDK (调用方)
  └─ Controller.acquire() → 获得 RemoteVM 句柄
        └─ 调度服务器 (WebSocket Server + 账号池 + 实例池)
              └─ 调用 GitHub API (workflow_dispatch)
                    └─ 启动 GitHub Actions Ubuntu runner
                          └─ agent.py → 主动反连 WebSocket 服务器
```

* **连接保活 (Keep-Alive)**：SDK 每 15 秒会通过 `ping` 操作发送应用层心跳，防止 Caddy 等反向代理因空闲切断连接。所有 WebSocket I/O 均运行在独立后台线程的 Event Loop 中，确保即使在 REPL 空闲期间 ping/pong 也能正常响应。
* **根命名空间 (Root Namespace)**：Agent 端 `obj_id=0` 是一个 `_AgentRoot` 实例。它支持自定义属性赋值，未找到的方法会优雅回退到 Python 的 `builtins` 模块（因此可以直接调用 `open`、`print` 等内置函数）。使用 `import_` 作为 `__import__` 的别名，避免了 dunder 方法带来的冲突问题。

---

## CLI 命令参考

| 命令 | 功能说明 |
| :--- | :--- |
| `workflowvm serve --config <file>` | 启动 WebSocket 调度服务器 |
| `workflowvm setup --config <file>` | 初始化并验证所有 Runner 仓库状态 |
| `workflowvm-agent --server <url> --token <tok> --duration <sec>` | 在 Runner 内运行 Agent（通常由 GitHub Workflow 自动执行，无需手动调用） |

---

## 测试

运行以下命令执行单元测试：

```bash
pytest tests/ -v
```