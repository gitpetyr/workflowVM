import asyncio
import json
import uuid
from workflowvm.server.protocol import (
    encode_request, decode_response,
    OP_GETATTR, OP_CALL, OP_SETATTR, OP_GETITEM, OP_REPR, OP_DEL, OP_SHUTDOWN, OP_PING,
    RemoteRef, encode_value, decode_value,
    TYPE_REF, TYPE_VALUE, TYPE_ERROR,
)


class RemoteError(Exception):
    def __init__(self, exc_type: str, msg: str, tb: str = ""):
        super().__init__(f"{exc_type}: {msg}")
        self.exc_type = exc_type
        self.remote_msg = msg
        self.tb = tb

    def __str__(self):
        base = super().__str__()
        if self.tb:
            return f"{base}\n--- Remote Traceback ---\n{self.tb}"
        return base


class RemoteObjectServer:
    """
    发送 RPC 请求给 agent，等待响应。

    支持两种模式：
    - 直接模式（默认）：每次 _request 自行 recv，适合测试和简单场景。
    - 分发器模式（调用 start() 后）：后台 recv loop 分发响应，支持并发请求和心跳。
    """

    def __init__(self, ws):
        self._ws = ws
        self._pending: dict[str, asyncio.Future] = {}
        self._recv_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    def start(self, heartbeat_interval: float = 15.0):
        """
        启动后台 recv loop 和心跳，需在事件循环内调用。
        调用后 _request 改用 Future 模式，支持并发。
        """
        loop = asyncio.get_event_loop()
        self._recv_task = loop.create_task(self._recv_loop())
        if heartbeat_interval > 0:
            self._heartbeat_task = loop.create_task(
                self._heartbeat_loop(heartbeat_interval)
            )

    async def stop(self):
        """取消 recv loop 和心跳任务。"""
        for task in (self._heartbeat_task, self._recv_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _recv_loop(self):
        """后台接收循环：将响应分发给等待的 Future。"""
        try:
            async for raw in self._ws:
                resp = decode_response(raw)
                req_id = resp.get("id")
                if req_id and req_id in self._pending:
                    fut = self._pending[req_id]
                    if not fut.done():
                        fut.set_result(resp)
        except Exception as exc:
            # 连接断开，唤醒所有等待中的 Future 并报错
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(ConnectionError(f"WebSocket closed: {exc}"))

    async def _heartbeat_loop(self, interval: float):
        """定期发送应用层心跳，防止 Caddy 等反代因空闲关闭连接。"""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.ping()
            except Exception:
                break

    async def _request(self, op: str, **kwargs) -> dict:
        req_id = str(uuid.uuid4())
        msg = encode_request(req_id, op, **kwargs)

        if self._recv_task is not None:
            # 分发器模式：注册 Future，等待 recv loop 填充结果
            loop = asyncio.get_event_loop()
            fut: asyncio.Future = loop.create_future()
            self._pending[req_id] = fut
            try:
                await self._ws.send(msg)
                return await fut
            finally:
                self._pending.pop(req_id, None)
        else:
            # 直接模式：串行 send + recv（兼容测试和无 start() 场景）
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

    async def ping(self) -> str:
        resp = await self._request(OP_PING)
        return self._parse_result(resp)
