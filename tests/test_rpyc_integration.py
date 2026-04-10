"""
rpyc 集成测试：用 pipe 配对直接连接，不依赖真实 WebSocket。
验证 rpyc classic 模式下的基本操作、模块访问、上下文管理器等。
"""
import queue
import threading
import pytest
import rpyc

from workflowvm.sdk.stream import WebSocketStream


# ── 辅助：用两个 Queue 对接构造配对 Stream ──────────────────────────────────

class QueueStream(WebSocketStream):
    """将两个 Queue 连接起来，模拟 WebSocket 双向流（测试用）。"""

    def __init__(self, recv_q: queue.Queue, send_q: queue.Queue):
        # 不调用 WebSocketStream.__init__，直接初始化字段
        self._recv_queue = recv_q
        self._send_q = send_q
        self._buf = b""
        self._closed = False

    def write(self, data: bytes):
        self._send_q.put(data)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._recv_queue.put(None)


def make_pair():
    """创建一对互相连接的 QueueStream（agent 端与 SDK 端）。"""
    a_to_b: queue.Queue = queue.Queue()
    b_to_a: queue.Queue = queue.Queue()
    agent_stream = QueueStream(recv_q=b_to_a, send_q=a_to_b)
    sdk_stream = QueueStream(recv_q=a_to_b, send_q=b_to_a)
    return agent_stream, sdk_stream


@pytest.fixture
def rpyc_conn():
    """启动 agent 端 rpyc classic 服务并返回 SDK 端连接。"""
    agent_stream, sdk_stream = make_pair()

    def serve():
        try:
            conn = rpyc.classic.connect_stream(agent_stream)
            conn.serve_all()
        except EOFError:
            pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    conn = rpyc.classic.connect_stream(sdk_stream)
    yield conn
    conn.close()


# ── 测试用例 ────────────────────────────────────────────────────────────────

def test_basic_eval(rpyc_conn):
    assert rpyc_conn.eval("1 + 1") == 2


def test_module_access(rpyc_conn):
    os = rpyc_conn.modules.os
    assert os.getpid() > 0


def test_context_manager(rpyc_conn):
    io = rpyc_conn.modules.io
    with io.StringIO("hello") as f:
        assert f.read() == "hello"


def test_remote_list(rpyc_conn):
    builtins = rpyc_conn.modules.builtins
    lst = builtins.list(range(5))
    assert list(lst) == [0, 1, 2, 3, 4]


def test_remote_exception(rpyc_conn):
    with pytest.raises(Exception):
        rpyc_conn.eval("1 / 0")


def test_execute(rpyc_conn):
    rpyc_conn.execute("x = 42")
    assert rpyc_conn.eval("x") == 42
