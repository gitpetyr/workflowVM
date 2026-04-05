import json
from workflowvm.server.protocol import (
    encode_request, decode_response,
    OP_GETATTR, OP_CALL, OP_SETATTR, OP_GETITEM, OP_REPR, OP_DEL, OP_SHUTDOWN,
    RemoteRef, encode_value, decode_value,
    TYPE_REF, TYPE_VALUE, TYPE_ERROR,
)

def test_encode_getattr():
    msg = encode_request("id1", OP_GETATTR, obj=0, name="__import__")
    d = json.loads(msg)
    assert d == {"id": "id1", "op": "getattr", "obj": 0, "name": "__import__"}

def test_encode_call():
    msg = encode_request("id2", OP_CALL, obj=5, args=["os"], kwargs={})
    d = json.loads(msg)
    assert d["op"] == "call"
    assert d["args"] == ["os"]

def test_encode_setattr_with_ref():
    msg = encode_request("id3", OP_SETATTR, obj=0, name="x", value=RemoteRef(7))
    d = json.loads(msg)
    assert d["value"] == {"$ref": 7}

def test_encode_value_primitives():
    assert encode_value(42) == 42
    assert encode_value("hello") == "hello"
    assert encode_value(None) is None
    assert encode_value(3.14) == 3.14

def test_encode_value_remote_ref():
    assert encode_value(RemoteRef(5)) == {"$ref": 5}

def test_decode_response_value():
    raw = json.dumps({"id": "id1", "type": "value", "val": "hello"})
    resp = decode_response(raw)
    assert resp["type"] == TYPE_VALUE
    assert resp["val"] == "hello"

def test_decode_response_ref():
    raw = json.dumps({"id": "id1", "type": "ref", "obj": 7})
    resp = decode_response(raw)
    assert resp["type"] == TYPE_REF
    assert resp["obj"] == 7

def test_decode_response_error():
    raw = json.dumps({"id": "id1", "type": "error", "exc": "NameError", "msg": "x"})
    resp = decode_response(raw)
    assert resp["type"] == TYPE_ERROR
    assert resp["exc"] == "NameError"

def test_decode_value_ref():
    assert decode_value({"$ref": 5}) == RemoteRef(5)

def test_decode_value_primitive():
    assert decode_value(42) == 42

def test_encode_shutdown():
    msg = encode_request("id9", OP_SHUTDOWN)
    d = json.loads(msg)
    assert d["op"] == "shutdown"
