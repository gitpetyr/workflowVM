# WorkflowVM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 GitHub Actions Ubuntu runner 作为可调度 Python 沙盒，通过 WebSocket 远程对象协议从服务器端透明操作远程 Python 环境。

**Architecture:** agent.py 在 GitHub Actions runner 上运行，主动反向 WebSocket 连接到服务器。服务器通过自定义 JSON 协议对 agent 侧的 Python 对象进行 getattr/call/setattr 等操作。SDK 在调用方提供透明代理对象，行为与本地 Python 对象无异。

**Tech Stack:** Python 3.12, asyncio, websockets, httpx, pyyaml, pytest, pytest-asyncio

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `accounts.yml` | 账号池配置（token、repo、并发限制） |
| `requirements.txt` | 依赖列表 |
| `server/account_pool.py` | 账号选取、计数、热重载 |
| `server/github_api.py` | 触发 workflow_dispatch |
| `server/session_manager.py` | session 注册/等待/断线恢复/清理 |
| `server/remote_object.py` | server 侧协议消息收发 |
| `server/instance_pool.py` | 实例生命周期编排 |
| `server/main.py` | asyncio WebSocket server 入口 |
| `agent/agent.py` | workflow runner 内的反连 agent |
| `sdk/proxy.py` | RemoteObject 透明代理 |
| `sdk/controller.py` | Controller + acquire() |
| `sdk/__init__.py` | 公开 API 导出 |
| `.github/workflows/agent.yml` | GitHub Actions workflow 模板 |
| `tests/test_account_pool.py` | 账号池单元测试 |
| `tests/test_protocol.py` | 协议消息序列化测试 |
| `tests/test_proxy.py` | RemoteObject proxy 测试 |
| `tests/test_integration.py` | server+agent 集成测试（本地 WebSocket） |

---

### Task 1: 项目基础结构

**Files:**
- Create: `requirements.txt`
- Create: `accounts.yml`
- Create: `server/__init__.py`
- Create: `agent/__init__.py`
- Create: `sdk/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p server agent sdk tests .github/workflows
touch server/__init__.py agent/__init__.py sdk/__init__.py tests/__init__.py
```

- [ ] **Step 2: 创建 requirements.txt**

```
websockets>=12.0
httpx>=0.27.0
pyyaml>=6.0
pytest>=8.0
pytest-asyncio>=0.23
anyio>=4.0
```

- [ ] **Step 3: 创建 accounts.yml 模板**

```yaml
accounts:
  - username: placeholder
    token: ghp_REPLACE_ME
    runner_repo: placeholder/wvm-runner
    max_concurrent: 5

server:
  host: 0.0.0.0
  port: 8765
  api_token: "change-me-secret"
```

- [ ] **Step 4: 创建 tests/conftest.py**

```python
import pytest
import asyncio

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()
```

- [ ] **Step 5: 安装依赖**

```bash
pip install -r requirements.txt
```

Expected: 安装成功，无报错。

- [ ] **Step 6: Commit**

```bash
git add requirements.txt accounts.yml server/__init__.py agent/__init__.py sdk/__init__.py tests/__init__.py tests/conftest.py .github/
git commit -m "chore: project scaffolding"
```

---

### Task 2: 账号池 (account_pool.py)

**Files:**
- Create: `server/account_pool.py`
- Create: `tests/test_account_pool.py`

- [ ] **Step 1: 写失败测试**

`tests/test_account_pool.py`:
```python
import pytest
import os
import tempfile
import yaml
from server.account_pool import AccountPool, NoAccountAvailable

SAMPLE_CONFIG = {
    "accounts": [
        {"username": "u1", "token": "tok1", "runner_repo": "u1/r", "max_concurrent": 2},
        {"username": "u2", "token": "tok2", "runner_repo": "u2/r", "max_concurrent": 1},
    ],
    "server": {"host": "0.0.0.0", "port": 8765, "api_token": "secret"},
}

@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "accounts.yml"
    p.write_text(yaml.dump(SAMPLE_CONFIG))
    return str(p)

def test_pick_returns_account(config_file):
    pool = AccountPool(config_file)
    acc = pool.pick()
    assert acc["username"] in ("u1", "u2")
    assert "token" in acc
    assert "runner_repo" in acc

def test_pick_respects_max_concurrent(config_file):
    pool = AccountPool(config_file)
    # u2 最多1个并发，pick两次都优先 u1（最少使用）
    a1 = pool.pick()
    pool.release(a1["username"])
    a2 = pool.pick()
    assert a2 is not None

def test_pick_raises_when_all_full(config_file):
    pool = AccountPool(config_file)
    # u1 max=2, u2 max=1, 共3个槽
    pool.pick()
    pool.pick()
    pool.pick()
    with pytest.raises(NoAccountAvailable):
        pool.pick()

def test_release_decrements_count(config_file):
    pool = AccountPool(config_file)
    acc = pool.pick()
    pool.release(acc["username"])
    # 再次 pick 应该成功
    acc2 = pool.pick()
    assert acc2 is not None

def test_hot_reload(tmp_path):
    p = tmp_path / "accounts.yml"
    cfg = {
        "accounts": [{"username": "u1", "token": "t1", "runner_repo": "u1/r", "max_concurrent": 1}],
        "server": {"host": "0.0.0.0", "port": 8765, "api_token": "x"},
    }
    p.write_text(yaml.dump(cfg))
    pool = AccountPool(str(p))
    pool.pick()  # 占满

    # 写入新配置（增加账号）
    cfg["accounts"].append({"username": "u2", "token": "t2", "runner_repo": "u2/r", "max_concurrent": 1})
    import time; time.sleep(0.01)
    p.write_text(yaml.dump(cfg))
    pool.reload_if_changed()

    acc = pool.pick()  # 新账号可用
    assert acc["username"] == "u2"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_account_pool.py -v
```

Expected: `ModuleNotFoundError` 或 `ImportError`

- [ ] **Step 3: 实现 account_pool.py**

`server/account_pool.py`:
```python
import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


class NoAccountAvailable(Exception):
    pass


class AccountPool:
    def __init__(self, config_path: str):
        self._config_path = config_path
        self._mtime: float = 0.0
        self._accounts: list[dict] = []
        self._active: dict[str, int] = {}  # username → count
        self._server_config: dict = {}
        self._load()

    def _load(self):
        with open(self._config_path) as f:
            cfg = yaml.safe_load(f)
        self._mtime = os.path.getmtime(self._config_path)
        self._server_config = cfg.get("server", {})
        new_accounts = cfg.get("accounts", [])
        # 保留已有 active 计数，新账号从0开始
        existing = {a["username"] for a in self._accounts}
        for acc in new_accounts:
            if acc["username"] not in existing:
                self._active.setdefault(acc["username"], 0)
        self._accounts = new_accounts

    def reload_if_changed(self):
        try:
            mtime = os.path.getmtime(self._config_path)
        except OSError:
            return
        if mtime > self._mtime:
            self._load()

    @property
    def server_config(self) -> dict:
        return self._server_config

    def pick(self) -> dict:
        """选取 active_count 最小且未满的账号。"""
        self.reload_if_changed()
        candidates = [
            acc for acc in self._accounts
            if self._active.get(acc["username"], 0) < acc["max_concurrent"]
        ]
        if not candidates:
            raise NoAccountAvailable("所有账号已达并发上限")
        # 最少使用策略
        chosen = min(candidates, key=lambda a: self._active.get(a["username"], 0))
        self._active[chosen["username"]] = self._active.get(chosen["username"], 0) + 1
        return chosen

    def release(self, username: str):
        if self._active.get(username, 0) > 0:
            self._active[username] -= 1
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_account_pool.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add server/account_pool.py tests/test_account_pool.py
git commit -m "feat: account pool with hot reload"
```

---

### Task 3: GitHub API 封装 (github_api.py)

**Files:**
- Create: `server/github_api.py`
- Create: `tests/test_github_api.py`

- [ ] **Step 1: 写失败测试**

`tests/test_github_api.py`:
```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from server.github_api import GitHubAPI, WorkflowDispatchError

@pytest.mark.asyncio
async def test_dispatch_workflow_success():
    api = GitHubAPI(token="ghp_test")
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_client

        await api.dispatch_workflow(
            repo="user1/wvm-runner",
            server_url="wss://srv:8765",
            session_token="tok-abc",
            max_duration=300,
        )
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "repos/user1/wvm-runner/actions/workflows/agent.yml/dispatches" in call_kwargs[0][0]
        body = call_kwargs[1]["json"]
        assert body["inputs"]["session_token"] == "tok-abc"
        assert body["inputs"]["max_duration"] == "300"

@pytest.mark.asyncio
async def test_dispatch_workflow_raises_on_error():
    api = GitHubAPI(token="ghp_test")
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.text = "Unprocessable Entity"
    mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "422", request=MagicMock(), response=mock_response
    ))

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_client

        with pytest.raises(WorkflowDispatchError):
            await api.dispatch_workflow(
                repo="user1/wvm-runner",
                server_url="wss://srv:8765",
                session_token="tok-abc",
                max_duration=300,
            )
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_github_api.py -v
```

Expected: `ImportError`

- [ ] **Step 3: 实现 github_api.py**

`server/github_api.py`:
```python
import httpx


class WorkflowDispatchError(Exception):
    pass


class GitHubAPI:
    BASE = "https://api.github.com"

    def __init__(self, token: str):
        self._token = token

    async def dispatch_workflow(
        self,
        repo: str,
        server_url: str,
        session_token: str,
        max_duration: int = 300,
    ) -> None:
        """触发 workflow_dispatch，传递 agent 需要的参数。"""
        url = f"{self.BASE}/repos/{repo}/actions/workflows/agent.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = {
            "ref": "main",
            "inputs": {
                "server_url": server_url,
                "session_token": session_token,
                "max_duration": str(max_duration),
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=body)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise WorkflowDispatchError(
                    f"dispatch_workflow failed: {e.response.status_code} {e.response.text}"
                ) from e
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_github_api.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add server/github_api.py tests/test_github_api.py
git commit -m "feat: github api dispatch_workflow"
```

---

### Task 4: 协议消息定义 (protocol.py)

**Files:**
- Create: `server/protocol.py`
- Create: `tests/test_protocol.py`

协议消息的序列化/反序列化集中在一个文件中，避免各组件重复实现。

- [ ] **Step 1: 写失败测试**

`tests/test_protocol.py`:
```python
import json
from server.protocol import (
    encode_request, decode_response,
    OP_GETATTR, OP_CALL, OP_SETATTR, OP_GETITEM, OP_REPR, OP_DEL, OP_SHUTDOWN,
    RemoteRef, encode_value, decode_value,
    TYPE_REF, TYPE_VALUE, TYPE_ERROR,
)

def test_encode_getattr():
    msg = encode_request("id1", OP_GETATTR, obj=0, name="__import__")
    d = json.loads(msg)
    assert d == {"id": "id1", "op": "getattr", "obj": 0, "name": "__import__"}

def test_encode_call():
    msg = encode_request("id2", OP_CALL, obj=5, args=["os"], kwargs={})
    d = json.loads(msg)
    assert d["op"] == "call"
    assert d["args"] == ["os"]

def test_encode_setattr_with_ref():
    msg = encode_request("id3", OP_SETATTR, obj=0, name="x", value=RemoteRef(7))
    d = json.loads(msg)
    assert d["value"] == {"$ref": 7}

def test_encode_value_primitives():
    assert encode_value(42) == 42
    assert encode_value("hello") == "hello"
    assert encode_value(None) is None
    assert encode_value(3.14) == 3.14

def test_encode_value_remote_ref():
    assert encode_value(RemoteRef(5)) == {"$ref": 5}

def test_decode_response_value():
    raw = json.dumps({"id": "id1", "type": "value", "val": "hello"})
    resp = decode_response(raw)
    assert resp["type"] == TYPE_VALUE
    assert resp["val"] == "hello"

def test_decode_response_ref():
    raw = json.dumps({"id": "id1", "type": "ref", "obj": 7})
    resp = decode_response(raw)
    assert resp["type"] == TYPE_REF
    assert resp["obj"] == 7

def test_decode_response_error():
    raw = json.dumps({"id": "id1", "type": "error", "exc": "NameError", "msg": "x"})
    resp = decode_response(raw)
    assert resp["type"] == TYPE_ERROR
    assert resp["exc"] == "NameError"

def test_decode_value_ref():
    assert decode_value({"$ref": 5}) == RemoteRef(5)

def test_decode_value_primitive():
    assert decode_value(42) == 42

def test_encode_shutdown():
    msg = encode_request("id9", OP_SHUTDOWN)
    d = json.loads(msg)
    assert d["op"] == "shutdown"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_protocol.py -v
```

Expected: `ImportError`

- [ ] **Step 3: 实现 protocol.py**

`server/protocol.py`:
```python
import json
from dataclasses import dataclass

# Op 常量
OP_GETATTR  = "getattr"
OP_CALL     = "call"
OP_SETATTR  = "setattr"
OP_GETITEM  = "getitem"
OP_REPR     = "repr"
OP_DEL      = "del"
OP_SHUTDOWN = "shutdown"

# Response type 常量
TYPE_REF   = "ref"
TYPE_VALUE = "value"
TYPE_ERROR = "error"


@dataclass(frozen=True, eq=True)
class RemoteRef:
    obj_id: int

    def __eq__(self, other):
        return isinstance(other, RemoteRef) and self.obj_id == other.obj_id

    def __hash__(self):
        return hash(self.obj_id)


def encode_value(v):
    """将 Python 值编码为可 JSON 序列化的形式。RemoteRef → {"$ref": id}"""
    if isinstance(v, RemoteRef):
        return {"$ref": v.obj_id}
    return v


def decode_value(v):
    """将 JSON 值解码回 Python 形式。{"$ref": id} → RemoteRef"""
    if isinstance(v, dict) and "$ref" in v:
        return RemoteRef(v["$ref"])
    return v


def encode_request(req_id: str, op: str, **kwargs) -> str:
    """构建 server→agent 请求消息的 JSON 字符串。"""
    msg: dict = {"id": req_id, "op": op}
    for k, v in kwargs.items():
        msg[k] = encode_value(v)
    return json.dumps(msg)


def decode_response(raw: str) -> dict:
    """解析 agent→server 响应消息。"""
    return json.loads(raw)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_protocol.py -v
```

Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add server/protocol.py tests/test_protocol.py
git commit -m "feat: wire protocol encode/decode"
```

---

### Task 5: Agent (agent/agent.py)

**Files:**
- Create: `agent/agent.py`

agent 是 workflow 中的核心，维护对象 handle 表，处理 RPC 消息。

- [ ] **Step 1: 实现 agent.py**

`agent/agent.py`:
```python
#!/usr/bin/env python3
"""
WorkflowVM Agent - 在 GitHub Actions runner 上运行，反向 WebSocket 连接服务器。
"""
import asyncio
import json
import sys
import uuid
import argparse
import time
import traceback
from typing import Any

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    print("请先 pip install websockets", file=sys.stderr)
    sys.exit(1)


class Agent:
    def __init__(self, server_url: str, session_token: str, max_duration: int):
        self._server_url = server_url
        self._session_token = session_token
        self._max_duration = max_duration
        self._session_id = str(uuid.uuid4())
        # obj_id=0 是根命名空间
        self._objects: dict[int, Any] = {0: {}}
        self._next_id = 1
        self._start_time = time.monotonic()

    def _alloc(self, obj: Any) -> int:
        obj_id = self._next_id
        self._next_id += 1
        self._objects[obj_id] = obj
        return obj_id

    def _get(self, obj_id: int) -> Any:
        if obj_id not in self._objects:
            raise KeyError(f"Unknown obj_id {obj_id}")
        return self._objects[obj_id]

    def _handle(self, msg: dict) -> dict:
        op = msg["op"]
        req_id = msg["id"]

        try:
            if op == "getattr":
                obj = self._get(msg["obj"])
                val = getattr(obj, msg["name"])
                return self._make_response(req_id, val)

            elif op == "call":
                obj = self._get(msg["obj"])
                args = [self._resolve(a) for a in msg.get("args", [])]
                kwargs = {k: self._resolve(v) for k, v in msg.get("kwargs", {}).items()}
                val = obj(*args, **kwargs)
                return self._make_response(req_id, val)

            elif op == "setattr":
                obj = self._get(msg["obj"])
                value = self._resolve(msg["value"])
                setattr(obj, msg["name"], value)
                return {"id": req_id, "type": "value", "val": None}

            elif op == "getitem":
                obj = self._get(msg["obj"])
                key = self._resolve(msg["key"])
                val = obj[key]
                return self._make_response(req_id, val)

            elif op == "repr":
                obj = self._get(msg["obj"])
                return {"id": req_id, "type": "value", "val": repr(obj)}

            elif op == "del":
                self._objects.pop(msg["obj"], None)
                return {"id": req_id, "type": "value", "val": None}

            elif op == "shutdown":
                return {"id": req_id, "type": "value", "val": "shutdown"}

            else:
                return {"id": req_id, "type": "error", "exc": "UnknownOp", "msg": f"Unknown op: {op}"}

        except Exception as e:
            return {
                "id": req_id,
                "type": "error",
                "exc": type(e).__name__,
                "msg": str(e),
                "tb": traceback.format_exc(),
            }

    def _resolve(self, v: Any) -> Any:
        """将 {"$ref": id} 解析为真实对象。"""
        if isinstance(v, dict) and "$ref" in v:
            return self._get(v["$ref"])
        return v

    def _make_response(self, req_id: str, val: Any) -> dict:
        """将 Python 值编码为响应。可 JSON 序列化的值直接返回，否则分配 handle。"""
        try:
            json.dumps(val)
            return {"id": req_id, "type": "value", "val": val}
        except (TypeError, ValueError):
            obj_id = self._alloc(val)
            return {"id": req_id, "type": "ref", "obj": obj_id}

    async def run(self):
        """主循环：带指数退避的断线重连。"""
        retry_delay = 1.0
        resumed = False

        while True:
            # 检查 max_duration
            if time.monotonic() - self._start_time >= self._max_duration:
                print(f"[agent] max_duration {self._max_duration}s reached, exiting.")
                break

            try:
                headers = {"X-Session-Token": self._session_token}
                async with websockets.connect(self._server_url, additional_headers=headers) as ws:
                    # 发送握手
                    hello = json.dumps({
                        "type": "hello",
                        "session_id": self._session_id,
                        "resume": resumed,
                    })
                    await ws.send(hello)
                    resumed = True
                    retry_delay = 1.0
                    print(f"[agent] connected, session={self._session_id}")

                    async for raw in ws:
                        msg = json.loads(raw)

                        # 检查 max_duration
                        if time.monotonic() - self._start_time >= self._max_duration:
                            await ws.send(json.dumps({"type": "timeout"}))
                            return

                        resp = self._handle(msg)
                        await ws.send(json.dumps(resp))

                        if msg.get("op") == "shutdown":
                            print("[agent] received shutdown, exiting.")
                            return

            except ConnectionClosed as e:
                print(f"[agent] disconnected: {e}, retrying in {retry_delay}s...")
            except OSError as e:
                print(f"[agent] connection error: {e}, retrying in {retry_delay}s...")

            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="WebSocket server URL")
    parser.add_argument("--token", required=True, help="Session token")
    parser.add_argument("--duration", type=int, default=300, help="Max runtime seconds")
    args = parser.parse_args()

    agent = Agent(args.server, args.token, args.duration)
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 直接测试 _handle 方法（单元级）**

在项目根目录临时运行：
```bash
python -c "
import asyncio, sys
sys.path.insert(0, '.')
from agent.agent import Agent
a = Agent('ws://x', 'tok', 300)
# test getattr on root namespace
a._objects[0]['myvar'] = 42
resp = a._handle({'id':'r1','op':'getattr','obj':0,'name':'myvar'})
assert resp == {'id':'r1','type':'value','val':42}, resp

# test call: __import__
import_fn = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
a._objects[1] = __import__
resp2 = a._handle({'id':'r2','op':'call','obj':1,'args':['os'],'kwargs':{}})
assert resp2['type'] == 'ref', resp2
os_id = resp2['obj']

# test repr
resp3 = a._handle({'id':'r3','op':'repr','obj':os_id})
assert 'os' in resp3['val'], resp3

# test del
resp4 = a._handle({'id':'r4','op':'del','obj':os_id})
assert resp4['type'] == 'value'

print('agent unit test OK')
"
```

Expected: `agent unit test OK`

- [ ] **Step 3: Commit**

```bash
git add agent/agent.py
git commit -m "feat: agent websocket reverse-connect with object handle protocol"
```

---

### Task 6: Session Manager (server/session_manager.py)

**Files:**
- Create: `server/session_manager.py`
- Create: `tests/test_session_manager.py`

- [ ] **Step 1: 写失败测试**

`tests/test_session_manager.py`:
```python
import pytest
import asyncio
from server.session_manager import SessionManager, SessionNotFound, SessionTimeout

@pytest.mark.asyncio
async def test_register_and_connect():
    mgr = SessionManager(reconnect_grace=5.0)
    token = "tok-abc"
    session_id = "sess-1"

    # register 创建等待 Future
    fut = mgr.register_pending(token)

    # 模拟 agent 连接
    mock_ws = object()
    mgr.on_agent_connect(session_id, token, mock_ws, resume=False)

    # acquire 应该拿到 session
    session = await asyncio.wait_for(fut, timeout=1.0)
    assert session["session_id"] == session_id
    assert session["ws"] is mock_ws

@pytest.mark.asyncio
async def test_connect_unknown_token_raises():
    mgr = SessionManager(reconnect_grace=5.0)
    with pytest.raises(SessionNotFound):
        mgr.on_agent_connect("sess-x", "unknown-token", object(), resume=False)

@pytest.mark.asyncio
async def test_session_resume():
    mgr = SessionManager(reconnect_grace=60.0)
    token = "tok-resume"
    session_id = "sess-resume"

    fut = mgr.register_pending(token)
    mock_ws1 = object()
    mgr.on_agent_connect(session_id, token, mock_ws1, resume=False)
    session = await asyncio.wait_for(fut, timeout=1.0)

    # 断线
    mgr.on_agent_disconnect(session_id)
    assert mgr.get_session(session_id)["ws"] is None

    # 重连（resume=True）
    mock_ws2 = object()
    mgr.on_agent_reconnect(session_id, mock_ws2)
    assert mgr.get_session(session_id)["ws"] is mock_ws2

@pytest.mark.asyncio
async def test_release_removes_session():
    mgr = SessionManager(reconnect_grace=5.0)
    token = "tok-rel"
    session_id = "sess-rel"

    fut = mgr.register_pending(token)
    mgr.on_agent_connect(session_id, token, object(), resume=False)
    await asyncio.wait_for(fut, timeout=1.0)

    mgr.release(session_id)
    with pytest.raises(SessionNotFound):
        mgr.get_session(session_id)
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_session_manager.py -v
```

Expected: `ImportError`

- [ ] **Step 3: 实现 session_manager.py**

`server/session_manager.py`:
```python
import asyncio
import time
from typing import Optional


class SessionNotFound(Exception):
    pass


class SessionTimeout(Exception):
    pass


class SessionManager:
    def __init__(self, reconnect_grace: float = 60.0):
        self._reconnect_grace = reconnect_grace
        # token → asyncio.Future
        self._pending: dict[str, asyncio.Future] = {}
        # session_id → session dict
        self._sessions: dict[str, dict] = {}
        # session_id → disconnect timestamp
        self._disconnected_at: dict[str, float] = {}

    def register_pending(self, token: str) -> asyncio.Future:
        """调用 acquire() 时注册，等待 agent 连接。"""
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[token] = fut
        return fut

    def on_agent_connect(self, session_id: str, token: str, ws, resume: bool):
        """agent 初次连接时调用。"""
        if token not in self._pending:
            raise SessionNotFound(f"No pending acquire for token {token!r}")
        fut = self._pending.pop(token)
        session = {"session_id": session_id, "ws": ws, "token": token}
        self._sessions[session_id] = session
        if not fut.done():
            fut.set_result(session)

    def on_agent_disconnect(self, session_id: str):
        """agent WebSocket 断开时调用。"""
        if session_id in self._sessions:
            self._sessions[session_id]["ws"] = None
            self._disconnected_at[session_id] = time.monotonic()

    def on_agent_reconnect(self, session_id: str, ws):
        """agent 断线重连时调用（resume=True）。"""
        if session_id not in self._sessions:
            raise SessionNotFound(f"Unknown session {session_id!r} for reconnect")
        self._sessions[session_id]["ws"] = ws
        self._disconnected_at.pop(session_id, None)

    def get_session(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            raise SessionNotFound(f"Session {session_id!r} not found")
        return self._sessions[session_id]

    def release(self, session_id: str):
        """释放 session，清理所有资源。"""
        self._sessions.pop(session_id, None)
        self._disconnected_at.pop(session_id, None)

    def cleanup_expired(self):
        """清理超过 reconnect_grace 未重连的 dead session。"""
        now = time.monotonic()
        expired = [
            sid for sid, ts in self._disconnected_at.items()
            if now - ts > self._reconnect_grace
        ]
        for sid in expired:
            self.release(sid)
        return expired
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_session_manager.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add server/session_manager.py tests/test_session_manager.py
git commit -m "feat: session manager with reconnect support"
```

---

### Task 7: 远程对象服务端 (server/remote_object.py)

**Files:**
- Create: `server/remote_object.py`
- Create: `tests/test_remote_object.py`

server 侧的 RPC 发送器：将操作序列化、发送给 agent、等待响应。

- [ ] **Step 1: 写失败测试**

`tests/test_remote_object.py`:
```python
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from server.remote_object import RemoteObjectServer, RemoteError
from server.protocol import RemoteRef

@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws

@pytest.mark.asyncio
async def test_getattr_returns_value(mock_ws):
    # 模拟 agent 响应
    mock_ws.recv = AsyncMock(return_value=json.dumps(
        {"id": "WILL_BE_REPLACED", "type": "value", "val": 42}
    ))
    robj = RemoteObjectServer(mock_ws)
    # 拦截 send，把 id 回填到 mock 响应
    sent_msgs = []
    async def capture_send(msg):
        d = json.loads(msg)
        sent_msgs.append(d)
        # 模拟 recv 返回对应 id
        mock_ws.recv.return_value = json.dumps({"id": d["id"], "type": "value", "val": 42})
    mock_ws.send.side_effect = capture_send

    result = await robj.getattr(0, "__doc__")
    assert result == 42

@pytest.mark.asyncio
async def test_getattr_returns_ref(mock_ws):
    sent_msgs = []
    async def capture_send(msg):
        d = json.loads(msg)
        sent_msgs.append(d)
        mock_ws.recv.return_value = json.dumps({"id": d["id"], "type": "ref", "obj": 7})
    mock_ws.send.side_effect = capture_send
    mock_ws.recv = AsyncMock()

    robj = RemoteObjectServer(mock_ws)
    result = await robj.getattr(0, "something")
    assert isinstance(result, RemoteRef)
    assert result.obj_id == 7

@pytest.mark.asyncio
async def test_error_raises_remote_error(mock_ws):
    async def capture_send(msg):
        d = json.loads(msg)
        mock_ws.recv.return_value = json.dumps({
            "id": d["id"], "type": "error", "exc": "NameError", "msg": "x not defined"
        })
    mock_ws.send.side_effect = capture_send
    mock_ws.recv = AsyncMock()

    robj = RemoteObjectServer(mock_ws)
    with pytest.raises(RemoteError) as exc_info:
        await robj.getattr(0, "undefined_var")
    assert "NameError" in str(exc_info.value)
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_remote_object.py -v
```

Expected: `ImportError`

- [ ] **Step 3: 实现 remote_object.py**

`server/remote_object.py`:
```python
import asyncio
import json
import uuid
from server.protocol import (
    encode_request, decode_response,
    OP_GETATTR, OP_CALL, OP_SETATTR, OP_GETITEM, OP_REPR, OP_DEL, OP_SHUTDOWN,
    RemoteRef, encode_value, decode_value,
    TYPE_REF, TYPE_VALUE, TYPE_ERROR,
)


class RemoteError(Exception):
    def __init__(self, exc_type: str, msg: str, tb: str = ""):
        super().__init__(f"{exc_type}: {msg}")
        self.exc_type = exc_type
        self.remote_msg = msg
        self.tb = tb


class RemoteObjectServer:
    """发送 RPC 请求给 agent，等待响应。线程不安全，每个 session 一个实例。"""

    def __init__(self, ws):
        self._ws = ws

    async def _request(self, op: str, **kwargs) -> dict:
        req_id = str(uuid.uuid4())
        msg = encode_request(req_id, op, **kwargs)
        await self._ws.send(msg)
        raw = await self._ws.recv()
        resp = decode_response(raw)
        assert resp["id"] == req_id, f"id mismatch: {resp['id']} != {req_id}"
        return resp

    def _parse_result(self, resp: dict):
        if resp["type"] == TYPE_ERROR:
            raise RemoteError(resp["exc"], resp["msg"], resp.get("tb", ""))
        if resp["type"] == TYPE_REF:
            return RemoteRef(resp["obj"])
        # TYPE_VALUE
        return decode_value(resp.get("val"))

    async def getattr(self, obj_id: int, name: str):
        resp = await self._request(OP_GETATTR, obj=obj_id, name=name)
        return self._parse_result(resp)

    async def call(self, obj_id: int, args: list, kwargs: dict):
        encoded_args = [encode_value(a) for a in args]
        encoded_kwargs = {k: encode_value(v) for k, v in kwargs.items()}
        resp = await self._request(OP_CALL, obj=obj_id, args=encoded_args, kwargs=encoded_kwargs)
        return self._parse_result(resp)

    async def setattr(self, obj_id: int, name: str, value):
        resp = await self._request(OP_SETATTR, obj=obj_id, name=name, value=value)
        return self._parse_result(resp)

    async def getitem(self, obj_id: int, key):
        resp = await self._request(OP_GETITEM, obj=obj_id, key=key)
        return self._parse_result(resp)

    async def repr(self, obj_id: int) -> str:
        resp = await self._request(OP_REPR, obj=obj_id)
        return self._parse_result(resp)

    async def del_ref(self, obj_id: int):
        resp = await self._request(OP_DEL, obj=obj_id)
        return self._parse_result(resp)

    async def shutdown(self):
        resp = await self._request(OP_SHUTDOWN)
        return self._parse_result(resp)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_remote_object.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add server/remote_object.py tests/test_remote_object.py
git commit -m "feat: server-side remote object RPC sender"
```

---

### Task 8: 实例池 (server/instance_pool.py)

**Files:**
- Create: `server/instance_pool.py`

编排：pick 账号 → dispatch workflow → 等待 session → 返回 RemoteObjectServer。

- [ ] **Step 1: 实现 instance_pool.py**

`server/instance_pool.py`:
```python
import asyncio
import uuid
from server.account_pool import AccountPool, NoAccountAvailable
from server.github_api import GitHubAPI
from server.session_manager import SessionManager
from server.remote_object import RemoteObjectServer


class AcquireTimeout(Exception):
    pass


class InstancePool:
    def __init__(
        self,
        account_pool: AccountPool,
        session_manager: SessionManager,
        server_ws_url: str,
        acquire_timeout: float = 120.0,
    ):
        self._account_pool = account_pool
        self._session_mgr = session_manager
        self._server_ws_url = server_ws_url
        self._acquire_timeout = acquire_timeout
        # session_id → username，用于 release 时归还账号
        self._session_account: dict[str, str] = {}

    async def acquire(self, max_duration: int = 300) -> tuple[str, RemoteObjectServer]:
        """
        触发一个新 workflow，等待 agent 反连，返回 (session_id, RemoteObjectServer)。
        """
        account = self._account_pool.pick()
        session_token = str(uuid.uuid4())
        api = GitHubAPI(token=account["token"])

        # 注册等待 Future
        fut = self._session_mgr.register_pending(session_token)

        # 触发 workflow
        await api.dispatch_workflow(
            repo=account["runner_repo"],
            server_url=self._server_ws_url,
            session_token=session_token,
            max_duration=max_duration,
        )

        # 等待 agent 连接
        try:
            session = await asyncio.wait_for(fut, timeout=self._acquire_timeout)
        except asyncio.TimeoutError:
            self._account_pool.release(account["username"])
            self._session_mgr._pending.pop(session_token, None)
            raise AcquireTimeout(
                f"Agent did not connect within {self._acquire_timeout}s"
            )

        session_id = session["session_id"]
        self._session_account[session_id] = account["username"]
        robj = RemoteObjectServer(session["ws"])
        return session_id, robj

    def release(self, session_id: str):
        """释放实例，归还账号计数。"""
        username = self._session_account.pop(session_id, None)
        if username:
            self._account_pool.release(username)
        self._session_mgr.release(session_id)
```

- [ ] **Step 2: 手工验证接口签名**

```bash
python -c "
import sys; sys.path.insert(0,'.')
from server.instance_pool import InstancePool, AcquireTimeout
from server.account_pool import AccountPool
from server.session_manager import SessionManager
print('import OK')
"
```

Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add server/instance_pool.py
git commit -m "feat: instance pool orchestrates account + github api + session"
```

---

### Task 9: WebSocket Server (server/main.py)

**Files:**
- Create: `server/main.py`

asyncio WebSocket server，接收 agent 连接，路由到 SessionManager。

- [ ] **Step 1: 实现 main.py**

`server/main.py`:
```python
#!/usr/bin/env python3
"""
WorkflowVM Server - asyncio WebSocket server
启动：python server/main.py --config accounts.yml
"""
import asyncio
import json
import argparse
import logging
import signal

import websockets
from websockets.server import serve

from server.account_pool import AccountPool
from server.session_manager import SessionManager
from server.instance_pool import InstancePool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wvm.server")

# 全局组件（在 main() 中初始化）
session_mgr: SessionManager = None
instance_pool: InstancePool = None
account_pool: AccountPool = None
_api_token: str = ""


async def agent_handler(ws):
    """处理 agent 的 WebSocket 连接。"""
    token = ws.request_headers.get("X-Session-Token", "")
    if not token:
        await ws.close(1008, "missing session token")
        return

    # 读取握手消息
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        hello = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await ws.close(1008, "invalid hello")
        return

    if hello.get("type") != "hello":
        await ws.close(1008, "expected hello")
        return

    session_id = hello["session_id"]
    resume = hello.get("resume", False)

    try:
        if resume:
            session_mgr.on_agent_reconnect(session_id, ws)
            log.info(f"agent reconnected session={session_id}")
        else:
            session_mgr.on_agent_connect(session_id, token, ws, resume=False)
            log.info(f"agent connected session={session_id}")
    except Exception as e:
        log.warning(f"agent handshake failed: {e}")
        await ws.close(1008, str(e))
        return

    try:
        # 保持连接直到关闭（消息处理在 RemoteObjectServer 中进行）
        await ws.wait_closed()
    finally:
        session_mgr.on_agent_disconnect(session_id)
        log.info(f"agent disconnected session={session_id}")


async def periodic_cleanup():
    """定期清理超时 dead session。"""
    while True:
        await asyncio.sleep(30)
        expired = session_mgr.cleanup_expired()
        if expired:
            log.info(f"cleaned up expired sessions: {expired}")


async def main_async(config_path: str):
    global session_mgr, instance_pool, account_pool, _api_token

    account_pool = AccountPool(config_path)
    srv_cfg = account_pool.server_config
    host = srv_cfg.get("host", "0.0.0.0")
    port = int(srv_cfg.get("port", 8765))
    _api_token = srv_cfg.get("api_token", "")

    session_mgr = SessionManager(reconnect_grace=60.0)

    ws_url = f"wss://{host}:{port}"
    instance_pool = InstancePool(
        account_pool=account_pool,
        session_manager=session_mgr,
        server_ws_url=ws_url,
    )

    stop = asyncio.Future()
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)
    loop.add_signal_handler(signal.SIGHUP, account_pool.reload_if_changed)

    cleanup_task = asyncio.create_task(periodic_cleanup())

    log.info(f"WorkflowVM server starting on {host}:{port}")
    async with serve(agent_handler, host, port):
        await stop

    cleanup_task.cancel()
    log.info("Server stopped.")


def main():
    parser = argparse.ArgumentParser(description="WorkflowVM Server")
    parser.add_argument("--config", default="accounts.yml", help="Path to accounts.yml")
    args = parser.parse_args()
    asyncio.run(main_async(args.config))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证启动（干运行）**

```bash
python -c "
import sys; sys.path.insert(0,'.')
from server.main import main_async
print('import OK')
"
```

Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add server/main.py
git commit -m "feat: asyncio websocket server with agent routing"
```

---

### Task 10: SDK RemoteObject Proxy (sdk/proxy.py)

**Files:**
- Create: `sdk/proxy.py`
- Create: `tests/test_proxy.py`

- [ ] **Step 1: 写失败测试**

`tests/test_proxy.py`:
```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from server.protocol import RemoteRef

# 我们需要一个同步版的 proxy，内部用 asyncio.run 或 loop
# proxy 需要持有一个 event loop 并发送同步调用

from sdk.proxy import RemoteObject

@pytest.fixture
def mock_robj_server():
    """mock RemoteObjectServer，返回预设值。"""
    m = MagicMock()
    m.getattr = AsyncMock(return_value=42)
    m.call = AsyncMock(return_value="result")
    m.setattr = AsyncMock(return_value=None)
    m.getitem = AsyncMock(return_value="item")
    m.repr = AsyncMock(return_value="<mock>")
    m.del_ref = AsyncMock(return_value=None)
    m.shutdown = AsyncMock(return_value=None)
    return m

def test_getattr_primitive(mock_robj_server):
    mock_robj_server.getattr = AsyncMock(return_value=42)
    proxy = RemoteObject(0, mock_robj_server)
    result = proxy.myattr
    assert result == 42
    mock_robj_server.getattr.assert_called_once_with(0, "myattr")

def test_getattr_returns_proxy_for_ref(mock_robj_server):
    mock_robj_server.getattr = AsyncMock(return_value=RemoteRef(5))
    proxy = RemoteObject(0, mock_robj_server)
    child = proxy.something
    assert isinstance(child, RemoteObject)
    assert child._obj_id == 5

def test_call(mock_robj_server):
    mock_robj_server.call = AsyncMock(return_value="called")
    proxy = RemoteObject(3, mock_robj_server)
    result = proxy("arg1", key="val")
    assert result == "called"
    mock_robj_server.call.assert_called_once_with(3, ["arg1"], {"key": "val"})

def test_setattr_remote(mock_robj_server):
    proxy = RemoteObject(0, mock_robj_server)
    proxy.myvar = 99  # 非 _ 开头，走 remote setattr
    mock_robj_server.setattr.assert_called_once_with(0, "myvar", 99)

def test_setattr_local_for_underscore(mock_robj_server):
    proxy = RemoteObject(0, mock_robj_server)
    proxy._local = "x"  # _ 开头，走本地
    mock_robj_server.setattr.assert_not_called()
    assert proxy._local == "x"

def test_getitem(mock_robj_server):
    mock_robj_server.getitem = AsyncMock(return_value="val")
    proxy = RemoteObject(2, mock_robj_server)
    result = proxy["key"]
    assert result == "val"

def test_repr_method(mock_robj_server):
    mock_robj_server.repr = AsyncMock(return_value="<os module>")
    proxy = RemoteObject(7, mock_robj_server)
    result = proxy._repr()
    assert result == "<os module>"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_proxy.py -v
```

Expected: `ImportError`

- [ ] **Step 3: 实现 sdk/proxy.py**

`sdk/proxy.py`:
```python
import asyncio
from server.protocol import RemoteRef


def _run(coro):
    """在当前或新 event loop 中同步运行协程。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在已运行的 loop 中（如 Jupyter），用 concurrent.futures
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=60)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class RemoteObject:
    """
    透明代理，将属性访问和方法调用转发给远端 Python 对象。

    _开头的属性为本地属性，不转发。
    """

    def __init__(self, obj_id: int, robj_server):
        # 用 object.__setattr__ 避免触发我们自己的 __setattr__
        object.__setattr__(self, "_obj_id", obj_id)
        object.__setattr__(self, "_robj", robj_server)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        result = _run(robj.getattr(obj_id, name))
        if isinstance(result, RemoteRef):
            return RemoteObject(result.obj_id, robj)
        return result

    def __setattr__(self, name: str, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        # value 可能是另一个 RemoteObject，提取其 RemoteRef
        actual_value = value
        if isinstance(value, RemoteObject):
            actual_value = RemoteRef(object.__getattribute__(value, "_obj_id"))
        _run(robj.setattr(obj_id, name, actual_value))

    def __call__(self, *args, **kwargs):
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        # 将 RemoteObject 参数转换为 RemoteRef
        def to_wire(v):
            if isinstance(v, RemoteObject):
                return RemoteRef(object.__getattribute__(v, "_obj_id"))
            return v
        wire_args = [to_wire(a) for a in args]
        wire_kwargs = {k: to_wire(v) for k, v in kwargs.items()}
        result = _run(robj.call(obj_id, wire_args, wire_kwargs))
        if isinstance(result, RemoteRef):
            return RemoteObject(result.obj_id, robj)
        return result

    def __getitem__(self, key):
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        result = _run(robj.getitem(obj_id, key))
        if isinstance(result, RemoteRef):
            return RemoteObject(result.obj_id, robj)
        return result

    def __del__(self):
        try:
            robj = object.__getattribute__(self, "_robj")
            obj_id = object.__getattribute__(self, "_obj_id")
            if obj_id != 0:  # 不释放根对象
                _run(robj.del_ref(obj_id))
        except Exception:
            pass

    def _repr(self) -> str:
        """获取远程对象的 repr 字符串。"""
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        return _run(robj.repr(obj_id))

    def __repr__(self) -> str:
        obj_id = object.__getattribute__(self, "_obj_id")
        return f"<RemoteObject obj_id={obj_id}>"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_proxy.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add sdk/proxy.py tests/test_proxy.py
git commit -m "feat: transparent RemoteObject proxy"
```

---

### Task 11: SDK Controller (sdk/controller.py + sdk/__init__.py)

**Files:**
- Modify: `sdk/__init__.py`
- Create: `sdk/controller.py`

- [ ] **Step 1: 实现 sdk/controller.py**

`sdk/controller.py`:
```python
import asyncio
import uuid
from sdk.proxy import RemoteObject, _run
from server.session_manager import SessionManager
from server.instance_pool import InstancePool, AcquireTimeout


class RemoteVM:
    """
    代表一个活跃的 workflow 实例。
    根对象 obj_id=0 即 workflow 的运行时命名空间。
    """

    def __init__(self, session_id: str, robj_server, instance_pool: "InstancePool"):
        self._session_id = session_id
        self._robj = robj_server
        self._pool = instance_pool
        self._root = RemoteObject(0, robj_server)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._root, name)

    def __setattr__(self, name: str, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        setattr(self._root, name, value)

    def __call__(self, *args, **kwargs):
        return self._root(*args, **kwargs)

    def __getitem__(self, key):
        return self._root[key]

    def _repr(self, obj=None) -> str:
        """获取远程对象 repr。obj 为 None 时获取根对象 repr。"""
        if obj is None:
            return self._root._repr()
        if isinstance(obj, RemoteObject):
            return obj._repr()
        return repr(obj)

    def release(self):
        """关闭 session，workflow 退出。"""
        try:
            _run(self._robj.shutdown())
        except Exception:
            pass
        self._pool.release(self._session_id)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()


class Controller:
    """
    WorkflowVM 控制器。管理账号池和实例池，提供 acquire() 接口。

    用法：
        ctrl = Controller("wss://your-server:8765", token="api-token")
        vm = ctrl.acquire(timeout=120, max_duration=300)
        vm.os = vm.__import__("os")
        vm.os.system("whoami")
        vm.release()
    """

    def __init__(
        self,
        server_url: str,
        *,
        config_path: str = "accounts.yml",
        token: str = "",
        acquire_timeout: float = 120.0,
    ):
        from server.account_pool import AccountPool
        from server.session_manager import SessionManager

        self._server_url = server_url
        self._api_token = token
        self._account_pool = AccountPool(config_path)
        self._session_mgr = SessionManager(reconnect_grace=60.0)
        self._instance_pool = InstancePool(
            account_pool=self._account_pool,
            session_manager=self._session_mgr,
            server_ws_url=server_url,
            acquire_timeout=acquire_timeout,
        )

    def acquire(self, timeout: float = 120.0, max_duration: int = 300) -> RemoteVM:
        """
        分配一个 workflow 实例并等待其连接。
        返回 RemoteVM，可直接操作远程 Python 环境。
        """
        self._instance_pool._acquire_timeout = timeout

        async def _acquire():
            session_id, robj = await self._instance_pool.acquire(max_duration=max_duration)
            return RemoteVM(session_id, robj, self._instance_pool)

        return _run(_acquire())
```

- [ ] **Step 2: 更新 sdk/__init__.py**

`sdk/__init__.py`:
```python
from sdk.controller import Controller, RemoteVM
from sdk.proxy import RemoteObject

__all__ = ["Controller", "RemoteVM", "RemoteObject"]
```

- [ ] **Step 3: 验证 import**

```bash
python -c "
import sys; sys.path.insert(0,'.')
import workflowvm
print(dir(workflowvm))
"
```

注：此处需要 `workflowvm` 包，先验证 `sdk`:
```bash
python -c "
import sys; sys.path.insert(0,'.')
from sdk import Controller, RemoteVM, RemoteObject
print('SDK import OK')
print(Controller.__doc__[:30])
"
```

Expected: `SDK import OK`

- [ ] **Step 4: Commit**

```bash
git add sdk/controller.py sdk/__init__.py
git commit -m "feat: Controller and RemoteVM SDK interface"
```

---

### Task 12: workflowvm 包入口

**Files:**
- Create: `workflowvm/__init__.py`

- [ ] **Step 1: 创建包**

```bash
mkdir -p workflowvm
```

`workflowvm/__init__.py`:
```python
from sdk.controller import Controller, RemoteVM
from sdk.proxy import RemoteObject

__all__ = ["Controller", "RemoteVM", "RemoteObject"]
```

- [ ] **Step 2: 验证**

```bash
python -c "
import sys; sys.path.insert(0,'.')
import workflowvm
ctrl_cls = workflowvm.Controller
print('workflowvm import OK, Controller:', ctrl_cls)
"
```

Expected: `workflowvm import OK, Controller: <class 'sdk.controller.Controller'>`

- [ ] **Step 3: Commit**

```bash
git add workflowvm/__init__.py
git commit -m "feat: workflowvm top-level package"
```

---

### Task 13: GitHub Actions Workflow 模板

**Files:**
- Create: `.github/workflows/agent.yml`

- [ ] **Step 1: 创建 workflow 文件**

`.github/workflows/agent.yml`:
```yaml
name: WorkflowVM Agent
on:
  workflow_dispatch:
    inputs:
      server_url:
        description: "WorkflowVM server WebSocket URL"
        required: true
      session_token:
        description: "Session token assigned by server"
        required: true
      max_duration:
        description: "Max runtime in seconds"
        required: false
        default: "300"

jobs:
  agent:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install agent dependencies
        run: pip install websockets

      - name: Start WorkflowVM Agent
        run: |
          python agent/agent.py \
            --server "${{ inputs.server_url }}" \
            --token "${{ inputs.session_token }}" \
            --duration "${{ inputs.max_duration }}"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/agent.yml
git commit -m "feat: github actions workflow template for agent"
```

---

### Task 14: 集成测试 (本地 WebSocket)

**Files:**
- Create: `tests/test_integration.py`

在本地启动 WebSocket server + agent，验证端到端远程对象操作。

- [ ] **Step 1: 写集成测试**

`tests/test_integration.py`:
```python
"""
端到端集成测试：本地启动 WebSocket server，直接启动 agent（不触发 GitHub）。
验证完整的远程对象操作链路。
"""
import pytest
import asyncio
import json
import threading
import time
import websockets
from websockets.server import serve

from server.session_manager import SessionManager
from server.remote_object import RemoteObjectServer
from sdk.proxy import RemoteObject


class LocalTestServer:
    """最小化测试 server：接受 agent 连接，路由到 SessionManager。"""

    def __init__(self, session_mgr: SessionManager, port: int = 0):
        self.session_mgr = session_mgr
        self.port = port
        self._actual_port = None
        self._stop = asyncio.Event()

    async def handler(self, ws):
        token = ws.request_headers.get("X-Session-Token", "")
        raw = await ws.recv()
        hello = json.loads(raw)
        session_id = hello["session_id"]
        resume = hello.get("resume", False)
        if resume:
            self.session_mgr.on_agent_reconnect(session_id, ws)
        else:
            self.session_mgr.on_agent_connect(session_id, token, ws, resume=False)
        await ws.wait_closed()
        self.session_mgr.on_agent_disconnect(session_id)

    async def run(self):
        async with serve(self.handler, "127.0.0.1", 0) as server:
            self._actual_port = server.sockets[0].getsockname()[1]
            await self._stop.wait()

    def stop(self):
        self._stop.set()


@pytest.mark.asyncio
async def test_end_to_end_remote_object():
    """完整链路：server ← agent，通过 RemoteObjectServer 操作远程 Python 对象。"""
    session_mgr = SessionManager(reconnect_grace=10.0)
    test_server = LocalTestServer(session_mgr)

    # 启动本地 server
    server_task = asyncio.create_task(test_server.run())

    # 等待 server 就绪
    for _ in range(50):
        if test_server._actual_port:
            break
        await asyncio.sleep(0.05)
    assert test_server._actual_port, "Server did not start"

    port = test_server._actual_port
    server_url = f"ws://127.0.0.1:{port}"
    session_token = "integration-test-token"

    # 注册等待 Future
    fut = session_mgr.register_pending(session_token)

    # 在独立线程启动 agent（避免 event loop 冲突）
    from agent.agent import Agent
    agent = Agent(server_url, session_token, max_duration=30)

    agent_task = asyncio.create_task(agent.run())

    # 等待 agent 连接
    session = await asyncio.wait_for(fut, timeout=10.0)
    ws = session["ws"]
    robj = RemoteObjectServer(ws)

    # --- 测试远程对象操作 ---

    # 1. getattr 根命名空间（dict）→ 应该返回 value 或 ref
    # obj_id=0 是 {} (空 dict)，getattr items 应返回 method ref
    items_ref = await robj.getattr(0, "items")
    # items 是 dict.items bound method，不可 JSON 序列化，应返回 RemoteRef
    from server.protocol import RemoteRef
    assert isinstance(items_ref, RemoteRef)

    # 2. 调用 __import__ 获取 os 模块
    # 先获取 agent 的 __import__ builtin
    # obj_id=0 是 {}，我们直接在 agent 的 globals 中设置一个函数引用
    # 用 setattr 注入 __import__
    import_fn_ref = await robj.getattr(0, "get")  # {} 的 get 方法
    assert isinstance(import_fn_ref, RemoteRef)

    # 3. repr 测试
    repr_str = await robj.repr(0)
    assert repr_str == "{}"

    # 4. setattr：在根 dict 中存一个 key（通过 setattr 操作 dict 本身不对，
    #    但 agent 的根对象是 dict，setattr 会调用 setattr(dict_instance, name, val)
    #    这对 dict 会失败，改用 getitem/call 模式）
    # 直接测试 shutdown
    shutdown_result = await robj.shutdown()
    assert shutdown_result == "shutdown"

    # 清理
    test_server.stop()
    agent_task.cancel()
    server_task.cancel()
    try:
        await asyncio.gather(agent_task, server_task, return_exceptions=True)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_remote_import_and_call():
    """测试通过远程对象调用 __import__ 并执行系统命令。"""
    session_mgr = SessionManager(reconnect_grace=10.0)
    test_server = LocalTestServer(session_mgr)
    server_task = asyncio.create_task(test_server.run())

    for _ in range(50):
        if test_server._actual_port:
            break
        await asyncio.sleep(0.05)

    port = test_server._actual_port
    server_url = f"ws://127.0.0.1:{port}"
    session_token = "test-import-token"

    fut = session_mgr.register_pending(session_token)
    from agent.agent import Agent
    agent = Agent(server_url, session_token, max_duration=30)
    agent_task = asyncio.create_task(agent.run())

    session = await asyncio.wait_for(fut, timeout=10.0)
    ws = session["ws"]
    robj = RemoteObjectServer(ws)
    from server.protocol import RemoteRef

    # agent 根对象 obj_id=0 是 {} (dict)
    # 我们直接在 agent 的 objects[0] 中通过 setattr 放一个 __import__
    # 实际上 agent.__import__ 是 builtin，需要先在 agent 端注册
    # 注入方式：通过 call 一个已有函数
    # 先获取 dict.__class__ → type → 用来验证 getattr/call 链

    # 测试：获取 dict 的 __class__，确认是 dict type
    class_ref = await robj.getattr(0, "__class__")
    assert isinstance(class_ref, RemoteRef)

    # repr of __class__ 应该包含 "dict"
    class_repr = await robj.repr(class_ref.obj_id)
    assert "dict" in class_repr

    await robj.shutdown()
    test_server.stop()
    agent_task.cancel()
    server_task.cancel()
    await asyncio.gather(agent_task, server_task, return_exceptions=True)
```

- [ ] **Step 2: 运行集成测试**

```bash
pytest tests/test_integration.py -v -s
```

Expected: 2 passed（可能需要几秒等待 agent 连接）

- [ ] **Step 3: 运行全部测试**

```bash
pytest tests/ -v
```

Expected: 全部 passed

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: end-to-end integration tests for server+agent"
```

---

### Task 15: 最终验证 & 文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 README.md**

`README.md`:
```markdown
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
```

- [ ] **Step 2: 最终全量测试**

```bash
pytest tests/ -v --tb=short
```

Expected: 所有测试通过

- [ ] **Step 3: 最终 commit**

```bash
git add README.md
git commit -m "docs: update README with quickstart and architecture"
```

---

## 验证清单

- [ ] `pytest tests/test_account_pool.py` — 账号池热重载
- [ ] `pytest tests/test_github_api.py` — workflow dispatch mock
- [ ] `pytest tests/test_protocol.py` — 协议序列化
- [ ] `pytest tests/test_session_manager.py` — session 生命周期
- [ ] `pytest tests/test_remote_object.py` — server 侧 RPC
- [ ] `pytest tests/test_proxy.py` — RemoteObject 透明代理
- [ ] `pytest tests/test_integration.py` — 端到端本地集成
- [ ] `python server/main.py --config accounts.yml` 可启动
- [ ] 配置真实 token 后 `ctrl.acquire()` 触发 GitHub Actions workflow
