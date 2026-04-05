#!/usr/bin/env python3
"""
WorkflowVM Server - asyncio WebSocket server
启动：python server/main.py --config accounts.yml
"""
import asyncio
import json
import argparse
import logging
import signal

import websockets
from websockets.server import serve

from workflowvm.server.account_pool import AccountPool
from workflowvm.server.session_manager import SessionManager
from workflowvm.server.instance_pool import InstancePool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wvm.server")

# 全局组件（在 main() 中初始化）
session_mgr: SessionManager = None
instance_pool: InstancePool = None
account_pool: AccountPool = None
_api_token: str = ""


async def agent_handler(ws):
    """处理 agent 的 WebSocket 连接。"""
    token = ws.request_headers.get("X-Session-Token", "")
    if not token:
        await ws.close(1008, "missing session token")
        return

    # 读取握手消息
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        hello = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await ws.close(1008, "invalid hello")
        return

    if hello.get("type") != "hello":
        await ws.close(1008, "expected hello")
        return

    session_id = hello["session_id"]
    resume = hello.get("resume", False)

    try:
        if resume:
            session_mgr.on_agent_reconnect(session_id, ws)
            log.info(f"agent reconnected session={session_id}")
        else:
            session_mgr.on_agent_connect(session_id, token, ws, resume=False)
            log.info(f"agent connected session={session_id}")
    except Exception as e:
        log.warning(f"agent handshake failed: {e}")
        await ws.close(1008, str(e))
        return

    try:
        # 保持连接直到关闭（消息处理在 RemoteObjectServer 中进行）
        await ws.wait_closed()
    finally:
        session_mgr.on_agent_disconnect(session_id)
        log.info(f"agent disconnected session={session_id}")


async def periodic_cleanup():
    """定期清理超时 dead session。"""
    while True:
        await asyncio.sleep(30)
        expired = session_mgr.cleanup_expired()
        if expired:
            log.info(f"cleaned up expired sessions: {expired}")


async def main_async(config_path: str):
    global session_mgr, instance_pool, account_pool, _api_token

    account_pool = AccountPool(config_path)
    srv_cfg = account_pool.server_config
    host = srv_cfg.get("host", "0.0.0.0")
    port = int(srv_cfg.get("port", 8765))
    _api_token = srv_cfg.get("api_token", "")

    session_mgr = SessionManager(reconnect_grace=60.0)

    ws_url = f"wss://{host}:{port}"
    instance_pool = InstancePool(
        account_pool=account_pool,
        session_manager=session_mgr,
        server_ws_url=ws_url,
    )

    stop = asyncio.Future()
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)
    loop.add_signal_handler(signal.SIGHUP, account_pool.reload_if_changed)

    cleanup_task = asyncio.create_task(periodic_cleanup())

    log.info(f"WorkflowVM server starting on {host}:{port}")
    async with serve(agent_handler, host, port):
        await stop

    cleanup_task.cancel()
    log.info("Server stopped.")


def main():
    parser = argparse.ArgumentParser(description="WorkflowVM Server")
    parser.add_argument("--config", default="accounts.yml", help="Path to accounts.yml")
    args = parser.parse_args()
    asyncio.run(main_async(args.config))


if __name__ == "__main__":
    main()
