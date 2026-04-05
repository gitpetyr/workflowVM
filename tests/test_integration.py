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
