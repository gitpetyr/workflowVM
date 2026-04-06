import json
from dataclasses import dataclass

# Op 常量
OP_GETATTR  = "getattr"
OP_CALL     = "call"
OP_SETATTR  = "setattr"
OP_GETITEM  = "getitem"
OP_REPR     = "repr"
OP_DEL      = "del"
OP_SHUTDOWN = "shutdown"
OP_PING     = "ping"

# Response type 常量
TYPE_REF   = "ref"
TYPE_VALUE = "value"
TYPE_ERROR = "error"


@dataclass(frozen=True, eq=True)
class RemoteRef:
    obj_id: int

    def __eq__(self, other):
        return isinstance(other, RemoteRef) and self.obj_id == other.obj_id

    def __hash__(self):
        return hash(self.obj_id)


def encode_value(v):
    """将 Python 值编码为可 JSON 序列化的形式。RemoteRef → {"$ref": id}"""
    if isinstance(v, RemoteRef):
        return {"$ref": v.obj_id}
    return v


def decode_value(v):
    """将 JSON 值解码回 Python 形式。{"$ref": id} → RemoteRef"""
    if isinstance(v, dict) and "$ref" in v:
        return RemoteRef(v["$ref"])
    return v


def encode_request(req_id: str, op: str, **kwargs) -> str:
    """构建 server→agent 请求消息的 JSON 字符串。"""
    msg: dict = {"id": req_id, "op": op}
    for k, v in kwargs.items():
        msg[k] = encode_value(v)
    return json.dumps(msg)


def decode_response(raw: str) -> dict:
    """解析 agent→server 响应消息。"""
    return json.loads(raw)
