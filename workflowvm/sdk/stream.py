"""
WebSocket ↔ rpyc 流桥接。

rpyc 使用阻塞 I/O（read/write），WebSocket 使用 async I/O。
用线程 + Queue 桥接两者，agent 和 SDK 共用此模块。
"""
import asyncio
import queue

from rpyc.core.stream import Stream


class WebSocketStream(Stream):
    """将 asyncio WebSocket 包装成 rpyc 所需的同步 Stream 接口。"""

    MAX_IO_CHUNK = 64000  # rpyc Channel.send() 需要此属性

    def __init__(self, ws, loop: asyncio.AbstractEventLoop):
        self._ws = ws
        self._loop = loop
        self._recv_queue: queue.Queue = queue.Queue()
        self._buf = b""
        self._closed = False

    # ── rpyc Stream 接口 ───────────────────────────────────────────────

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self):
        if self._closed:
            return
        self._closed = True
        # 唤醒阻塞在 read() 的线程
        self._recv_queue.put(None)
        asyncio.run_coroutine_threadsafe(
            self._ws.close(), self._loop
        ).result(timeout=5)

    def read(self, count: int) -> bytes:
        """从缓冲区读取恰好 count 字节，不足时阻塞等待队列。"""
        while len(self._buf) < count:
            chunk = self._recv_queue.get()
            if chunk is None:
                raise EOFError("WebSocket closed")
            self._buf += chunk
        data, self._buf = self._buf[:count], self._buf[count:]
        return data

    def write(self, data: bytes):
        """将数据通过 WebSocket 发送（线程安全）。"""
        asyncio.run_coroutine_threadsafe(
            self._ws.send(data), self._loop
        ).result()

    def poll(self, timeout) -> bool:
        """检查是否有数据可读。timeout 可以是 float 或 rpyc.lib.Timeout 对象。"""
        if self._buf:
            return True
        if self._closed:
            return False
        # 将 rpyc Timeout 对象转换为剩余秒数
        if hasattr(timeout, "timeleft"):
            wait = timeout.timeleft()  # None 表示无限等待，0 表示非阻塞
        else:
            wait = None if (timeout is None or timeout < 0) else timeout
        try:
            chunk = self._recv_queue.get(block=(wait != 0), timeout=wait)
            if chunk is None:
                self._closed = True
                return False
            self._buf += chunk
            return True
        except queue.Empty:
            return False

    def fileno(self):
        raise NotImplementedError("WebSocketStream does not support fileno()")


async def feed_loop(ws, stream: WebSocketStream):
    """将 WebSocket 收到的消息放入 stream 队列，直到连接关闭。"""
    try:
        async for msg in ws:
            data = msg if isinstance(msg, bytes) else msg.encode()
            stream._recv_queue.put(data)
    except Exception:
        pass
    finally:
        stream._recv_queue.put(None)
