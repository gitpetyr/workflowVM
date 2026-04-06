import asyncio
import threading
from workflowvm.server.protocol import RemoteRef

# 全局后台 event loop，持续运行在独立线程中。
# WebSocket ping/pong、keepalive 等都在此 loop 中自动处理，
# 不受主线程（REPL/同步代码）是否阻塞的影响。
_bg_loop = asyncio.new_event_loop()
_bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True, name="wvm-io")
_bg_thread.start()


def _run(coro):
    """将协程提交到后台 loop 并同步等待结果。"""
    future = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return future.result()


class RemoteObject:
    """
    透明代理，将属性访问和方法调用转发给远端 Python 对象。

    _开头的属性为本地属性，不转发。
    """

    def __init__(self, obj_id: int, robj_server):
        # 用 object.__setattr__ 避免触发我们自己的 __setattr__
        object.__setattr__(self, "_obj_id", obj_id)
        object.__setattr__(self, "_robj", robj_server)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        result = _run(robj.getattr(obj_id, name))
        if isinstance(result, RemoteRef):
            return RemoteObject(result.obj_id, robj)
        return result

    def __setattr__(self, name: str, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        # value 可能是另一个 RemoteObject，提取其 RemoteRef
        actual_value = value
        if isinstance(value, RemoteObject):
            actual_value = RemoteRef(object.__getattribute__(value, "_obj_id"))
        _run(robj.setattr(obj_id, name, actual_value))

    def __call__(self, *args, **kwargs):
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        # 将 RemoteObject 参数转换为 RemoteRef
        def to_wire(v):
            if isinstance(v, RemoteObject):
                return RemoteRef(object.__getattribute__(v, "_obj_id"))
            return v
        wire_args = [to_wire(a) for a in args]
        wire_kwargs = {k: to_wire(v) for k, v in kwargs.items()}
        result = _run(robj.call(obj_id, wire_args, wire_kwargs))
        if isinstance(result, RemoteRef):
            return RemoteObject(result.obj_id, robj)
        return result

    def __getitem__(self, key):
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        result = _run(robj.getitem(obj_id, key))
        if isinstance(result, RemoteRef):
            return RemoteObject(result.obj_id, robj)
        return result

    def __del__(self):
        try:
            robj = object.__getattribute__(self, "_robj")
            obj_id = object.__getattribute__(self, "_obj_id")
            if obj_id != 0:  # 不释放根对象
                _run(robj.del_ref(obj_id))
        except Exception:
            pass

    def _repr(self) -> str:
        """获取远程对象的 repr 字符串。"""
        robj = object.__getattribute__(self, "_robj")
        obj_id = object.__getattribute__(self, "_obj_id")
        return _run(robj.repr(obj_id))

    def __repr__(self) -> str:
        obj_id = object.__getattribute__(self, "_obj_id")
        return f"<RemoteObject obj_id={obj_id}>"
