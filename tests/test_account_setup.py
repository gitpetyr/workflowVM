import pytest
import base64
from unittest.mock import AsyncMock, MagicMock, patch
from workflowvm.server.account_setup import setup_account, setup_all_accounts, SetupResult, _AGENT_YML

ACCOUNT = {
    "username": "user1",
    "token": "ghp_test",
    "runner_repo": "wvm-runner",
    "max_concurrent": 5,
}


def _make_resp(status_code: int, json_data: dict = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json = MagicMock(return_value=json_data or {})
    return resp


def _make_client(responses: list):
    """按顺序返回 responses 的 mock AsyncClient。"""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=responses[:])
    client.post = AsyncMock(return_value=_make_resp(201))
    client.put = AsyncMock(return_value=_make_resp(201))
    return client


def _workflow_resp(content: str = None):
    """返回 workflow 文件已存在的 mock 响应，content 默认为当前模板。"""
    body = content if content is not None else _AGENT_YML
    return _make_resp(200, json_data={
        "content": base64.b64encode(body.encode()).decode(),
        "sha": "abc123",
    })


@pytest.mark.asyncio
async def test_all_exists_returns_ready():
    """repo 已存在，workflow 内容与模板相同 → status=ready，不调用 POST/PUT。"""
    client = _make_client([
        _make_resp(200),      # GET /user
        _make_resp(200),      # GET /repos/user1/wvm-runner
        _workflow_resp(),     # GET workflow file（内容与模板一致）
    ])
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "ready"
    client.post.assert_not_called()
    client.put.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_outdated_updates_file():
    """workflow 内容与模板不同 → PUT 更新，status=updated。"""
    client = _make_client([
        _make_resp(200),                        # GET /user
        _make_resp(200),                        # GET /repos
        _workflow_resp("outdated content\n"),   # GET workflow（内容不同）
    ])
    client.put = AsyncMock(return_value=_make_resp(200))  # 更新文件返回 200
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "updated"
    client.put.assert_called_once()


@pytest.mark.asyncio
async def test_repo_missing_creates_repo_and_pushes_workflow():
    """repo 不存在 → POST 建 repo，PUT 推 workflow。"""
    client = _make_client([
        _make_resp(200),   # GET /user
        _make_resp(404),   # GET /repos → 不存在
        _make_resp(404),   # GET workflow → 不存在
    ])
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "created"
    client.post.assert_called_once()  # 建 repo
    client.put.assert_called_once()   # 推 workflow


@pytest.mark.asyncio
async def test_repo_exists_workflow_missing_pushes_workflow():
    """repo 已存在，workflow 不存在 → 只 PUT workflow。"""
    client = _make_client([
        _make_resp(200),  # GET /user
        _make_resp(200),  # GET /repos → 存在
        _make_resp(404),  # GET workflow → 不存在
    ])
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "workflow_added"
    client.post.assert_not_called()
    client.put.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_pat_returns_error():
    """PAT 无效（401）→ status=error，不继续后续步骤。"""
    client = _make_client([
        _make_resp(401),  # GET /user → 未授权
    ])
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "error"
    assert "401" in result.message


@pytest.mark.asyncio
async def test_setup_all_accounts_runs_concurrently():
    """setup_all_accounts 对多个账号都返回结果。"""
    accounts = [
        {**ACCOUNT, "username": "u1", "runner_repo": "r"},
        {**ACCOUNT, "username": "u2", "runner_repo": "r"},
    ]

    async def fake_setup(acc):
        return SetupResult(acc["username"], acc["runner_repo"], "ready", "OK")

    with patch("workflowvm.server.account_setup.setup_account", side_effect=fake_setup):
        results = await setup_all_accounts(accounts)

    assert len(results) == 2
    assert all(r.status == "ready" for r in results)
