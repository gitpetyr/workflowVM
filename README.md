# WorkflowVM

[![License](https://img.shields.io/github/license/gitpetyr/workflowVM)](https://github.com/gitpetyr/workflowVM/blob/main/LICENSE)
[![Workflow Status](https://github.com/gitpetyr/workflowVM/actions/workflows/release.yml/badge.svg)](https://github.com/gitpetyr/workflowVM/actions)
[![Release](https://img.shields.io/github/v/release/gitpetyr/workflowVM?label=Release)](https://github.com/gitpetyr/workflowVM/packages)
[![PyPI version](https://img.shields.io/pypi/v/workflowvm.svg)](https://pypi.org/project/workflowvm/)
[![Docker Image version](https://ghcr-badge.egpl.dev/gitpetyr/workflowvm/latest_tag?color=%2344cc11&ignore=latest&label=docker+image+version&trim=)](https://github.com/gitpetyr/workflowVM/pkgs/container/workflowvm)
[![Docker Image size](https://ghcr-badge.egpl.dev/gitpetyr/workflowvm/size?color=%2344cc11&tag=latest&label=image+size&trim=)](https://github.com/gitpetyr/workflowVM/pkgs/container/workflowvm)
[![Last Commit](https://img.shields.io/github/last-commit/gitpetyr/workflowvm)](https://github.com/gitpetyr/workflowvm/commits/main)

将 GitHub Actions 免费 Ubuntu runner 作为可调度 Python 沙盒，通过 WebSocket 远程对象协议从服务器端透明操作远程 Python 环境。

## 快速开始

### 1. 配置账号池

编辑 `accounts.yml`：

```yaml
accounts:
  - username: your-github-username
    token: ghp_YOUR_CLASSIC_PAT  # 需要 repo + workflow scope
    runner_repo: wvm-runner
    max_concurrent: 5

server:
  host: 0.0.0.0
  port: 8765
  api_token: "your-server-api-token"
  # ws_url: "wss://your-domain.com"  # 反代时配置，agent 用此地址反连；默认 ws://host:port
```

### 2. 初始化 runner repo（自动）

```bash
workflowvm setup --config accounts.yml
```

`setup` 命令会自动为 accounts.yml 中的每个账号创建 runner repo（若不存在）并推送 workflow 文件。`workflowvm serve` 启动时也会自动执行此初始化。

### 3. 启动服务器

**方式 A：直接安装运行**

```bash
pip install workflowvm
workflowvm serve --config accounts.yml
```

**方式 B：Docker**

```bash
mkdir config
cp accounts.yml config/
# 将 docker-compose.yml 中的 OWNER 替换为你的 GitHub 用户名
docker compose up -d
```

### 4. 使用 SDK

```python
import workflowvm

ctrl = workflowvm.Controller(
    "wss://your-server:8765",
    token="your-server-api-token",
)

vm = ctrl.acquire(timeout=120, max_duration=300)

# 透明远程对象操作
# 用 import_ 导入模块（_AgentRoot 根命名空间提供的 dunder-free 别名）
vm.os = vm.import_("os")
print(vm.os.system("whoami"))      # 在 GitHub Actions runner 上执行

f = vm.open("/etc/hostname")       # 内置函数（open/print 等）直接可用
content = f.read()
print(vm._repr(content))           # → 'runner-hostname\n'

vm.release()

# 或使用 with 语句自动释放
with ctrl.acquire(timeout=120, max_duration=300) as vm:
    result = vm.import_("platform")
    print(vm._repr(result.system()))
```

## Classic PAT 权限

在 GitHub Settings → Developer settings → Personal access tokens → Generate new token (classic) 中勾选：
- `repo` - 完整仓库访问
- `workflow` - 触发 workflow_dispatch（必需）

## 架构

```
SDK (调用方)
  └─ Controller.acquire() → RemoteVM
        └─ 服务器 (WebSocket server + 账号池 + 实例池)
              └─ GitHub API workflow_dispatch
                    └─ GitHub Actions Ubuntu runner
                          └─ agent.py → 反连 WebSocket
```

**连接保活**：SDK 每 15 秒通过 `ping` 操作发送应用层心跳，防止 Caddy 等反代因空闲关闭连接。所有 WebSocket IO 运行在独立后台线程的 event loop 中，确保 REPL 空闲期间 ping/pong 正常工作。

**根命名空间**：agent 端 obj_id=0 是一个 `_AgentRoot` 实例，支持自定义属性赋值，未找到时回退到 `builtins`（`open`、`print` 等内置函数直接可用）。`import_` 是 `__import__` 的无 dunder 别名，用于在远程环境导入模块。

## CLI 参考

| 命令 | 说明 |
|------|------|
| `workflowvm serve --config accounts.yml` | 启动 WebSocket 服务器 |
| `workflowvm setup --config accounts.yml` | 初始化所有 runner repo |
| `workflowvm-agent --server <url> --token <tok> --duration <sec>` | 在 runner 内直接运行 agent（通常由 workflow 调用） |

## 测试

```bash
pytest tests/ -v
```
