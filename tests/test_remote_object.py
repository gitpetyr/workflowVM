import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from server.remote_object import RemoteObjectServer, RemoteError
from server.protocol import RemoteRef

@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws

@pytest.mark.asyncio
async def test_getattr_returns_value(mock_ws):
    # 模拟 agent 响应
    mock_ws.recv = AsyncMock(return_value=json.dumps(
        {"id": "WILL_BE_REPLACED", "type": "value", "val": 42}
    ))
    robj = RemoteObjectServer(mock_ws)
    # 拦截 send，把 id 回填到 mock 响应
    sent_msgs = []
    async def capture_send(msg):
        d = json.loads(msg)
        sent_msgs.append(d)
        # 模拟 recv 返回对应 id
        mock_ws.recv.return_value = json.dumps({"id": d["id"], "type": "value", "val": 42})
    mock_ws.send.side_effect = capture_send

    result = await robj.getattr(0, "__doc__")
    assert result == 42

@pytest.mark.asyncio
async def test_getattr_returns_ref(mock_ws):
    sent_msgs = []
    async def capture_send(msg):
        d = json.loads(msg)
        sent_msgs.append(d)
        mock_ws.recv.return_value = json.dumps({"id": d["id"], "type": "ref", "obj": 7})
    mock_ws.send.side_effect = capture_send
    mock_ws.recv = AsyncMock()

    robj = RemoteObjectServer(mock_ws)
    result = await robj.getattr(0, "something")
    assert isinstance(result, RemoteRef)
    assert result.obj_id == 7

@pytest.mark.asyncio
async def test_error_raises_remote_error(mock_ws):
    async def capture_send(msg):
        d = json.loads(msg)
        mock_ws.recv.return_value = json.dumps({
            "id": d["id"], "type": "error", "exc": "NameError", "msg": "x not defined"
        })
    mock_ws.send.side_effect = capture_send
    mock_ws.recv = AsyncMock()

    robj = RemoteObjectServer(mock_ws)
    with pytest.raises(RemoteError) as exc_info:
        await robj.getattr(0, "undefined_var")
    assert "NameError" in str(exc_info.value)
