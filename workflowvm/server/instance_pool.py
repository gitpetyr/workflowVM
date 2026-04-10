"""
InstancePool - 保留占位，实际 acquire 逻辑已移至 server/main.py 的 _handle_sdk_client。
"""
from workflowvm.server.account_pool import AccountPool
from workflowvm.server.session_manager import SessionManager


class InstancePool:
    """账号池与 session 管理的组合视图（当前仅用于服务器初始化上下文，不直接执行 acquire）。"""

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
