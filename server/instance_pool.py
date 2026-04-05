import asyncio
import uuid
from server.account_pool import AccountPool, NoAccountAvailable
from server.github_api import GitHubAPI
from server.session_manager import SessionManager
from server.remote_object import RemoteObjectServer


class AcquireTimeout(Exception):
    pass


class InstancePool:
    def __init__(
        self,
        account_pool: AccountPool,
        session_manager: SessionManager,
        server_ws_url: str,
        acquire_timeout: float = 120.0,
    ):
        self._account_pool = account_pool
        self._session_mgr = session_manager
        self._server_ws_url = server_ws_url
        self._acquire_timeout = acquire_timeout
        # session_id → username，用于 release 时归还账号
        self._session_account: dict[str, str] = {}

    async def acquire(self, max_duration: int = 300) -> tuple[str, RemoteObjectServer]:
        """
        触发一个新 workflow，等待 agent 反连，返回 (session_id, RemoteObjectServer)。
        """
        account = self._account_pool.pick()
        session_token = str(uuid.uuid4())
        api = GitHubAPI(token=account["token"])

        # 注册等待 Future
        fut = self._session_mgr.register_pending(session_token)

        # 触发 workflow
        await api.dispatch_workflow(
            repo=account["runner_repo"],
            server_url=self._server_ws_url,
            session_token=session_token,
            max_duration=max_duration,
        )

        # 等待 agent 连接
        try:
            session = await asyncio.wait_for(fut, timeout=self._acquire_timeout)
        except asyncio.TimeoutError:
            self._account_pool.release(account["username"])
            self._session_mgr._pending.pop(session_token, None)
            raise AcquireTimeout(
                f"Agent did not connect within {self._acquire_timeout}s"
            )

        session_id = session["session_id"]
        self._session_account[session_id] = account["username"]
        robj = RemoteObjectServer(session["ws"])
        return session_id, robj

    def release(self, session_id: str):
        """释放实例，归还账号计数。"""
        username = self._session_account.pop(session_id, None)
        if username:
            self._account_pool.release(username)
        self._session_mgr.release(session_id)
