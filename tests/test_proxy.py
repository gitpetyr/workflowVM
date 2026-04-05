import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from workflowvm.server.protocol import RemoteRef

from workflowvm.sdk.proxy import RemoteObject

@pytest.fixture
def mock_robj_server():
    m = MagicMock()
    m.getattr = AsyncMock(return_value=42)
    m.call = AsyncMock(return_value="result")
    m.setattr = AsyncMock(return_value=None)
    m.getitem = AsyncMock(return_value="item")
    m.repr = AsyncMock(return_value="<mock>")
    m.del_ref = AsyncMock(return_value=None)
    m.shutdown = AsyncMock(return_value=None)
    return m

def test_getattr_primitive(mock_robj_server):
    mock_robj_server.getattr = AsyncMock(return_value=42)
    proxy = RemoteObject(0, mock_robj_server)
    result = proxy.myattr
    assert result == 42
    mock_robj_server.getattr.assert_called_once_with(0, "myattr")

def test_getattr_returns_proxy_for_ref(mock_robj_server):
    mock_robj_server.getattr = AsyncMock(return_value=RemoteRef(5))
    proxy = RemoteObject(0, mock_robj_server)
    child = proxy.something
    assert isinstance(child, RemoteObject)
    assert child._obj_id == 5

def test_call(mock_robj_server):
    mock_robj_server.call = AsyncMock(return_value="called")
    proxy = RemoteObject(3, mock_robj_server)
    result = proxy("arg1", key="val")
    assert result == "called"
    mock_robj_server.call.assert_called_once_with(3, ["arg1"], {"key": "val"})

def test_setattr_remote(mock_robj_server):
    proxy = RemoteObject(0, mock_robj_server)
    proxy.myvar = 99  # 非 _ 开头，走 remote setattr
    mock_robj_server.setattr.assert_called_once_with(0, "myvar", 99)

def test_setattr_local_for_underscore(mock_robj_server):
    proxy = RemoteObject(0, mock_robj_server)
    proxy._local = "x"  # _ 开头，走本地
    mock_robj_server.setattr.assert_not_called()
    assert proxy._local == "x"

def test_getitem(mock_robj_server):
    mock_robj_server.getitem = AsyncMock(return_value="val")
    proxy = RemoteObject(2, mock_robj_server)
    result = proxy["key"]
    assert result == "val"

def test_repr_method(mock_robj_server):
    mock_robj_server.repr = AsyncMock(return_value="<os module>")
    proxy = RemoteObject(7, mock_robj_server)
    result = proxy._repr()
    assert result == "<os module>"
