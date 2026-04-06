#!/usr/bin/env python3
"""
WorkflowVM Server - asyncio WebSocket server
启动：workflowvm serve --config accounts.yml
"""
import asyncio
import json
import uuid
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

# 全局组件（在 main_async() 中初始化）
session_mgr: SessionManager = None
instance_pool: InstancePool = None
account_pool: AccountPool = None
_api_token: str = ""
_server_ws_url: str = ""  # 传给 agent 的服务器地址


async def _handle_agent(ws, token: str):
    """处理 agent 的 WebSocket 连接。"""
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
        await ws.wait_closed()
    finally:
        session_mgr.on_agent_disconnect(session_id)
        log.info(f"agent disconnected session={session_id}")


async def _handle_sdk_client(ws):
    """处理 SDK 客户端连接：acquire → proxy。"""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        msg = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await ws.close(1008, "invalid acquire request")
        return

    if msg.get("type") != "acquire":
        await ws.close(1008, "expected acquire message")
        return

    max_duration = int(msg.get("max_duration", 300))

    # 选取账号
    try:
        account = account_pool.pick()
    except Exception as e:
        await ws.close(1011, f"no account available: {e}")
        return

    session_token = str(uuid.uuid4())

    from workflowvm.server.github_api import GitHubAPI
    api = GitHubAPI(token=account["token"])
    fut = session_mgr.register_pending(session_token)

    try:
        await api.dispatch_workflow(
            repo=f"{account['username']}/{account['runner_repo']}",
            server_url=_server_ws_url,
            session_token=session_token,
            max_duration=max_duration,
        )
    except Exception as e:
        account_pool.release(account["username"])
        session_mgr._pending.pop(session_token, None)
        await ws.close(1011, f"dispatch failed: {e}")
        return

    await ws.send(json.dumps({"type": "acquiring"}))
    log.info(f"SDK client acquiring, dispatched token={session_token}")

    # 等待 agent 连接
    try:
        session = await asyncio.wait_for(fut, timeout=120.0)
    except asyncio.TimeoutError:
        account_pool.release(account["username"])
        await ws.close(1011, "timeout waiting for agent")
        return

    session_id = session["session_id"]
    agent_ws = session["ws"]

    await ws.send(json.dumps({"type": "acquired", "session_id": session_id}))
    log.info(f"SDK client acquired session={session_id}")

    # 透明代理双向消息
    async def forward(src, dst, label):
        try:
            async for data in src:
                await dst.send(data)
        except Exception:
            pass
        finally:
            log.debug(f"{label} forwarding ended")

    try:
        await asyncio.gather(
            forward(ws, agent_ws, "sdk→agent"),
            forward(agent_ws, ws, "agent→sdk"),
            return_exceptions=True,
        )
    finally:
        account_pool.release(account["username"])
        session_mgr.release(session_id)
        log.info(f"SDK session released session={session_id}")


async def ws_handler(ws):
    """根据连接头部路由到 agent 或 SDK 客户端处理器。"""
    session_token = ws.request_headers.get("X-Session-Token", "")
    client_token = ws.request_headers.get("X-Api-Token", "")

    if session_token:
        await _handle_agent(ws, session_token)
    elif client_token and client_token == _api_token:
        await _handle_sdk_client(ws)
    else:
        await ws.close(1008, "Unauthorized")


async def periodic_cleanup():
    """定期清理超时 session。"""
    while True:
        await asyncio.sleep(30)
        expired = session_mgr.cleanup_expired()
        if expired:
            log.info(f"cleaned up expired sessions: {expired}")


async def main_async(config_path: str):
    global session_mgr, instance_pool, account_pool, _api_token, _server_ws_url

    account_pool = AccountPool(config_path)
    srv_cfg = account_pool.server_config
    host = srv_cfg.get("host", "0.0.0.0")
    port = int(srv_cfg.get("port", 8765))
    _api_token = srv_cfg.get("api_token", "")
    # ws_url 用于传给 agent，可在 accounts.yml 中配置（如反代场景）
    _server_ws_url = srv_cfg.get("ws_url", f"ws://{host}:{port}")

    from workflowvm.server.account_setup import setup_all_accounts
    log.info("检查并初始化所有 runner repo...")
    setup_results = await setup_all_accounts(account_pool._accounts)
    for r in setup_results:
        if r.status == "error":
            log.warning(f"账号 {r.username} ({r.runner_repo}) 初始化失败: {r.message}")
        else:
            log.info(f"账号 {r.username} ({r.runner_repo}): {r.message}")

    session_mgr = SessionManager(reconnect_grace=60.0)

    instance_pool = InstancePool(
        account_pool=account_pool,
        session_manager=session_mgr,
        server_ws_url=_server_ws_url,
    )

    stop = asyncio.Future()
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)
    loop.add_signal_handler(signal.SIGHUP, account_pool.reload_if_changed)

    cleanup_task = asyncio.create_task(periodic_cleanup())

    log.info(f"WorkflowVM server starting on {host}:{port}")
    async with serve(ws_handler, host, port):
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
