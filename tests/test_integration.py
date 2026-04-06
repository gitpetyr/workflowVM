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

from workflowvm.server.session_manager import SessionManager
from workflowvm.server.remote_object import RemoteObjectServer
from workflowvm.sdk.proxy import RemoteObject


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
    from workflowvm.agent.agent import Agent
    agent = Agent(server_url, session_token, max_duration=30)

    agent_task = asyncio.create_task(agent.run())

    # 等待 agent 连接
    session = await asyncio.wait_for(fut, timeout=10.0)
    ws = session["ws"]
    robj = RemoteObjectServer(ws)

    # --- 测试远程对象操作 ---
    from workflowvm.server.protocol import RemoteRef

    # 1. 获取 builtins 函数（open 是 builtin，不可序列化 → RemoteRef）
    open_ref = await robj.getattr(0, "open")
    assert isinstance(open_ref, RemoteRef)

    # 2. 获取 import_ 方法
    import_ref = await robj.getattr(0, "import_")
    assert isinstance(import_ref, RemoteRef)

    # 3. setattr + getattr 往返测试
    await robj.setattr(0, "test_val", 42)
    val = await robj.getattr(0, "test_val")
    assert val == 42

    # 4. shutdown
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
    from workflowvm.agent.agent import Agent
    agent = Agent(server_url, session_token, max_duration=30)
    agent_task = asyncio.create_task(agent.run())

    session = await asyncio.wait_for(fut, timeout=10.0)
    ws = session["ws"]
    robj = RemoteObjectServer(ws)
    from workflowvm.server.protocol import RemoteRef

    # 通过 import_ 获取 os 模块
    import_ref = await robj.getattr(0, "import_")
    assert isinstance(import_ref, RemoteRef)

    os_ref = await robj.call(import_ref.obj_id, ["os"], {})
    assert isinstance(os_ref, RemoteRef)

    # repr of os 应该包含 "module"
    os_repr = await robj.repr(os_ref.obj_id)
    assert "os" in os_repr

    await robj.shutdown()
    test_server.stop()
    agent_task.cancel()
    server_task.cancel()
    await asyncio.gather(agent_task, server_task, return_exceptions=True)
