import pytest
import asyncio
from workflowvm.server.session_manager import SessionManager, SessionNotFound, SessionTimeout

@pytest.mark.asyncio
async def test_register_and_connect():
    mgr = SessionManager(reconnect_grace=5.0)
    token = "tok-abc"
    session_id = "sess-1"

    # register 创建等待 Future
    fut = mgr.register_pending(token)

    # 模拟 agent 连接
    mock_ws = object()
    mgr.on_agent_connect(session_id, token, mock_ws, resume=False)

    # acquire 应该拿到 session
    session = await asyncio.wait_for(fut, timeout=1.0)
    assert session["session_id"] == session_id
    assert session["ws"] is mock_ws

@pytest.mark.asyncio
async def test_connect_unknown_token_raises():
    mgr = SessionManager(reconnect_grace=5.0)
    with pytest.raises(SessionNotFound):
        mgr.on_agent_connect("sess-x", "unknown-token", object(), resume=False)

@pytest.mark.asyncio
async def test_session_resume():
    mgr = SessionManager(reconnect_grace=60.0)
    token = "tok-resume"
    session_id = "sess-resume"

    fut = mgr.register_pending(token)
    mock_ws1 = object()
    mgr.on_agent_connect(session_id, token, mock_ws1, resume=False)
    session = await asyncio.wait_for(fut, timeout=1.0)

    # 断线
    mgr.on_agent_disconnect(session_id)
    assert mgr.get_session(session_id)["ws"] is None

    # 重连（resume=True）
    mock_ws2 = object()
    mgr.on_agent_reconnect(session_id, mock_ws2)
    assert mgr.get_session(session_id)["ws"] is mock_ws2

@pytest.mark.asyncio
async def test_release_removes_session():
    mgr = SessionManager(reconnect_grace=5.0)
    token = "tok-rel"
    session_id = "sess-rel"

    fut = mgr.register_pending(token)
    mgr.on_agent_connect(session_id, token, object(), resume=False)
    await asyncio.wait_for(fut, timeout=1.0)

    mgr.release(session_id)
    with pytest.raises(SessionNotFound):
        mgr.get_session(session_id)
