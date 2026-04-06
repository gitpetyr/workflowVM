#!/usr/bin/env python3
"""
WorkflowVM Agent - 在 GitHub Actions runner 上运行，反向 WebSocket 连接服务器。
"""
import asyncio
import builtins
import json
import sys
import uuid
import argparse
import time
import traceback
from typing import Any


class _AgentRoot:
    """
    agent 根命名空间：支持自定义属性赋值，未找到时回退到 builtins。
    提供 import_() 方法用于导入模块。
    """
    def __init__(self):
        object.__setattr__(self, '_store', {
            'import_': __import__,
        })

    def __getattr__(self, name: str):
        store = object.__getattribute__(self, '_store')
        if name in store:
            return store[name]
        return getattr(builtins, name)

    def __setattr__(self, name: str, value):
        object.__getattribute__(self, '_store')[name] = value

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
        self._objects: dict[int, Any] = {0: _AgentRoot()}
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
                    print(f"[agent] connected, session={self._session_id}")

                    async for raw in ws:
                        # 首条消息收到才确认 session 已建立
                        resumed = True
                        retry_delay = 1.0
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
                # 1008 = 服务器主动拒绝（token 无效或 session 已过期），无需重试
                if e.rcvd and e.rcvd.code == 1008:
                    print(f"[agent] rejected by server (1008): {e.rcvd.reason}, giving up.")
                    return
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
