#!/usr/bin/env python3
"""
WorkflowVM Agent - 在 GitHub Actions runner 上运行，反向 WebSocket 连接服务器。
通过 rpyc classic 模式将本地 Python 环境暴露给远端 SDK。
"""
import asyncio
import json
import sys
import threading
import uuid
import argparse
import time

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    print("请先 pip install websockets", file=sys.stderr)
    sys.exit(1)

try:
    import rpyc
except ImportError:
    print("请先 pip install rpyc", file=sys.stderr)
    sys.exit(1)

from workflowvm.sdk.stream import WebSocketStream, feed_loop


class Agent:
    def __init__(self, server_url: str, session_token: str, max_duration: int):
        self._server_url = server_url
        self._session_token = session_token
        self._max_duration = max_duration
        self._session_id = str(uuid.uuid4())
        self._start_time = time.monotonic()

    async def run(self):
        """主循环：带指数退避的断线重连。"""
        retry_delay = 1.0
        resumed = False

        while True:
            if time.monotonic() - self._start_time >= self._max_duration:
                print(f"[agent] max_duration {self._max_duration}s reached, exiting.")
                break

            try:
                headers = {"X-Session-Token": self._session_token}
                async with websockets.connect(self._server_url, additional_headers=headers) as ws:
                    await ws.send(json.dumps({
                        "type": "hello",
                        "session_id": self._session_id,
                        "resume": resumed,
                    }))
                    resumed = True
                    retry_delay = 1.0
                    print(f"[agent] connected, session={self._session_id}")

                    loop = asyncio.get_event_loop()
                    stream = WebSocketStream(ws, loop)
                    feed_task = asyncio.create_task(feed_loop(ws, stream))

                    done_future = loop.create_future()

                    def serve():
                        conn = rpyc.classic.connect_stream(stream)
                        conn.serve_all()
                        loop.call_soon_threadsafe(done_future.set_result, None)

                    threading.Thread(target=serve, daemon=True).start()
                    await done_future
                    feed_task.cancel()

            except ConnectionClosed as e:
                # 1008 = SDK 断开，服务器通知 agent 退出，无需重连
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
