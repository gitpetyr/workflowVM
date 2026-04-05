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
