# WorkflowVM Design Spec

## 概述

将 GitHub Actions 免费 Ubuntu runner 作为可调度 Python 沙盒计算节点。workflow 启动后主动反向 WebSocket 连接到公网服务器，服务器通过自定义远程对象协议像操作本地 Python 对象一样操作远程环境。

## 架构

```
SDK (调用方)
  └─ Controller("wss://server") .acquire() → RemoteVM proxy
        └─ 服务器 (WebSocket server + 账号池 + 实例池)
              └─ GitHub API trigger workflow_dispatch
                    └─ GitHub Actions runner → agent.py 反连 WebSocket
```

## 组件职责

### accounts.yml
账号池配置文件，支持热重载。每个账号含 username、Classic PAT token、runner_repo、max_concurrent。

### server/account_pool.py
加载 accounts.yml，维护每个账号的 active_count，提供 pick()/release() 接口，文件 mtime 变化时热重载。

### server/github_api.py
封装 GitHub REST API，用 httpx.AsyncClient 触发 workflow_dispatch，传递 server_url/session_token/max_duration inputs。

### server/session_manager.py
管理 WebSocket session 生命周期：注册 pending acquire、等待 agent 连接、session 断线保持状态、超时清理。

### server/remote_object.py
Server 侧协议处理：将 RemoteObject proxy 的操作序列化为 JSON 消息发送给 agent，等待响应，反序列化结果。

### server/instance_pool.py
实例完整生命周期：pick 账号 → dispatch workflow → 等待 session 建立 → 运行中 → 释放/清理。

### server/main.py
asyncio 入口，启动 WebSocket server，整合所有组件，处理 CLI 参数 --config。

### agent/agent.py
在 GitHub Actions runner 上运行。维护 objects dict（obj_id → 真实Python对象），反连 WebSocket，处理 op 消息，支持断线重试和 max_duration 自动退出。

### sdk/proxy.py
RemoteObject 透明代理，拦截 __getattr__/__setattr__/__call__/__getitem__/__del__，同步调用 server/remote_object.py 接口。

### sdk/controller.py
Controller 类，持有 WebSocket 到服务器的管理连接，acquire() 触发实例分配并返回 RemoteVM。

### sdk/__init__.py
导出 Controller 和 RemoteObject。

## 远程对象协议

### 握手
```json
// agent → server（初次连接）
{"type":"hello","session_id":"<uuid>","resume":false}
// agent → server（断线重连）
{"type":"hello","session_id":"<uuid>","resume":true}
```

### Server → Agent 操作
```json
{"id":"<uuid>","op":"getattr","obj":0,"name":"__import__"}
{"id":"<uuid>","op":"call",   "obj":5,"args":["os"],"kwargs":{}}
{"id":"<uuid>","op":"setattr","obj":0,"name":"x","value":{"$ref":7}}
{"id":"<uuid>","op":"getitem","obj":3,"key":0}
{"id":"<uuid>","op":"repr",   "obj":7}
{"id":"<uuid>","op":"del",    "obj":7}
{"id":"<uuid>","op":"shutdown"}
```

### Agent → Server 响应
```json
{"id":"<uuid>","type":"ref",  "obj":7}
{"id":"<uuid>","type":"value","val":"hello"}
{"id":"<uuid>","type":"error","exc":"NameError","msg":"..."}
```

obj=0 是 agent 侧的根命名空间 dict（globals 等价物）。

## SDK 用法

```python
import workflowvm

ctrl = workflowvm.Controller("wss://your-server:8765", token="api-token")
vm = ctrl.acquire(timeout=120, max_duration=300)

vm.os = vm.__import__("os")
vm.os.system("whoami")
f = vm.open("/etc/hostname")
content = f.read()
print(vm._repr(content))   # 'myhost\n'

vm.release()
```

## GitHub Actions Workflow

```yaml
name: WorkflowVM Agent
on:
  workflow_dispatch:
    inputs:
      server_url: {required: true}
      session_token: {required: true}
      max_duration: {default: "300"}
jobs:
  agent:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install websockets
      - run: |
          python agent/agent.py \
            --server "${{ inputs.server_url }}" \
            --token "${{ inputs.session_token }}" \
            --duration "${{ inputs.max_duration }}"
```

## accounts.yml 格式

```yaml
accounts:
  - username: user1
    token: ghp_xxxxx
    runner_repo: user1/wvm-runner
    max_concurrent: 5

server:
  host: 0.0.0.0
  port: 8765
  api_token: "server-side-auth-token"
```

## Classic PAT 权限

需要 scope：`repo` + `workflow`

GitHub Settings → Developer settings → Personal access tokens → Generate new token (classic)
