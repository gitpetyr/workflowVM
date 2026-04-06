import asyncio
import json

import websockets

from workflowvm.sdk.proxy import RemoteObject, _run
from workflowvm.server.remote_object import RemoteObjectServer


class RemoteVM:
    """
    代表一个活跃的 workflow 实例。
    根对象 obj_id=0 即 workflow 的运行时命名空间。
    """

    def __init__(self, session_id: str, robj_server: RemoteObjectServer, ws):
        self._session_id = session_id
        self._robj = robj_server
        self._ws = ws
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
        try:
            _run(self._ws.close())
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()


class AcquireTimeout(Exception):
    pass


class Controller:
    """
    WorkflowVM 远程控制器。连接服务器，触发 GitHub Actions runner。

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
        token: str = "",
        acquire_timeout: float = 120.0,
        config_path: str = None,  # 保留兼容旧用法，不再使用
    ):
        self._server_url = server_url
        self._token = token
        self._acquire_timeout = acquire_timeout

    def acquire(self, timeout: float = None, max_duration: int = 300) -> RemoteVM:
        """
        向服务器请求分配一个 workflow 实例并等待其连接。
        返回 RemoteVM，可直接操作远程 Python 环境。
        """
        t = timeout if timeout is not None else self._acquire_timeout
        return _run(self._acquire_async(t, max_duration))

    async def _acquire_async(self, timeout: float, max_duration: int) -> RemoteVM:
        headers = {"X-Api-Token": self._token}
        ws = await websockets.connect(self._server_url, additional_headers=headers)
        try:
            await ws.send(json.dumps({"type": "acquire", "max_duration": max_duration}))

            # 等待服务器响应（acquiring → acquired）
            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise AcquireTimeout("Timed out waiting for agent to connect")
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                msg = json.loads(raw)
                if msg["type"] == "acquiring":
                    continue
                if msg["type"] == "acquired":
                    session_id = msg["session_id"]
                    robj = RemoteObjectServer(ws)
                    return RemoteVM(session_id, robj, ws)
                raise RuntimeError(f"Unexpected server message: {msg}")
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass
            raise
