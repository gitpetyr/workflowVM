import asyncio
import uuid
from workflowvm.sdk.proxy import RemoteObject, _run
from workflowvm.server.session_manager import SessionManager
from workflowvm.server.instance_pool import InstancePool, AcquireTimeout


class RemoteVM:
    """
    代表一个活跃的 workflow 实例。
    根对象 obj_id=0 即 workflow 的运行时命名空间。
    """

    def __init__(self, session_id: str, robj_server, instance_pool: "InstancePool"):
        self._session_id = session_id
        self._robj = robj_server
        self._pool = instance_pool
        self._root = RemoteObject(0, robj_server)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._root, name)

    def __setattr__(self, name: str, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        setattr(self._root, name, value)

    def __call__(self, *args, **kwargs):
        return self._root(*args, **kwargs)

    def __getitem__(self, key):
        return self._root[key]

    def _repr(self, obj=None) -> str:
        """获取远程对象 repr。obj 为 None 时获取根对象 repr。"""
        if obj is None:
            return self._root._repr()
        if isinstance(obj, RemoteObject):
            return obj._repr()
        return repr(obj)

    def release(self):
        """关闭 session，workflow 退出。"""
        try:
            _run(self._robj.shutdown())
        except Exception:
            pass
        self._pool.release(self._session_id)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()


class Controller:
    """
    WorkflowVM 控制器。管理账号池和实例池，提供 acquire() 接口。

    用法：
        ctrl = Controller("wss://your-server:8765", token="api-token")
        vm = ctrl.acquire(timeout=120, max_duration=300)
        vm.os = vm.__import__("os")
        vm.os.system("whoami")
        vm.release()
    """

    def __init__(
        self,
        server_url: str,
        *,
        config_path: str = "accounts.yml",
        token: str = "",
        acquire_timeout: float = 120.0,
    ):
        from workflowvm.server.account_pool import AccountPool
        from workflowvm.server.session_manager import SessionManager

        self._server_url = server_url
        self._api_token = token
        self._account_pool = AccountPool(config_path)
        self._session_mgr = SessionManager(reconnect_grace=60.0)
        self._instance_pool = InstancePool(
            account_pool=self._account_pool,
            session_manager=self._session_mgr,
            server_ws_url=server_url,
            acquire_timeout=acquire_timeout,
        )

    def acquire(self, timeout: float = 120.0, max_duration: int = 300) -> RemoteVM:
        """
        分配一个 workflow 实例并等待其连接。
        返回 RemoteVM，可直接操作远程 Python 环境。
        """
        self._instance_pool._acquire_timeout = timeout

        async def _acquire():
            session_id, robj = await self._instance_pool.acquire(max_duration=max_duration)
            return RemoteVM(session_id, robj, self._instance_pool)

        return _run(_acquire())
