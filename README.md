# WorkflowVM

将 GitHub Actions 免费 Ubuntu runner 作为可调度 Python 沙盒，通过 WebSocket 远程对象协议从服务器端透明操作远程 Python 环境。

## 快速开始

### 1. 配置账号池

编辑 `accounts.yml`：

```yaml
accounts:
  - username: your-github-username
    token: ghp_YOUR_CLASSIC_PAT  # 需要 repo + workflow scope
    runner_repo: your-username/wvm-runner
    max_concurrent: 5

server:
  host: 0.0.0.0
  port: 8765
  api_token: "your-server-api-token"
```

### 2. 在 runner repo 中提交 workflow 文件

将 `.github/workflows/agent.yml` 提交到你的 runner repo（`runner_repo` 指定的仓库）。

### 3. 启动服务器

```bash
pip install -r requirements.txt
python server/main.py --config accounts.yml
```

### 4. 使用 SDK

```python
import sys; sys.path.insert(0, '.')
import workflowvm

ctrl = workflowvm.Controller(
    "wss://your-server:8765",
    token="your-server-api-token",
    config_path="accounts.yml",
)

vm = ctrl.acquire(timeout=120, max_duration=300)

# 透明远程对象操作
vm.os = vm.__import__("os")
print(vm.os.system("whoami"))      # 在 GitHub Actions runner 上执行

f = vm.open("/etc/hostname")
content = f.read()
print(vm._repr(content))           # → 'runner-hostname\n'

vm.release()
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

## 测试

```bash
pytest tests/ -v
```
