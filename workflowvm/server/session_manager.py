import asyncio
import time
from typing import Optional


class SessionNotFound(Exception):
    pass


class SessionTimeout(Exception):
    pass


class SessionManager:
    def __init__(self, reconnect_grace: float = 60.0):
        self._reconnect_grace = reconnect_grace
        # token → asyncio.Future
        self._pending: dict[str, asyncio.Future] = {}
        # session_id → session dict
        self._sessions: dict[str, dict] = {}
        # session_id → disconnect timestamp
        self._disconnected_at: dict[str, float] = {}

    def register_pending(self, token: str) -> asyncio.Future:
        """调用 acquire() 时注册，等待 agent 连接。"""
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[token] = fut
        return fut

    def on_agent_connect(self, session_id: str, token: str, ws, resume: bool):
        """agent 初次连接时调用。"""
        if token not in self._pending:
            raise SessionNotFound(f"No pending acquire for token {token!r}")
        fut = self._pending.pop(token)
        session = {"session_id": session_id, "ws": ws, "token": token}
        self._sessions[session_id] = session
        if not fut.done():
            fut.set_result(session)

    def on_agent_disconnect(self, session_id: str):
        """agent WebSocket 断开时调用。"""
        if session_id in self._sessions:
            self._sessions[session_id]["ws"] = None
            self._disconnected_at[session_id] = time.monotonic()

    def on_agent_reconnect(self, session_id: str, ws):
        """agent 断线重连时调用（resume=True）。"""
        if session_id not in self._sessions:
            raise SessionNotFound(f"Unknown session {session_id!r} for reconnect")
        self._sessions[session_id]["ws"] = ws
        self._disconnected_at.pop(session_id, None)

    def get_session(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            raise SessionNotFound(f"Session {session_id!r} not found")
        return self._sessions[session_id]

    def release(self, session_id: str):
        """释放 session，清理所有资源。"""
        self._sessions.pop(session_id, None)
        self._disconnected_at.pop(session_id, None)

    def cleanup_expired(self):
        """清理超过 reconnect_grace 未重连的 dead session。"""
        now = time.monotonic()
        expired = [
            sid for sid, ts in self._disconnected_at.items()
            if now - ts > self._reconnect_grace
        ]
        for sid in expired:
            self.release(sid)
        return expired
