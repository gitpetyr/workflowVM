import asyncio
import json
import threading

import websockets
import rpyc

from workflowvm.sdk.stream import WebSocketStream, feed_loop

# 持续运行的后台 event loop，处理 WebSocket I/O（ping/pong、send、feed）
_bg_loop = asyncio.new_event_loop()
threading.Thread(target=_bg_loop.run_forever, daemon=True, name="wvm-io").start()


class Controller:
    """
    WorkflowVM 远程控制器。连接服务器，触发 GitHub Actions runner。

    用法：
        ctrl = Controller("wss://your-server:8765", token="api-token")
        conn = ctrl.acquire()          # 返回 rpyc.Connection

        os = conn.modules.os
        os.system("whoami")

        conn.close()
    """

    def __init__(
        self,
        server_url: str,
        *,
        token: str = "",
        acquire_timeout: float = 120.0,
    ):
        self._server_url = server_url
        self._token = token
        self._acquire_timeout = acquire_timeout

    def acquire(self, timeout: float = None, max_duration: int = 300) -> rpyc.Connection:
        """
        向服务器请求分配一个 workflow 实例并等待其连接。
        返回 rpyc.Connection，可通过 conn.modules.xxx 透明访问远端 Python 环境。
        """
        t = timeout if timeout is not None else self._acquire_timeout
        future = asyncio.run_coroutine_threadsafe(
            self._acquire_async(t, max_duration),
            _bg_loop,
        )
        return future.result(timeout=t + 30)

    async def _acquire_async(self, timeout: float, max_duration: int) -> rpyc.Connection:
        headers = {"X-Api-Token": self._token}
        ws = await websockets.connect(self._server_url, additional_headers=headers)
        try:
            await ws.send(json.dumps({"type": "acquire", "max_duration": max_duration}))

            # 等待服务器响应（acquiring → acquired）
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for agent to connect")
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                msg = json.loads(raw)
                if msg["type"] == "acquiring":
                    continue
                if msg["type"] == "acquired":
                    break
                raise RuntimeError(f"Unexpected server message: {msg}")

            loop = asyncio.get_running_loop()
            stream = WebSocketStream(ws, loop)
            feed_task = asyncio.create_task(feed_loop(ws, stream))
            conn = await asyncio.to_thread(rpyc.classic.connect_stream, stream)
            conn._feed_task = feed_task
            conn._ws = ws
            return conn

        except Exception:
            try:
                await ws.close()
            except Exception:
                pass
            raise
