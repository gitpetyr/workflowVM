# rpyc 架构重设计

**日期：** 2026-04-10  
**状态：** 已实现（2026-04-10，commit 808c814）  
**背景：** 当前手搓的自定义 WebSocket 协议无法透明代理 Python dunder 协议（上下文管理器、迭代器、运算符等），健壮性不足。用 rpyc 替换协议层，彻底解决这类问题。

---

## 目标

用 rpyc classic 模式替换当前自定义 RPC 协议，使 SDK 客户端通过 rpyc NetRef 透明访问远端 Python 环境，所有 Python 协议（`with`、`for`、运算符、`len()`、`bool()` 等）自动支持。

## 架构概览

```
SDK client ─── WebSocket ──→ Server ─── WebSocket ──→ Agent
              (acquire协商)   (字节隧道)              (rpyc classic server)
                        ←─── rpyc 协议字节流 ─────────
```

Server 只负责协商阶段（acquire → acquiring → acquired），之后变成纯字节隧道转发，不再理解协议内容。rpyc 协议端到端运行在 SDK 和 Agent 之间。

## 用户侧 API

```python
ctrl = Controller("wss://server:8765", token="xxx")
conn = ctrl.acquire()          # 返回 rpyc.Connection

# 访问远端模块
os = conn.modules.os
os.system("whoami")

# 上下文管理器（自动透明）
camoufox = conn.modules.camoufox
with camoufox.SyncCamoufox() as browser:
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())

# async 函数（如需要）
async_fn = rpyc.async_(browser.some_async_method)
result = async_fn()
result.wait()
value = result.value

conn.close()
```

## 文件变更

| 操作 | 文件 |
|---|---|
| 删除 | `workflowvm/server/protocol.py` |
| 删除 | `workflowvm/server/remote_object.py` |
| 删除 | `workflowvm/sdk/proxy.py` |
| 大幅重写 | `workflowvm/agent/agent.py` |
| 大幅重写 | `workflowvm/sdk/controller.py` |
| 简化 | `workflowvm/server/main.py` |
| 新增 | `workflowvm/sdk/stream.py` |
| 不动 | `server/account_pool.py` / `session_manager.py` / `github_api.py` / `account_setup.py` / `cli/` |

## 详细设计

### 1. WebSocket → rpyc Stream 桥接（`sdk/stream.py`）

rpyc 使用阻塞 I/O，WebSocket 使用 async I/O。用线程 + Queue 桥接，agent 和 SDK 共用同一模块。

```python
class WebSocketStream:
    def __init__(self, ws, loop):
        self._ws = ws
        self._loop = loop
        self._recv_queue = queue.Queue()
        self._buf = b""

    def read(self, n):
        while len(self._buf) < n:
            chunk = self._recv_queue.get()
            if chunk is None:      # 哨兵：连接关闭
                raise EOFError("WebSocket closed")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def write(self, data):
        asyncio.run_coroutine_threadsafe(
            self._ws.send(data), self._loop
        ).result()

    def close(self):
        self._recv_queue.put(None)
        asyncio.run_coroutine_threadsafe(
            self._ws.close(), self._loop
        ).result()


async def feed_loop(ws, stream):
    """将 WebSocket 收到的消息放入 stream 队列。"""
    try:
        async for msg in ws:
            data = msg if isinstance(msg, bytes) else msg.encode()
            stream._recv_queue.put(data)
    except Exception:
        pass
    finally:
        stream._recv_queue.put(None)
```

### 2. Agent 端（`agent/agent.py`）

删除所有自定义协议处理（`_objects`、`_handle`、`_make_response` 等），改为启动 rpyc classic server。

```python
async def run(self):
    retry_delay = 1.0
    resumed = False

    while True:
        if time.monotonic() - self._start_time >= self._max_duration:
            break

        try:
            async with websockets.connect(self._server_url, additional_headers=headers) as ws:
                await ws.send(json.dumps({
                    "type": "hello",
                    "session_id": self._session_id,
                    "resume": resumed,
                }))
                resumed = True
                retry_delay = 1.0

                loop = asyncio.get_event_loop()
                stream = WebSocketStream(ws, loop)
                feed_task = asyncio.create_task(feed_loop(ws, stream))

                def serve():
                    conn = rpyc.classic.connect_stream(stream)
                    conn.serve_all()

                await asyncio.to_thread(serve)
                feed_task.cancel()

        except ConnectionClosed as e:
            if e.rcvd and e.rcvd.code == 1008:
                return
            ...

        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 30.0)
```

### 3. Server 端（`server/main.py`）

握手阶段不变。握手完成后，`_handle_sdk_client` 改为纯字节隧道：

```python
async def forward(src, dst):
    try:
        async for msg in src:
            await dst.send(msg)
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            await dst.close(1001, "peer disconnected")

await asyncio.gather(
    forward(ws, agent_ws),
    forward(agent_ws, ws),
    return_exceptions=True,
)
```

删除 `session_id` 从 `acquired` 消息中传出（客户端不再需要）。

### 4. SDK 端（`sdk/controller.py`）

`acquire()` 完成 WebSocket 协商后，建立 rpyc 连接并返回 `rpyc.Connection`：

```python
def acquire(self, timeout=None, max_duration=300) -> rpyc.Connection:
    t = timeout if timeout is not None else self._acquire_timeout
    return asyncio.run(self._acquire_async(t, max_duration))

async def _acquire_async(self, timeout, max_duration):
    ws = await websockets.connect(self._server_url, additional_headers=headers)
    # ... 协商 acquire → acquired ...
    
    loop = asyncio.get_event_loop()
    stream = WebSocketStream(ws, loop)
    feed_task = asyncio.create_task(feed_loop(ws, stream))
    conn = await asyncio.to_thread(rpyc.classic.connect_stream, stream)
    conn._feed_task = feed_task
    conn._ws = ws
    return conn
```

### 5. 依赖

```toml
dependencies = [
    "rpyc>=6.0",
    "websockets>=12.0",
]
```

## 测试策略

删除：`test_proxy.py`、`test_remote_object.py`、`test_protocol.py`（测试被删除的代码）。

新增 `tests/test_rpyc_integration.py`，用 `rpyc.classic.connect_stream` 直接连本地测试 agent（无需真实 WebSocket）：

```python
def test_basic_exec(rpyc_conn):
    assert rpyc_conn.eval("1 + 1") == 2

def test_module_access(rpyc_conn):
    os = rpyc_conn.modules.os
    assert os.getpid() > 0

def test_context_manager(rpyc_conn):
    io = rpyc_conn.modules.io
    with io.StringIO("hello") as f:
        assert f.read() == "hello"
```

## 安全说明

rpyc classic 模式暴露完整 Python 环境（任意代码执行）。WorkflowVM 的使用场景是一次性 GitHub Actions Runner，这是可接受的——用户本来就完全控制 runner 环境。生产部署中，API token 是唯一访问控制。
